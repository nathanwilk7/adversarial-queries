"""
plot_qerror.py — Plot Q-Error distributions for adversarial queries and JOB.

Usage:
    uv run python -m experiments.plot_qerror
"""

import sqlite3
from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import numpy as np

ADV_DB = Path(__file__).parent / "cardinality_qerror.db"
JOB_DB = Path(__file__).parent / "job_qerror.db"


def load_adversarial_qerrors() -> list[float]:
    db = sqlite3.connect(str(ADV_DB))
    rows = db.execute("""
        SELECT de.result_value, wc.result_value
        FROM cardinality_jobs de
        JOIN cardinality_jobs wc
          ON de.query_dsl = wc.query_dsl AND wc.job_type = 'witness_count'
        WHERE de.job_type = 'default_explain'
          AND de.status = 'complete' AND wc.status = 'complete'
    """).fetchall()
    return [_qerror(w_true, de_est) for de_est, w_true in rows]


def load_job_qerrors() -> list[float]:
    db = sqlite3.connect(str(JOB_DB))
    rows = db.execute("""
        SELECT e.result_value, x.result_value
        FROM job_qerror e
        JOIN job_qerror x ON e.query_name = x.query_name AND x.job_type = 'execute'
        WHERE e.job_type = 'explain' AND e.status = 'complete' AND x.status = 'complete'
    """).fetchall()
    return [_qerror(true, est) for est, true in rows]


def _qerror(true, estimated) -> float:
    true = max(float(true), 1.0)
    estimated = max(float(estimated), 1.0)
    return max(true / estimated, estimated / true)


def plot(adv: list[float], job: list[float]):
    log_adv = np.log10(adv)
    log_job = np.log10(job)

    # Shared x range across both datasets
    xmin = min(log_adv.min(), log_job.min())
    xmax = max(log_adv.max(), log_job.max())
    bins = np.linspace(xmin, xmax, 41)

    fig, axes = plt.subplots(1, 2, figsize=(13, 4))

    x_formatter = ticker.FuncFormatter(
        lambda x, _: f"$10^{{{int(x)}}}$" if x == int(x) else f"$10^{{{x:.1f}}}$"
    )

    # --- Histogram ---
    ax = axes[0]
    ax.hist(log_adv, bins=bins, alpha=0.7, color="steelblue", edgecolor="white",
            linewidth=0.4, label=f"Adversarial (n={len(adv)})", density=True)
    ax.hist(log_job, bins=bins, alpha=0.7, color="darkorange", edgecolor="white",
            linewidth=0.4, label=f"JOB (n={len(job)})", density=True)
    ax.set_xlabel("Q-Error (log₁₀ scale)")
    ax.set_ylabel("Density")
    ax.set_title("Q-Error distribution")
    ax.xaxis.set_major_formatter(x_formatter)
    ax.legend(fontsize=9)

    # --- CDF ---
    ax = axes[1]
    for qerrors, color, label in [
        (log_adv, "steelblue", f"Adversarial (n={len(adv)})"),
        (log_job, "darkorange", f"JOB (n={len(job)})"),
    ]:
        sorted_qe = np.sort(qerrors)
        cdf = np.arange(1, len(sorted_qe) + 1) / len(sorted_qe)
        ax.plot(sorted_qe, cdf, color=color, linewidth=1.8, label=label)
        p50 = np.percentile(qerrors, 50)
        ax.axvline(p50, color=color, linestyle="--", linewidth=1.0, alpha=0.6)

    ax.set_xlabel("Q-Error (log₁₀ scale)")
    ax.set_ylabel("Cumulative fraction of queries")
    ax.set_title("Q-Error CDF")
    ax.xaxis.set_major_formatter(x_formatter)
    ax.yaxis.set_major_formatter(ticker.PercentFormatter(xmax=1))
    ax.grid(True, alpha=0.3)
    ax.legend(fontsize=9)

    fig.suptitle("Cardinality Q-Error: default optimizer plan vs. true count", fontsize=11)
    fig.tight_layout()

    out = Path(__file__).parent / "qerror_distribution.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    print(f"Saved to {out}")
    plt.show()


if __name__ == "__main__":
    adv = load_adversarial_qerrors()
    job = load_job_qerrors()

    for label, qerrors in [("Adversarial", adv), ("JOB", job)]:
        print(f"{label} ({len(qerrors)} queries):")
        print(f"  Median:  {np.median(qerrors):.1f}x")
        print(f"  p90:     {np.percentile(qerrors, 90):.1f}x")
        print(f"  Max:     {max(qerrors):.1f}x")

    plot(adv, job)
