"""Restart-safe Colab bootstrap for the Stack adversarial-query reproduction.

Paste this entire file into one Colab cell, or upload it and run:

    %run /content/genadversarialqueriesbo_resume.py

Expected persistent Google Drive layout::

    MyDrive/adversarial-query-data/
      stack.duckdb
      cpu-artifacts/
        stack_results.csv
        stack_embedded.parquet
        train_stack.txt
        val_stack.txt
        workload.db
      trained-models/
        latest-stack-query-decoder.txt
        latest-stack-plan-vae.txt

The script recreates the disposable Colab state, starts vLLM, PostgreSQL, and
the DuckDB worker, performs service smoke tests, and resumes with the real
default-plan versus witness-plan Stack oracle preflight.

It intentionally does not make a paid OpenAI request.  The decoder smoke test
uses a previously saved embedding.  Keep this cell running until it prints the
final READY message; initial setup and the 17 GiB database copy can take a while.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import textwrap
import time
from urllib.error import URLError
from urllib.request import urlopen


REPO = Path("/content/adversarial-queries")
REPO_URL = "https://github.com/nathanwilk7/adversarial-queries.git"
REPO_BRANCH = "codex/stack-cpu-repro"
DRIVE_ROOT = Path("/content/drive/MyDrive/adversarial-query-data")
CPU_BACKUP = DRIVE_ROOT / "cpu-artifacts"
MODEL_BACKUP_ROOT = DRIVE_ROOT / "trained-models"
# Reuse the environment created by the earlier notebook when it survived in the
# current runtime.  On a genuinely fresh Colab VM, create a dedicated runtime
# environment instead.
PREVIOUS_ENV_DIR = Path("/content/advq-training-env")
ENV_DIR = (
    PREVIOUS_ENV_DIR
    if (PREVIOUS_ENV_DIR / "bin/python").exists()
    else Path("/content/advq-runtime-env")
)
PYTHON = ENV_DIR / "bin/python"
UV_CANDIDATES = (
    Path("/usr/local/bin/uv"),
    Path("/root/.local/bin/uv"),
)
LOCAL_ARTIFACTS = Path("/content/advq-artifacts")
LOCAL_DB = REPO / "workload/stack/stack.duckdb"
VLLM_LOG = Path("/content/vllm-stack.log")
VLLM_PID = Path("/content/vllm-stack.pid")
WORKER_LOG = Path("/content/duckdb-worker.log")
WORKER_PID = Path("/content/duckdb-worker.pid")


def section(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}", flush=True)


def run(
    command: list[str | Path],
    *,
    cwd: Path | str | None = None,
    env: dict[str, str] | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess:
    rendered = [str(item) for item in command]
    print("+", " ".join(rendered), flush=True)
    process = subprocess.Popen(
        rendered,
        cwd=cwd,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        bufsize=1,
    )
    assert process.stdout is not None
    for line in process.stdout:
        print(line, end="", flush=True)
    return_code = process.wait()
    result = subprocess.CompletedProcess(rendered, return_code)
    if check and return_code:
        raise subprocess.CalledProcessError(return_code, rendered)
    return result


def run_capture(
    command: list[str | Path],
    *,
    cwd: Path | str | None = None,
    env: dict[str, str] | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess:
    rendered = [str(item) for item in command]
    result = subprocess.run(
        rendered,
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    if check and result.returncode:
        print(result.stdout)
        print(result.stderr, file=sys.stderr)
        result.check_returncode()
    return result


def venv_env(**extra: str) -> dict[str, str]:
    environment = os.environ.copy()
    environment.update(
        {
            "PYTHONPATH": str(REPO),
            "MPLBACKEND": "Agg",
            "PYTHONUNBUFFERED": "1",
            "WANDB_MODE": "disabled",
            "WANDB_SILENT": "true",
        }
    )
    environment.update(extra)
    return environment


def run_python(
    code: str,
    *,
    cwd: Path | str = REPO,
    env: dict[str, str] | None = None,
    timeout: int | None = None,
) -> subprocess.CompletedProcess:
    result = subprocess.run(
        [str(PYTHON), "-u", "-c", textwrap.dedent(code)],
        cwd=cwd,
        env=env or venv_env(),
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    if result.stdout:
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    if result.stderr:
        print(result.stderr, file=sys.stderr, end="" if result.stderr.endswith("\n") else "\n")
    if result.returncode:
        raise RuntimeError(
            f"Python subprocess failed with exit code {result.returncode}"
        )
    return result


def process_alive(pid_path: Path) -> bool:
    if not pid_path.exists():
        return False
    try:
        pid = int(pid_path.read_text().strip())
        os.kill(pid, 0)
        return True
    except (ValueError, ProcessLookupError, PermissionError):
        return False


def http_healthy(url: str, timeout: float = 2.0) -> bool:
    try:
        with urlopen(url, timeout=timeout) as response:
            return response.status == 200
    except (URLError, TimeoutError, ConnectionError):
        return False


def tail(path: Path, count: int = 100) -> str:
    if not path.exists():
        return f"<missing log: {path}>"
    return "\n".join(path.read_text(errors="replace").splitlines()[-count:])


def runtime_dependencies_ready() -> bool:
    """Return whether the existing venv already has the pinned runtime stack."""
    if not PYTHON.exists():
        return False
    probe = run_capture(
        [
            PYTHON,
            "-c",
            (
                "import accelerate, botorch, duckdb, gpytorch, lark, lightning, loguru, matplotlib, "
                "networkx, openai, pandas, psycopg, pyarrow, pydantic, pydot, "
                "sqlglot, torch, transformers, vllm; "
                "assert transformers.__version__ == '4.55.0'; "
                "assert vllm.__version__ == '0.10.1'; "
                "assert duckdb.__version__ == '1.3.2'; "
                "assert torch.cuda.is_available()"
            ),
        ],
        check=False,
    )
    return probe.returncode == 0


def copy_large_file(source: Path, destination: Path) -> None:
    """Copy a large file with progress and an atomic final rename."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    expected = source.stat().st_size
    if destination.exists() and destination.stat().st_size == expected:
        print(f"Already restored: {destination} ({expected / 2**30:.2f} GiB)")
        return

    free = shutil.disk_usage(destination.parent).free
    reserve = 5 * 2**30
    if free < expected + reserve:
        raise RuntimeError(
            f"Not enough local disk for {source.name}: need "
            f"{(expected + reserve) / 2**30:.1f} GiB including reserve, "
            f"have {free / 2**30:.1f} GiB"
        )

    partial = destination.with_suffix(destination.suffix + ".partial")
    partial.unlink(missing_ok=True)
    copied = 0
    last_report = 0.0
    start = time.time()
    with source.open("rb") as src, partial.open("wb") as dst:
        while True:
            chunk = src.read(64 * 2**20)
            if not chunk:
                break
            dst.write(chunk)
            copied += len(chunk)
            now = time.time()
            if now - last_report >= 15:
                print(
                    f"Copied {copied / 2**30:.1f}/{expected / 2**30:.1f} GiB "
                    f"({100 * copied / expected:.0f}%)",
                    flush=True,
                )
                last_report = now
    if partial.stat().st_size != expected:
        raise RuntimeError("Database copy size mismatch")
    partial.replace(destination)
    print(f"Database restored in {(time.time() - start) / 60:.1f} minutes")


