"""
cardinality_qerror.py — Top-level cardinality Q-Error for adversarial queries on DuckDB.

For each adversarial query we collect three numbers via the cluster job queue:
  1. default_estimated  — Plan Rows at the root join node from EXPLAIN (FORMAT JSON) on the
                          default (comma-FROM) plan, i.e. what DuckDB's optimizer thinks will
                          come out of the join.
  2. witness_estimated  — Same, but for the witness (CROSS JOIN) plan with join_order disabled.
  3. witness_true       — Actual count(*) result from running the witness plan (fast by design).

Q-Error = max(true/estimated, estimated/true) for each plan's estimate.

Results are stored in a SQLite database alongside the existing pg_validation_results.db.

Usage:
    uv run python -m experiments.cardinality_qerror submit   # submit/resume
    uv run python -m experiments.cardinality_qerror status   # show progress + Q-Errors
"""

import json
import sqlite3
import sys
import time
from pathlib import Path

import pandas as pd

from experiments.adversarial_sql import AdversarialSQLResolver
from oracle.adversarial_queries import QueryTask, ensure_monitor_thread
from oracle.pg_celery_worker.pg_worker import contracts

CSV_PATH = Path(__file__).parent / "imdb_adversarial_absolute.csv"
SQLITE_PATH = Path(__file__).parent / "cardinality_qerror.db"

EXPLAIN_TIMEOUT_SECS = 30        # EXPLAIN never executes, should be instant
WITNESS_TIMEOUT_BUFFER = 1.5     # multiply observed DuckDB time by this for the ceiling
WITNESS_TIMEOUT_MIN_SECS = 30    # floor so very fast queries still get a reasonable window

JOB_TYPES = ("default_explain", "witness_explain", "witness_count")


# ---------------------------------------------------------------------------
# SQLite setup
# ---------------------------------------------------------------------------

def init_db() -> sqlite3.Connection:
    db = sqlite3.connect(str(SQLITE_PATH))
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("""
        CREATE TABLE IF NOT EXISTS cardinality_jobs (
            query_dsl     TEXT    NOT NULL,
            job_type      TEXT    NOT NULL CHECK(job_type IN ('default_explain', 'witness_explain', 'witness_count')),
            sql_sent      TEXT,
            job_id        INTEGER,
            status        TEXT    NOT NULL DEFAULT 'pending',
            result_value  REAL,
            error_message TEXT,
            submitted_at  REAL,
            finished_at   REAL,
            PRIMARY KEY (query_dsl, job_type)
        )
    """)
    db.commit()
    return db


# ---------------------------------------------------------------------------
# DuckDB EXPLAIN parsing
# ---------------------------------------------------------------------------

_AGGREGATE_NODES = {"UNGROUPED_AGGREGATE", "HASH_GROUP_BY", "PERFECT_HASH_GROUP_BY", "STREAMING_WINDOW"}


def _find_root_join_node(node: dict) -> dict | None:
    """Walk past top-level aggregate/projection nodes to the first real join/scan node."""
    name = node.get("name", "").upper().strip()
    if name in _AGGREGATE_NODES or name in ("PROJECTION", "EXPLAIN_ANALYZE", "RESULT_COLLECTOR"):
        for child in node.get("children", []):
            result = _find_root_join_node(child)
            if result is not None:
                return result
        return None
    return node


def extract_estimated_cardinality(explain_json_str: str) -> float | None:
    """
    Parse the JSON returned by DuckDB EXPLAIN (FORMAT JSON) and return the
    estimated cardinality at the root join node (below any aggregate wrapper).
    """
    try:
        nodes = json.loads(explain_json_str)
        root = nodes[0] if isinstance(nodes, list) else nodes
        join_node = _find_root_join_node(root)
        if join_node is None:
            return None
        est_str = join_node.get("extra_info", {}).get("Estimated Cardinality")
        if est_str is None:
            return None
        return float(est_str)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Job submission helpers
