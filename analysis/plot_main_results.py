"""
plot_main_results.py — Main results figure: median and max absolute and relative
headroom per dataset (2×2 panels).

Datasets (in bar order)
-----------------------
Adversarial (generated queries):
  G1 DuckDB         g1_duckdb_top143_dedup_by_{abs,rel}.csv
  G1 Postgres       g1_pg_top143_dedup_by_{abs,rel}.csv
  G2                g2_duckdb_top143_dedup_by_{abs,rel}.csv
  G3                g3_duckdb_top143_dedup_by_{abs,rel}.csv
  Stack (adv.)      stack_top143_dedup_by_{abs,rel}.csv

Baselines (full benchmark, all queries):
  JOB DuckDB        job_headroom_*.csv
  JOB Postgres      eval.db  baoplan(nohint) vs bayesrun CSVs
  JOB-Complex       jobcomplex_headroom_*.csv
  Stack DuckDB      stack_headroom_*.csv
  Stack Postgres    eval.db  baoplan(nohint) vs bayesrun CSVs

Usage
-----
  uv run python analysis/plot_main_results.py
"""

import csv
import sqlite3
import statistics
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np
from labellines import labelLines
import pandas as pd

# ── Paths ──────────────────────────────────────────────────────────────────────
DIR       = Path(__file__).parent
DB_PATH   = DIR.parent / "eval.db"
BAYES_DIR = DIR.parent / "db_eval" / "bayes"

RCPARAMS = {
    "font.size": 14, "axes.titlesize": 15, "axes.labelsize": 14,
    "xtick.labelsize": 12, "ytick.labelsize": 12, "legend.fontsize": 12,
}


# ── Data loaders ───────────────────────────────────────────────────────────────

def load_top143_ms(csv_path: Path) -> list[float]:
    """Load absolute_advantage_ms from a top-143 CSV (already in ms)."""
    with open(csv_path) as f:
        return [float(r["absolute_advantage_ms"]) for r in csv.DictReader(f)]


def load_top143_rel(csv_path: Path) -> list[float]:
    """Load relative_advantage from a top-143 CSV."""
    with open(csv_path) as f:
        return [float(r["relative_advantage"]) for r in csv.DictReader(f)]


def load_headroom_csv_ms(csv_path: Path) -> list[float]:
    """Load (default_time - optimized_time)*1000 from a headroom CSV (times in s)."""
    with open(csv_path) as f:
        return [(float(r["default_time"]) - float(r["optimized_time"])) * 1000
                for r in csv.DictReader(f)]


def load_headroom_csv_rel(csv_path: Path) -> list[float]:
    """Load default_time / optimized_time from a headroom CSV (times in s)."""
    with open(csv_path) as f:
        return [float(r["default_time"]) / float(r["optimized_time"])
                for r in csv.DictReader(f)]


def _best_for_query(query_name: str) -> float | None:
    d = BAYES_DIR / query_name
    if not d.is_dir():
        return None
    best = None
    for f in d.glob("*.csv"):
        try:
            df = pd.read_csv(f)
            t = float(-1 * df.dropna(subset=["best_found"]).iloc[-1]["best_found"])
            if best is None or t < best:
                best = t
        except Exception:
            continue
    return best


def load_eval_db(workload_set: str) -> tuple[list[float], list[float]]:
    """
    Return (abs_ms, rel) per-query for a workload from eval.db.
    Postgres baseline = AVG of baoplan nohint runs.
    BayesQO best      = min final best_found across all CSV runs.
    """
    con = sqlite3.connect(str(DB_PATH))
    pg_map = dict(con.execute(
        "SELECT query_name, AVG(runtime_secs) FROM baoplan "
        "WHERE workload_set=? AND join_hint='nohint' AND scan_hint='nohint' "
        "GROUP BY query_name",
        (workload_set,),
    ).fetchall())
    con.close()

    abs_ms, rel = [], []
    for q, pg_s in pg_map.items():
        best_s = _best_for_query(q)
        if best_s is not None:
            abs_ms.append((pg_s - best_s) * 1000)
            rel.append(pg_s / best_s)
    return abs_ms, rel


# ── Assemble datasets ──────────────────────────────────────────────────────────