section("1. Mount Google Drive")
try:
    from google.colab import drive  # type: ignore
except ImportError as error:
    raise RuntimeError("Run this script inside Google Colab") from error

drive.mount("/content/drive", force_remount=False)
required_drive_paths = [
    DRIVE_ROOT / "stack.duckdb",
    CPU_BACKUP / "stack_results.csv",
    CPU_BACKUP / "stack_embedded.parquet",
    CPU_BACKUP / "train_stack.txt",
    CPU_BACKUP / "val_stack.txt",
    MODEL_BACKUP_ROOT / "latest-stack-query-decoder.txt",
    MODEL_BACKUP_ROOT / "latest-stack-plan-vae.txt",
]
missing = [path for path in required_drive_paths if not path.exists()]
if missing:
    raise FileNotFoundError("Missing Drive artifacts:\n" + "\n".join(map(str, missing)))


section("2. Restore repository")
if not REPO.exists():
    run(
        [
            "git",
            "clone",
            "--depth",
            "1",
            "--branch",
            REPO_BRANCH,
            REPO_URL,
            REPO,
        ]
    )
else:
    print(f"Repository already exists: {REPO}")
run(["git", "log", "-1", "--oneline"], cwd=REPO)


section("3. Recreate the Python 3.11 runtime")
if not any(path.exists() for path in UV_CANDIDATES) and shutil.which("uv") is None:
    run([sys.executable, "-m", "pip", "install", "-q", "uv"])

