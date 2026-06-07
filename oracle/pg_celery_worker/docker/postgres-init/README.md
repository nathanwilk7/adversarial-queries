# PostgreSQL Schema Initialization

This directory contains SQL scripts that initialize the PostgreSQL database schema when the container is first started.

## How It Works

PostgreSQL's official Docker image automatically executes all `.sql` and `.sh` files in `/docker-entrypoint-initdb.d/` **on first startup only** (when the data volume is empty). Files are executed in alphabetical order.

## Local Development

The provided `01_create_schema.sql` file contains a minimal schema for local development and testing. You can use it as-is to get started quickly.

## Production Deployment

For production, you should replace `01_create_schema.sql` with your production schema:

### Option 1: Export from existing database (Recommended)

```bash
# Export schema from production
pg_dump -h pg.rm.cab -U bayesopt -d bayesopt --schema-only > docker/postgres-init/01_create_schema.sql

# Start local environment with production schema
docker-compose up -d
```

### Option 2: Manual schema management

If you prefer to manage the schema manually:

1. Remove or rename the `01_create_schema.sql` file
2. Start the PostgreSQL container:
   ```bash
   docker-compose up -d postgres
   ```
3. Connect and run your schema scripts manually:
   ```bash
   docker-compose exec postgres psql -U bayesopt -d bayesopt -f /path/to/your/schema.sql
   ```

## Files

- `01_create_schema.sql` - Main schema initialization (executed first)
- `README.md` - This file

## Notes

- **Initialization only runs on first startup** when the `postgres-data` volume is empty
- To re-initialize the database, delete the Docker volume:
  ```bash
  docker-compose down -v
  ```
  ⚠️ This will **delete all data** in the database
- Subsequent container restarts will not re-run these scripts
- The schema includes tables:
  - `template_jobs` - Job queue with JSONB request/result
  - `predicate_values` - Cache for query predicates
  - `query_connected_tables` - Cache for Steiner tree join resolution

## Troubleshooting

**Problem:** Schema didn't initialize

- Check if the `postgres-data` volume already existed before first startup
- Solution: `docker-compose down -v` and then `docker-compose up -d`

**Problem:** Need to update schema after initialization

- Option 1: Connect manually and run ALTER statements
- Option 2: Delete volume and re-initialize (loses data)
