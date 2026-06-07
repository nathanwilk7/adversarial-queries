# Production Docker Deployment

This directory contains Docker configuration for deploying the DuckDB worker in production environments.

**Note**: For local development, use the simplified setup in the parent directory's [README.md](../README.md) which runs only PostgreSQL in Docker and the worker on the host.

## Prerequisites

- Docker Engine 20.10+
- DuckDB database files (IMDB and/or StackOverflow datasets)
- Access to PostgreSQL job queue (can be remote or local)

## Production Deployment

### 1. Build Worker Image

```bash
# From project root (/home/jtao/phd/bayes-lqo/)

# Build production worker image
docker build -f bayes_lqo/oracle/pg_celery_worker/docker/Dockerfile.worker -t bayesopt-worker:latest .

# Tag for registry (optional)
docker tag bayesopt-worker:latest your-registry.com/bayesopt-worker:latest

# Push to registry (optional)
docker push your-registry.com/bayesopt-worker:latest
```

### 2. Deploy Configuration

Create `oracle-config.json` with production settings:

```json
{
  "job_queue": {
    "host": "pg.rm.cab",
    "port": 5432,
    "database": "bayesopt",
    "user": "bayesopt",
    "password": "your-production-password"
  },
  "schemas": {
    "JOB": "/root/imdb.duckdb",
    "SQLStorm": "/root/stackoverflow.duckdb"
  },
  "worker": {
    "hostname": "production-worker-01"
  }
}
```

### 3. Run Worker

```bash
# Run worker container
docker run -d \
  --name bayesopt-worker \
  --restart unless-stopped \
  -v /path/to/oracle-config.json:/app/oracle-config.json:ro \
  -v /path/to/duckdb/data:/root:ro \
  bayesopt-worker:latest

# View logs
docker logs -f bayesopt-worker

# Restart worker (picks up config changes)
docker restart bayesopt-worker
```

### 4. Adding New Schemas

To add support for a new dataset:

1. Update `oracle-config.json` with the new schema entry:
   ```json
   {
     "schemas": {
       "JOB": "/root/imdb.duckdb",
       "SQLStorm": "/root/stackoverflow.duckdb",
       "NewDataset": "/root/newdataset.duckdb"
     }
   }
   ```

2. Restart the worker:
   ```bash
   docker restart bayesopt-worker
   ```

No code changes needed!

## Configuration Reference

### oracle-config.json Structure

```json
{
  "job_queue": {
    "host": "postgres",        // PostgreSQL hostname
    "port": 5432,              // PostgreSQL port
    "database": "bayesopt",    // Database name
    "user": "bayesopt",        // Username
    "password": "bayesopt"     // Password
  },
  "schemas": {
    "JOB": "/data/duckdb/imdb.duckdb",              // Path to IMDB DuckDB
    "SQLStorm": "/data/duckdb/stackoverflow.duckdb"  // Path to StackOverflow DuckDB
  },
  "worker": {
    "hostname": "local-docker-worker"  // Worker identifier
  }
}
```


## Troubleshooting

### Worker can't connect to PostgreSQL

- Check network connectivity to PostgreSQL server
- Verify credentials in `oracle-config.json`
- Ensure the PostgreSQL host/port are correct

### DuckDB file not found

- Check that files exist at the paths specified in `oracle-config.json`
- Verify volume mounts in the `docker run` command
- Ensure paths are absolute, not relative

### Worker not processing jobs

- Check worker logs: `docker logs -f bayesopt-worker`
- Verify PostgreSQL is accessible and running
- Check job queue by connecting to PostgreSQL directly

## Architecture

```
┌─────────────────────┐
│   Client Code       │
│  (adversarial_      │
│   queries.py)       │
└──────────┬──────────┘
           │ Submit jobs
           ▼
┌─────────────────────┐
│   PostgreSQL        │
│  (Job Queue DB)     │
│  - template_jobs    │
│  - LISTEN/NOTIFY    │
└──────────┬──────────┘
           │ Poll jobs
           ▼
┌─────────────────────┐
│  DuckDB Worker      │
│  - Acquire jobs     │
│  - Execute queries  │
│  - Return results   │
└──────────┬──────────┘
           │ Query
           ▼
┌─────────────────────┐
│   DuckDB Files      │
│  - imdb.duckdb      │
│  - stackoverflow.db │
└─────────────────────┘
```

## Files

- [Dockerfile.worker](Dockerfile.worker) - Worker container image definition
- [postgres-init/01_create_schema.sql](postgres-init/01_create_schema.sql) - Database schema initialization
- [../oracle-config.example.json](../oracle-config.example.json) - Example configuration file