uv_path = shutil.which("uv")
if uv_path is None:
    uv_path = next((str(path) for path in UV_CANDIDATES if path.exists()), None)
if uv_path is None:
    raise RuntimeError("uv was installed but its executable could not be found")

if not PYTHON.exists():
    run([uv_path, "python", "install", "3.11"])
    run([uv_path, "venv", "--python", "3.11", ENV_DIR])
else:
    print(f"Reusing existing Python environment: {ENV_DIR}")

# vLLM 0.10.1 resolves to its supported torch 2.7.1 CUDA build.  Pin
# Transformers after resolution so vLLM does not pick an incompatible 5.x.
packages = [
    "vllm==0.10.1",
    # vLLM 0.10.1 requires >=4.55.0. Pin the first compatible 4.x release;
    # Transformers 5.x removes tokenizer properties used by this vLLM build.
    "transformers==4.55.0",
    "accelerate==1.8.1",
    "sentencepiece==0.2.0",
    "openai>=1.87,<2",
    "duckdb==1.3.2",
    "psycopg[binary]==3.2.9",
    "pydantic==2.11.7",
    "pyarrow==19.0.1",
    "pandas==2.2.3",
    "polars==1.30.0",
    "lark==1.2.2",
    "sqlglot==25.20.2",
    "networkx==3.4.2",
    "loguru==0.7.3",
    "matplotlib==3.10.1",
    "pydot==3.0.4",
    "peewee==3.17.9",
    "glom==24.11.0",
    "lightning==2.5.1.post0",
    "torchmetrics==1.7.1",
    "gpytorch==1.14",
    "botorch==0.14.0",
    "fire>=0.7,<1",
    "wandb>=0.19,<1",
]
if runtime_dependencies_ready():
    print(f"Pinned runtime dependencies already ready in {ENV_DIR}; skipping install")
else:
    run([uv_path, "pip", "install", "--python", PYTHON, *packages])
run_python(
    """
    import accelerate, botorch, duckdb, gpytorch, psycopg, torch, transformers, vllm
    from optimization.lolbo.lolbo import LOLBOState
    print("torch:", torch.__version__)
    print("transformers:", transformers.__version__)
    print("vllm:", vllm.__version__)
    print("accelerate:", accelerate.__version__)
    print("duckdb:", duckdb.__version__)
    print("psycopg:", psycopg.__version__)
    print("botorch:", botorch.__version__)
    print("gpytorch:", gpytorch.__version__)
    print("LOLBO import: PASS")
    print("CUDA available:", torch.cuda.is_available())
    if not torch.cuda.is_available():
        raise RuntimeError("Select an A100 GPU runtime before running this script")
    """
)


section("4. Apply durable oracle/inference repairs")
provisioning = REPO / "oracle/provisioning.py"
if not provisioning.exists():
    provisioning.write_text(
        textwrap.dedent(
            '''\
            """Execution-environment definitions for the legacy oracle."""
            from dataclasses import dataclass

            @dataclass(frozen=True)
            class ExecutionEnvironment:
                host: str
                port: int
                user: str
                password: str
            '''
        )
    )
    print(f"Created missing {provisioning}")
else:
    print(f"Already present: {provisioning}")

