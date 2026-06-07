"""
plot_diversity.py — Query diversity analysis for G1 DuckDB top-143 absolute-headroom
queries, comparing to JOB benchmark.

Generates in analysis/:
  diversity_pred_counts.png        histogram: # filter predicates per query
  diversity_table_occurrence.png   bar: per-table occurrence frequency
  diversity_pred_patterns.png      bar: top (table, column) predicate patterns
  diversity_table_pairs.png        bar: top table-pair co-occurrence
  diversity_headroom_vs_joins.png  box: abs advantage (ours and JOB) by join count
  diversity_rel_vs_abs.png         scatter: relative vs. absolute advantage for top-143

Usage:
    uv run python analysis/plot_diversity.py
"""

import csv
import json
import re
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

import lark
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np

# ── Paths ──────────────────────────────────────────────────────────────────────
G1_CSV            = Path(__file__).parent / "g1_duckdb_top143_dedup_by_abs.csv"
G1_PG_CSV         = Path(__file__).parent / "g1_pg_top143_dedup_by_abs.csv"
G2_CSV            = Path(__file__).parent / "g2_duckdb_top143_dedup_by_abs.csv"
G3_CSV            = Path(__file__).parent / "g3_duckdb_top143_dedup_by_abs.csv"
STACK_CSV         = Path(__file__).parent / "stack_top143_dedup_by_abs.csv"
JOB_HEADROOM_CSV  = Path(__file__).parent / "job_headroom_20260530.csv"
JOIN_COUNTS_CACHE = Path(__file__).parent / "join_counts_cache.json"
ADV_DB            = Path(__file__).parent / "cardinality_qerror.db"
JOB_DB            = Path(__file__).parent / "job_qerror.db"
OUT_DIR           = Path(__file__).parent

# Keep TOP143_CSV pointing at G1 for the non-scatter plots
TOP143_CSV = G1_CSV

G1_LABEL    = "G1"
G1_PG_LABEL = "G1-PG"
G2_LABEL    = "G2"
G3_LABEL    = "G3"
STACK_LABEL = "GStack"
JOB_LABEL   = "JOB"
ADV_LABEL   = G1_LABEL   # alias used by non-scatter plots
ADV_COLOR   = "steelblue"
G1_PG_COLOR = "tomato"
G2_COLOR    = "mediumseagreen"
G3_COLOR    = "mediumpurple"
STACK_COLOR = "goldenrod"
JOB_COLOR   = "darkorange"

RCPARAMS = {
    "font.size": 18, "axes.titlesize": 20, "axes.labelsize": 18,
    "xtick.labelsize": 16, "ytick.labelsize": 16, "legend.fontsize": 16,
}


# ══════════════════════════════════════════════════════════════════════════════
# DSL parsing (G1)
# ══════════════════════════════════════════════════════════════════════════════
_DSL_GRAMMAR = """
start: selector+
selector: "(" ident " " filter* ")"
?ident: /[a-z0-9_]+/
filter: int_filter | str_filter
int_filter: "(" ident " " intop " " intval ")"
str_filter:  "(" ident " " strop ")"
!intop: "<" | ">" | "=" | "!="
!strop: "most_popular" | "random"
!intval: "first" | "median" | "last" | "mode" | /[0-9]{4}/
"""
_dsl = lark.Lark(_DSL_GRAMMAR)


def dsl_tables(q: str) -> list[str]:
    return [str(s.children[0]) for s in _dsl.parse(q).children]


def dsl_pred_count(q: str) -> int:
    return sum(len(s.children) - 1 for s in _dsl.parse(q).children)


def generic_pred_count(q: str) -> int:
    """Count filter predicates by depth: each ( at depth 2 is one predicate.
    Works for both IMDB and Stack DSL grammars."""
    count, depth = 0, 0
    for c in q:
        if c == '(':
            depth += 1
            if depth == 2:
                count += 1
        elif c == ')':
            depth -= 1
    return count


