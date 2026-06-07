import json
import os
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class JobQueueConfig:
    """PostgreSQL job queue connection configuration"""
    host: str
    port: int
    database: str
    user: str
    password: str


@dataclass
class WorkerConfig:
    """Worker configuration"""
    hostname: str


@dataclass
class DuckDBConfig:
    """DuckDB configuration"""
    memory_limit: str = "4GB"


@dataclass
class Config:
    """Global configuration"""
    job_queue: JobQueueConfig
    schemas: dict[str, str]
    worker: WorkerConfig
    duckdb: DuckDBConfig


def _get_default_config() -> Config:
    """
    Get default configuration for local Docker development.

    These defaults assume:
    - PostgreSQL running on postgres:5432 (Docker service name)
    - DuckDB files in /data/duckdb/ (Docker volume mount)
    - Worker hostname is the system hostname
    """
    return Config(
        job_queue=JobQueueConfig(
            host="postgres",
            port=5432,
            database="bayesopt",
            user="bayesopt",
            password="bayesopt",
        ),
        schemas={
            "JOB": "/data/duckdb/imdb.duckdb",
            "SQLStorm": "/data/duckdb/stackoverflow.duckdb",
        },
        worker=WorkerConfig(
            hostname=socket.gethostname(),
        ),
        duckdb=DuckDBConfig(),
    )


def load_config(config_path: Optional[Path] = None) -> Config:
    """
    Load configuration from JSON file.

    Search order:
    1. Explicit config_path parameter
    2. oracle-config.json in current directory
    3. oracle-config.json in pg_worker/ directory
    4. oracle-config.json in pg_celery_worker/ directory
    5. Fall back to default config

    Args:
        config_path: Optional explicit path to config file

    Returns:
        Config object with settings loaded from file or defaults

    Raises:
        FileNotFoundError: If explicit config_path is provided but doesn't exist
        json.JSONDecodeError: If config file contains invalid JSON
        ValueError: If config file is missing required fields
    """
    # If explicit path is provided, it must exist
    if config_path is not None:
        if not config_path.exists():
            raise FileNotFoundError(f"Config file not found: {config_path}")
        search_paths = [config_path]
    else:
        # Search in multiple locations
        search_paths = [
            Path("oracle-config.json"),  # Current directory
            Path(__file__).parent / "oracle-config.json",  # pg_worker/oracle-config.json
            Path(__file__).parent.parent / "oracle-config.json",  # pg_celery_worker/oracle-config.json
        ]

    # Try to find and load config file
    for path in search_paths:
        if path.exists():
            with open(path) as f:
                data = json.load(f)

            try:
                # Get worker hostname from environment, config, or auto-generate
                worker_data = data.get("worker", {})
                hostname = (
                    os.environ.get("WORKER_HOSTNAME")  # Environment variable takes precedence
                    or worker_data.get("hostname")  # Then config file
                    or f"{socket.gethostname()}-{os.getpid()}"  # Finally auto-generate with PID
                )

                return Config(
                    job_queue=JobQueueConfig(**data["job_queue"]),
                    schemas=data["schemas"],
                    worker=WorkerConfig(hostname=hostname),
                    duckdb=DuckDBConfig(**data.get("duckdb", {})),
                )
            except KeyError as e:
                raise ValueError(
                    f"Config file {path} is missing required field: {e}"
                ) from e

    # No config file found, use defaults
    return _get_default_config()


# Global singleton instance
_config: Optional[Config] = None


def get_config() -> Config:
    """
    Get the global configuration instance.

    This function uses a singleton pattern to ensure configuration is only
    loaded once. The first call loads the config from file or defaults,
    subsequent calls return the same instance.

    Returns:
        Config object with current settings
    """
    global _config
    if _config is None:
        _config = load_config()
    return _config


def reset_config():
    """Reset the global config singleton. Useful for testing."""
    global _config
    _config = None
