"""
Postgres worker that reads from the template_jobs queue and executes
TimeQueryRequests against local PostgreSQL.

RunSQLRequests are deliberately skipped. Those use DuckDB-specific aggregate
functions (median(), quantile_disc()) for predicate value resolution. A separate
DuckDB worker must remain active to handle RunSQLRequests and populate the
predicate_values cache on pg.rm.cab. Once the cache is warm, the adversarial
query oracle will never submit RunSQLRequests for previously-seen predicates,
so Postgres workers can operate unimpeded.
"""

import json
import os
import selectors
import socket
import threading
import time
from queue import Queue
from typing import Optional

import psycopg
from psycopg.rows import dict_row

import contracts
from config import get_config

# Thread-local storage for job-queue connections
_local = threading.local()


def _get_hostname() -> str:
    if os.path.exists("./hostname"):
        with open("./hostname") as f:
            return f.read().strip()
    return get_config().worker.hostname


def _get_available_schemas() -> list[str]:
    return list(get_config().schemas.keys())


def _get_new_jobs_sql() -> tuple[str, tuple]:
    hostname = _get_hostname()
    available_schemas = _get_available_schemas()
    schema_filter = " AND schema = ANY(%s)" if available_schemas else ""
    params = (available_schemas,) if available_schemas else ()
    sql = f"""
        WITH next_job AS (
            SELECT id, request, schema
            FROM template_jobs
            WHERE taken_by IS NULL{schema_filter}
            ORDER BY issued_at
            LIMIT 1
            FOR UPDATE SKIP LOCKED
        )
        UPDATE template_jobs t
        SET taken_by = '{hostname}',
            taken_at = now(),
            status = 'in-progress'
        FROM next_job
        WHERE t.id = next_job.id
        RETURNING t.id, t.request, t.schema;
    """
    return sql, params


def _get_incomplete_jobs_sql() -> tuple[str, tuple]:
    hostname = _get_hostname()
    available_schemas = _get_available_schemas()
    schema_filter = " AND schema = ANY(%s)" if available_schemas else ""
    params = (available_schemas,) if available_schemas else ()
    sql = f"""
        WITH next_job AS (
            SELECT id, request, schema
            FROM template_jobs
            WHERE taken_by = '{hostname}' AND status = 'in-progress'{schema_filter}
            ORDER BY issued_at
            LIMIT 1
            FOR UPDATE SKIP LOCKED
        )
        UPDATE template_jobs t
        SET taken_at = now()
        FROM next_job
        WHERE t.id = next_job.id
        RETURNING t.id, t.request, t.schema;
    """
    return sql, params


def _get_queue_connection() -> psycopg.Connection:
    """Thread-local connection to the job queue database (pg.rm.cab)."""
    if not hasattr(_local, "queue_conn") or _local.queue_conn.closed:
        cfg = get_config().job_queue
        _local.queue_conn = psycopg.connect(
            host=cfg.host,
            port=cfg.port,
            dbname=cfg.database,
            user=cfg.user,
            password=cfg.password,
            autocommit=True,
            row_factory=dict_row,
        )
    return _local.queue_conn


def _run_pg_query(
    request: contracts.TimeQueryRequest,
    db_name: str,
    job_id: int,
) -> contracts.TimeQueryResponse:
    """Execute a TimeQueryRequest against local PostgreSQL."""
    timeout_ms = int(request.timeout_secs * 1000)

    try:
        # Connect to the local database (e.g. imdb) as the matching user.
        # autocommit=True avoids transaction overhead; statement_timeout is
        # a session-level setting and applies to all subsequent statements.
        with psycopg.connect(
            dbname=db_name,
            user=db_name,  # by convention, db name == user name (e.g. imdb/imdb)
            host="localhost",
            autocommit=True,
        ) as conn:
            with conn.cursor() as cur:
                cur.execute(f"SET statement_timeout TO {timeout_ms}")

                queries = list(request.query)
                if not queries:
                    return contracts.TimeQueryResponse(
                        result=contracts.QueryErrorResponse(error="Empty query list")
                    )

                # Execute all but the last query (setup statements, etc.)
                for q in queries[:-1]:
                    if isinstance(q, contracts.PreparedQuery):
                        cur.execute(q.sql, q.params)
                    else:
                        cur.execute(q)

                # Time only the final query
                final_q = queries[-1]
                start = time.time()
                if isinstance(final_q, contracts.PreparedQuery):
                    cur.execute(final_q.sql, final_q.params)
                else:
                    cur.execute(final_q)
                elapsed_secs = time.time() - start

                query_result = None
                if request.return_result:
                    rows = cur.fetchall()
                    col_names = [desc[0] for desc in cur.description]
                    query_result = json.dumps(
                        [{col: val for col, val in zip(col_names, row)} for row in rows]
                    )

                return contracts.TimeQueryResponse(
                    result=contracts.QueryCompleteResponse(
                        elapsed_secs=elapsed_secs,
                        query_result=query_result,
                    )
                )

    except psycopg.errors.QueryCanceled:
        return contracts.TimeQueryResponse(
            result=contracts.QueryTimeoutResponse(elapsed_secs=request.timeout_secs)
        )
    except Exception as e:
        return contracts.TimeQueryResponse(
            result=contracts.QueryErrorResponse(error=str(e))
        )