# The legacy direct-PostgreSQL helpers are imported by the modern objective,
# even though this run uses the job queue.  Make that import side-effect free.
legacy_oracle = REPO / "oracle/oracle.py"
legacy_source = legacy_oracle.read_text()
if "import os\n" not in legacy_source.split("from dataclasses", 1)[0]:
    legacy_source = legacy_source.replace("import asyncio\n", "import asyncio\nimport os\n", 1)
if 'PG_PASS = os.environ["PG_PASS"]' in legacy_source:
    legacy_source = legacy_source.replace(
        'PG_PASS = os.environ["PG_PASS"]',
        'PG_PASS = os.environ.get("PG_PASS", "")',
        1,
    )
legacy_oracle.write_text(legacy_source)
print("Legacy oracle import is side-effect safe")

# SQLGlot represents ALTER TABLE statements with the generic Alter node.  The
# repository referenced a class that does not exist in the pinned release.
schema_module = REPO / "workload/schema.py"
schema_source = schema_module.read_text()
if "sqlglot.expressions.AlterTable()" in schema_source:
    schema_module.write_text(
        schema_source.replace(
            "sqlglot.expressions.AlterTable()",
            "sqlglot.expressions.Alter()",
        )
    )
    print("Updated the SQLGlot ALTER expression matcher")
else:
    print("SQLGlot ALTER expression matcher already compatible")

# This checkout omits three optional benchmark schema files, but workloads.py
# eagerly constructs every workload at import time.  Fall back to the matching
# bundled schemas so Stack-only imports do not fail on unrelated benchmarks.
workloads_module = REPO / "workload/workloads.py"
workloads_source = workloads_module.read_text()
fallbacks = {
    'DSB_SCHEMA_PATH = os.path.join(DSB_DIR, "schema.sql")':
        'DSB_SCHEMA_PATH = os.path.join(DSB_DIR, "schema.sql")\n'
        'if not os.path.exists(DSB_SCHEMA_PATH):\n'
        '    DSB_SCHEMA_PATH = IMDB_SCHEMA_PATH',
    'SQLSTORM_SCHEMA_PATH = os.path.join(SQLSTORM_DIR, "sqlstorm_schema.sql")':
        'SQLSTORM_SCHEMA_PATH = os.path.join(SQLSTORM_DIR, "sqlstorm_schema.sql")\n'
        'if not os.path.exists(SQLSTORM_SCHEMA_PATH):\n'
        '    SQLSTORM_SCHEMA_PATH = STACK_SCHEMA_PATH',
    'STACK_ON_SQLSTORM_SCHEMA_PATH = os.path.join(STACK_ON_SQLSTORM_DIR, "schema.sql")':
        'STACK_ON_SQLSTORM_SCHEMA_PATH = os.path.join(STACK_ON_SQLSTORM_DIR, "schema.sql")\n'
        'if not os.path.exists(STACK_ON_SQLSTORM_SCHEMA_PATH):\n'
        '    STACK_ON_SQLSTORM_SCHEMA_PATH = STACK_SCHEMA_PATH',
}
for original, replacement in fallbacks.items():
    if replacement not in workloads_source:
        if original not in workloads_source:
            raise RuntimeError(f"Could not locate workload path assignment: {original}")
        workloads_source = workloads_source.replace(original, replacement, 1)
workloads_module.write_text(workloads_source)
print("Optional workload schema fallbacks are present")

inference_file = REPO / "optimization/query_inference/grammar_constrained_inference.py"
inference_source = inference_file.read_text()
if 'stop=["<|eot_id|>"]' not in inference_source:
    old = '''                temperature=temperature,
                extra_body={
                    "prompt_embeds": encoded_embeds,
                    "guided_grammar": grammar
                },
'''
    new = '''                temperature=temperature,
                # Training targets end with this literal sentinel. Qwen does
                # not treat it as a native EOS token.
                stop=["<|eot_id|>"],
                extra_body={
                    "prompt_embeds": encoded_embeds,
                    "guided_grammar": grammar
                },
'''
    if old not in inference_source:
        raise RuntimeError("Could not locate the vLLM completion call to repair")
    inference_file.write_text(inference_source.replace(old, new, 1))
    print("Added the trained <|eot_id|> stop sequence")
