# DuckDB Worker with PostgreSQL Job Queue

A DuckDB query execution worker that processes jobs from a PostgreSQL queue.

## Quick Start (Local Development)

The recommended setup runs PostgreSQL in Docker and the worker on the host machine.

### 1. Start PostgreSQL Queue

```bash
docker-compose up -d
```

This starts PostgreSQL on `localhost:5432`.

### 2. Configure Worker

```bash
# Use the local dev config (or create your own)
cp oracle-config.local.json oracle-config.json

# Edit paths to your DuckDB files if needed
# Default assumes: /home/jtao/phd/bayes-lqo/workload/adversarial-benchmark/*.duckdb
```

### 3. Run Worker

```bash
uv run python -m oracle.pg_celery_worker.pg_worker.duckdb_worker
```

The worker will connect to postgres on localhost:5432 and start processing jobs.

### 4. Stop PostgreSQL

```bash
docker-compose down
```
