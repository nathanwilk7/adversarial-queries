"""
job_qerror.py — Top-level cardinality Q-Error for the Join Order Benchmark (JOB) on DuckDB.

For each of the 113 JOB queries we collect:
  1. default_estimated  — estimated cardinality at the root join node from EXPLAIN (FORMAT JSON)
  2. true_count         — actual result row count from running the query

Q-Error = max(true/estimated, estimated/true)

Usage:
    uv run python -m experiments.job_qerror submit
    uv run python -m experiments.job_qerror status
"""

import json
import sqlite3
import sys
import time
from pathlib import Path

from oracle.adversarial_queries import QueryTask, ensure_monitor_thread
from oracle.oracle import _default_plan
from oracle.pg_celery_worker.pg_worker import contracts
from workload.workloads import OracleCodec, WorkloadSpec, get_workload_set

SQLITE_PATH = Path(__file__).parent / "job_qerror.db"
EXPLAIN_TIMEOUT_SECS = 30
EXECUTE_TIMEOUT_SECS = 60

JOB_TYPES = ("explain", "execute")


# ---------------------------------------------------------------------------
# SQLite setup
# ---------------------------------------------------------------------------

def init_db() -> sqlite3.Connection:
    db = sqlite3.connect(str(SQLITE_PATH))
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("""
        CREATE TABLE IF NOT EXISTS job_qerror (
            query_name   TEXT    NOT NULL,
            job_type     TEXT    NOT NULL CHECK(job_type IN ('explain', 'execute')),
            sql_sent     TEXT,
            job_id       INTEGER,
            status       TEXT    NOT NULL DEFAULT 'pending',
            result_value REAL,
            error_message TEXT,
            submitted_at  REAL,
            finished_at   REAL,
            PRIMARY KEY (query_name, job_type)
        )
    """)
    db.commit()
    return db


# ---------------------------------------------------------------------------
# EXPLAIN parsing (same logic as cardinality_qerror.py)
# ---------------------------------------------------------------------------

_AGGREGATE_NODES = {"UNGROUPED_AGGREGATE", "HASH_GROUP_BY", "PERFECT_HASH_GROUP_BY", "STREAMING_WINDOW"}


def _find_root_join_node(node: dict) -> dict | None:
    name = node.get("name", "").upper().strip()
    if name in _AGGREGATE_NODES or name in ("PROJECTION", "EXPLAIN_ANALYZE", "RESULT_COLLECTOR"):
        for child in node.get("children", []):
            result = _find_root_join_node(child)
            if result is not None:
                return result
        return None
    return node


def extract_estimated_cardinality(explain_json_str: str) -> float | None:
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
# Cluster job helpers
# ---------------------------------------------------------------------------

def _submit_run_sql(sql: str) -> int:
    task = QueryTask(contracts.RunSQLRequest(query=[sql], db_schema="JOB"))
    return task.submit()


def _submit_time_query(sql: str) -> int:
    task = QueryTask(contracts.TimeQueryRequest(
        query=[sql],
        timeout_secs=EXECUTE_TIMEOUT_SECS,
        db_schema="JOB",
        return_result=True,
    ))
    return task.submit()


def _poll_job(job_id: int) -> contracts.ResponseType | None:
    from oracle.adversarial_queries import _get_pg_connection
    conn = _get_pg_connection()
    with conn.cursor() as cur:
        cur.execute("SELECT status, result FROM template_jobs WHERE id = %s", (job_id,))
        row = cur.fetchone()
    if row is None:
        return None
    status, result = row[0], row[1]
    if status == "complete" and result is not None:
        return contracts.Response.validate_python(result)
    return None


# ---------------------------------------------------------------------------
# Submit
# ---------------------------------------------------------------------------

def cmd_submit():
    db = init_db()
    ws = get_workload_set("JOB")

    ensure_monitor_thread()

    # Build default-plan SQL for each query, rewritten as COUNT(*) for cardinality comparison.
    # Use _default_plan to get the correct FROM clause (handles self-joins with multiple aliases),
    # then swap the SELECT clause for count(*).
    queries: dict[str, str] = {}
    for name, wdef in ws.queries.items():
        wspec = WorkloadSpec.from_definition(wdef, OracleCodec.Aliases)
        default_sql = _default_plan(wspec)
        count_sql = "SELECT count(*)\nFROM" + default_sql.split("FROM", 1)[1]
        queries[name] = count_sql

    # Seed missing rows
    existing = set(db.execute("SELECT query_name, job_type FROM job_qerror").fetchall())
    for name in queries:
        for jt in JOB_TYPES:
            if (name, jt) not in existing:
                db.execute("INSERT INTO job_qerror (query_name, job_type) VALUES (?, ?)", (name, jt))
    db.commit()

    # Poll any previously submitted jobs
    _poll_pending(db)

    # Submit pending jobs
    pending = db.execute("""
        SELECT query_name, job_type FROM job_qerror WHERE status = 'pending' ORDER BY rowid
    """).fetchall()

    print(f"{len(pending)} jobs to submit.")
    for query_name, job_type in pending:
        sql = queries[query_name]
        try:
            if job_type == "explain":
                job_id = _submit_run_sql(f"EXPLAIN (FORMAT JSON) {sql}")
            else:
                job_id = _submit_time_query(sql)

            db.execute(
                """UPDATE job_qerror SET sql_sent=?, job_id=?, status='submitted', submitted_at=?
                   WHERE query_name=? AND job_type=?""",
                (sql, job_id, time.time(), query_name, job_type),
            )
            db.commit()
            print(f"  {query_name} {job_type} → job {job_id}")
        except Exception as e:
            print(f"  {query_name} {job_type}: FAILED to submit: {e}")

    print("\nWaiting for all jobs to complete...")
    _poll_pending(db)
    print("Done.")