else:
    print("Stop-sequence repair already present")


section("5. Restore persistent data and model artifacts")
copy_large_file(DRIVE_ROOT / "stack.duckdb", LOCAL_DB)

artifact_destinations = {
    CPU_BACKUP / "stack_results.csv": REPO / "optimization/objectives/stack_results.csv",
    CPU_BACKUP / "stack_embedded.parquet": REPO / "training/query_decoder/data/stack_embedded.parquet",
    CPU_BACKUP / "train_stack.txt": REPO / "training/plan_vae/train_stack.txt",
    CPU_BACKUP / "val_stack.txt": REPO / "training/plan_vae/val_stack.txt",
}
workload_backup = CPU_BACKUP / "workload.db"
if workload_backup.exists():
    artifact_destinations[workload_backup] = REPO / "workload.db"

for source, destination in artifact_destinations.items():
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.exists() or destination.stat().st_size != source.stat().st_size:
        shutil.copy2(source, destination)
        print(f"Restored {destination}")
    else:
        print(f"Already restored: {destination}")

decoder_pointer = MODEL_BACKUP_ROOT / "latest-stack-query-decoder.txt"
vae_pointer = MODEL_BACKUP_ROOT / "latest-stack-plan-vae.txt"
decoder_backup = Path(decoder_pointer.read_text().strip())
vae_backup = Path(vae_pointer.read_text().strip())
if not decoder_backup.exists() or not vae_backup.exists():
    raise FileNotFoundError("A trained-model pointer targets a missing Drive directory")

weight_candidates = sorted(decoder_backup.rglob("model-*.safetensors"))
if not weight_candidates:
    weight_candidates = sorted(decoder_backup.rglob("model.safetensors"))
mapping_candidates = sorted(decoder_backup.rglob("mapping_layer_epoch_0.pt"))
if not weight_candidates or not mapping_candidates:
    raise FileNotFoundError("Decoder backup lacks model weights or the mapping layer")

decoder_source = weight_candidates[0].parent
decoder_local = LOCAL_ARTIFACTS / "stack-query-decoder"
mapping_local = LOCAL_ARTIFACTS / "mapping_layer_epoch_0.pt"
vae_local = LOCAL_ARTIFACTS / "best_64_stack.ckpt"
LOCAL_ARTIFACTS.mkdir(parents=True, exist_ok=True)
decoder_complete = (
    (decoder_local / "config.json").exists()
    and any(decoder_local.glob("*.safetensors"))
)
if not decoder_complete:
    if decoder_local.exists():
        shutil.rmtree(decoder_local)
    shutil.copytree(decoder_source, decoder_local)
else:
    print(f"Already restored: {decoder_local}")
shutil.copy2(mapping_candidates[0], mapping_local)
shutil.copy2(vae_backup / "best_64_stack.ckpt", vae_local)

run_python(
    f"""
    from pathlib import Path
    import duckdb
    path = Path({str(LOCAL_DB)!r})
    con = duckdb.connect(str(path), read_only=True)
    tables = [row[0] for row in con.execute("SHOW TABLES").fetchall()]
    comments = con.execute("SELECT COUNT(*) FROM comment").fetchone()[0]
    con.close()
    print("Tables:", tables)
    print("Comment rows:", comments)
    assert len(tables) == 10
    assert comments == 103_459_958
    print("DuckDB verified")
    """
)