def dsl_pred_patterns(q: str) -> list[tuple[str, str]]:
    out = []
    for sel in _dsl.parse(q).children:
        t = str(sel.children[0])
        for f in sel.children[1:]:
            col = str(f.children[0].children[0])
            out.append((t, col))
    return out


# ══════════════════════════════════════════════════════════════════════════════
# JOB SQL parsing
# ══════════════════════════════════════════════════════════════════════════════
def _split_and(text: str) -> list[str]:
    """Split a WHERE clause by AND at paren depth 0."""
    parts, buf, depth = [], [], 0
    i = 0
    while i < len(text):
        c = text[i]
        if c == '(':
            depth += 1; buf.append(c)
        elif c == ')':
            depth -= 1; buf.append(c)
        elif (depth == 0
              and text[i:i+3].upper() == 'AND'
              and (i == 0 or text[i-1] in ' \n\t\r')
              and (i+3 >= len(text) or text[i+3] in ' \n\t\r')):
            parts.append(''.join(buf).strip())
            buf = []; i += 3; continue
        else:
            buf.append(c)
        i += 1
    if buf:
        parts.append(''.join(buf).strip())
    return [p for p in parts if p]


def _is_join(cond: str) -> bool:
    return bool(re.match(r'^\(?\s*\w+\.\w+\s*=\s*\w+\.\w+\s*\)?$', cond.strip()))


def parse_job_sql(sql: str) -> tuple[list[str], list[tuple[str, str]]]:
    """Return (unique_base_tables, filter_pred_patterns) for one JOB query."""
    fm = re.search(r'\bFROM\b(.+?)\bWHERE\b', sql, re.I | re.S)
    wm = re.search(r'\bWHERE\b(.+)$',          sql, re.I | re.S)
    if not fm or not wm:
        return [], []

    alias: dict[str, str] = {}
    tables: list[str] = []
    for item in fm.group(1).split(','):
        m = re.match(r'\s*(\w+)(?:\s+AS\s+(\w+))?', item.strip(), re.I)
        if m:
            base, al = m.group(1), m.group(2) or m.group(1)
            alias[al] = base
            if base not in tables:
                tables.append(base)

    patterns: list[tuple[str, str]] = []
    for cond in _split_and(wm.group(1).rstrip(';')):
        if _is_join(cond):
            continue
        m = re.match(r'(?:NOT\s+)?\(?\s*(\w+)\.(\w+)', cond.strip(), re.I)
        if m:
            patterns.append((alias.get(m.group(1), m.group(1)), m.group(2)))

    return tables, patterns


def _count_from_tables(sql: str) -> int:
    """Count comma-separated entries in FROM clause (Steiner-resolved join size)."""
    m = re.search(r'\bFROM\b(.+?)\bWHERE\b', sql, re.I | re.S)
    if not m:
        raise ValueError(f"Cannot parse FROM in: {sql[:80]!r}")
    return len([t.strip() for t in m.group(1).split(',') if t.strip()])


def _qerror(true: float, est: float) -> float:
    t, e = max(float(true), 1.0), max(float(est), 1.0)
    return max(t / e, e / t)


# ══════════════════════════════════════════════════════════════════════════════
# Data loading
# ══════════════════════════════════════════════════════════════════════════════
def load_csv(path: Path):
    """Load a top-143 CSV; return (dsls, abs_advs_ms, rel_advs)."""
    with open(path) as f:
        rows = list(csv.DictReader(f))
    dsls     = [r["query"] for r in rows]
    abs_advs = [float(r["absolute_advantage_ms"]) for r in rows]
    rel_advs = [float(r["relative_advantage"]) for r in rows]
    return dsls, abs_advs, rel_advs