# ---------------------------------------------------------------------------

def _submit_run_sql(sql_statements: list[str]) -> int:
    task = QueryTask(
        contracts.RunSQLRequest(query=sql_statements, db_schema="JOB")
    )
    return task.submit()


def _submit_time_query(sql_statements: list[str], timeout_secs: float) -> int:
    task = QueryTask(
        contracts.TimeQueryRequest(
            query=sql_statements,
            timeout_secs=timeout_secs,
            db_schema="JOB",
            return_result=True,
        )
    )
    return task.submit()


def _poll_job(job_id: int) -> contracts.ResponseType | None:
    """Return the parsed response if the job is complete, else None."""
    from oracle.adversarial_queries import _get_pg_connection
    conn = _get_pg_connection()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT status, result FROM template_jobs WHERE id = %s",
            (job_id,),
        )
        row = cur.fetchone()
    if row is None:
        return None
    status, result = row[0], row[1]
    if status == "complete" and result is not None:
        return contracts.Response.validate_python(result)
    return None


# ---------------------------------------------------------------------------
# Main submit loop
# ---------------------------------------------------------------------------

def _resolve_sql(resolver: AdversarialSQLResolver, csv_row) -> tuple[str, str]:
    """Return (default_sql, witness_select_sql) for a CSV row."""
    q = resolver.resolve_row(csv_row)
    # adversarial_sql is: "SET ...;\n\nSELECT ...;\n\nSET ...;"
    # We want just the SELECT, sent as a separate statement alongside the SET.
    witness_select = q.adversarial_sql.split(";\n\n")[1].strip().rstrip(";")
    return q.default_sql, witness_select


def _sql_for_job_type(job_type: str, default_sql: str, witness_sql: str) -> list[str]:
    if job_type == "default_explain":
        return [f"EXPLAIN (FORMAT JSON) {default_sql}"]
    elif job_type == "witness_explain":
        return [
            "SET disabled_optimizers = 'join_order,build_side_probe_side'",
            f"EXPLAIN (FORMAT JSON) {witness_sql}",
        ]
    else:  # witness_count
        return [
            "SET disabled_optimizers = 'join_order,build_side_probe_side'",
            witness_sql,
        ]


def _submit_job(db: sqlite3.Connection, query_dsl: str, job_type: str, sql_statements: list[str], witness_timeout_secs: float = 120.0):
    """Submit one job to the cluster and record it. Idempotent: skips if already submitted."""
    try:
        if job_type == "witness_count":
            job_id = _submit_time_query(sql_statements, witness_timeout_secs)
        else:
            job_id = _submit_run_sql(sql_statements)

        db.execute(
            """UPDATE cardinality_jobs
               SET sql_sent=?, job_id=?, status='submitted', submitted_at=?
               WHERE query_dsl=? AND job_type=?""",
            ("\n".join(sql_statements), job_id, time.time(), query_dsl, job_type),
        )
        db.commit()
        print(f"    {job_type} → job {job_id}")
    except Exception as e:
        print(f"    {job_type}: FAILED to submit: {e}")


