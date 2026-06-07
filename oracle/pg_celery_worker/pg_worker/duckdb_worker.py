import json
import multiprocessing
import os
import queue
import selectors
import socket
import threading
import time
from queue import Queue
from threading import Timer
from typing import Optional

import duckdb
import psycopg
from psycopg.rows import dict_row

import contracts
from config import get_config

# Use 'spawn' instead of 'fork' to avoid inheriting parent process state
# (particularly PostgreSQL connections) which can cause issues
multiprocessing.set_start_method('spawn', force=True)

def _get_hostname() -> str:
    """Get worker hostname from config or hostname file."""
    if os.path.exists("./hostname"):
        with open("./hostname") as f:
            return f.read().strip()
    return get_config().worker.hostname


def _get_available_schemas() -> list[str]:
    """Get list of schemas this worker can handle."""
    return list(get_config().schemas.keys())


def _get_new_jobs_sql() -> tuple[str, tuple]:
    """Get SQL query and parameters for fetching new jobs."""
    hostname = _get_hostname()
    available_schemas = _get_available_schemas()

    if available_schemas:
        schema_filter = " AND schema = ANY(%s)"
        params = (available_schemas,)
    else:
        schema_filter = ""
        params = ()

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
    """Get SQL query and parameters for fetching incomplete jobs."""
    hostname = _get_hostname()
    available_schemas = _get_available_schemas()

    if available_schemas:
        schema_filter = " AND schema = ANY(%s)"
        params = (available_schemas,)
    else:
        schema_filter = ""
        params = ()

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

# Thread-local storage for connections
_local = threading.local()


def _get_pg_connection() -> psycopg.Connection:
    """Get a connection to the PostgreSQL database"""
    if not hasattr(_local, "pg_conn") or _local.pg_conn.closed:
        cfg = get_config().job_queue
        _local.pg_conn = psycopg.connect(
            host=cfg.host,
            port=cfg.port,
            dbname=cfg.database,
            user=cfg.user,
            password=cfg.password,
            autocommit=True,
            row_factory=dict_row,  # Use dict_row factory for all connections
        )
    return _local.pg_conn


def _execute_query_process(
    q: multiprocessing.Queue, request: contracts.RequestType, db_path: str, schema: str, memory_limit: str, job_id: int
):
    """Executes a DuckDB query in a separate process."""
    try:
        if not os.path.exists(db_path):
            raise FileNotFoundError(f"Database file not found: {db_path} for schema {schema}")

        conn = duckdb.connect(db_path, read_only=True)
        conn.execute(f"SET memory_limit='{memory_limit}'")

        if isinstance(request, contracts.TimeQueryRequest):
            start = time.time()
            for query in request.query:
                if isinstance(query, contracts.PreparedQuery):
                    conn.execute(query.sql, query.params)
                else:
                    conn.execute(query)
            elapsed = (time.time() - start) * 1000

            query_result = None
            if request.return_result:
                df = conn.df()
                query_result = df.to_json(orient="records", date_format="iso")

            result = contracts.TimeQueryResponse(
                result=contracts.QueryCompleteResponse(
                    elapsed_secs=elapsed / 1000,
                    query_result=query_result,
                ),
            )
        elif isinstance(request, contracts.RunSQLRequest):
            for query in request.query:
                if isinstance(query, contracts.PreparedQuery):
                    conn.execute(query.sql, query.params)
                else:
                    conn.execute(query)

            df = conn.df()
            df_json = df.to_json(orient="records", date_format="iso")

            result = contracts.RunSQLResponse(
                result=contracts.RunSQLCompleteResponse(
                    df_json=df_json,
                ),
            )
        else:
            raise ValueError(f"Unknown job_type: {type(request)}")

        q.put(result)

    except Exception as e:
        q.put(
            contracts.TimeQueryResponse(
                result=contracts.QueryErrorResponse(error=str(e)),
            )
        )
    finally:
        if "conn" in locals() and conn:
            conn.close()