def get_datasets() -> list[tuple[str, list[float], list[float], str, str]]:
    """Return [(label, abs_ms_list, rel_list, color, hatch)]."""
    adv_blue   = "#3a7dbd"
    adv_blue_l = "#89b8df"   # Postgres variant (lighter)
    adv_green  = "#3aab6e"
    adv_purple = "#8b5cc7"
    adv_red    = "#d95f39"

    base_orange  = "#e07b21"
    base_orange_l= "#f2b06e"  # Postgres variant
    base_tan     = "#c9933a"
    base_teal    = "#2a9d8f"
    base_teal_l  = "#80cec7"  # Postgres variant

    job_abs_ms, job_rel     = load_eval_db("JOB")
    stack_pg_abs_ms, stack_pg_rel = load_eval_db("SO_FUTURE")

    return [
        # ── Adversarial ────────────────────────────────────────────────────────
        ("G1 (DuckDB)",
         load_top143_ms(DIR / "g1_duckdb_top143_dedup_by_abs.csv"),
         load_top143_rel(DIR / "g1_duckdb_top143_dedup_by_rel.csv"),
         adv_blue, ""),
        ("G1 (PostgreSQL)",
         load_top143_ms(DIR / "g1_pg_top143_dedup_by_abs.csv"),
         load_top143_rel(DIR / "g1_pg_top143_dedup_by_rel.csv"),
         adv_blue_l, "//"),
        ("G2",
         load_top143_ms(DIR / "g2_duckdb_top143_dedup_by_abs.csv"),
         load_top143_rel(DIR / "g2_duckdb_top143_dedup_by_rel.csv"),
         adv_green, ""),
        ("G3",
         load_top143_ms(DIR / "g3_duckdb_top143_dedup_by_abs.csv"),
         load_top143_rel(DIR / "g3_duckdb_top143_dedup_by_rel.csv"),
         adv_purple, ""),
        ("GStack",
         load_top143_ms(DIR / "stack_top143_dedup_by_abs.csv"),
         load_top143_rel(DIR / "stack_top143_dedup_by_rel.csv"),
         adv_red, ""),
        # ── Baselines ──────────────────────────────────────────────────────────
        ("JOB (DuckDB)",
         load_headroom_csv_ms(DIR / "job_headroom_20260530.csv"),
         load_headroom_csv_rel(DIR / "job_headroom_20260530.csv"),
         base_orange, ""),
        ("JOB (PostgreSQL)",
         job_abs_ms, job_rel,
         base_orange_l, "//"),
        ("JOB-Complex",
         load_headroom_csv_ms(DIR / "jobcomplex_headroom_20260530.csv"),
         load_headroom_csv_rel(DIR / "jobcomplex_headroom_20260530.csv"),
         base_tan, ""),
        ("Stack (DuckDB)",
         load_headroom_csv_ms(DIR / "stack_headroom_20260530.csv"),
         load_headroom_csv_rel(DIR / "stack_headroom_20260530.csv"),
         base_teal, ""),
        ("Stack (PostgreSQL)",
         stack_pg_abs_ms, stack_pg_rel,
         base_teal_l, "//"),
    ]


# ── Plot ───────────────────────────────────────────────────────────────────────

def _draw_bar_panel(ax, x, vals, colors, hatches, title, y_formatter):
    bars = ax.bar(x, vals, color=colors, edgecolor="white", linewidth=0.8, zorder=2)
    for bar, hatch in zip(bars, hatches):
        bar.set_hatch(hatch)
        bar.set_edgecolor("#444444" if hatch else "white")
    ax.axvline(x=4.5, color="gray", linewidth=1.0, linestyle="--", zorder=1)
    ax.set_yscale("log")
    ax.yaxis.set_major_formatter(ticker.FuncFormatter(y_formatter))
    ax.tick_params(axis="y", labelleft=True)
    ax.set_xticks(x)
    ax.set_title(title, pad=10)
    ax.grid(True, axis="y", alpha=0.3, zorder=0)
    ax.set_axisbelow(True)
    for xpos, txt in [(2.0, "adversarial"), (7.5, "baseline")]:
        ax.text(xpos, -0.30, txt,
                ha="center", va="top", fontsize=11, color="#555555",
                style="italic", transform=ax.get_xaxis_transform(),
                clip_on=False)


