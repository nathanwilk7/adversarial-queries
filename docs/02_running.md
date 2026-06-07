# Running adversarial optimization

This assumes you have already trained a **query-decoder LM** and a **plan VAE** for
your target schema (see [01_training.md](01_training.md)).

## Prerequisites

- The BO Python environment (`uv sync` in the repo root, per the README).
- A running **oracle backend** for the target schema — DuckDB worker or the
  Postgres job-queue worker (see the repo README / `oracle/`).
- `OPENAI_API_KEY` exported — the loop encodes query strings with
  `text-embedding-3-large` (256-dim) at run time.
- Trained artifacts in place (or pointed at via flags):
  ```
  optimization/query_inference/epoch_0/                  # served decoder model
  optimization/query_inference/mapping_layer_epoch_0.pt  # embedding→soft-prompt FFN
  training/plan_vae/checkpoints/best_64.ckpt             # plan VAE
  ```

## Step 1 — Serve the query-decoder LM with vLLM

The decoder is driven through vLLM's OpenAI-compatible API using **prompt
embeddings** (the soft-prompt tokens) and **grammar-constrained decoding**, so the
server must be started with `--enable-prompt-embeds`:

```bash
vllm serve optimization/query_inference/epoch_0 \
    --served-model-name advq-decoder \
    --enable-prompt-embeds \
    --tensor-parallel-size 1 \
    --dtype auto \
    --port 8000
```

The BO loop talks to this server via `--api_base_url` (default
`http://localhost:8000/v1`) and `--api_model_name` (must match
`--served-model-name`). The grammar is sent per-request as `guided_grammar`; no
grammar needs to be baked into the server.

> `--enable-prompt-embeds` requires a vLLM build that supports passing
> `prompt_embeds` through `extra_body`. If your vLLM rejects the flag, upgrade/patch
> vLLM to a version that supports prompt-embedding inputs.

## Step 2 — Provide initialization data

The loop seeds BO with pre-evaluated `query [SEP] plan` points. Dispatch is by
`--schema`:

| `--schema` | Init source (relative to `optimization/scripts/`) |
|------------|---------------------------------------------|
| `JOB` (IMDB) | `../../workload/adversarial-benchmark/aggregated_init_30s_timeout.jsonl` |
| `SQLStorm` | `../objectives/sqlstorm_results.csv` |
| `Stack` | `../objectives/stack_results.csv`, **or** `--init_log_path <prior oracle-log csv>` |

Each init row is a `query_string` + comma-separated `encoded_plan` (plus runtimes
if known). Rows without runtimes are evaluated through the oracle at startup. You
generate this file once by sampling random valid `query+plan` pairs for your schema
and running them through the oracle (the same path the loop uses); pass
`--init_log_path` to reuse a previous run's `oracle_logs_*` CSV and skip
re-evaluation.

## Step 3 — Launch the BO run

```bash
cd optimization/scripts/

python adversarial_query_optimization.py \
    --grammar_name stack \
    --schema Stack \
    --task_id adversarial_query_abs \
    --db_backend duckdb \
    --path_to_query_vae_model ../query_inference/epoch_0 \
    --path_to_mapping_layer  ../query_inference/mapping_layer_epoch_0.pt \
    --path_to_plan_vae_statedict ../../training/plan_vae/checkpoints/best_64_stack.ckpt \
    --api_base_url http://localhost:8000/v1 \
    --api_model_name advq-decoder \
    --timeout_ms 30000 \
    --timeout_strategy constant --constant_timeout 30 \
    --num_initialization_points 2000 \
    --max_n_oracle_calls 4000 \
    --track_with_wandb False \
    - run_lolbo - done
```

The `- run_lolbo - done` suffix is the `python-fire` calling convention (note the
spaces): construct the object, call `run_lolbo()`, finish.

### Key flags

| Flag | Meaning |
|------|---------|
| `--grammar_name` | which `.lark` grammar (see the matrix in [README](README.md)) |
| `--schema` | oracle `db_schema`: `JOB` (IMDB) / `SQLStorm` / `Stack` — **not `IMDB`** |
| `--task_id` | objective: `adversarial_query_abs` (absolute speedup) or `adversarial_query_rel` (ratio) |
| `--timeout_ms` | per-query wall-clock cap; **30000 = the fixed 30 s timeout** (default) |
| `--db_backend` | `duckdb` or `postgres` |
| `--num_initialization_points` | BO seed size |
| `--max_n_oracle_calls` | BO budget |
| `--bsz` | acquisition batch size (default 1; for batched advq use `--bsz 10 --thompson_rejection False`) |
| `--track_with_wandb` / `--wandb_entity` / `--wandb_project_name` | W&B logging (default entity `nmaus-penn`; set your own or `--track_with_wandb False`) |

### Objectives

- **`adversarial_query_abs`** → score = `default_time − generated_time` (seconds saved).
- **`adversarial_query_rel`** → score = `default_time / generated_time` (speedup ratio).

Both run a **fixed 30 s timeout** per query rather than the censored-BO timeout
machinery used in plan optimization. A failed/timed-out plan is recorded at exactly
the timeout (no inflated penalty), so it cannot manufacture a fake advantage.

## Outputs

Per-query results stream to CSV under `optimization/scripts/`:

```
oracle_logs_rel/<timestamp>_adversarial_query_results.csv   # task_id=adversarial_query_rel
oracle_logs_abs/<timestamp>_absolute_time_results.csv       # task_id=adversarial_query_abs
```

Columns include the query, the generated plan, default vs generated runtimes, and
the advantage. Adversarial queries are the rows where the generated plan beats the
default by a meaningful margin (e.g. ≥1 s absolute or ≥2× relative).

## Quick smoke test (no real run)

Confirms the full import + arg-parse chain without a live oracle/server (it will
fail at the first oracle call, which is expected):

```bash
cd optimization/scripts/
python adversarial_query_optimization.py \
    --grammar_name stack --schema Stack --task_id adversarial_query_abs \
    --api_model_name advq-decoder \
    --num_initialization_points 3 --max_n_oracle_calls 5 \
    --track_with_wandb False \
    - run_lolbo - done
```
