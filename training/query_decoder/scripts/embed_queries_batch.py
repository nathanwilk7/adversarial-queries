#!/usr/bin/env python3
"""
Embed SQL queries using the OpenAI Batch API (50% cheaper, no rate limits).

Three-phase workflow:
    1. submit  — upload JSONL batch files and start processing
    2. status  — check batch completion status
    3. collect — download results and assemble into parquet

Usage:
    # Phase 1: Submit batches (splits 200K queries into 4 batches of 50K)
    python scripts/embed_queries_batch.py submit \\
        --input data/stack_adversarial_vae.csv \\
        --text-column query_string \\
        --work-dir data/stack_batch_work

    # Phase 2: Check status
    python scripts/embed_queries_batch.py status --work-dir data/stack_batch_work

    # Phase 3: Collect results into parquet
    python scripts/embed_queries_batch.py collect \\
        --input data/stack_adversarial_vae.csv \\
        --output data/stack_embedded.parquet \\
        --text-column query_string \\
        --work-dir data/stack_batch_work
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

import polars as pl

try:
    from openai import OpenAI
except ImportError:
    print("Error: openai package not installed. Run: pip install openai")
    sys.exit(1)


BATCH_REQUEST_LIMIT = 50_000  # OpenAI max requests per batch


def cmd_submit(args):
    """Prepare JSONL files and submit batches to OpenAI."""
    client = OpenAI()
    work_dir = Path(args.work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    # Check for existing state
    state_path = work_dir / "batch_state.json"
    if state_path.exists():
        print(f"Batch state already exists at {state_path}")
        print("Use 'status' to check progress, or delete the work-dir to restart.")
        sys.exit(1)

    # Load CSV
    print(f"Loading data from: {args.input}")
    df = pl.read_csv(args.input)
    texts = df[args.text_column].to_list()
    total = len(texts)
    print(f"Total queries: {total}")

    # Split into chunks
    batch_size = args.batch_size
    chunks = []
    for start in range(0, total, batch_size):
        end = min(start + batch_size, total)
        chunks.append((start, end))
    print(f"Will create {len(chunks)} batch(es) of up to {batch_size} requests")

    # Write JSONL files and submit
    batches = []
    for chunk_idx, (start, end) in enumerate(chunks):
        jsonl_path = work_dir / f"batch_{chunk_idx}.jsonl"
        print(f"\nBatch {chunk_idx}: rows {start}-{end-1} ({end-start} requests)")

        # Write JSONL
        with open(jsonl_path, "w") as f:
            for i in range(start, end):
                request = {
                    "custom_id": f"q-{i}",
                    "method": "POST",
                    "url": "/v1/embeddings",
                    "body": {
                        "model": args.model,
                        "input": texts[i].replace("\n", " "),
                        "dimensions": args.dimensions,
                        "encoding_format": "float",
                    },
                }
                f.write(json.dumps(request) + "\n")
        print(f"  Wrote {jsonl_path} ({os.path.getsize(jsonl_path) / 1e6:.1f} MB)")

        # Upload file
        with open(jsonl_path, "rb") as f:
            file_obj = client.files.create(file=f, purpose="batch")
        print(f"  Uploaded as file_id: {file_obj.id}")

        # Submit batch
        batch = client.batches.create(
            input_file_id=file_obj.id,
            endpoint="/v1/embeddings",
            completion_window="24h",
        )
        print(f"  Submitted batch_id: {batch.id} (status: {batch.status})")

        batches.append({
            "chunk_idx": chunk_idx,
            "start": start,
            "end": end,
            "input_file_id": file_obj.id,
            "batch_id": batch.id,
            "jsonl_path": str(jsonl_path),
        })

    # Save state
    state = {
        "total_queries": total,
        "model": args.model,
        "dimensions": args.dimensions,
        "text_column": args.text_column,
        "batches": batches,
    }
    with open(state_path, "w") as f:
        json.dump(state, f, indent=2)
    print(f"\nState saved to {state_path}")
    print(f"Run 'status --work-dir {args.work_dir}' to check progress.")


def cmd_status(args):
    """Check the status of all submitted batches."""
    client = OpenAI()
    work_dir = Path(args.work_dir)
    state_path = work_dir / "batch_state.json"

    if not state_path.exists():
        print(f"No batch state found at {state_path}. Run 'submit' first.")
        sys.exit(1)

    with open(state_path) as f:
        state = json.load(f)

    all_done = True
    any_failed = False

    for b in state["batches"]:
        batch = client.batches.retrieve(b["batch_id"])
        status = batch.status
        counts = batch.request_counts

        completed = counts.completed if counts else 0
        failed = counts.failed if counts else 0
        total = counts.total if counts else (b["end"] - b["start"])

        print(f"Batch {b['chunk_idx']} ({b['batch_id']}): {status}  "
              f"[{completed}/{total} done, {failed} failed]")

        if status not in ("completed", "failed", "expired", "cancelled"):
            all_done = False
        if status in ("failed", "expired", "cancelled"):
            any_failed = True

    if all_done and not any_failed:
        print("\nAll batches completed! Run 'collect' to download results.")
    elif any_failed:
        print("\nSome batches failed. Check the OpenAI dashboard for details.")
    else:
        print("\nStill processing. Check again later.")


def cmd_collect(args):
    """Download completed batch results and assemble into parquet."""
    client = OpenAI()
    work_dir = Path(args.work_dir)
    state_path = work_dir / "batch_state.json"

    if not state_path.exists():
        print(f"No batch state found at {state_path}. Run 'submit' first.")
        sys.exit(1)

    with open(state_path) as f:
        state = json.load(f)

    total_queries = state["total_queries"]
    embeddings = [None] * total_queries

    for b in state["batches"]:
        batch = client.batches.retrieve(b["batch_id"])
        if batch.status != "completed":
            print(f"Batch {b['chunk_idx']} ({b['batch_id']}) is {batch.status}, not completed.")
            sys.exit(1)

        # Download output
        output_file_id = batch.output_file_id
        print(f"Batch {b['chunk_idx']}: downloading {output_file_id}...")
        content = client.files.content(output_file_id).content

        # Save raw output
        output_path = work_dir / f"batch_{b['chunk_idx']}_output.jsonl"
        with open(output_path, "wb") as f:
            f.write(content)

        # Parse results
        parsed = 0
        errors = 0
        for line in content.decode("utf-8").splitlines():
            obj = json.loads(line)
            custom_id = obj["custom_id"]
            idx = int(custom_id.split("-")[1])

            if obj.get("error"):
                errors += 1
                continue

            embedding = obj["response"]["body"]["data"][0]["embedding"]
            embeddings[idx] = embedding
            parsed += 1

        print(f"  Parsed {parsed} embeddings, {errors} errors")

    # Check for missing embeddings
    missing = sum(1 for e in embeddings if e is None)
    if missing > 0:
        print(f"\nWarning: {missing} embeddings missing")

    # Load original CSV and build parquet
    print(f"\nLoading original data from: {args.input}")
    df = pl.read_csv(args.input)

    # Add embeddings column
    df = df.with_columns(embedding=pl.Series(embeddings))

    # Filter out nulls
    if missing > 0:
        original_len = len(df)
        df = df.filter(pl.col("embedding").is_not_null())
        print(f"Filtered to {len(df)} valid samples (removed {original_len - len(df)})")

    # Rename text column to sql_spec for training compatibility
    text_col = state["text_column"]
    if text_col in df.columns and text_col != "sql_spec":
        df = df.rename({text_col: "sql_spec"})
        print(f"Renamed '{text_col}' to 'sql_spec'")

    # Validate
    first_emb = df["embedding"][0]
    if first_emb is not None:
        print(f"Embedding dimension: {len(first_emb)}")

    # Save
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(str(output_path))

    print(f"\nSaved to: {args.output}")
    print(f"Total samples: {len(df)}")


def main():
    parser = argparse.ArgumentParser(
        description="Embed queries using OpenAI Batch API (50% cheaper)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Submit
    p_submit = subparsers.add_parser("submit", help="Prepare and submit batch jobs")
    p_submit.add_argument("--input", "-i", required=True, help="Input CSV file")
    p_submit.add_argument("--text-column", default="query_string", help="Column with text")
    p_submit.add_argument("--model", default="text-embedding-3-large", help="Embedding model")
    p_submit.add_argument("--dimensions", type=int, default=256, help="Embedding dimensions")
    p_submit.add_argument("--batch-size", type=int, default=BATCH_REQUEST_LIMIT, help="Requests per batch")
    p_submit.add_argument("--work-dir", required=True, help="Working directory for batch state")

    # Status
    p_status = subparsers.add_parser("status", help="Check batch status")
    p_status.add_argument("--work-dir", required=True, help="Working directory")

    # Collect
    p_collect = subparsers.add_parser("collect", help="Download results and build parquet")
    p_collect.add_argument("--input", "-i", required=True, help="Original input CSV")
    p_collect.add_argument("--output", "-o", required=True, help="Output parquet file")
    p_collect.add_argument("--work-dir", required=True, help="Working directory")

    args = parser.parse_args()

    if not os.environ.get("OPENAI_API_KEY"):
        print("Error: OPENAI_API_KEY environment variable not set")
        sys.exit(1)

    {"submit": cmd_submit, "status": cmd_status, "collect": cmd_collect}[args.command](args)


if __name__ == "__main__":
    main()
