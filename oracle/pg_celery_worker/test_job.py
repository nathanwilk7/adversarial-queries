#!/usr/bin/env python3
"""Test script to submit a simple job to the queue and verify the worker processes it."""

import json
import time
import psycopg
from psycopg.rows import dict_row

# Connect to the job queue
conn = psycopg.connect(
    host="localhost",
    port=5433,
    dbname="bayesopt",
    user="bayesopt",
    password="bayesopt",
    autocommit=True,
    row_factory=dict_row,
)

# Create a simple test query
test_request = {
    "type": "time_query",
    "query": ["SELECT 1 as test"],
    "timeout_secs": 5.0,
    "schema": "JOB"
}

print("Submitting test job...")
with conn.cursor() as cur:
    cur.execute(
        """
        INSERT INTO jobs (request, status, worker)
        VALUES (%s, 'pending', NULL)
        RETURNING id
        """,
        (json.dumps(test_request),)
    )
    job_id = cur.fetchone()["id"]
    print(f"Job {job_id} submitted")

    # Notify workers
    cur.execute("NOTIFY new_job")

print("Waiting for job to complete...")
for i in range(10):
    time.sleep(1)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT status, response FROM jobs WHERE id = %s",
            (job_id,)
        )
        job = cur.fetchone()

        if job["status"] == "complete":
            print(f"\n✓ Job completed!")
            print(f"Response: {job['response']}")
            break
        elif job["status"] == "failed":
            print(f"\n✗ Job failed")
            print(f"Response: {job['response']}")
            break
        else:
            print(f"  Status: {job['status']}")
else:
    print("\n✗ Timeout waiting for job")

conn.close()
