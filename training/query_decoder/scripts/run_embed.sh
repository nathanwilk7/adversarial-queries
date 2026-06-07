#!/bin/bash
# Run embedding generation for SQLStorm dataset
#
# Usage:
#   ./scripts/run_embed.sh
#
# Prerequisites:
#   - OPENAI_API_KEY environment variable set
#   - Python environment with openai, polars, tqdm installed

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_DIR"

# Configuration
INPUT_FILE="data/sqlstorm_larger.csv"
OUTPUT_FILE="data/sqlstorm_larger_embedded.parquet"
MODEL="text-embedding-3-large"
DIMENSIONS=256
WORKERS=16

# Check for API key
if [ -z "$OPENAI_API_KEY" ]; then
    echo "Error: OPENAI_API_KEY environment variable not set"
    echo "Set it with: export OPENAI_API_KEY='your-api-key'"
    exit 1
fi

# Create data directory if needed
mkdir -p data

# Check if input file exists
if [ ! -f "$INPUT_FILE" ]; then
    echo "Error: Input file not found: $INPUT_FILE"
    echo "Please place your sqlstorm.csv in the data/ directory"
    exit 1
fi

echo "========================================"
echo "SQLStorm Embedding Generation"
echo "========================================"
echo "Input: $INPUT_FILE"
echo "Output: $OUTPUT_FILE"
echo "Model: $MODEL"
echo "Dimensions: $DIMENSIONS"
echo "Workers: $WORKERS"
echo "========================================"

python scripts/embed_queries.py \
    --input "$INPUT_FILE" \
    --output "$OUTPUT_FILE" \
    --text-column "query_string" \
    --model "$MODEL" \
    --dimensions "$DIMENSIONS" \
    --workers "$WORKERS"

echo ""
echo "Embedding complete! Output saved to: $OUTPUT_FILE"
