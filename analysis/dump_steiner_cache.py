"""
dump_steiner_cache.py — Dump the query_connected_tables Steiner-resolution cache
from the job-queue database to a local JSON file for reproducibility.

Output: analysis/steiner_cache.json
Format: list of {"schema", "input_tables", "connected_tables"} objects.

Usage:
    PYTHONPATH=. uv run python analysis/dump_steiner_cache.py
"""

import json
from pathlib import Path

import psycopg

from oracle.pg_celery_worker.pg_worker.config import get_config

OUT = Path(__file__).parent / "steiner_cache.json"

if __name__ == "__main__":
    cfg = get_config().job_queue
    conn = psycopg.connect(
        host=cfg.host, port=cfg.port, dbname=cfg.database,
        user=cfg.user, password=cfg.password,
    )
    with conn.cursor() as cur:
        cur.execute(
            "SELECT schema, input_tables, connected_tables "
            "FROM query_connected_tables ORDER BY schema, input_tables"
        )
        rows = cur.fetchall()
    conn.close()

    data = [
        {"schema": schema, "input_tables": inp, "connected_tables": conn_}
        for schema, inp, conn_ in rows
    ]

    with open(OUT, "w") as f:
        json.dump(data, f)

    print(f"Dumped {len(data)} rows to {OUT}")