section("6. Start vLLM")
health_url = "http://" + "127.0.0.1:8000/health"
models_url = "http://" + "127.0.0.1:8000/v1/models"
if not http_healthy(health_url):
    if process_alive(VLLM_PID):
        print("A recorded vLLM process exists but is not healthy; inspect the log")
        print(tail(VLLM_LOG))
        raise RuntimeError("Unhealthy recorded vLLM process")
    with socket.socket() as sock:
        if sock.connect_ex(("127.0.0.1", 8000)) == 0:
            raise RuntimeError("Port 8000 is occupied by a non-healthy process")
    log_handle = VLLM_LOG.open("w")
    process = subprocess.Popen(
        [
            str(PYTHON),
            "-m",
            "vllm.entrypoints.openai.api_server",
            "--model",
            str(decoder_local),
            "--served-model-name",
            "advq-decoder",
            "--enable-prompt-embeds",
            "--tensor-parallel-size",
            "1",
            "--dtype",
            "bfloat16",
            "--max-model-len",
            "1024",
            "--gpu-memory-utilization",
            "0.70",
            "--host",
            "127.0.0.1",
            "--port",
            "8000",
        ],
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        env=venv_env(),
        start_new_session=True,
    )
    VLLM_PID.write_text(f"{process.pid}\n")
    print(f"Started vLLM PID {process.pid}")
    for attempt in range(90):
        if process.poll() is not None:
            print(tail(VLLM_LOG, 150))
            raise RuntimeError(f"vLLM exited with code {process.returncode}")
        if http_healthy(health_url):
            break
        if attempt % 6 == 0:
            print(f"Waiting for vLLM... {attempt * 5}s", flush=True)
        time.sleep(5)
    else:
        print(tail(VLLM_LOG, 150))
        raise TimeoutError("vLLM did not become healthy")
else:
    print("Existing vLLM server is healthy")

with urlopen(models_url, timeout=10) as response:
    served = json.load(response)
served_ids = [entry["id"] for entry in served["data"]]
print("Served models:", served_ids)
if "advq-decoder" not in served_ids:
    raise RuntimeError("Port 8000 serves the wrong model")


section("7. Smoke-test grammar-constrained decoder inference")
run_python(
    f"""
    from pathlib import Path
    import numpy as np
    import pyarrow.parquet as pq
    from lark import Lark
    from grammars import get_grammar
    from optimization.query_inference.grammar_constrained_inference import GrammarConstrainedInference

    parquet = Path({str(CPU_BACKUP / 'stack_embedded.parquet')!r})
    row = pq.read_table(parquet, columns=["sql_spec", "embedding"]).slice(0, 1).to_pylist()[0]
    embedding = np.asarray(row["embedding"], dtype=np.float32)
    print("Expected query:", row["sql_spec"])
    print("Embedding shape:", embedding.shape)
    assert embedding.shape == (256,)

    inference = GrammarConstrainedInference(
        grammar_name="stack",
        model_path={str(decoder_local)!r},
        mapping_layer_path={str(mapping_local)!r},
        api_base_url="http://" + "127.0.0.1:8000/v1",
        api_model_name="advq-decoder",
    )
    generated = inference.generate_with_grammar(
        embedding_vector=embedding,
        max_tokens=128,
        temperature=0.0,
    )
    print("Generated query:", repr(generated))
    assert generated and "<|eot_id|>" not in generated
    Lark(get_grammar("stack"), start="start", parser="earley").parse(generated)
    print("Grammar-constrained decoder: PASS")
    """,
    env=venv_env(OPENAI_API_KEY="unused-for-saved-embedding-test"),
    timeout=240,
)


section("8. Install and initialize the local PostgreSQL job queue")
if shutil.which("psql") is None:
    apt_update = run(
        ["sudo", "apt-get", "update", "-qq", "-o", "Acquire::Retries=3"],
        check=False,
    )
    if apt_update.returncode:
        # Colab sometimes ships a CRAN mirror entry while that mirror is
        # mid-sync, causing an unrelated size/hash failure. PostgreSQL does
        # not need CRAN, so disable only that source in this disposable VM.
        disabled = []
        source_roots = [Path("/etc/apt/sources.list"), Path("/etc/apt/sources.list.d")]
        source_files = []
        for source_root in source_roots:
            if source_root.is_file():
                source_files.append(source_root)
            elif source_root.is_dir():
                source_files.extend(source_root.glob("*.list"))
                source_files.extend(source_root.glob("*.sources"))
        for source_file in source_files:
            try:
                contents = source_file.read_text(errors="replace")
            except OSError:
                continue
            if "cloud.r-project.org" not in contents:
                continue
            disabled_path = source_file.with_name(source_file.name + ".disabled")
            run(["sudo", "mv", source_file, disabled_path])
            disabled.append(str(disabled_path))
        if not disabled:
            raise RuntimeError(
                "APT update failed, and no failing CRAN source could be identified"
            )
        print("Temporarily disabled CRAN APT source(s):", disabled)
        run(["sudo", "apt-get", "update", "-qq", "-o", "Acquire::Retries=3"])
    run(["sudo", "apt-get", "install", "-y", "postgresql", "postgresql-client"])
