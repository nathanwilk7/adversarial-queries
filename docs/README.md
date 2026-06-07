# Adversarial Query Generation

This directory documents the **adversarial query synthesis** pipeline: it jointly
generates a SQL query **and** an execution plan such that a Bayesian-Optimization
(BO)–discovered plan runs dramatically faster than the database's default plan,
automatically producing challenging benchmark queries.

It is built on top of the BayesLQO codebase. The **oracle side** (executing
adversarial queries on Postgres/DuckDB, schema handling, the job queue) already
lives in `oracle/adversarial_queries.py`. The pieces documented here are
the **optimizer + model side**:

- a **query-decoder LM** (fine-tuned Qwen-2.5-0.5B) that maps a query embedding to a
  grammar-constrained SQL query string, and
- a **plan VAE** (64-dim latent) that encodes/decodes integer join plans, and
- the **adversarial BO loop** that searches a joint 320-dim latent space
  (256-dim query embedding + 64-dim plan latent) to maximize a runtime-advantage
  objective.

## Architecture

```
                 OpenAI text-embedding-3-large (256-dim)
                                │
   query string  ──────────────┤ (encode)
                                ▼
        ┌─────────────── joint latent z ∈ R^320 ───────────────┐
        │   z_query ∈ R^256              z_plan ∈ R^64          │
        │       │                            │                  │
   (decode)     ▼                            ▼   (decode)       │
  query-decoder LM (Qwen-0.5B,         plan VAE (training/       │
  4 soft-prompt tokens, vLLM           64-dim, integer          │
  grammar-constrained)                 join-plan encoding)      │
        │                                    │                  │
        └──────────────► "query [SEP] plan" ◄┘                  │
                                │                               │
                                ▼                               │
        oracle/adversarial_queries.py  (DuckDB / Postgres)      │
          • decode plan → SQL FROM clause (join-graph-safe)     │
          • run default plan vs generated plan, 30s timeout     │
          • score = runtime advantage  ──────────────────────► BO (LOLBO/TuRBO)
```

The query string is decoded under a **grammar constraint** (`grammars/*.lark`) so
every sample is syntactically valid SQL for the target schema.

## Components in this repo

| Path | Role |
|------|------|
| `training/query_decoder/` | Train the query-decoder LM (embedding data-gen + torchtune soft-prompt fine-tune) |
| `grammars/` | Grammar registry + `.lark` files (IMDB grammars 1–4, SQLStorm, Stack) |
| `optimization/query_inference/` | Grammar-constrained inferencer (`GrammarConstrainedInference`, `EmbeddingMapper`) |
| `training/plan_vae/` | Plan VAE (model + `train_vae.py`) |
| `optimization/lolbo/adversarial_query_vae_objective.py` | Joint query+plan VAE objective for BO |
| `optimization/objectives/your_objective_functions.py` | `AdversarialQueryObjective` (rel) / `AbsoluteTimeImprovementObjective` (abs) |
| `optimization/scripts/adversarial_query_optimization.py` | CLI entry point for an adversarial BO run |
| `oracle/adversarial_queries.py` | Oracle: decode plan, run query, score advantage |

## Grammar / schema / model matrix

A single query-decoder model is trained **per schema**; the four IMDB grammars
share one IMDB model and differ only by the `.lark` file.

| `--grammar_name` | Tables | `--schema` (worker `db_schema`) | Query-decoder model |
|------------------|--------|---------------------------------|---------------------|
| `imdb_21table_optional` | 21 | `JOB` | IMDB model |
| `imdb_full_21table` | 21 | `JOB` | IMDB model |
| `imdb_8table_optional` | 8 | `JOB` | IMDB model |
| `imdb_8table_filtered` | 8 | `JOB` | IMDB model |
| `sqlstorm` | 12 | `SQLStorm` | SQLStorm model |
| `stack` | 10 | `Stack` | Stack model |

> **Naming gotcha:** the grammar registry's `schema` field uses `"IMDB"`, but the
> oracle worker's `db_schema` literal requires **`"JOB"`** for the IMDB database.
> Always pass `--schema JOB` for IMDB grammars, never `--schema IMDB`. See
> `optimization/scripts/adversarial_query_optimization.py` comments.

## Documentation

1. **[01_training.md](01_training.md)** — train the query-decoder LM and the plan VAE from scratch.
2. **[02_running.md](02_running.md)** — serve the model and run an adversarial optimization once both models are trained.
3. **[03_oracle.md](03_oracle.md)** — how the query execution oracle works: grammar resolution, plan decoding, job queue, and database workers.

## A note on model weights

Trained weights are **not committed** to this repository (see `.gitignore`):
fine-tuned decoder checkpoints (~940 MB each), the `mapping_layer_*.pt` files, and
the plan-VAE `*.ckpt` files are all reproducible from the training documentation
above. Train them and place them where [02_running.md](02_running.md) expects, or
point the CLI flags at your own paths.
