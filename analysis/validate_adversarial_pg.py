"""
Validate adversarial queries on Postgres.

Reads queries from imdb_adversarial_absolute.csv, submits them via the pg.rm.cab
job queue (the `job` table that pg_worker.py reads), and collects results into a
local SQLite database.

The join order is enforced via join_collapse_limit=1 (already set in postgresql.conf)
and explicit CROSS JOIN nesting in the FROM clause. No operator hints are used.

Usage:
    uv run python -m experiments.validate_adversarial_pg submit   # submit queries
    uv run python -m experiments.validate_adversarial_pg status   # show progress
"""

import ast
import csv
import json
import sqlite3
import sys
import time
from pathlib import Path

import psycopg

# -- Project imports (run from bayes_lqo/) --
from optimization.codec.codec import HashProbeStackMachineCodec
from oracle.adversarial_queries import (
    AdversarialQueryInput,
    AdversarialQueryOracle,
    get_predicate_graph,
)
from workload.workloads import get_workload_set

PG_PASS = os.environ["PG_PASS"]
JOB_QUEUE_DSN = dict(host=os.environ["PG_HOST"], user="bayesopt", dbname="bayesopt", password=PG_PASS)

CSV_PATH = Path(__file__).parent / "imdb_adversarial_absolute.csv"
SQLITE_PATH = Path(__file__).parent / "pg_validation_results.db"

TIMEOUT_MS = 2 * 60 * 1000 # 2 minutes
TARGET_DB = "imdb"
DB_USER = "postgres"


def get_pg_conn():
    return psycopg.connect(**JOB_QUEUE_DSN, autocommit=True)


# ---------------------------------------------------------------------------
# SQLite setup
# ---------------------------------------------------------------------------

def init_db() -> sqlite3.Connection:
    db = sqlite3.connect(str(SQLITE_PATH))
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("""
        CREATE TABLE IF NOT EXISTS validation_runs (
            row_idx          INTEGER NOT NULL,
            plan_type        TEXT NOT NULL CHECK(plan_type IN ('default', 'adversarial')),
            query_dsl        TEXT NOT NULL,
            encoded_plan     TEXT,
            sql_text         TEXT NOT NULL,
            job_id           INTEGER,
            status           TEXT NOT NULL DEFAULT 'pending',
            duration_ns      INTEGER,
            error_message    TEXT,
            duckdb_time_ms   REAL,
            submitted_at     REAL,
            finished_at      REAL,
            PRIMARY KEY (row_idx, plan_type)
        )
    """)
    db.commit()
    return db


# ---------------------------------------------------------------------------
# SQL generation (mirrors adversarial_queries.py logic)
# ---------------------------------------------------------------------------

def build_oracle():
    workload_set = get_workload_set("JOB")
    predicate_graph = get_predicate_graph(workload_set)
    oracle = AdversarialQueryOracle(predicate_graph)
    return oracle


def resolve_and_generate_sql(oracle: AdversarialQueryOracle, query_dsl: str, encoded_plan: list[int] | None):
    """
    Use the oracle to resolve predicates and generate the final SQL.
    Returns the full SQL string (with setup statements separated by ';').

    For the adversarial plan: CROSS JOIN nesting + join_collapse_limit=1 forces the order.
    For the default plan: comma-separated FROM + high from_collapse_limit lets PG optimize.

    pg_worker.py splits on ';' and runs all statements before the last one as setup.
    """
    import asyncio

    async def get_sql():
        sql_template, params, tables = await oracle._AdversarialQueryOracle__decode_query_template(
            query_dsl, "JOB"
        )
        if encoded_plan is not None:
            sql = oracle._AdversarialQueryOracle__decode_plan(sql_template, tables, encoded_plan)
            # join_collapse_limit=1 is set globally in postgresql.conf, but be explicit
            setup = "SET join_collapse_limit = 1"
        else:
            sql = oracle._AdversarialQueryOracle__baseline_plan(sql_template, tables)
            # Let PG freely reorder all tables (some queries have >8 tables)
            setup = "SET from_collapse_limit = 30;SET join_collapse_limit = 30"

        # Substitute ? placeholders with actual values (pg_worker uses raw SQL)
        for param in params:
            sql = sql.replace("?", f"'{param}'", 1)

        return f"{setup};{sql}"

    return asyncio.run(get_sql())