run(["sudo", "service", "postgresql", "start"])
run(["pg_isready"])

role = run_capture(
    [
        "sudo",
        "-u",
        "postgres",
        "psql",
        "-tAc",
        "SELECT 1 FROM pg_roles WHERE rolname='bayesopt'",
    ]
).stdout.strip()
if role != "1":
    run(
        [
            "sudo",
            "-u",
            "postgres",
            "psql",
            "-c",
            "CREATE ROLE bayesopt LOGIN PASSWORD 'bayesopt';",
        ]
    )
else:
    run(
        [
            "sudo",
            "-u",
            "postgres",
            "psql",
            "-c",
            "ALTER ROLE bayesopt WITH LOGIN PASSWORD 'bayesopt';",
        ]
    )

database = run_capture(
    [
        "sudo",
        "-u",
        "postgres",
        "psql",
        "-tAc",
        "SELECT 1 FROM pg_database WHERE datname='bayesopt'",
    ]
).stdout.strip()
if database != "1":
    run(["sudo", "-u", "postgres", "createdb", "-O", "bayesopt", "bayesopt"])

pg_env = os.environ.copy()
pg_env["PGPASSWORD"] = "bayesopt"
table_check = run_capture(
    [
        "psql",
        "--host",
        "127.0.0.1",
        "--username",
        "bayesopt",
        "--dbname",
        "bayesopt",
        "-tAc",
        "SELECT to_regclass('public.template_jobs');",
    ],
    env=pg_env,
).stdout.strip()
if table_check != "template_jobs":
    schema_file = REPO / "oracle/pg_celery_worker/docker/postgres-init/01_create_schema.sql"
    run(
        [
            "psql",
            "--host",
            "127.0.0.1",
            "--username",
            "bayesopt",
            "--dbname",
            "bayesopt",
            "--file",
            schema_file,
        ],
        env=pg_env,
    )
else:
    print("Queue schema already exists")


section("9. Configure and start the DuckDB worker")
worker_config = REPO / "oracle/pg_celery_worker/oracle-config.json"
worker_config.write_text(
    json.dumps(
        {
            "job_queue": {
                "host": "127.0.0.1",
                "port": 5432,
                "database": "bayesopt",
                "user": "bayesopt",
                "password": "bayesopt",
            },
            "schemas": {"Stack": str(LOCAL_DB)},
            "worker": {"hostname": "colab-stack-worker-1"},
            "duckdb": {"memory_limit": "16GB"},
        },
        indent=2,
    )
    + "\n"
)

