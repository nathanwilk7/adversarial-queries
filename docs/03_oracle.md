# The Query Execution Oracle

The oracle is the bridge between the Bayesian optimization loop and the database.
For each candidate `(query, plan)` pair proposed by BO, it resolves the grammar
output into SQL, decodes the integer plan encoding into a join order, executes both
the default plan and the witness plan against the target DBMS, and returns the
measured runtimes. It is split into two layers: a **client-side oracle**
(`oracle/adversarial_queries.py`) that runs in the same process as the BO loop, and
a **cluster of database workers** that execute queries in isolation.

---

## Architecture

```
  BO loop (lolbo_scripts/)
        │
        │  AdversarialQueryOracle.query([AdversarialQueryInput, ...])
        ▼
  oracle/adversarial_queries.py          ← runs in BO process
  ┌────────────────────────────────┐
  │ 1. Parse grammar output        │
  │ 2. Resolve predicates          │  ← cached in predicate_values table
  │ 3. Steiner tree join resolution│  ← cached in query_connected_tables table
  │ 4. Decode plan (integer → SQL) │
  │ 5. INSERT into template_jobs   │──NOTIFY new_job──►  worker machines
  │ 6. LISTEN / poll for result    │◄─NOTIFY job_complete─
  └────────────────────────────────┘
              ▲ ▼
    PostgreSQL job queue (docker-compose)
    ┌─────────────────────────────────────┐
    │  template_jobs      (job queue)     │
    │  predicate_values   (cache)         │
    │  query_connected_tables (cache)     │
    └─────────────────────────────────────┘
              ▲ ▼
  DuckDB workers (oracle/pg_celery_worker/pg_worker/duckdb_worker.py)
  PostgreSQL workers (oracle/pg_celery_worker/pg_worker/pg_worker.py)
```

One query execution involves two oracle calls in sequence — one with `plan=None`
(default plan) and one with `plan=<encoded>` (witness plan) — each going through
this pipeline independently.

---

## Client-side oracle: `AdversarialQueryOracle`

### Instantiation

```python
from oracle.adversarial_queries import AdversarialQueryOracle, get_predicate_graph, DuckDBAdapter
from workload.workloads import get_workload_set

workload_set = get_workload_set("JOB")
predicate_graph = get_predicate_graph(workload_set)  # nx.Graph: nodes=tables, edges=PK-FK join predicates
oracle = AdversarialQueryOracle(predicate_graph, adapter=DuckDBAdapter())
```

`get_predicate_graph` builds a NetworkX graph from the workload's join graph: nodes are
table names, edges carry the join predicate as a string label
(`"cast_info.movie_id = title.id"`). This graph is used for Steiner tree resolution
and for the join-graph-safe plan decoder.

The `adapter` selects the engine-specific preamble:
- `DuckDBAdapter` — emits `SET disabled_optimizers = 'join_order,build_side_probe_side'`
  before the witness-plan query to prevent DuckDB from reordering the specified join.
- `PostgresAdapter` — no preamble needed; workers run with `join_collapse_limit=1`
  in `postgresql.conf` globally.

### Submitting queries

```python
from oracle.adversarial_queries import AdversarialQueryInput

results = oracle.query([
    AdversarialQueryInput(
        llm_output="(title (production_year > 0750))(name (gender most_popular))",
        plan=None,          # None → default plan
        timeout_ms=30_000,
        db_schema="JOB",
    ),
    AdversarialQueryInput(
        llm_output="(title (production_year > 0750))(name (gender most_popular))",
        plan=[4, 7, 1, 3],  # encoded witness plan
        timeout_ms=30_000,
        db_schema="JOB",
    ),
])
```

The batch is processed in parallel using `asyncio.gather`. Results are
`contracts.TimeQueryResult` values — one of `QueryCompleteResponse(elapsed_secs)`,
`QueryTimeoutResponse(elapsed_secs)`, or `QueryErrorResponse(error)`.

### Step-by-step: what happens inside `query()`

**1. Parse the grammar output.**
The `llm_output` string is the raw grammar-constrained output from the query decoder,
e.g. `(title (production_year > 0750))(name (gender most_popular))`. A Lark parser
(`parsing_grammar` at the top of `adversarial_queries.py`) extracts the list of
tables and their filter predicates (integer comparisons, string equality, timestamp
comparisons, or enum equality).