def plot_main_results():
    plt.rcParams.update(RCPARAMS)
    datasets = get_datasets()

    labels   = [d[0] for d in datasets]
    abs_meds = [statistics.median(d[1]) for d in datasets]
    abs_maxs = [max(d[1]) for d in datasets]
    rel_meds = [statistics.median(d[2]) for d in datasets]
    rel_maxs = [max(d[2]) for d in datasets]
    colors   = [d[3] for d in datasets]
    hatches  = [d[4] for d in datasets]
    x = np.arange(len(labels))

    abs_fmt = lambda v, _: f"{v/1000:.0f}s" if v >= 1000 else f"{v:.0f}ms"
    rel_fmt = lambda v, _: f"{v:.0f}×"

    fig, axes = plt.subplots(2, 2, figsize=(16, 11), sharey="row")

    panels = [
        (axes[0, 0], abs_meds, "Median absolute advantage", abs_fmt),
        (axes[0, 1], abs_maxs, "Max absolute advantage",    abs_fmt),
        (axes[1, 0], rel_meds, "Median relative advantage", rel_fmt),
        (axes[1, 1], rel_maxs, "Max relative advantage",    rel_fmt),
    ]

    for ax, vals, title, fmt in panels:
        _draw_bar_panel(ax, x, vals, colors, hatches, title, fmt)
        ax.set_xticklabels(labels, rotation=30, ha="right", rotation_mode="anchor")

    axes[0, 0].set_ylabel("Absolute advantage")
    axes[0, 1].set_ylabel("Absolute advantage")
    axes[1, 0].set_ylabel("Relative advantage")
    axes[1, 1].set_ylabel("Relative advantage")

    fig.tight_layout()
    fig.subplots_adjust(bottom=0.12, hspace=0.45)
    out = DIR / "main_results_bar.png"
    fig.savefig(out, dpi=300, bbox_inches="tight")
    print(f"Saved {out}")
    plt.close(fig)


# ── CDF plot ───────────────────────────────────────────────────────────────────

CLIP_MS = 10  # clip negative/near-zero headroom to this value for log-scale CDF


def plot_main_results_cdf():
    plt.rcParams.update(RCPARAMS)
    datasets = get_datasets()

    fig, ax = plt.subplots(figsize=(12, 6))

    for label, abs_vals, _rel_vals, color, hatch in datasets:
        linestyle = "--" if hatch else "-"
        xs = np.sort(np.clip(abs_vals, CLIP_MS, None))
        ys = np.arange(1, len(xs) + 1) / len(xs)
        ax.step(xs, ys, where="post", color=color, linewidth=2,
                linestyle=linestyle, label=label)

    ax.set_xscale("log")
    ax.xaxis.set_major_formatter(ticker.FuncFormatter(
        lambda v, _: f"{v/1000:.0f}s" if v >= 1000 else f"{v:.0f}ms"
    ))
    ax.set_xlabel("Absolute advantage")
    ax.set_ylabel("Cumulative fraction of queries")
    ax.yaxis.set_major_locator(ticker.MultipleLocator(0.2))
    ax.grid(True, alpha=0.3)
    ax.set_axisbelow(True)
    labelLines(ax.get_lines(), fontsize=12,
               outline_color="white", outline_width=4)
    # matplotlib fills legend column-major, so interleave adv/baseline to get
    # adversarial on top row and baselines on bottom row
    handles, labels = ax.get_legend_handles_labels()
    adv_h, base_h = handles[:5], handles[5:]
    adv_l, base_l = labels[:5],  labels[5:]
    ordered_h = [h for pair in zip(adv_h, base_h) for h in pair]
    ordered_l = [l for pair in zip(adv_l, base_l) for l in pair]
    ax.legend(ordered_h, ordered_l, fontsize=11, ncol=5, loc="lower center",
              bbox_to_anchor=(0.5, 1.02), bbox_transform=ax.transAxes,
              borderaxespad=0)

    fig.tight_layout()
    out = DIR / "main_results.png"
    fig.savefig(out, dpi=300, bbox_inches="tight")
    print(f"Saved {out}")
    plt.close(fig)


if __name__ == "__main__":
    datasets = get_datasets()
    print(f"{'Dataset':<22} {'n':>5}  {'med abs':>12}  {'max abs':>12}  {'med rel':>10}  {'max rel':>10}")
    print("-" * 75)
    for label, abs_vals, rel_vals, *_ in datasets:
        label_1line = label.replace("\n", " ")
        print(f"{label_1line:<22} {len(abs_vals):>5}"
              f"  {statistics.median(abs_vals):>10.0f}ms"
              f"  {max(abs_vals):>10.0f}ms"
              f"  {statistics.median(rel_vals):>9.2f}x"
              f"  {max(rel_vals):>9.2f}x")

    plot_main_results()
    plot_main_results_cdf()
