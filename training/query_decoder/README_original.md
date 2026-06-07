# ADVQ Soft Prompt Fine-tuning

A framework for fine-tuning language models with embedding-based soft prompts. Given a query embedding (e.g., from OpenAI's text-embedding-3-large), this trains a model to reconstruct the original query string.

## Project Structure

```
ADVQ-finetuning/
├── configs/                    # Training configurations
│   ├── sqlstorm.yaml          # Config for SQLStorm dataset
│   └── default.yaml           # Template config
├── data/                       # Data directory (created by scripts)
│   ├── sqlstorm.csv           # Raw query data (you provide this)
│   └── sqlstorm_embedded.parquet  # Embedded data (generated)
├── scripts/                    # Utility scripts
│   ├── embed_queries.py       # Generate embeddings for queries
│   ├── run_embed.sh           # Run embedding generation
│   └── run_train.sh           # Run training
├── src/                        # Source code
│   ├── __init__.py
│   ├── model.py               # EmbeddingPromptFullModel
│   ├── dataset.py             # Dataset and collate functions
│   └── recipe.py              # Training recipe
├── outputs/                    # Training outputs (created during training)
├── train.py                    # Main training entry point
└── README.md
```

## Quick Start

### 1. Setup Environment

```bash
# Create conda environment (or use existing)
conda activate torch280

# Install additional dependencies if needed
pip install openai polars tqdm
```

### 2. Prepare Data

Place your raw query CSV file in the `data/` directory:

```bash
mkdir -p data
cp sqlstorm.csv data/sqlstorm.csv
```

The CSV should have a `query_string` column containing the queries to embed.

### 3. Generate Embeddings

Set your OpenAI API key and run the embedding script:

```bash
export OPENAI_API_KEY='your-api-key'
./scripts/run_embed.sh
```

Or run directly with custom options:

```bash
python scripts/embed_queries.py \
    --input data/sqlstorm.csv \
    --output data/sqlstorm_embedded.parquet \
    --model text-embedding-3-large \
    --dimensions 256 \
    --workers 16
```

### 4. Download Base Model

Download the Qwen2.5-0.5B-Instruct model:

```bash
mkdir -p saved_models/tt-models/Qwen
# Download model files to saved_models/tt-models/Qwen/Qwen2.5-0.5B-Instruct/
```

### 5. Run Training

```bash
# Using script (defaults to GPUs 6,7)
./scripts/run_train.sh

# Or with specific GPUs
./scripts/run_train.sh 0,1

# Or directly with tune
CUDA_VISIBLE_DEVICES="6,7" tune run --nproc_per_node 2 train.py --config configs/sqlstorm.yaml
```

## Configuration

### Key Config Options

| Option | Description | Default |
|--------|-------------|---------|
| `num_embedding_tokens` | Number of soft prompt tokens | 4 |
| `input_embedding_dim` | Embedding dimension | 256 |
| `batch_size` | Training batch size | 32 |
| `lr` | Learning rate | 2e-5 |
| `data_multiply` | Multiply dataset (simulates epochs) | 10 |
| `test_holdout` | Samples to hold out for testing | 50 |

### Creating Custom Configs

Copy `configs/default.yaml` and modify for your dataset:

```yaml
dataset:
  _component_: src.dataset.EmbeddingPromptDataset
  source: ./data/your_data.parquet  # Your embedded data
  max_seq_len: 512
  input_embedding_dim: 256
  data_multiply: 5
  test_holdout: 100
```

## Model Architecture

The `EmbeddingPromptFullModel` wraps a base transformer and adds:

1. **Mapping FFN**: A 3-layer feedforward network that maps input embeddings to the model's hidden dimension
2. **Multi-token encoding**: Each embedding is encoded as multiple tokens (default: 4) for richer representation
3. **Embedding insertion**: Soft prompt tokens are inserted at a specified position in the input sequence

## Outputs

Training produces:
- Model checkpoints in `outputs/{run_name}/`
- Mapping layer checkpoints (`mapping_layer_epoch_N.pt`)
- Training logs via WandB (configurable)

## Legacy Files

The original monolithic files are preserved for reference:
- `qwen2_5_db_reconstruct_4token_ffd.py` - Original all-in-one script
- `05b_qwen_db_recons.yaml` - Original config

## License

MIT License
