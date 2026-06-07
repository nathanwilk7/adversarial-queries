#!/usr/bin/env python3
"""
Embed SQL queries using OpenAI's text-embedding-3-large model.

This script reads a CSV file with query strings, generates embeddings using the OpenAI API,
and saves the result as a parquet file that can be used for training.

Usage:
    python scripts/embed_queries.py --input data/sqlstorm.csv --output data/sqlstorm_embedded.parquet
    
    # With custom settings
    python scripts/embed_queries.py --input data/sqlstorm.csv --output data/sqlstorm_embedded.parquet \
        --model text-embedding-3-large --dimensions 256 --workers 16 --batch-size 10
"""

import argparse
import os
import sys
from pathlib import Path
from functools import partial
from typing import List, Optional
import multiprocessing as mp

import polars as pl
from tqdm import tqdm

try:
    from openai import OpenAI
except ImportError:
    print("Error: openai package not installed. Run: pip install openai")
    sys.exit(1)


def get_embedding(
    text: str, 
    client: OpenAI,
    model: str = "text-embedding-3-large",
    dimensions: int = 256
) -> List[float]:
    """
    Get embedding for a single text using OpenAI API.
    
    Args:
        text: Text to embed
        client: OpenAI client instance
        model: Embedding model to use
        dimensions: Output dimension of embeddings
        
    Returns:
        List of floats representing the embedding
    """
    text = text.replace("\n", " ")
    response = client.embeddings.create(
        input=[text], 
        model=model, 
        dimensions=dimensions
    )
    return response.data[0].embedding


def process_text_wrapper(
    text: str, 
    model: str = "text-embedding-3-large",
    dimensions: int = 256
) -> Optional[List[float]]:
    """
    Wrapper function for multiprocessing that creates its own client.
    
    Args:
        text: Text to embed
        model: Embedding model to use
        dimensions: Output dimension of embeddings
        
    Returns:
        Embedding list or None if error
    """
    try:
        # Each worker creates its own client
        client = OpenAI()
        return get_embedding(text, client, model, dimensions)
    except Exception as e:
        print(f"Error embedding text: {e}")
        return None


def add_embeddings_with_mp(
    df: pl.DataFrame, 
    text_column: str = "query_string",
    model: str = "text-embedding-3-large", 
    dimensions: int = 256,
    batch_size: int = 1, 
    n_processes: int = 16
) -> pl.DataFrame:
    """
    Add embeddings to a Polars DataFrame using multiprocessing with progress tracking.
    
    Args:
        df: Input DataFrame
        text_column: Column containing text to embed
        model: OpenAI embedding model to use
        dimensions: Output dimension of embeddings
        batch_size: Number of texts to process in each batch
        n_processes: Number of parallel processes
        
    Returns:
        DataFrame with added 'embedding' column
    """
    texts = df[text_column].to_list()
    
    if n_processes is None:
        n_processes = mp.cpu_count()
    
    # Create a partial function with fixed parameters
    process_func = partial(
        process_text_wrapper, 
        model=model,
        dimensions=dimensions
    )
    
    print(f"\n{'='*60}")
    print(f"Embedding Configuration:")
    print(f"  Model: {model}")
    print(f"  Dimensions: {dimensions}")
    print(f"  Total samples: {len(texts)}")
    print(f"  Workers: {n_processes}")
    print(f"  Batch size: {batch_size}")
    print(f"{'='*60}\n")
    
    # Process texts with multiprocessing and progress bar
    with mp.Pool(processes=n_processes) as pool:
        embeddings = list(tqdm(
            pool.imap(process_func, texts, chunksize=batch_size),
            total=len(texts),
            desc="Generating embeddings",
            unit="queries",
            ncols=100
        ))
    
    # Check for failed embeddings
    failed_count = sum(1 for e in embeddings if e is None)
    if failed_count > 0:
        print(f"\nWarning: {failed_count} embeddings failed to generate")
    
    return df.with_columns(embedding=pl.Series(embeddings))


