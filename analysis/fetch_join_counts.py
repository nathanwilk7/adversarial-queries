"""
fetch_join_counts.py — Build join_counts_cache.json from the local Steiner cache.

Reads steiner_cache.json (produced by dump_steiner_cache.py) and extracts the
join count (len of connected_tables) for each unique DSL table set found in the
G1, G2, and G3 top-143 CSVs.

Results are written to analysis/join_counts_cache.json as:
  { "<sorted_tables_key>": <int join count>, ... }

Usage:
    uv run python analysis/fetch_join_counts.py
"""

import csv
import json
from pathlib import Path

import lark

BASE = Path(__file__).parent

CSVS = {
    "G1": BASE / "g1_duckdb_top143_dedup_by_abs.csv",
    "G2": BASE / "g2_duckdb_top143_dedup_by_abs.csv",
    "G3": BASE / "g3_duckdb_top143_dedup_by_abs.csv",
}
STEINER_CACHE = BASE / "steiner_cache.json"
OUT           = BASE / "join_counts_cache.json"

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


def cache_key(tables: list[str]) -> str:
    return ",".join(tables)


if __name__ == "__main__":
    # Load local Steiner cache (JOB schema only)
    with open(STEINER_CACHE) as f:
        steiner_rows = json.load(f)
    steiner: dict[tuple, int] = {
        tuple(r["input_tables"]): len(r["connected_tables"])
        for r in steiner_rows
        if r["schema"] == "JOB"
    }
    print(f"Loaded {len(steiner)} JOB entries from {STEINER_CACHE}")

    # Collect all unique sorted table sets across all grammars
    all_table_sets: dict[str, list[str]] = {}  # cache_key -> sorted tables
    for label, path in CSVS.items():
        with open(path) as f:
            dsls = {r["query"] for r in csv.DictReader(f)}
        for dsl in dsls:
            tables = dsl_tables(dsl)
            all_table_sets[cache_key(tables)] = tables
        print(f"  {label}: {len(dsls)} unique DSLs")

    print(f"\n{len(all_table_sets)} unique table sets to look up")

    results: dict[str, int] = {}
    missing = []
    for key, tables in all_table_sets.items():
        count = steiner.get(tuple(tables))
        if count is not None:
            results[key] = count
        else:
            missing.append(key)

    print(f"Found: {len(results)}, Missing: {len(missing)}")
    if missing:
        print("Missing table sets:")
        for k in missing:
            print(f"  {k}")

    with open(OUT, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nSaved to {OUT}")
