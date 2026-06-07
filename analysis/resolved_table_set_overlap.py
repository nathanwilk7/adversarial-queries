"""
resolved_table_set_overlap.py — Analyse overlap between grammar top-143 lists
at the level of Steiner-resolved table sets.

For each pair of interest (G1-DuckDB vs G1-PG, G1-DuckDB vs G2) we report how
many distinct resolved table sets each list contains and how many are shared.
We also write the full per-grammar inventories to g1_resolved_table_sets.txt.

Steiner resolution is read from steiner_cache.json (produced by dump_steiner_cache.py).

Usage:
    uv run python analysis/resolved_table_set_overlap.py
"""

import csv
import json
from collections import defaultdict
from pathlib import Path

import lark

BASE = Path(__file__).parent

CSVS = {
    "G1-DuckDB": BASE / "g1_duckdb_top143_dedup_by_abs.csv",
    "G1-PG":     BASE / "g1_pg_top143_dedup_by_abs.csv",
    "G2":        BASE / "g2_duckdb_top143_dedup_by_abs.csv",
}

STEINER_CACHE = BASE / "steiner_cache.json"

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
_p = lark.Lark(_DSL_GRAMMAR)


def dsl_tables(q: str) -> list[str]:
    return sorted(str(s.children[0]) for s in _p.parse(q).children)


def load(path: Path) -> list[tuple[str, float]]:
    with open(path) as f:
        return [(r["query"], float(r["absolute_advantage_ms"])) for r in csv.DictReader(f)]


def load_steiner_cache(path: Path) -> dict[tuple, frozenset]:
    """Return input_tables_tuple -> frozenset(connected_tables) from local cache."""
    with open(path) as f:
        rows = json.load(f)
    return {
        tuple(r["input_tables"]): frozenset(r["connected_tables"])
        for r in rows
        if r["schema"] == "JOB"
    }


def resolved_sets_for(rows: list[tuple[str, float]],
                      resolved: dict[tuple, frozenset]) -> dict[frozenset, list[tuple[str, float]]]:
    by_rs: dict[frozenset, list] = defaultdict(list)
    missing = []
    for q, adv in rows:
        rs = resolved.get(tuple(dsl_tables(q)))
        if rs is not None:
            by_rs[rs].append((q, adv))
        else:
            missing.append(q)
    if missing:
        print(f"WARNING: {len(missing)} queries not found in Steiner cache")
    return dict(by_rs)


def report_overlap(label_a: str, label_b: str,
                   by_rs_a: dict, by_rs_b: dict) -> None:
    shared = set(by_rs_a) & set(by_rs_b)
    print(f"\n{label_a} vs {label_b}")
    print(f"  Unique resolved table sets — {label_a}: {len(by_rs_a)}, "
          f"{label_b}: {len(by_rs_b)}")
    print(f"  Shared: {len(shared)}")
    for rs in sorted(shared, key=lambda s: (-len(s), sorted(s))):
        tables = sorted(rs)
        a_entries = sorted(by_rs_a[rs], key=lambda x: -x[1])
        b_entries = sorted(by_rs_b[rs], key=lambda x: -x[1])
        print(f"  [{len(tables)} tables] {', '.join(tables)}")
        for q, adv in a_entries:
            print(f"    {label_a:<10} [{adv:>9.0f} ms] {q}")
        for q, adv in b_entries:
            print(f"    {label_b:<10} [{adv:>9.0f} ms] {q}")


def write_inventory(path: Path,
                    grammars: dict[str, dict[frozenset, list[tuple[str, float]]]]) -> None:
    with open(path, "w") as f:
        def w(s=""): f.write(s + "\n")
        for label, by_rs in grammars.items():
            total = sum(len(v) for v in by_rs.values())
            w("=" * 80)
            w(f"{label} — {len(by_rs)} unique resolved table sets ({total} queries total)")
            w("=" * 80)
            for rs in sorted(by_rs, key=lambda s: (-len(s), sorted(s))):
                entries = sorted(by_rs[rs], key=lambda x: -x[1])
                tables  = sorted(rs)
                w(f"\n[{len(tables)} tables] {', '.join(tables)}")
                for q, adv in entries:
                    w(f"  {adv:>10.0f} ms  {q}")
            w()
    print(f"Inventory written to {path}")


if __name__ == "__main__":
    print("Loading CSVs...")
    data = {label: load(path) for label, path in CSVS.items()}
    for label, rows in data.items():
        print(f"  {label}: {len(rows)} rows ({len(set(q for q, _ in rows))} unique)")

    print(f"\nLoading Steiner cache from {STEINER_CACHE}...")
    resolved = load_steiner_cache(STEINER_CACHE)
    print(f"  {len(resolved)} JOB entries loaded")

    by_rs = {label: resolved_sets_for(rows, resolved) for label, rows in data.items()}

    report_overlap("G1-DuckDB", "G1-PG", by_rs["G1-DuckDB"], by_rs["G1-PG"])
    report_overlap("G1-DuckDB", "G2",    by_rs["G1-DuckDB"], by_rs["G2"])

    write_inventory(
        BASE / "g1_resolved_table_sets.txt",
        {"G1-PG": by_rs["G1-PG"], "G1-DuckDB": by_rs["G1-DuckDB"], "G2": by_rs["G2"]},
    )