def load_adv():
    """Load G1 data including sql_sent for the non-scatter plots."""
    dsls, abs_advs, rel_advs = load_csv(TOP143_CSV)

    db = sqlite3.connect(str(ADV_DB))
    ph = ",".join(["?"] * len(dsls))
    sql_map = {r[0]: r[1] for r in db.execute(
        f"SELECT query_dsl, sql_sent FROM cardinality_jobs "
        f"WHERE job_type='default_explain' AND status='complete' AND query_dsl IN ({ph})",
        dsls,
    ).fetchall()}

    return dsls, abs_advs, rel_advs, [sql_map.get(d) for d in dsls]


def load_job():
    """Return (sql_sents, abs_advantages_ms) for JOB queries."""
    # Load headroom CSV: default_time and optimized_time are in seconds
    with open(JOB_HEADROOM_CSV) as f:
        headroom = {r["task"]: (float(r["default_time"]) - float(r["optimized_time"])) * 1000
                    for r in csv.DictReader(f)}

    db = sqlite3.connect(str(JOB_DB))
    rows = db.execute(
        "SELECT query_name, sql_sent FROM job_qerror "
        "WHERE job_type='explain' AND status='complete'"
    ).fetchall()

    sql_sents, abs_advs = [], []
    for name, sql in rows:
        if name in headroom:
            sql_sents.append(sql)
            abs_advs.append(headroom[name])

    return sql_sents, abs_advs


# ══════════════════════════════════════════════════════════════════════════════
# Plots
# ══════════════════════════════════════════════════════════════════════════════
def _save(fig: plt.Figure, name: str):
    path = OUT_DIR / name
    fig.savefig(path, dpi=300, bbox_inches="tight")
    print(f"Saved {path}")
    plt.close(fig)


def plot_pred_counts(adv_counts: list[int], g1_pg_counts: list[int],
                     g2_counts: list[int], g3_counts: list[int],
                     stack_counts: list[int], job_counts: list[int]):
    plt.rcParams.update(RCPARAMS)
    all_c = adv_counts + g1_pg_counts + g2_counts + g3_counts + stack_counts + job_counts
    bins = np.arange(min(all_c), max(all_c) + 2) - 0.5

    panels = [
        (adv_counts,   ADV_COLOR,   G1_LABEL),
        (g1_pg_counts, G1_PG_COLOR, G1_PG_LABEL),
        (g2_counts,    G2_COLOR,    G2_LABEL),
        (g3_counts,    G3_COLOR,    G3_LABEL),
        (stack_counts, STACK_COLOR, STACK_LABEL),
        (job_counts,   JOB_COLOR,   JOB_LABEL),
    ]

    fig, axes = plt.subplots(6, 1, figsize=(9, 14), sharex=True, sharey=True)
    for ax, (counts, color, label) in zip(axes, panels):
        ax.hist(counts, bins=bins, color=color, edgecolor="white",
                linewidth=0.4, density=True)
        ax.set_ylabel("Density")
        ax.text(0.97, 0.95, f"{label}  (n={len(counts)})",
                transform=ax.transAxes, ha="right", va="top", fontsize=15)
        ax.yaxis.set_major_locator(ticker.MultipleLocator(0.2))
        ax.grid(True, axis="y", alpha=0.3)
        ax.set_axisbelow(True)

    axes[-1].set_xlabel("Number of filter predicates")
    axes[-1].xaxis.set_major_locator(ticker.MaxNLocator(integer=True))
    fig.tight_layout()
    _save(fig, "diversity_pred_counts.png")