def cmd_submit():
    db = init_db()
    df = pd.read_csv(CSV_PATH)
    resolver = AdversarialSQLResolver()

    ensure_monitor_thread()

    # Seed rows for any query_dsl/job_type pairs not yet in the DB
    existing = set(db.execute("SELECT query_dsl, job_type FROM cardinality_jobs").fetchall())
    for _, row in df.iterrows():
        dsl = row["query"]
        for jt in JOB_TYPES:
            if (dsl, jt) not in existing:
                db.execute(
                    "INSERT INTO cardinality_jobs (query_dsl, job_type) VALUES (?, ?)",
                    (dsl, jt),
                )
    db.commit()

    # Poll any previously submitted jobs before submitting new ones
    _poll_pending(db)

    # Submit pending jobs row by row
    pending = db.execute("""
        SELECT DISTINCT query_dsl FROM cardinality_jobs WHERE status = 'pending'
        ORDER BY rowid
    """).fetchall()

    total = len(pending)
    print(f"{total} queries still have pending jobs.")

    for i, (dsl,) in enumerate(pending):
        csv_row = df[df["query"] == dsl].iloc[0]
        print(f"\n[{i+1}/{total}] {dsl[:70]}")

        try:
            default_sql, witness_sql = _resolve_sql(resolver, csv_row)
        except Exception as e:
            print(f"  FAILED to resolve SQL: {e}")
            db.execute(
                "UPDATE cardinality_jobs SET status='error', error_message=? WHERE query_dsl=?",
                (str(e), dsl),
            )
            db.commit()
            continue

        pending_types = [r[0] for r in db.execute(
            "SELECT job_type FROM cardinality_jobs WHERE query_dsl=? AND status='pending'",
            (dsl,),
        ).fetchall()]

        witness_timeout_secs = max(
            csv_row["generated_time_ms"] / 1000 * WITNESS_TIMEOUT_BUFFER,
            WITNESS_TIMEOUT_MIN_SECS,
        )
        for job_type in pending_types:
            stmts = _sql_for_job_type(job_type, default_sql, witness_sql)
            _submit_job(db, dsl, job_type, stmts, witness_timeout_secs)

    print("\nWaiting for all jobs to complete...")
    _poll_pending(db)
    print("Done.")


# ---------------------------------------------------------------------------
# Polling
# ---------------------------------------------------------------------------

def _poll_pending(db: sqlite3.Connection):
    """Poll all submitted jobs until complete, saving results."""
    while True:
        submitted = db.execute("""
            SELECT query_dsl, job_type, job_id
            FROM cardinality_jobs
            WHERE status = 'submitted'
        """).fetchall()

        if not submitted:
            break

        any_progress = False
        for query_dsl, job_type, job_id in submitted:
            response = _poll_job(job_id)
            if response is None:
                continue
            any_progress = True
            if job_type in ("default_explain", "witness_explain"):
                _save_explain_result(db, query_dsl, job_type, response)
            else:
                _save_count_result(db, query_dsl, response)

        if not any_progress:
            time.sleep(3)


def _save_explain_result(
    db: sqlite3.Connection, query_dsl: str, job_type: str, result: contracts.ResponseType
):
    if not isinstance(result, contracts.RunSQLResponse):
        # Worker exception handling always wraps errors as TimeQueryResponse regardless
        # of request type — unwrap to get the real error message if possible.
        inner_error = getattr(getattr(result, "result", None), "error", None)
        msg = inner_error or f"Unexpected response type: {type(result)}"
        db.execute(
            "UPDATE cardinality_jobs SET status='error', error_message=? WHERE query_dsl=? AND job_type=?",
            (msg, query_dsl, job_type),
        )
        db.commit()
        return

    r = result.result
    if isinstance(r, contracts.RunSQLErrorResponse):
        db.execute(
            "UPDATE cardinality_jobs SET status='error', error_message=? WHERE query_dsl=? AND job_type=?",
            (r.error, query_dsl, job_type),
        )
        db.commit()
        return

    try:
        records = json.loads(r.df_json)
        explain_json_str = records[0].get("explain_value") or list(records[0].values())[1]
        cardinality = extract_estimated_cardinality(explain_json_str)
    except Exception as e:
        db.execute(
            "UPDATE cardinality_jobs SET status='error', error_message=? WHERE query_dsl=? AND job_type=?",
            (f"Parse error: {e}", query_dsl, job_type),
        )
        db.commit()
        return

    db.execute(
        """UPDATE cardinality_jobs
           SET status='complete', result_value=?, finished_at=?
           WHERE query_dsl=? AND job_type=?""",
        (cardinality, time.time(), query_dsl, job_type),
    )
    db.commit()
    print(f"  {job_type}: estimated={cardinality}")