# ---------------------------------------------------------------------------
# Job queue interaction (old `job` table used by pg_worker.py)
# ---------------------------------------------------------------------------

INSERT_JOB_SQL = """
INSERT INTO job (sql_statement, target_db, db_user, timeout_ms)
VALUES (%s, %s, %s, %s)
RETURNING id
"""


def submit_to_pg_job_queue(sql: str, timeout_ms: int = TIMEOUT_MS) -> int:
    """Insert a job into the `job` table on pg.rm.cab and return the job ID."""
    with get_pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(INSERT_JOB_SQL, (sql, TARGET_DB, DB_USER, timeout_ms))
            return cur.fetchone()[0]


def poll_job_result(job_id: int) -> dict | None:
    """Check if a job is complete. Returns the result dict or None if still running."""
    with get_pg_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT status, result FROM job WHERE id = %s",
                (job_id,),
            )
            row = cur.fetchone()
            if row is None:
                return None
            status, result = row
            if status == "complete" and result is not None:
                return json.loads(result) if isinstance(result, str) else result
            return None


# ---------------------------------------------------------------------------
# CSV loading
# ---------------------------------------------------------------------------

def load_csv() -> list[dict]:
    rows = []
    with open(CSV_PATH) as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader):
            rows.append({
                "row_idx": i,
                "query_dsl": row["query"],
                "encoded_plan": ast.literal_eval(row["generated_plan"]),
                "default_time_ms": float(row["default_time_ms"]),
                "generated_time_ms": float(row["generated_time_ms"]),
                "absolute_advantage_ms": float(row["absolute_advantage_ms"]),
                "relative_advantage": float(row["relative_advantage"]),
            })
    return rows


# ---------------------------------------------------------------------------
# Submit command
# ---------------------------------------------------------------------------

BATCH_SIZE = 5  # Number of CSV rows per batch
ADV_TIMEOUT_MULTIPLIER = 1.5  # Adversarial timeout = default_duration * this
MIN_ADV_TIMEOUT_MS = 10_000   # Floor for adversarial timeout (10s)


def _resolve_and_submit(db, oracle, row, plan_type, timeout_ms=TIMEOUT_MS):
    """Resolve SQL, submit to job queue, record in SQLite. Returns job_id or None."""
    plan = row["encoded_plan"] if plan_type == "adversarial" else None
    duckdb_time = row["generated_time_ms"] if plan_type == "adversarial" else row["default_time_ms"]

    try:
        sql = resolve_and_generate_sql(oracle, row["query_dsl"], plan)
    except Exception as e:
        print(f"  row {row['row_idx']} {plan_type}: FAILED to resolve: {e}")
        db.execute(
            """INSERT OR REPLACE INTO validation_runs
               (row_idx, plan_type, query_dsl, encoded_plan, sql_text, status, error_message, duckdb_time_ms)
               VALUES (?, ?, ?, ?, ?, 'error', ?, ?)""",
            (row["row_idx"], plan_type, row["query_dsl"],
             json.dumps(row["encoded_plan"]) if plan else None,
             "", str(e), duckdb_time),
        )
        db.commit()
        return None

    job_id = submit_to_pg_job_queue(sql, int(timeout_ms))
    db.execute(
        """INSERT OR REPLACE INTO validation_runs
           (row_idx, plan_type, query_dsl, encoded_plan, sql_text, job_id, status, duckdb_time_ms, submitted_at)
           VALUES (?, ?, ?, ?, ?, ?, 'submitted', ?, ?)""",
        (row["row_idx"], plan_type, row["query_dsl"],
         json.dumps(row["encoded_plan"]) if plan else None,
         sql, job_id, duckdb_time, time.time()),
    )
    db.commit()
    print(f"  row {row['row_idx']} {plan_type}: submitted job {job_id} (timeout={timeout_ms/1000:.0f}s)")
    return job_id


