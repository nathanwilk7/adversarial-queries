"""Dependency-light workload types used by Stack data generation.

The general workload module eagerly constructs every benchmark at import time.
Several of those optional benchmark files are not included in the artifact, so
Stack data generation must not import that module merely to obtain these two
data containers.
"""

from dataclasses import dataclass
from typing import Optional, Union

import networkx as nx


@dataclass
class WorkloadSchema:
    all_columns: dict[str, list[str]]
    db_join_graph: nx.Graph
    query_join_graph: nx.Graph


@dataclass
class WorkloadSpecDefinition:
    name: str
    all_tables: list[str]
    query_tables: list[tuple[str, int]]
    query_template: str
    schema: WorkloadSchema
    db: str
    db_user: str
    prewarm: bool
    pg_hint_plan_join_order: bool
    params: Optional[list[Union[str, int]]]


def default_plan(workload: WorkloadSpecDefinition) -> str:
    """Render the unhinted FROM clause for a workload definition."""
    return workload.query_template.format(
        ", ".join(
            f"{table} AS {table}{alias_num}"
            for table, num_aliases in workload.query_tables
            for alias_num in range(1, num_aliases + 1)
        )
    )