def plot_pred_counts_cdf(adv_counts: list[int], g1_pg_counts: list[int],
                         g2_counts: list[int], g3_counts: list[int],
                         stack_counts: list[int], job_counts: list[int]):
    plt.rcParams.update(RCPARAMS)

    series = [
        (adv_counts,   ADV_COLOR,   G1_LABEL),
        (g1_pg_counts, G1_PG_COLOR, G1_PG_LABEL),
        (g2_counts,    G2_COLOR,    G2_LABEL),
        (g3_counts,    G3_COLOR,    G3_LABEL),
        (stack_counts, STACK_COLOR, STACK_LABEL),
        (job_counts,   JOB_COLOR,   JOB_LABEL),
    ]

    fig, ax = plt.subplots(figsize=(9, 5))
    for counts, color, label in series:
        xs = np.sort(counts)
        ys = np.arange(1, len(xs) + 1) / len(xs)
        ax.step(xs, ys, where="post", color=color, linewidth=2,
                label=f"{label} (n={len(counts)})")

    ax.set_xlabel("Number of filter predicates")
    ax.set_ylabel("Cumulative fraction")
    ax.xaxis.set_major_locator(ticker.MaxNLocator(integer=True))
    ax.yaxis.set_major_locator(ticker.MultipleLocator(0.2))
    ax.grid(True, alpha=0.3)
    ax.set_axisbelow(True)
    ax.legend()
    fig.tight_layout()
    _save(fig, "diversity_pred_counts_cdf.png")


def _bar_comparison(adv_counter: Counter, job_counter: Counter,
                    xlabel: str, fname: str, top_n: int = 15,
                    fmt=str):
    plt.rcParams.update(RCPARAMS)
    all_keys = sorted(adv_counter, key=lambda k: adv_counter[k], reverse=True)[:top_n]

    adv_vals = [adv_counter[k] for k in all_keys]
    job_vals = [job_counter[k] for k in all_keys]
    labels   = [fmt(k) for k in all_keys]
    y = np.arange(len(labels))
    h = 0.35

    fig, ax = plt.subplots(figsize=(10, max(5, len(labels) * 0.55)))
    ax.barh(y + h/2, adv_vals, h, color=ADV_COLOR, alpha=0.85, label=ADV_LABEL)
    ax.barh(y - h/2, job_vals, h, color=JOB_COLOR, alpha=0.85, label=JOB_LABEL)
    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=14)
    ax.invert_yaxis()
    ax.set_xlabel(xlabel)
    ax.legend()
    ax.grid(True, axis="x", alpha=0.3)
    ax.set_axisbelow(True)
    fig.tight_layout()
    _save(fig, fname)


def plot_table_occurrence(adv_dsls: list[str], job_sqls: list[str]):
    adv_c = Counter(t for q in adv_dsls for t in set(dsl_tables(q)))
    job_c = Counter(t for sql in job_sqls for t in parse_job_sql(sql)[0])
    _bar_comparison(adv_c, job_c, "Occurrences across queries",
                    "diversity_table_occurrence.png")


def plot_pred_patterns(adv_dsls: list[str], job_sqls: list[str]):
    adv_c = Counter(p for q in adv_dsls for p in dsl_pred_patterns(q))
    job_c = Counter(p for sql in job_sqls for p in set(parse_job_sql(sql)[1]))
    _bar_comparison(adv_c, job_c, "Occurrences across queries",
                    "diversity_pred_patterns.png",
                    fmt=lambda k: f"{k[0]}.{k[1]}")


def plot_table_pairs(adv_dsls: list[str], job_sqls: list[str]):
    def pairs(tables):
        ts = sorted(set(tables))
        return [tuple(sorted([ts[i], ts[j]])) for i in range(len(ts)) for j in range(i+1, len(ts))]

    adv_c = Counter(p for q in adv_dsls for p in pairs(dsl_tables(q)))
    job_c = Counter(p for sql in job_sqls for p in pairs(parse_job_sql(sql)[0]))
    _bar_comparison(adv_c, job_c, "Co-occurrences across queries",
                    "diversity_table_pairs.png",
                    fmt=lambda k: f"{k[0]}, {k[1]}")