**2. Resolve predicate values.**
Grammar predicates are abstract (e.g. `production_year > 0750` where `0750` means
the 75th percentile). The oracle converts these to concrete SQL predicates by
running a lookup query against the target database — e.g.
`SELECT quantile_disc(production_year, 0.75) AS val FROM title`. Results are cached
in the `predicate_values` table in the PostgreSQL job queue database, keyed by
`(schema, table_name, column_name, predicate_name)`. All predicate lookups within a
batch are dispatched concurrently via `asyncio.gather`.

Predicate types and their SQL translation:

| Grammar type | Example | SQL |
|---|---|---|
| `int` with keyword | `production_year > median` | `SELECT median(production_year) FROM title` |
| `int` with percentile | `production_year > 0750` | `SELECT quantile_disc(production_year, 0.75) FROM title` |
| `str` with `most_popular` | `gender most_popular` | `SELECT gender … ORDER BY count(*) DESC LIMIT 1` |
| `str` with `random` | `gender random` | median-by-count (deterministic) |
| `timestamp` | `creation_date t> median` | `SELECT median(creation_date) FROM …` |
| `enum` | `type "movie"` | literal string, no lookup needed |

**3. Resolve joins (Steiner tree).**
The grammar output only specifies the tables the user directly requested. Tables may
not all be directly connected in the PK-FK join graph (e.g. `title` and `name` have
no direct FK relationship in IMDB). The oracle computes the Steiner tree of the
join graph over the requested tables using `networkx.approximation.steiner_tree`,
which finds the minimum set of additional tables needed to connect them. Join
predicates for all edges in the resulting subgraph are added to the WHERE clause.

Steiner tree results are cached in the `query_connected_tables` table, keyed by
`(schema, sorted(input_tables))`. On a cache hit the tree lookup is skipped entirely.

**4. Build the SQL template.**
After steps 1–3, the oracle has all the WHERE clause fragments (filter predicates +
join predicates) and the full list of connected tables. It constructs:

```sql
SELECT count(*) FROM {} WHERE <predicate1> AND <predicate2> AND ...
```

where `{}` is a format placeholder for the FROM clause (filled in differently for
default vs. witness plans).

**5. Decode the plan (witness plan only).**
For `plan=None` the FROM clause is simply a comma-separated table list (letting the
DBMS choose its own join order).