if not process_alive(WORKER_PID):
    log_handle = WORKER_LOG.open("w")
    worker = subprocess.Popen(
        [str(PYTHON), "-u", "duckdb_worker.py"],
        cwd=REPO / "oracle/pg_celery_worker/pg_worker",
        env=venv_env(WORKER_HOSTNAME="colab-stack-worker-1"),
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    WORKER_PID.write_text(f"{worker.pid}\n")
    time.sleep(4)
    if worker.poll() is not None:
        print(tail(WORKER_LOG, 150))
        raise RuntimeError(f"DuckDB worker exited with code {worker.returncode}")
    print(f"Started DuckDB worker PID {worker.pid}")
else:
    print(f"Existing DuckDB worker is running (PID {WORKER_PID.read_text().strip()})")


section("10. Smoke-test the queue and DuckDB worker")
run_python(
    """
    import json
    import time
    import psycopg
    from psycopg.rows import dict_row

    connection = psycopg.connect(
        host="127.0.0.1", port=5432, dbname="bayesopt",
        user="bayesopt", password="bayesopt", autocommit=True,
        row_factory=dict_row,
    )
    request = {
        "type": "time_query",
        "query": ["SELECT COUNT(*) AS site_count FROM site"],
        "timeout_secs": 30.0,
        "db_schema": "Stack",
        "return_result": True,
    }
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO template_jobs (request, schema) VALUES (%s::jsonb, %s) RETURNING id",
            (json.dumps(request), "Stack"),
        )
        job_id = cursor.fetchone()["id"]
        cursor.execute("SELECT pg_notify('new_job', %s)", (str(job_id),))
    print("Submitted queue job:", job_id)
    completed = None
    for attempt in range(60):
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT status, taken_by, result FROM template_jobs WHERE id=%s",
                (job_id,),
            )
            job = cursor.fetchone()
        if job["status"] == "complete":
            completed = job
            break
        time.sleep(1)
    connection.close()
    assert completed is not None, "Queue job did not complete"
    print(json.dumps(completed["result"], indent=2, default=str))
    inner = completed["result"]["result"]
    assert inner["result"] == "complete"
    assert "site_count" in inner["query_result"]
    print("Queue and DuckDB worker: PASS")
    """,
    timeout=90,
)


section("11. Import the Stack objective")
run_python(
    """
    import logging
    logging.getLogger("sqlglot").setLevel(logging.ERROR)

    from optimization.objectives.your_objective_functions import AbsoluteTimeImprovementObjective
    from oracle.adversarial_queries import get_predicate_graph
    from workload.workloads import get_workload_set
    stack = get_workload_set("Stack")
    graph = get_predicate_graph(stack)
    print("Stack tables:", stack.tables)
    assert len(stack.tables) == 10
    print("Stack join edges:", graph.number_of_edges())
    assert graph.number_of_edges() > 0
    assert graph.has_edge("answer", "question")
    print("Objective import: PASS")
    """,
    timeout=180,
)


section("12. Resume point: real default-versus-witness Stack oracle call")
run_python(
    """
    import json
    import logging
    from pathlib import Path

    logging.getLogger("sqlglot").setLevel(logging.ERROR)

    from optimization.objectives.your_objective_functions import AbsoluteTimeImprovementObjective

    log_path = Path("/content/oracle-smoke-results.csv")
    objective = AbsoluteTimeImprovementObjective(
        workload_name="ADVERSARIAL_QUERY_STACK",
        timeout_ms=10_000,
        csv_log_path=str(log_path),
        schema="Stack",
        db_backend="duckdb",
    )
    candidate = "(answer )(question )[SEP]0,1"
    print("Candidate:", candidate)
    scores, censoring = objective.query_black_box([candidate])
    print("Scores:", scores)
    print("Censoring:", censoring)
    print("Details:", json.dumps(objective.last_call_details, indent=2, default=str))
    assert len(scores) == len(censoring) == len(objective.last_call_details) == 1
    details = objective.last_call_details[0]
    assert details["default_status"] == "complete", details
    assert details["generated_status"] == "complete", details
    print("Real Stack oracle preflight: PASS")
    """,
    env=venv_env(LOG_LEVEL="INFO", ORACLE_CONCURRENCY="1"),
    timeout=120,
)


section("READY")
print(
    "All persistent artifacts are restored and the model server, PostgreSQL "
    "queue, DuckDB worker, grammar-constrained decoder, and real Stack oracle "
    "have passed. This runtime is ready for the small end-to-end Bayesian "
    "optimization smoke run.\n\n"
    f"vLLM log: {VLLM_LOG}\n"
    f"DuckDB worker log: {WORKER_LOG}\n"
    f"Plan VAE: {vae_local}\n"
    f"Query decoder: {decoder_local}\n"
    f"Mapping layer: {mapping_local}"
)