def cmd_submit():
    db = init_db()
    csv_rows = load_csv()
    oracle = build_oracle()

    # First, recover any jobs that were submitted but not polled to completion
    stale_submitted = db.execute(
        "SELECT row_idx, plan_type, job_id FROM validation_runs WHERE status = 'submitted'"
    ).fetchall()
    if stale_submitted:
        print(f"Recovering {len(stale_submitted)} previously submitted jobs...")
        _poll_jobs(db, stale_submitted)

    # Figure out which rows still need work (no entry or not yet complete)
    done = {}  # (row_idx, plan_type) -> {status, duration_ns}
    for row_idx, plan_type, status, duration_ns in db.execute(
        "SELECT row_idx, plan_type, status, duration_ns FROM validation_runs"
    ).fetchall():
        if status in ("complete", "timeout", "error"):
            done[(row_idx, plan_type)] = {"status": status, "duration_ns": duration_ns}

    # Build list of rows that still need at least one plan run
    rows_todo = []
    for row in csv_rows:
        needs_default = (row["row_idx"], "default") not in done
        needs_adv = (row["row_idx"], "adversarial") not in done
        if needs_default or needs_adv:
            rows_todo.append((row, needs_default, needs_adv))

    if not rows_todo:
        print("All queries complete.")
        return

    print(f"{len(rows_todo)} rows remaining ({len(csv_rows)} total). Processing in batches of {BATCH_SIZE}...")

    for batch_start in range(0, len(rows_todo), BATCH_SIZE):
        batch = rows_todo[batch_start : batch_start + BATCH_SIZE]
        batch_num = batch_start // BATCH_SIZE + 1
        total_batches = (len(rows_todo) + BATCH_SIZE - 1) // BATCH_SIZE
        print(f"\n=== Batch {batch_num}/{total_batches} (rows {batch[0][0]['row_idx']}-{batch[-1][0]['row_idx']}) ===")

        # Phase 1: Submit and poll all default plans for this batch
        default_jobs = []
        for row, needs_default, _ in batch:
            if not needs_default:
                continue
            job_id = _resolve_and_submit(db, oracle, row, "default")
            if job_id is not None:
                default_jobs.append((row["row_idx"], "default", job_id))

        if default_jobs:
            _poll_jobs(db, default_jobs)

        # Phase 2: Submit adversarial plans with timeout based on default duration
        adv_jobs = []
        for row, _, needs_adv in batch:
            if not needs_adv:
                continue

            # Look up default duration (may have just been polled, or from a prior run)
            default_info = done.get((row["row_idx"], "default"))
            if default_info is None:
                # Just completed in phase 1 — read from DB
                result = db.execute(
                    "SELECT status, duration_ns FROM validation_runs WHERE row_idx = ? AND plan_type = 'default'",
                    (row["row_idx"],),
                ).fetchone()
                if result:
                    default_info = {"status": result[0], "duration_ns": result[1]}

            # Compute adversarial timeout
            if (default_info
                    and default_info["status"] == "complete"
                    and default_info["duration_ns"] is not None):
                default_ms = default_info["duration_ns"] / 1e6
                adv_timeout_ms = max(default_ms * ADV_TIMEOUT_MULTIPLIER, MIN_ADV_TIMEOUT_MS)
            else:
                adv_timeout_ms = TIMEOUT_MS

            job_id = _resolve_and_submit(db, oracle, row, "adversarial", timeout_ms=adv_timeout_ms)
            if job_id is not None:
                adv_jobs.append((row["row_idx"], "adversarial", job_id))

        if adv_jobs:
            _poll_jobs(db, adv_jobs)