def run_duckdb_query(request: contracts.RequestType, schema: str = "JOB", job_id: int = 0) -> contracts.ResponseType:
    """Execute a query in DuckDB with timeout using a child process"""
    q: multiprocessing.Queue = multiprocessing.Queue()

    # Get schema mapping and memory limit from config
    config = get_config()
    schemas = config.schemas
    db_path = schemas.get(schema)
    if db_path is None:
        raise ValueError(f"Unknown schema: {schema}. Valid schemas: {list(schemas.keys())}")

    memory_limit = config.duckdb.memory_limit

    p = multiprocessing.Process(
        target=_execute_query_process,
        args=(q, request, db_path, schema, memory_limit, job_id),
    )
    p.start()

    timeout_secs = 10
    if isinstance(request, contracts.TimeQueryRequest):
        timeout_secs = request.timeout_secs

    # Poll for result with timeout instead of blocking on join
    # This prevents deadlock when queue is full and child is blocked on q.put()
    start_time = time.time()
    result = None
    while time.time() - start_time < timeout_secs:
        # Check if result is available
        try:
            result = q.get(timeout=0.1)
            break
        except queue.Empty:
            pass

        # Check if process has exited
        if not p.is_alive():
            # Process died without putting result
            try:
                result = q.get_nowait()
                break
            except queue.Empty:
                # Process exited with no result - check exit code
                if p.exitcode != 0:
                    if isinstance(request, contracts.TimeQueryRequest):
                        return contracts.TimeQueryResponse(
                            result=contracts.QueryErrorResponse(
                                error=f"Process exited with code {p.exitcode}",
                            ),
                        )
                    elif isinstance(request, contracts.RunSQLRequest):
                        return contracts.RunSQLResponse(
                            result=contracts.RunSQLErrorResponse(
                                error=f"Process exited with code {p.exitcode}",
                            ),
                        )
                else:
                    if isinstance(request, contracts.TimeQueryRequest):
                        return contracts.TimeQueryResponse(
                            result=contracts.QueryErrorResponse(
                                error="Process returned no result",
                            ),
                        )
                    elif isinstance(request, contracts.RunSQLRequest):
                        return contracts.RunSQLResponse(
                            result=contracts.RunSQLErrorResponse(
                                error="Process returned no result",
                            ),
                        )

    # If we got a result, clean up and return it
    if result is not None:
        # Try a quick join first (non-blocking check)
        p.join(timeout=0.01)  # 10ms should be enough for process cleanup
        if p.is_alive():
            # Process is taking a while to exit, but we have the result
            # Just terminate it to free resources faster
            p.terminate()
            p.join(timeout=0.1)  # Wait briefly for clean termination
        return result

    # Timeout - kill the process
    p.terminate()
    p.join()
    if isinstance(request, contracts.TimeQueryRequest):
        return contracts.TimeQueryResponse(
            result=contracts.QueryTimeoutResponse(
                elapsed_secs=timeout_secs,
            ),
        )
    elif isinstance(request, contracts.RunSQLRequest):
        return contracts.RunSQLResponse(
            result=contracts.RunSQLErrorResponse(
                error="Process timed out",
            ),
        )


def process_job(
    conn: psycopg.Connection,
    get_job_sql: str,
    sql_params: tuple = (),
) -> bool:
    """Try to acquire and process a job. Returns True if a job was processed."""

    # Try to acquire a job and mark it as in progress in one query
    acquire_start = time.time()
    job = None
    with conn.transaction() as txn:
        with conn.cursor() as cur:
            cur.execute(get_job_sql, sql_params)
            job = cur.fetchone()
            if not job:
                return False
    acquire_time = time.time() - acquire_start
    print(f"Job {job['id']}: Acquired in {acquire_time*1000:.1f}ms")

    try:
        request = contracts.Request.validate_python(job["request"])
    except Exception as e:
        print(f"Job {job['id']}: Invalid request: {e}")
        return False

    # Execute the job
    try:
        exec_start = time.time()
        # Get schema from database row or request object
        schema = job.get("schema") or getattr(request, "db_schema", "JOB")
        result = run_duckdb_query(request, schema, job_id=job['id'])
        exec_time = time.time() - exec_start
        print(f"Job {job['id']}: Executed in {exec_time*1000:.1f}ms")
    except Exception as e:
        if isinstance(request, contracts.TimeQueryRequest):
            result = contracts.TimeQueryResponse(
                result=contracts.QueryErrorResponse(
                    error=f"Worker exception: {e}",
                ),
            )
        elif isinstance(request, contracts.RunSQLRequest):
            result = contracts.RunSQLResponse(
                result=contracts.RunSQLErrorResponse(
                    error=f"Worker exception: {e}",
                ),
            )
        else:
            raise ValueError(f"Unknown job type: {type(request)}")

    # Update job status
    commit_start = time.time()
    completed_id = None
    with conn.transaction() as txn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE template_jobs SET status = 'complete', result = %s, finished_at = now() WHERE id = %s RETURNING id",
                (result.model_dump_json(), job["id"]),
            )
            completed_id = cur.fetchone()["id"]
            # Notify any listeners that this job is complete with the job ID in payload
            cur.execute(f"NOTIFY job_complete, '{completed_id}'")
    commit_time = time.time() - commit_start
    print(f"Job {job['id']}: Results committed in {commit_time*1000:.1f}ms")

    total_time = time.time() - acquire_start
    print(f"Job {job['id']}: Total processing time {total_time*1000:.1f}ms")
    return True