# ---------------------------------------------------------------------------
# Polling
# ---------------------------------------------------------------------------

def _poll_pending(db: sqlite3.Connection):
    while True:
        submitted = db.execute(
            "SELECT query_name, job_type, job_id FROM job_qerror WHERE status = 'submitted'"
        ).fetchall()

        if not submitted:
            break

        any_progress = False
        for query_name, job_type, job_id in submitted:
            response = _poll_job(job_id)
            if response is None:
                continue
            any_progress = True
            if job_type == "explain":
                _save_explain_result(db, query_name, response)
            else:
                _save_execute_result(db, query_name, response)

        if not any_progress:
            time.sleep(3)


def _save_explain_result(db: sqlite3.Connection, query_name: str, result: contracts.ResponseType):
    if not isinstance(result, contracts.RunSQLResponse):
        inner_error = getattr(getattr(result, "result", None), "error", None)
        msg = inner_error or f"Unexpected response type: {type(result)}"
        db.execute("UPDATE job_qerror SET status='error', error_message=? WHERE query_name=? AND job_type='explain'",
                   (msg, query_name))
        db.commit()
        return

    r = result.result
    if isinstance(r, contracts.RunSQLErrorResponse):
        db.execute("UPDATE job_qerror SET status='error', error_message=? WHERE query_name=? AND job_type='explain'",
                   (r.error, query_name))
        db.commit()
        return

    try:
        records = json.loads(r.df_json)
        explain_json_str = records[0].get("explain_value") or list(records[0].values())[1]
        cardinality = extract_estimated_cardinality(explain_json_str)
    except Exception as e:
        db.execute("UPDATE job_qerror SET status='error', error_message=? WHERE query_name=? AND job_type='explain'",
                   (f"Parse error: {e}", query_name))
        db.commit()
        return

    db.execute(
        "UPDATE job_qerror SET status='complete', result_value=?, finished_at=? WHERE query_name=? AND job_type='explain'",
        (cardinality, time.time(), query_name),
    )
    db.commit()
    print(f"  {query_name} explain: estimated={cardinality}")


def _save_execute_result(db: sqlite3.Connection, query_name: str, result: contracts.ResponseType):
    if not isinstance(result, contracts.TimeQueryResponse):
        inner_error = getattr(getattr(result, "result", None), "error", None)
        msg = inner_error or f"Unexpected response type: {type(result)}"
        db.execute("UPDATE job_qerror SET status='error', error_message=? WHERE query_name=? AND job_type='execute'",
                   (msg, query_name))
        db.commit()
        return

    r = result.result
    if isinstance(r, contracts.QueryTimeoutResponse):
        db.execute("UPDATE job_qerror SET status='error', error_message='timeout' WHERE query_name=? AND job_type='execute'",
                   (query_name,))
        db.commit()
        print(f"  {query_name} execute: TIMEOUT")
        return

    if isinstance(r, contracts.QueryErrorResponse):
        db.execute("UPDATE job_qerror SET status='error', error_message=? WHERE query_name=? AND job_type='execute'",
                   (r.error, query_name))
        db.commit()
        print(f"  {query_name} execute: ERROR: {r.error}")
        return

    try:
        records = json.loads(r.query_result)
        true_count = float(list(records[0].values())[0])
    except Exception as e:
        db.execute("UPDATE job_qerror SET status='error', error_message=? WHERE query_name=? AND job_type='execute'",
                   (f"Parse error: {e}", query_name))
        db.commit()
        return

    db.execute(
        "UPDATE job_qerror SET status='complete', result_value=?, finished_at=? WHERE query_name=? AND job_type='execute'",
        (true_count, time.time(), query_name),
    )
    db.commit()
    print(f"  {query_name} execute: true_count={true_count:.0f}")


# ---------------------------------------------------------------------------
# Status
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
        SELECT e.query_name, e.status, e.result_value, x.status, x.result_value, e.error_message
        FROM job_qerror e
        JOIN job_qerror x ON e.query_name = x.query_name AND x.job_type = 'execute'
        WHERE e.job_type = 'explain'
        ORDER BY e.rowid
    """).fetchall()

    complete = sum(1 for r in rows if r[1] == "complete" and r[3] == "complete")
    print(f"{complete}/{len(rows)} queries fully complete.\n")
    print(f"{'Query':<20}  {'Estimated':>12}  {'True':>10}  {'Q-Error':>10}  Statuses")
    print("-" * 70)
    for query_name, e_st, e_est, x_st, x_true, err in rows:
        qe = _qerror(x_true, e_est)
        print(
            f"{query_name:<20}  {e_est or 0:>12.0f}  {x_true or 0:>10.0f}  "
            f"{qe or 0:>10.1f}x  {e_st}/{x_st}"
            + (f"  ERR: {err[:40]}" if err else "")
        )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m experiments.job_qerror [submit|status]")
        sys.exit(1)
    cmd = sys.argv[1]
    if cmd == "submit":
        cmd_submit()
    elif cmd == "status":
        cmd_status()
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
