"""Execution-environment definitions used by the legacy PostgreSQL oracle.

The current adversarial-query pipeline uses the PostgreSQL job queue and does
not provision machines itself.  The legacy oracle modules still annotate their
direct PostgreSQL execution helpers with ``ExecutionEnvironment``, so keep the
small connection descriptor here without introducing cloud dependencies.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ExecutionEnvironment:
    """Connection details for one directly managed PostgreSQL executor."""

    host: str
    port: int
    user: str
    password: str