def validate_embeddings(df: pl.DataFrame) -> bool:
    """
    Validate that all embeddings were generated successfully.
    
    Args:
        df: DataFrame with embedding column
        
    Returns:
        True if all embeddings are valid, False otherwise
    """
    if "embedding" not in df.columns:
        print("Error: 'embedding' column not found")
        return False
    
    null_count = df["embedding"].null_count()
    if null_count > 0:
        print(f"Warning: {null_count} null embeddings found")
        return False
    
    # Check embedding dimensions
    first_embedding = df["embedding"][0]
    if first_embedding is not None:
        print(f"Embedding dimension: {len(first_embedding)}")
    
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Embed SQL queries using OpenAI's text-embedding-3-large model",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Basic usage
    python scripts/embed_queries.py --input data/sqlstorm.csv --output data/sqlstorm_embedded.parquet
    
    # Custom settings
    python scripts/embed_queries.py --input data/sqlstorm.csv --output data/sqlstorm_embedded.parquet \\
        --model text-embedding-3-large --dimensions 256 --workers 16
        """
    )
    
    parser.add_argument(
        "--input", "-i",
        type=str,
        required=True,
        help="Path to input CSV file with query strings"
    )
    parser.add_argument(
        "--output", "-o",
        type=str,
        required=True,
        help="Path to output parquet file"
    )
    parser.add_argument(
        "--text-column",
        type=str,
        default="query_string",
        help="Name of the column containing text to embed (default: query_string)"
    )
    parser.add_argument(
        "--model",
        type=str,
        default="text-embedding-3-large",
        help="OpenAI embedding model (default: text-embedding-3-large)"
    )
    parser.add_argument(
        "--dimensions",
        type=int,
        default=256,
        help="Output embedding dimensions (default: 256)"
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=16,
        help="Number of parallel workers (default: 16)"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1,
        help="Batch size for multiprocessing (default: 1)"
    )
    parser.add_argument(
        "--target-column",
        type=str,
        default=None,
        help="Column to use as target output (renamed to 'sql_spec'). If not specified, uses text_column."
    )
    
    args = parser.parse_args()
    
    # Validate input file exists
    if not os.path.exists(args.input):
        print(f"Error: Input file not found: {args.input}")
        sys.exit(1)
    
    # Create output directory if needed
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Check for OpenAI API key
    if not os.environ.get("OPENAI_API_KEY"):
        print("Error: OPENAI_API_KEY environment variable not set")
        print("Set it with: export OPENAI_API_KEY='your-api-key'")
        sys.exit(1)
    
    print(f"Loading data from: {args.input}")
    
    # Load CSV file
    df = pl.read_csv(args.input)
    print(f"Loaded {len(df)} rows")
    print(f"Columns: {df.columns}")
    
    # Validate text column exists
    if args.text_column not in df.columns:
        print(f"Error: Column '{args.text_column}' not found in CSV")
        print(f"Available columns: {df.columns}")
        sys.exit(1)
    
    # Generate embeddings
    df = add_embeddings_with_mp(
        df,
        text_column=args.text_column,
        model=args.model,
        dimensions=args.dimensions,
        batch_size=args.batch_size,
        n_processes=args.workers
    )
    
    # Rename target column to sql_spec for compatibility with training
    target_col = args.target_column or args.text_column
    if target_col in df.columns and target_col != "sql_spec":
        df = df.rename({target_col: "sql_spec"})
        print(f"Renamed column '{target_col}' to 'sql_spec'")
    
    # Validate embeddings
    if not validate_embeddings(df):
        print("\nProceeding with available embeddings...")
        # Filter out null embeddings
        original_len = len(df)
        df = df.filter(pl.col("embedding").is_not_null())
        print(f"Filtered to {len(df)} valid samples (removed {original_len - len(df)})")
    
    # Save to parquet
    print(f"\nSaving to: {args.output}")
    df.write_parquet(args.output)
    
    print(f"\n{'='*60}")
    print("Embedding Complete!")
    print(f"  Input: {args.input}")
    print(f"  Output: {args.output}")
    print(f"  Total samples: {len(df)}")
    print(f"  Embedding dim: {args.dimensions}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