def _poll_jobs(db: sqlite3.Connection, jobs: list[tuple[int, str, int]]):
    """Poll until all (row_idx, plan_type, job_id) tuples are complete."""
    remaining = list(jobs)
    total = len(remaining)
    poll_round = 0

    while remaining:
        poll_round += 1
        still_waiting = []
        completed_this_round = 0

        for row_idx, plan_type, job_id in remaining:
            result = poll_job_result(job_id)
            if result is None:
                still_waiting.append((row_idx, plan_type, job_id))
                continue

            completed_this_round += 1
            status = result.get("status", "unknown")
            duration_ns = result.get("duration (ns)")
            error_msg = result.get("message")

            if status == "complete":
                db_status = "complete"
                dur_str = f"{duration_ns / 1e6:.1f}ms" if duration_ns else "complete"
            elif status == "timeout":
                db_status = "timeout"
                dur_str = "TIMEOUT"
            else:
                db_status = "error"
                dur_str = f"ERROR: {(error_msg or '')[:60]}"

            db.execute(
                """UPDATE validation_runs
                   SET status = ?, duration_ns = ?, error_message = ?, finished_at = ?
                   WHERE row_idx = ? AND plan_type = ?""",
                (db_status, duration_ns, error_msg, time.time(), row_idx, plan_type),
            )
            print(f"  row {row_idx} {plan_type}: {dur_str}")

        db.commit()
        remaining = still_waiting

        if remaining:
            time.sleep(5)

    print(f"  Batch done ({total} jobs).")


def cmd_poll(db: sqlite3.Connection | None = None):
    if db is None:
        db = init_db()

    submitted = db.execute(
        "SELECT row_idx, plan_type, job_id FROM validation_runs WHERE status = 'submitted'"
    ).fetchall()

    if not submitted:
        print("No submitted jobs waiting for results.")
        return

    print(f"Polling {len(submitted)} submitted jobs...")
    _poll_jobs(db, submitted)


# ---------------------------------------------------------------------------
# Status command
# ---------------------------------------------------------------------------

