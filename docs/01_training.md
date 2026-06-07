# Training the models

Two models must be trained before running adversarial optimization:

1. the **query-decoder LM** (a fine-tuned Qwen-2.5-0.5B that turns a query embedding into a SQL query string), and
2. the **plan VAE** (a 64-dim VAE over integer join-plan encodings).

Both are trained **once per schema** (IMDB / SQLStorm / Stack).

---

## Part A — Query-decoder LM

### Model

- Base: **Qwen-2.5-0.5B-Instruct** (hidden size 896).
- A 3-layer FFN "mapping layer" projects a **256-dim OpenAI embedding** to
  **4 soft-prompt tokens** (`256 → 512 → 512 → 4×896`), which are spliced into the
  prompt after the header. The whole model + FFN are **fully fine-tuned** jointly
  (not LoRA).
- Training objective: reconstruct the query string from its embedding
  (teacher-forced cross-entropy on the assistant span only).

The training recipe lives in `training/query_decoder/` (a self-contained
[torchtune](https://github.com/pytorch/torchtune) project).

### Prerequisites

```bash
cd training/query_decoder/

# 1. A Python env with torchtune + torch installed (SEPARATE from the optimization
#    Docker image — fine-tuning uses torchtune's `tune run` launcher). See
#    training/query_decoder/requirements.txt; production used torch 2.8 + Python 3.11.
#        pip install -r requirements.txt

# 2. The base model, in torchtune's expected layout:
#    saved_models/tt-models/Qwen/Qwen2.5-0.5B-Instruct/{model.safetensors,vocab.json,merges.txt,...}
#    e.g. download with the HF CLI:
#    huggingface-cli download Qwen/Qwen2.5-0.5B-Instruct \
#        --local-dir saved_models/tt-models/Qwen/Qwen2.5-0.5B-Instruct

# 3. An OpenAI API key for the embedding step:
export OPENAI_API_KEY='...'
```

### Step 1 — Prepare a query corpus

Produce a CSV with (at least) a `query_string` column — one SQL query per row, in
the grammar's serialized form. The corpus defines the distribution the decoder
learns to invert. (Schemas used in the paper draw queries from the workload
generator; any large, schema-valid query set works.)

```
data/<schema>.csv          # columns: query_string[, ...]
```

### Step 2 — Generate embeddings

Embed each query with OpenAI `text-embedding-3-large` reduced to **256 dims**, and
write a parquet that pairs each `query_string` with its `embedding`:

```bash
python scripts/embed_queries.py \
    --input  data/<schema>.csv \
    --output data/<schema>_embedded.parquet \
    --text-column query_string \
    --model text-embedding-3-large \
    --dimensions 256 \
    --workers 16
```

(`scripts/run_embed.sh` wraps this with the SQLStorm defaults; edit the paths for
your schema. `scripts/embed_queries_batch.py` is a batched variant for large
corpora.)

> The embedding model/dim used here **must match** inference: the BO loop encodes
> queries with `text-embedding-3-large` @ 256 dims too. Do not change one without
> the other.

### Step 3 — Configure

Copy a config (`configs/stack.yaml`, `configs/sqlstorm.yaml`, or
`configs/default.yaml`) and set:

- `dataset.source` → your `data/<schema>_embedded.parquet`
- `dataset.input_embedding_dim: 256`
- `num_embedding_tokens: 4`
- `tokenizer.path` / `checkpointer.checkpoint_dir` → the base-model dir
- `tokenizer.max_seq_len` → 512 for short queries (SQLStorm/Stack), 1024 for IMDB
- hyperparameters (the production runs used: IMDB `lr=2e-5, batch=20, max_seq_len=1024`;
  Stack/SQLStorm `lr=1e-4, batch=64, max_seq_len=512, data_multiply=2–5`)

### Step 4 — Fine-tune

```bash
# N = number of GPUs
CUDA_VISIBLE_DEVICES=0,1 tune run --nproc_per_node 2 train.py --config configs/stack.yaml
# or: ./scripts/run_train.sh 0,1
```

### Outputs

In `output_dir` you get a Hugging-Face model directory plus the mapping layer:

```
<output_dir>/epoch_0/                  # model.safetensors + tokenizer + configs (the served model)
<output_dir>/mapping_layer_epoch_0.pt  # the embedding→soft-prompt FFN weights
```

`mapping_layer_epoch_0.pt` is a dict with `input_embedding_dim`, `hidden_dim`,
`ffn_hidden_dim`, `num_embedding_tokens`, and `mapping_ffn` (a state-dict whose
keys are **relative**, e.g. `0.weight`, so they load directly into
`EmbeddingMapper.mapping_ffn` at inference time).

For inference, place/symlink these where the BO loop's default flags expect them
(or pass explicit paths — see [02_running.md](02_running.md)):

```
optimization/query_inference/epoch_0/                  ← <output_dir>/epoch_0/
optimization/query_inference/mapping_layer_epoch_0.pt  ← <output_dir>/mapping_layer_epoch_0.pt
```

---

## Part B — Plan VAE

A small variable-length VAE over integer join-plan encodings; 64-dim latent. It
decodes a `z_plan ∈ R^64` to a list of integers that the oracle turns into a join
tree.

### Data

A text file of plan encodings, **one plan per line, comma-separated integers**
(the same SELFIES-style encoding the codec uses). Example training/val files for
the Stack and Postgres schemas ship in `training/plan_vae/`
(`train_stack.txt`, `train_pg.txt`, `val_pg.txt`).

### Train

```bash
cd training/plan_vae/
# Edit the __main__ block of train_vae.py to point DATA_FILE/VAL_FILE at your
# plan-encoding file(s) and set the output checkpoint name, then:
python train_vae.py
```

Key settings (in `train_variable_length_vae(...)`): `latent_dim=64`,
`learning_rate=1e-4`, `batch_size=32`. The vocabulary is built automatically from
the maximum token value in the data, so **a schema with a different plan-token
range needs its own VAE** (you cannot reuse a checkpoint across vocabularies).

### Output

A Lightning checkpoint, e.g. `checkpoints/best_64_<schema>.ckpt`. Place it where
the BO loop expects it (default `training/plan_vae/checkpoints/best_64.ckpt`) or
pass `--path_to_plan_vae_statedict`.

---

Once both models exist, continue to **[02_running.md](02_running.md)**.
