#!/bin/bash
# Run training for SQLStorm dataset
#
# Usage:
#   ./scripts/run_train.sh                    # Uses default GPUs 6,7
#   ./scripts/run_train.sh 0,1                # Uses GPUs 0,1
#   ./scripts/run_train.sh 0,1,2,3            # Uses 4 GPUs
#
# Prerequisites:
#   - Conda environment with torchtune installed
#   - Embedded data at data/sqlstorm_embedded.parquet
#   - Base model at saved_models/tt-models/Qwen/Qwen2.5-0.5B-Instruct/

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

# Parse GPU argument
GPUS="${1:-6,7}"
IFS=',' read -ra GPU_ARRAY <<< "$GPUS"
NUM_GPUS=${#GPU_ARRAY[@]}

# Configuration
CONFIG="configs/sqlstorm.yaml"
TRAIN_SCRIPT="train.py"

# Check if embedded data exists
if [ ! -f "data/sqlstorm_embedded.parquet" ]; then
    echo "Error: Embedded data not found at data/sqlstorm_embedded.parquet"
    echo "Run the embedding script first: ./scripts/run_embed.sh"
    exit 1
fi

echo "========================================"
echo "SQLStorm Training"
echo "========================================"
echo "Config: $CONFIG"
echo "GPUs: $GPUS ($NUM_GPUS devices)"
echo "========================================"

# Run training with distributed data parallel
CUDA_VISIBLE_DEVICES="$GPUS" tune run --nproc_per_node "$NUM_GPUS" "$TRAIN_SCRIPT" --config "$CONFIG"

echo ""
echo "Training complete!"
