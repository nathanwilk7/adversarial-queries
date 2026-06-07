#!/usr/bin/env python3
"""Test script to verify SQLStorm schema works using the QueryTask interface."""

import json
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from oracle.adversarial_queries import QueryTask, ensure_monitor_thread
from oracle.pg_celery_worker.pg_worker.contracts import RunSQLRequest
from logger.log import l

# Start the notification monitor thread
ensure_monitor_thread()

# SQLStorm tables (StackOverflow schema)
tables = [
    "Badges",
    "CloseReasonTypes",
    "Comments",
    "LinkTypes",
    "PostHistory",
    "PostHistoryTypes",
    "PostLinks",
    "PostTypes",
    "Posts",
    "Tags",
    "Users",
    "VoteTypes",
    "Votes",
]

print("Testing SQLStorm schema with RunSQL requests...")
print(f"Will submit count queries for {len(tables)} tables\n")

# Create and submit tasks for each table
tasks = []
for table in tables:
    request = RunSQLRequest(
        query=[f"SELECT COUNT(*) as count FROM {table}"],
        schema="SQLStorm"
    )
    task = QueryTask(request)
    job_id = task.submit()
    tasks.append((task, table))
    print(f"  Job {job_id} submitted for table: {table}")

print(f"\nSubmitted {len(tasks)} jobs. Waiting for completion...\n")

# Wait for all tasks to complete
for task, table in tasks:
    result = task.result()

    # Parse the result
    if result.result.result == "complete":
        df_json = json.loads(result.result.df_json)
        # df_json is an array of row objects, get the first row's count
        count = df_json[0]["count"]
        print(f"✓ {table:20s} - {count:,} rows")
    else:
        print(f"✗ {table:20s} - Error: {result}")

print(f"\n✓ All {len(tasks)} jobs completed!")