For `plan=<encoded>` the integer list is decoded into a binary join tree using
`HashProbeStackMachineCodec`. The codec is a SELFIES-style total mapping: every
integer list decodes to *some* join tree over the query's tables, handling
out-of-bounds indices via hash-probing. The resulting tree is formatted as a nested
SQL JOIN expression that the DBMS must execute in that exact order (enforced by the
adapter's preamble statements).

For SQLStorm and Stack schemas, a **join-graph-safe** variant of the decoder is used
instead. This additional constraint ensures that no intermediate join step creates a
Cartesian product — at each step, the decoder checks whether the chosen right-hand
subtree is joinable with the left-hand side (i.e., shares at least one PK-FK edge),
and if not, deterministically remaps to a joinable component. This prevents OOM
errors in DuckDB when join reordering is disabled.

**6. Submit to the job queue and wait.**
The resolved SQL is wrapped in a `TimeQueryRequest` (Pydantic model) and inserted
into the `template_jobs` table with a `NOTIFY new_job` signal. The oracle then waits
for the result using PostgreSQL `LISTEN job_complete` with a polling fallback (1s
interval). A background monitor thread receives `NOTIFY job_complete` signals from
workers and wakes the waiting coroutine.

---

## Job queue database

The PostgreSQL job queue is the coordination point between the BO process and the
worker machines. Its schema (`oracle/pg_celery_worker/docker/postgres-init/01_create_schema.sql`):

| Table | Purpose |
|-------|---------|
| `template_jobs` | One row per query execution; written by the oracle, claimed and updated by workers |
| `predicate_values` | Cache for resolved abstract predicate values (e.g. `median(production_year)`) |
| `query_connected_tables` | Cache for Steiner tree results |

`template_jobs` columns of note:
- `request` (JSONB) — serialized `TimeQueryRequest` or `RunSQLRequest`
- `status` — `issued` → `in-progress` → `complete`
- `schema` — `"JOB"`, `"SQLStorm"`, `"JOB-Complex"`, or `"Stack"` — used by workers to select the right database file
- `taken_by` — worker hostname (used for crash recovery)
- `result` (JSONB) — serialized `TimeQueryResponse`

Workers use `SELECT … FOR UPDATE SKIP LOCKED` to atomically claim jobs without
contention. `NOTIFY new_job` wakes idle workers immediately; `NOTIFY job_complete`
with the job ID as payload wakes the waiting oracle client.

### Starting the job queue locally

```bash
cd oracle/pg_celery_worker/
docker-compose up -d    # starts PostgreSQL on localhost:5432
docker-compose down     # stop when done
```

The init SQL in `docker/postgres-init/01_create_schema.sql` runs automatically on
first start. For a production cluster, export your existing schema with
`pg_dump … --schema-only` and replace that file's contents.

---

## Workers

Workers are long-running processes that poll the job queue, execute queries, and
write results back. They are configured via `oracle-config.json`.

### DuckDB worker

`oracle/pg_celery_worker/pg_worker/duckdb_worker.py`

Runs each query in a **child process** (not a thread) using `multiprocessing.Process`.
This ensures that a timed-out or crashing query can be hard-killed without affecting
the worker process itself. The child process opens the DuckDB file in `read_only=True`
mode, executes the statement list from the request, and returns the result via a
`multiprocessing.Queue`. If the child does not respond within `timeout_secs`, the
parent terminates it and returns a `QueryTimeoutResponse`.

```bash
# Run from repo root
uv run python -m oracle.pg_celery_worker.pg_worker.duckdb_worker
```

### PostgreSQL worker

`oracle/pg_celery_worker/pg_worker/pg_worker.py`

Structured identically but executes queries against a PostgreSQL server instead of
a DuckDB file. Join-order locking relies on `join_collapse_limit=1` being set in
`postgresql.conf` on the target server; no per-query SET is needed.

### Worker configuration

Workers look for `oracle-config.json` in the current directory,
`pg_worker/oracle-config.json`, or `pg_celery_worker/oracle-config.json`
(in that order). Copy `oracle-config.example.json` and fill in:

```json
{
  "job_queue": {
    "host": "localhost",
    "port": 5432,
    "database": "bayesopt",
    "user": "bayesopt",
    "password": "bayesopt"
  },
  "schemas": {
    "JOB":      "/path/to/imdb.duckdb",
    "SQLStorm": "/path/to/stackoverflow.duckdb",
    "Stack":    "/path/to/stack.duckdb"
  },
  "worker": { "hostname": "my-worker-01" },
  "duckdb": { "memory_limit": "32GB" }
}
```

- `schemas` maps the `db_schema` field from each job to the local DuckDB file path.
  A worker only picks up jobs whose `schema` appears in its `schemas` map, so you
  can run IMDB-only and Stack-only worker pools on different machines.
- `hostname` identifies which worker claimed a job (used for crash recovery on restart).
- `memory_limit` is passed as `SET memory_limit='32GB'` in every DuckDB connection.

### Running a worker cluster

In the paper, 20 database worker machines each ran one DuckDB worker process,
connected to a shared PostgreSQL job queue. No additional orchestration is needed:
workers are stateless and self-coordinating via the job queue. To add capacity,
start more workers pointing at the same `job_queue` host.

For crash recovery, when a worker starts it first scans `template_jobs` for any
rows with `status='in-progress'` and `taken_by=<its hostname>` (left over from a
prior crash) and re-executes them before picking up new jobs.

---

## See also

- `oracle/pg_celery_worker/pg_worker/contracts.py` — Pydantic types for all request/response messages
- `oracle/pg_celery_worker/pg_worker/config.py` — config loading logic
- `codec/codec.py` — `HashProbeStackMachineCodec` and join tree types
- [01_training.md](01_training.md) — training the models whose outputs the oracle executes
- [02_running.md](02_running.md) — end-to-end BO run setup, including oracle prerequisites
