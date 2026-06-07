"""
plot_g1_abs_join_counts.py — Distribution of join count (# tables) for G1 DuckDB
top-143 absolute-headroom queries vs. JOB.

Join counts are derived from the sql_sent field in the job queues, which reflects
the Steiner-tree-resolved table sets used during actual execution.

Usage:
    uv run python analysis/plot_g1_abs_join_counts.py
"""

import csv
import re
import sqlite3
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np

TOP143_CSV = Path(__file__).parent / "g1_duckdb_top143_dedup_by_abs.csv"
ADV_DB = Path(__file__).parent / "cardinality_qerror.db"
JOB_DB = Path(__file__).parent / "job_qerror.db"
OUT_PNG = Path(__file__).parent / "g1_abs_join_counts.png"


def _count_tables_from_sql(sql: str) -> int:
    """Count tables in the FROM clause (each comma-separated entry is one table)."""
    m = re.search(r"\bFROM\b(.+?)\bWHERE\b", sql, re.IGNORECASE | re.DOTALL)
    if not m:
        raise ValueError(f"Could not parse FROM clause in: {sql[:120]!r}")
    from_clause = m.group(1)
    return len([t.strip() for t in from_clause.split(",") if t.strip()])


def load_top143_queries() -> list[str]:
    with open(TOP143_CSV) as f:
        return [row["query"] for row in csv.DictReader(f)]


def load_adversarial_join_counts(queries: list[str]) -> list[int]:
    placeholders = ",".join(["?"] * len(queries))
    db = sqlite3.connect(str(ADV_DB))
    rows = db.execute(f"""
        SELECT sql_sent FROM cardinality_jobs
        WHERE job_type = 'default_explain'
          AND status = 'complete'
          AND query_dsl IN ({placeholders})
    """, queries).fetchall()
    return [_count_tables_from_sql(r[0]) for r in rows]


def load_job_join_counts() -> list[int]:
    db = sqlite3.connect(str(JOB_DB))
    rows = db.execute("""
        SELECT sql_sent FROM job_qerror
        WHERE job_type = 'explain' AND status = 'complete'
    """).fetchall()
    return [_count_tables_from_sql(r[0]) for r in rows]


def plot(adv: list[int], job: list[int]) -> None:
    plt.rcParams.update({
        "font.size": 18,
        "axes.titlesize": 20,
        "axes.labelsize": 18,
        "xtick.labelsize": 16,
        "ytick.labelsize": 16,
        "legend.fontsize": 16,
    })

    all_counts = adv + job
    bins = np.arange(min(all_counts), max(all_counts) + 2) - 0.5

    fig, ax = plt.subplots(figsize=(9, 5))
    ax.hist(adv, bins=bins, alpha=0.7, color="steelblue", edgecolor="white",
            linewidth=0.4, label="G1", density=True)
    ax.hist(job, bins=bins, alpha=0.7, color="darkorange", edgecolor="white",
            linewidth=0.4, label="JOB", density=True)
    ax.set_xlabel("Number of tables")
    ax.set_ylabel("Density")
    ax.xaxis.set_major_locator(ticker.MaxNLocator(integer=True))
    ax.legend()
    ax.grid(True, axis="y", alpha=0.3)
    ax.set_axisbelow(True)
    fig.tight_layout()

    fig.savefig(OUT_PNG, dpi=300, bbox_inches="tight")
    print(f"Saved to {OUT_PNG}")
    plt.show()


if __name__ == "__main__":
    queries = load_top143_queries()
    print(f"Loaded {len(queries)} queries from CSV ({len(set(queries))} unique)")

    adv = load_adversarial_join_counts(queries)
    job = load_job_join_counts()

    for label, counts in [("G1 abs top-143", adv), ("JOB", job)]:
        print(f"{label} ({len(counts)} queries):")
        print(f"  Median: {np.median(counts):.1f} tables")
        print(f"  Min:    {min(counts)}")
        print(f"  Max:    {max(counts)}")

    plot(adv, job)