def _save_count_result(
    db: sqlite3.Connection, query_dsl: str, result: contracts.ResponseType
):
    if not isinstance(result, contracts.TimeQueryResponse):
        db.execute(
            "UPDATE cardinality_jobs SET status='error', error_message=? WHERE query_dsl=? AND job_type=?",
            (f"Unexpected response type: {type(result)}", query_dsl, "witness_count"),
        )
        db.commit()
        return

    r = result.result
    if isinstance(r, contracts.QueryTimeoutResponse):
        db.execute(
            "UPDATE cardinality_jobs SET status='error', error_message='timeout' WHERE query_dsl=? AND job_type=?",
            (query_dsl, "witness_count"),
        )
        db.commit()
        print(f"  witness_count: TIMEOUT")
        return

    if isinstance(r, contracts.QueryErrorResponse):
        db.execute(
            "UPDATE cardinality_jobs SET status='error', error_message=? WHERE query_dsl=? AND job_type=?",
            (r.error, query_dsl, "witness_count"),
        )
        db.commit()
        print(f"  witness_count: ERROR: {r.error}")
        return

    try:
        records = json.loads(r.query_result)
        true_count = float(list(records[0].values())[0])
    except Exception as e:
        db.execute(
            "UPDATE cardinality_jobs SET status='error', error_message=? WHERE query_dsl=? AND job_type=?",
            (f"Parse error: {e}", query_dsl, "witness_count"),
        )
        db.commit()
        return

    db.execute(
        """UPDATE cardinality_jobs
           SET status='complete', result_value=?, finished_at=?
           WHERE query_dsl=? AND job_type=?""",
        (true_count, time.time(), query_dsl, "witness_count"),
    )
    db.commit()
    print(f"  witness_count: true={true_count:.0f}")


# ---------------------------------------------------------------------------
# Status command
# ---------------------------------------------------------------------------

def _qerror(true: float | None, estimated: float | None) -> float | None:
    if true is None or estimated is None:
        return None
    true = max(true, 1.0)
    estimated = max(estimated, 1.0)
    return max(true / estimated, estimated / true)


def cmd_status():
    db = init_db()

    rows = db.execute("""
        SELECT
            de.query_dsl,
            de.status, de.result_value,
            we.status, we.result_value,
            wc.status, wc.result_value,
            de.error_message
        FROM cardinality_jobs de
        JOIN cardinality_jobs we ON de.query_dsl = we.query_dsl AND we.job_type = 'witness_explain'
        JOIN cardinality_jobs wc ON de.query_dsl = wc.query_dsl AND wc.job_type = 'witness_count'
        WHERE de.job_type = 'default_explain'
        ORDER BY de.rowid
    """).fetchall()

    complete = sum(1 for r in rows if r[1] == "complete" and r[3] == "complete" and r[5] == "complete")
    print(f"{complete}/{len(rows)} queries fully complete.\n")

    print(f"{'DE_est':>12}  {'WE_est':>12}  {'W_true':>12}  {'DE Q-err':>10}  {'WE Q-err':>10}  {'Statuses'}")
    print("-" * 100)
    for dsl, de_st, de_est, we_st, we_est, wc_st, w_true, err in rows:
        de_qe = _qerror(w_true, de_est)
        we_qe = _qerror(w_true, we_est)
        print(
            f"{de_est or 0:>12.0f}  "
            f"{we_est or 0:>12.0f}  "
            f"{w_true or 0:>12.0f}  "
            f"{de_qe or 0:>10.1f}x  "
            f"{we_qe or 0:>10.1f}x  "
            f"{de_st}/{we_st}/{wc_st}"
            + (f"  ERR: {err[:40]}" if err else "")
        )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m experiments.cardinality_qerror [submit|status]")
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "submit":
        cmd_submit()
    elif cmd == "status":
        cmd_status()
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