def check_for_incomplete_jobs(conn: psycopg.Connection) -> None:
    """Check for and process any jobs that were left in-progress by this worker from a previous crash"""
    print(f"Checking for incomplete jobs from previous crash...")

    # Keep processing incomplete jobs until there are none left
    sql, params = _get_incomplete_jobs_sql()
    while process_job(conn, sql, params):
        pass

    print("No more incomplete jobs found from previous crash")


def monitor_jobs(job_queue: Queue) -> None:
    """Monitor a dedicated connection for new job notifications"""
    sel = selectors.DefaultSelector()

    while True:
        try:
            conn = _get_pg_connection()
            # Register for new job notifications
            with conn.cursor() as cur:
                cur.execute("LISTEN new_job")

            # Register connection with selector
            sel.register(conn, selectors.EVENT_READ)

            while True:
                # Wait for OS to notify us of any events
                events = sel.select()

                if not events:
                    continue

                # Process notifications if any
                for notify in conn.notifies():
                    if notify.channel == "new_job":
                        # Signal main thread to check for jobs
                        job_queue.put("check")

        except Exception as e:
            print(f"Monitor connection error: {e}")
            time.sleep(1)  # Brief delay before reconnecting
            continue
        finally:
            sel.unregister(conn)


def process_jobs(job_queue: Queue) -> None:
    """Process jobs in a dedicated connection"""
    sql, params = _get_new_jobs_sql()
    while True:
        try:
            conn = _get_pg_connection()
            while True:
                # Try to get a job
                if process_job(conn, sql, params):
                    continue

                # Wait for notification that new jobs are available
                try:
                    # Much shorter timeout since we have NOTIFY
                    job_queue.get(timeout=0.1)
                    print("Received NOTIFY of new job")
                    # Immediately check for jobs when we get a notification
                    continue
                except:
                    # Short timeout, try getting a job again
                    continue

        except Exception as e:
            print(f"Process connection error: {e}")
            time.sleep(1)  # Brief delay before reconnecting


def main() -> None:
    hostname = _get_hostname()
    print(f"{hostname} is waiting for a job...")

    # Wait for PostgreSQL to be reachable (handles Docker DNS initialization delay)
    max_retries = 10
    retry_delay = 2
    for attempt in range(max_retries):
        try:
            with _get_pg_connection() as conn:
                # First check for any incomplete jobs from a previous crash
                check_for_incomplete_jobs(conn)
            break  # Connection successful
        except Exception as e:
            if attempt < max_retries - 1:
                print(f"Connection attempt {attempt + 1} failed: {e}. Retrying in {retry_delay}s...")
                time.sleep(retry_delay)
            else:
                print(f"Failed to connect after {max_retries} attempts")
                raise

    # Create a queue for communication between monitor and processor threads
    job_queue: Queue = Queue()

    # Start the monitor thread
    monitor_thread = threading.Thread(
        target=monitor_jobs,
        args=(job_queue,),
        daemon=True,
    )
    monitor_thread.start()

    # Process jobs in the main thread
    process_jobs(job_queue)


if __name__ == "__main__":
    main()