def plot_headroom_vs_joins(adv_dsls, adv_abs_advs, adv_sql_sents,
                           job_sqls, job_abs_advs):
    plt.rcParams.update(RCPARAMS)

    adv_by_jc: dict[int, list[float]] = defaultdict(list)
    for dsl, adv, sql in zip(adv_dsls, adv_abs_advs, adv_sql_sents):
        if sql is None:
            continue
        adv_by_jc[_count_from_tables(sql)].append(adv)

    job_by_jc: dict[int, list[float]] = defaultdict(list)
    for sql, adv in zip(job_sqls, job_abs_advs):
        job_by_jc[_count_from_tables(sql)].append(adv)

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))

    for ax, by_jc, color, label in [
        (ax1, adv_by_jc, ADV_COLOR, ADV_LABEL),
        (ax2, job_by_jc, JOB_COLOR, JOB_LABEL),
    ]:
        jcs = sorted(by_jc)
        ax.boxplot([by_jc[jc] for jc in jcs], tick_labels=jcs,
                   patch_artist=True,
                   boxprops=dict(facecolor=color, alpha=0.7),
                   medianprops=dict(color="black", linewidth=2))
        ax.set_xlabel("Number of tables")
        ax.set_ylabel("Absolute advantage (ms)")
        ax.set_title(label)
        ax.grid(True, alpha=0.3, axis="y")

    fig.tight_layout()
    _save(fig, "diversity_headroom_vs_joins.png")


def plot_headroom_vs_joins_scatter(datasets: list[tuple[list, list, str, str]],
                                   job_sqls, job_abs_advs):
    """
    datasets: list of (dsls, abs_advs, color, label).
    Join counts for adversarial grammars come from join_counts_cache.json
    (Steiner-tree-resolved via query_connected_tables).
    JOB join count from FROM clause of sql_sent.
    """
    plt.rcParams.update(RCPARAMS)

    with open(JOIN_COUNTS_CACHE) as f:
        jc_cache: dict[str, int] = json.load(f)

    def _cache_key(q: str) -> str:
        return ",".join(sorted(str(s.children[0]) for s in _dsl.parse(q).children))

    rng    = np.random.default_rng(42)
    jitter = 0.15

    fig, ax = plt.subplots(figsize=(10, 6))

    for dsls, abs_advs, color, label in datasets:
        pts = [(jc_cache[_cache_key(q)], adv) for q, adv in zip(dsls, abs_advs)]
        xs  = np.array([p[0] for p in pts], dtype=float)
        ys  = np.array([p[1] for p in pts])
        ax.scatter(xs + rng.uniform(-jitter, jitter, size=len(xs)),
                   ys, alpha=0.35, s=35, color=color, zorder=2)
        by_jc: dict[int, list[float]] = defaultdict(list)
        for jc, adv in pts:
            by_jc[jc].append(adv)
        med_xs = sorted(by_jc)
        ax.plot(med_xs, [np.median(by_jc[jc]) for jc in med_xs],
                color=color, linewidth=2.5, marker="o", markersize=7,
                label=label, zorder=3)

    # JOB — join count from resolved SQL
    job_pts = [(_count_from_tables(sql), adv) for sql, adv in zip(job_sqls, job_abs_advs)]
    xs = np.array([p[0] for p in job_pts], dtype=float)
    ys = np.array([p[1] for p in job_pts])
    ax.scatter(xs + rng.uniform(-jitter, jitter, size=len(xs)),
               ys, alpha=0.35, s=35, color=JOB_COLOR, zorder=2)
    by_jc = defaultdict(list)
    for jc, adv in job_pts:
        by_jc[jc].append(adv)
    med_xs = sorted(by_jc)
    ax.plot(med_xs, [np.median(by_jc[jc]) for jc in med_xs],
            color=JOB_COLOR, linewidth=2.5, marker="o", markersize=7,
            label=JOB_LABEL, zorder=3)

    ax.set_yscale("log")
    ax.set_xlabel("Number of tables")
    ax.set_ylabel("Absolute advantage (ms)")
    ax.xaxis.set_major_locator(ticker.MaxNLocator(integer=True))
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    _save(fig, "diversity_headroom_vs_joins_scatter.png")


def plot_rel_vs_abs(adv_abs_advs: list[float], adv_rel_advs: list[float]):
    plt.rcParams.update(RCPARAMS)
    fig, ax = plt.subplots(figsize=(8, 6))
    ax.scatter(adv_rel_advs, adv_abs_advs, alpha=0.6, s=40, color=ADV_COLOR)
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("Relative advantage (×)")
    ax.set_ylabel("Absolute advantage (ms)")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    _save(fig, "diversity_rel_vs_abs.png")