def cmd_status():
    db = init_db()
    csv_rows = load_csv()
    csv_by_idx = {r["row_idx"]: r for r in csv_rows}

    # Get all validation results
    results = db.execute("""
        SELECT row_idx, plan_type, status, duration_ns, duckdb_time_ms, error_message, job_id
        FROM validation_runs
        ORDER BY row_idx, plan_type
    """).fetchall()

    # Build lookup: (row_idx, plan_type) -> result
    result_map: dict[tuple[int, str], dict] = {}
    for row_idx, plan_type, status, duration_ns, duckdb_time_ms, error_message, job_id in results:
        result_map[(row_idx, plan_type)] = {
            "status": status,
            "duration_ns": duration_ns,
            "duckdb_time_ms": duckdb_time_ms,
            "error_message": error_message,
            "job_id": job_id,
        }

    # Summary counters
    total = len(csv_rows)
    n_complete = 0
    n_submitted = 0
    n_pending = 0
    n_timeout = 0
    n_error = 0
    n_missing = 0

    print(f"{'Row':>4}  {'Query (truncated)':50}  {'DuckDB Δ':>12}  {'PG Default':>12}  {'PG Advers':>12}  {'PG Δ abs':>12}  {'PG Δ rel':>10}  {'Status'}")
    print("-" * 170)

    for row in csv_rows:
        idx = row["row_idx"]
        query_short = row["query_dsl"][:50]

        duckdb_default_ms = row["default_time_ms"]
        duckdb_adv_ms = row["generated_time_ms"]
        duckdb_abs = row["absolute_advantage_ms"]
        duckdb_rel = row["relative_advantage"]

        default_r = result_map.get((idx, "default"))
        adv_r = result_map.get((idx, "adversarial"))

        # Determine row status
        if default_r is None or adv_r is None:
            row_status = "missing"
            n_missing += 1
        elif default_r["status"] == "submitted" or adv_r["status"] == "submitted":
            row_status = "submitted"
            n_submitted += 1
        elif default_r["status"] == "pending" or adv_r["status"] == "pending":
            row_status = "pending"
            n_pending += 1
        elif default_r["status"] in ("error",) or adv_r["status"] in ("error",):
            row_status = "error"
            n_error += 1
        elif default_r["status"] == "timeout" or adv_r["status"] == "timeout":
            row_status = "timeout"
            n_timeout += 1
        else:
            row_status = "complete"
            n_complete += 1

        # Format PG times
        def fmt_time(r):
            if r is None:
                return "---"
            if r["status"] == "complete" and r["duration_ns"] is not None:
                return f"{r['duration_ns'] / 1e6:.1f}ms"
            elif r["status"] == "timeout":
                return "TIMEOUT"
            elif r["status"] == "submitted":
                return "running..."
            elif r["status"] == "pending":
                return "pending"
            elif r["status"] == "error":
                return "ERROR"
            return r["status"]

        pg_default_str = fmt_time(default_r)
        pg_adv_str = fmt_time(adv_r)

        # Compute PG disparity if both complete
        pg_abs_str = ""
        pg_rel_str = ""
        if (default_r and adv_r
                and default_r["status"] == "complete" and adv_r["status"] == "complete"
                and default_r["duration_ns"] is not None and adv_r["duration_ns"] is not None):
            pg_default_ms = default_r["duration_ns"] / 1e6
            pg_adv_ms = adv_r["duration_ns"] / 1e6
            pg_abs = pg_default_ms - pg_adv_ms
            pg_rel = pg_default_ms / pg_adv_ms if pg_adv_ms > 0 else float("inf")
            pg_abs_str = f"{pg_abs:.1f}ms"
            pg_rel_str = f"{pg_rel:.1f}x"

        print(
            f"{idx:>4}  {query_short:50}  "
            f"{duckdb_abs:>10.0f}ms  "
            f"{pg_default_str:>12}  {pg_adv_str:>12}  "
            f"{pg_abs_str:>12}  {pg_rel_str:>10}  "
            f"{row_status}"
        )

    print("-" * 170)
    print(f"Total: {total} queries")
    print(f"  Complete: {n_complete}  Timeout: {n_timeout}  Submitted: {n_submitted}  Pending: {n_pending}  Error: {n_error}  Missing: {n_missing}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def cmd_retry():
    """Reset timed-out (or errored) rows so submit will re-run them.

    Usage:
        retry                  -- retry all timeouts and errors
        retry timeout          -- retry only timeouts
        retry error            -- retry only errors
        retry default          -- retry only default plan timeouts/errors
        retry timeout default  -- retry only default plan timeouts
    """
    filters = set(sys.argv[2:])
    plan_filter = None
    status_filter = ("timeout", "error")

    if "default" in filters:
        plan_filter = "default"
        filters.discard("default")
    if "adversarial" in filters:
        plan_filter = "adversarial"
        filters.discard("adversarial")
    if "timeout" in filters:
        status_filter = ("timeout",)
        filters.discard("timeout")
    if "error" in filters:
        status_filter = ("error",)
        filters.discard("error")

    if filters:
        print(f"Unknown filter(s): {filters}")
        sys.exit(1)

    db = init_db()
    placeholders = ",".join("?" for _ in status_filter)
    if plan_filter:
        count = db.execute(
            f"SELECT count(*) FROM validation_runs WHERE status IN ({placeholders}) AND plan_type = ?",
            (*status_filter, plan_filter),
        ).fetchone()[0]
        db.execute(
            f"DELETE FROM validation_runs WHERE status IN ({placeholders}) AND plan_type = ?",
            (*status_filter, plan_filter),
        )
    else:
        count = db.execute(
            f"SELECT count(*) FROM validation_runs WHERE status IN ({placeholders})",
            status_filter,
        ).fetchone()[0]
        db.execute(
            f"DELETE FROM validation_runs WHERE status IN ({placeholders})",
            status_filter,
        )
    db.commit()
    print(f"Cleared {count} rows (filter: status={status_filter}, plan={plan_filter or 'all'}). Run 'submit' to re-run them.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m experiments.validate_adversarial_pg [submit|poll|status|retry]")
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "submit":
        cmd_submit()
    elif cmd == "poll":
        cmd_poll()
    elif cmd == "status":
        cmd_status()
    elif cmd == "retry":
        cmd_retry()
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
