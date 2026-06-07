#!/usr/bin/env python3
"""
Convert Stack Overflow PostgreSQL dump to DuckDB.

This script:
1. Sets up a temporary PostgreSQL database
2. Restores the pg_dump file
3. Uses DuckDB's postgres_scanner to copy data from PostgreSQL to DuckDB
4. Creates indexes and statistics
"""

import os
import subprocess
import sys
import tempfile
import duckdb

def run_command(cmd, check=True):
    """Run a shell command and return the result."""
    print(f"Running: {cmd}", flush=True, flush=True)
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if check and result.returncode != 0:
        print(f"Error: {result.stderr}", flush=True, flush=True)
        sys.exit(1)
    return result

def main():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    pg_dump_file = os.path.join(script_dir, "so_pg13")
    duckdb_file = os.path.join(script_dir, "stack.duckdb")

    if not os.path.exists(pg_dump_file):
        print(f"Error: PostgreSQL dump file not found at {pg_dump_file}", flush=True)
        sys.exit(1)

    print(f"Converting {pg_dump_file} to {duckdb_file}", flush=True, flush=True)

    # Configuration
    pg_host = "localhost"
    pg_port = "5433"  # Non-standard port to avoid conflicts
    pg_user = "postgres"
    pg_password = "temp_conversion_pass"
    pg_db = "stack_temp"
    container_name = "stack_pg_converter"

    # Step 1: Start PostgreSQL in Docker
    print("\n=== Step 1: Starting PostgreSQL Docker container ===", flush=True)

    # Stop and remove existing container if it exists
    run_command(f"docker stop {container_name} 2>/dev/null", check=False)
    run_command(f"docker rm {container_name} 2>/dev/null", check=False)

    # Start new PostgreSQL container
    docker_cmd = f"""docker run -d \
        --name {container_name} \
        -e POSTGRES_PASSWORD={pg_password} \
        -e POSTGRES_DB={pg_db} \
        -p {pg_port}:5432 \
        -v {script_dir}:/data \
        postgres:13"""
    run_command(docker_cmd)

    # Wait for PostgreSQL to be ready
    print("Waiting for PostgreSQL to be ready...", flush=True)
    import time
    for i in range(30):
        result = run_command(
            f"docker exec {container_name} pg_isready -U {pg_user}",
            check=False
        )
        if result.returncode == 0:
            print("PostgreSQL is ready!", flush=True)
            break
        time.sleep(1)
    else:
        print("Error: PostgreSQL did not start in time", flush=True)
        sys.exit(1)

    # Step 2: Restore the pg_dump
    print("\n=== Step 2: Restoring pg_dump to PostgreSQL ===", flush=True)
    restore_cmd = f"docker exec {container_name} pg_restore -U {pg_user} -d {pg_db} -c /data/so_pg13"
    result = run_command(restore_cmd, check=False)
    # pg_restore might have warnings, so we don't check=True here
    if result.returncode != 0:
        print(f"pg_restore warnings (expected): {result.stderr[:500]}", flush=True)

    # Step 3: Get table list from PostgreSQL
    print("\n=== Step 3: Getting table list from PostgreSQL ===", flush=True)
    result = run_command(
        f"docker exec {container_name} psql -U {pg_user} -d {pg_db} -t -c \"SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename;\"",
        check=True
    )
    tables = [line.strip() for line in result.stdout.strip().split('\n') if line.strip()]
    print(f"Found tables: {tables}", flush=True)

    # Step 4: Create DuckDB and copy data
    print("\n=== Step 4: Creating DuckDB and copying data ===", flush=True)

    # Remove old DuckDB file if it exists
    if os.path.exists(duckdb_file):
        os.remove(duckdb_file)

    # Connect to DuckDB
    conn = duckdb.connect(duckdb_file)

    # Set memory limit to 32GB to avoid OOM
    print("Setting DuckDB memory limit to 32GB...", flush=True)
    conn.execute("SET memory_limit='32GB';")

    # Install and load postgres_scanner
    print("Installing postgres_scanner extension...", flush=True)
    conn.execute("INSTALL postgres_scanner;")
    conn.execute("LOAD postgres_scanner;")

    # Attach PostgreSQL database
    print(f"Attaching PostgreSQL database...", flush=True)
    attach_cmd = f"""
    ATTACH 'dbname={pg_db} user={pg_user} password={pg_password} host={pg_host} port={pg_port}'
    AS pg_db (TYPE POSTGRES);
    """
    conn.execute(attach_cmd)

    # Copy each table
    for table in tables:
        print(f"Copying table: {table}", flush=True)
        try:
            conn.execute(f"CREATE TABLE {table} AS SELECT * FROM pg_db.public.{table};")
            count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            print(f"  -> Copied {count:,} rows", flush=True)
        except Exception as e:
            print(f"  -> Error copying {table}: {e}", flush=True)

    # Detach PostgreSQL
    conn.execute("DETACH pg_db;")

    # Step 5: Analyze tables for statistics
    print("\n=== Step 5: Analyzing tables for statistics ===", flush=True)
    for table in tables:
        try:
            print(f"Analyzing {table}...", flush=True)
            conn.execute(f"ANALYZE {table};")
        except Exception as e:
            print(f"  -> Error analyzing {table}: {e}", flush=True)

    conn.close()

    # Step 6: Clean up Docker container
    print("\n=== Step 6: Cleaning up Docker container ===", flush=True)
    run_command(f"docker stop {container_name}", check=False)
    run_command(f"docker rm {container_name}", check=False)

    print(f"\n=== Conversion complete! ===", flush=True)
    print(f"DuckDB file created at: {duckdb_file}", flush=True)

    # Print file size
    size_mb = os.path.getsize(duckdb_file) / (1024 * 1024)
    print(f"File size: {size_mb:.2f} MB", flush=True)

if __name__ == "__main__":
    main()