# ══════════════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("Loading data...")
    adv_dsls, adv_abs_advs, adv_rel_advs, adv_sql_sents = load_adv()
    g1_pg_dsls, g1_pg_abs_advs, _  = load_csv(G1_PG_CSV)
    g2_dsls, g2_abs_advs, _        = load_csv(G2_CSV)
    g3_dsls, g3_abs_advs, _        = load_csv(G3_CSV)
    stack_dsls, stack_abs_advs, _  = load_csv(STACK_CSV)
    job_sqls, job_abs_advs         = load_job()
    print(f"  G1: {len(adv_dsls)} rows ({len(set(adv_dsls))} unique)")
    print(f"  G1-PG: {len(g1_pg_dsls)} rows ({len(set(g1_pg_dsls))} unique)")
    print(f"  G2: {len(g2_dsls)} rows ({len(set(g2_dsls))} unique)")
    print(f"  G3: {len(g3_dsls)} rows ({len(set(g3_dsls))} unique)")
    print(f"  Stack: {len(stack_dsls)} rows ({len(set(stack_dsls))} unique)")
    print(f"  JOB: {len(job_sqls)} queries")

    print("\nPredicate counts...")
    adv_pred_counts   = [dsl_pred_count(q) for q in adv_dsls]
    g1_pg_pred_counts = [dsl_pred_count(q) for q in g1_pg_dsls]
    g2_pred_counts    = [dsl_pred_count(q) for q in g2_dsls]
    g3_pred_counts    = [dsl_pred_count(q) for q in g3_dsls]
    stack_pred_counts = [generic_pred_count(q) for q in stack_dsls]
    job_pred_counts   = [len(parse_job_sql(sql)[1]) for sql in job_sqls]
    for label, counts in [
        (G1_LABEL,    adv_pred_counts),
        (G1_PG_LABEL, g1_pg_pred_counts),
        (G2_LABEL,    g2_pred_counts),
        (G3_LABEL,    g3_pred_counts),
        (STACK_LABEL, stack_pred_counts),
        (JOB_LABEL,   job_pred_counts),
    ]:
        print(f"  {label}: median={np.median(counts):.1f}, "
              f"min={min(counts)}, max={max(counts)}")
    plot_pred_counts(adv_pred_counts, g1_pg_pred_counts, g2_pred_counts, g3_pred_counts, stack_pred_counts, job_pred_counts)
    plot_pred_counts_cdf(adv_pred_counts, g1_pg_pred_counts, g2_pred_counts, g3_pred_counts, stack_pred_counts, job_pred_counts)

    print("\nTable occurrence...")
    plot_table_occurrence(adv_dsls, job_sqls)

    print("\nPredicate patterns...")
    plot_pred_patterns(adv_dsls, job_sqls)

    print("\nTable pairs...")
    plot_table_pairs(adv_dsls, job_sqls)

    print("\nHeadroom vs. join count (box plots)...")
    plot_headroom_vs_joins(adv_dsls, adv_abs_advs, adv_sql_sents,
                           job_sqls, job_abs_advs)

    print("\nHeadroom vs. join count (scatter + median)...")
    plot_headroom_vs_joins_scatter(
        datasets=[
            (adv_dsls, adv_abs_advs, ADV_COLOR, G1_LABEL),
            (g2_dsls,  g2_abs_advs,  G2_COLOR,  G2_LABEL),
            (g3_dsls,  g3_abs_advs,  G3_COLOR,  G3_LABEL),
        ],
        job_sqls=job_sqls,
        job_abs_advs=job_abs_advs,
    )

    print("\nRelative vs. absolute advantage...")
    plot_rel_vs_abs(adv_abs_advs, adv_rel_advs)

    print("\nDone.")