def process_job(
    conn: psycopg.Connection,
    get_job_sql: str,
    sql_params: tuple = (),
) -> bool:
    """Try to acquire and process one job. Returns True if a job was processed."""
    acquire_start = time.time()
    job = None
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute(get_job_sql, sql_params)
            job = cur.fetchone()
            if not job:
                return False
    print(f"Job {job['id']}: Acquired in {(time.time() - acquire_start)*1000:.1f}ms")

    try:
        request = contracts.Request.validate_python(job["request"])
    except Exception as e:
        print(f"Job {job['id']}: Invalid request: {e}")
        return False

    schema = job.get("schema") or getattr(request, "db_schema", "JOB")

    # RunSQLRequests use DuckDB-specific SQL for predicate resolution; skip them.
    # A DuckDB worker handles these and populates the predicate_values cache so
    # that Postgres workers never need to resolve raw predicate SQL themselves.
    if isinstance(request, contracts.RunSQLRequest):
        print(f"Job {job['id']}: Skipping RunSQLRequest (handled by DuckDB worker)")
        # Put the job back so the DuckDB worker can pick it up
        with conn.transaction():
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE template_jobs SET status = 'issued', taken_by = NULL, taken_at = NULL WHERE id = %s",
                    (job["id"],),
                )
        return True

    if not isinstance(request, contracts.TimeQueryRequest):
        print(f"Job {job['id']}: Unknown request type {type(request)}, skipping")
        return False

    # Map schema name → local Postgres db name via config schemas dict
    schemas = get_config().schemas
    db_name = schemas.get(schema)
    if db_name is None:
        print(f"Job {job['id']}: Unknown schema '{schema}', available: {list(schemas.keys())}")
        result = contracts.TimeQueryResponse(
            result=contracts.QueryErrorResponse(error=f"Unknown schema: {schema}")
        )
    else:
        exec_start = time.time()
        result = _run_pg_query(request, db_name, job_id=job["id"])
        print(f"Job {job['id']}: Executed in {(time.time() - exec_start)*1000:.1f}ms")

    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE template_jobs SET status = 'complete', result = %s, finished_at = now() WHERE id = %s RETURNING id",
                (result.model_dump_json(), job["id"]),
            )
            completed_id = cur.fetchone()["id"]
            cur.execute(f"NOTIFY job_complete, '{completed_id}'")
    print(f"Job {job['id']}: Result committed")
    return True


def check_for_incomplete_jobs(conn: psycopg.Connection) -> None:
    print("Checking for incomplete jobs from previous crash...")
    sql, params = _get_incomplete_jobs_sql()
    while process_job(conn, sql, params):
        pass
    print("No incomplete jobs found")


def monitor_jobs(job_queue: Queue) -> None:
    """Listen for new_job notifications and signal the processor thread."""
    sel = selectors.DefaultSelector()
    while True:
        try:
            conn = _get_queue_connection()
            with conn.cursor() as cur:
                cur.execute("LISTEN new_job")
            sel.register(conn, selectors.EVENT_READ)
            while True:
                events = sel.select()
                if not events:
                    continue
                for notify in conn.notifies():
                    if notify.channel == "new_job":
                        job_queue.put("check")
        except Exception as e:
            print(f"Monitor connection error: {e}")
            time.sleep(1)
        finally:
            try:
                sel.unregister(conn)
            except Exception:
                pass


def process_jobs(job_queue: Queue) -> None:
    sql, params = _get_new_jobs_sql()
    while True:
        try:
            conn = _get_queue_connection()
            while True:
                if process_job(conn, sql, params):
                    continue
                try:
                    job_queue.get(timeout=0.1)
                    print("Received NOTIFY of new job")
                except Exception:
                    continue
        except Exception as e:
            print(f"Process connection error: {e}")
            time.sleep(1)


def main() -> None:
    hostname = _get_hostname()
    print(f"{hostname} (pg_worker_template) is waiting for jobs...")

    max_retries = 10
    retry_delay = 2
    for attempt in range(max_retries):
        try:
            conn = _get_queue_connection()
            check_for_incomplete_jobs(conn)
            break
        except Exception as e:
            if attempt < max_retries - 1:
                print(f"Connection attempt {attempt + 1} failed: {e}. Retrying in {retry_delay}s...")
                time.sleep(retry_delay)
            else:
                print(f"Failed to connect after {max_retries} attempts")
                raise

    job_queue: Queue = Queue()

    monitor_thread = threading.Thread(target=monitor_jobs, args=(job_queue,), daemon=True)
    monitor_thread.start()

    process_jobs(job_queue)


if __name__ == "__main__":
    main()
