"""
adversarial_sql.py — Reusable helpers for resolving adversarial query/plan DSL
into executable SQL for both the default (optimizer-chosen) and adversarial
(fixed join-order) plans.

Requires:
  - A live Postgres connection to the job-queue DB (for predicate values and
    Steiner-tree connected-table lookups).
  - The IMDB predicate graph (from oracle.adversarial_queries).
  - The plan codec (codec.codec.HashProbeStackMachineCodec).

Typical usage
-------------
    from adversarial_sql import AdversarialSQLResolver

    resolver = AdversarialSQLResolver()          # reads oracle-config.json
    default_sql, adv_sql, meta = resolver.resolve(dsl, plan_vector_str)
    print(meta['join_order'])   # left-to-right table list
    print(meta['sexp'])         # s-expression of the join tree
"""

import ast
import json
import os
import sys
from dataclasses import dataclass, field
from typing import Optional

import lark
import psycopg

# Make sure the package root is importable whether run from experiments/ or root
_HERE = os.path.dirname(__file__)
_ROOT = os.path.dirname(_HERE)
for _p in [_ROOT, os.path.dirname(_ROOT)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

from optimization.codec.codec import HashProbeStackMachineCodec, JoinTreeLeaf
from oracle.adversarial_queries import get_predicate_graph
from workload.workloads import IMDB_WORKLOAD_SET


# ---------------------------------------------------------------------------
# DSL grammar (mirrors the one in gap_investigation.ipynb)
# ---------------------------------------------------------------------------
_GRAMMAR = """
start: selector+
selector: "(" ident " " filter* ")"
?ident: /[a-z0-9_]+/
filter: int_filter | str_filter
int_filter: "(" ident " " intop " " intval ")"
str_filter: "(" ident " " strop ")"

!intop: "<" | ">" | "=" | "!="
!strop: "most_popular" | "random"

!intval: "first" | "median" | "last" | "mode" | /[0-9]{4}/
"""
_parser = lark.Lark(_GRAMMAR)


@dataclass
class ResolvedQuery:
    """All SQL and metadata produced by resolving one DSL + plan-vector pair."""
    default_sql: str
    adversarial_sql: str          # includes SET disabled_optimizers lines
    tables: list[str]             # connected (Steiner-tree expanded) tables
    join_order: list[str]         # left-to-right leaf traversal of plan tree
    sexp: str                     # s-expression of the plan tree
    where_clauses: list[str]      # individual predicates
    filter_preds: list[str]       # single-table filter predicates
    join_preds: list[str]         # cross-table join predicates


class AdversarialSQLResolver:
    """
    Resolves adversarial query DSL + plan vector strings into executable SQL.

    Parameters
    ----------
    config_path : str, optional
        Path to oracle-config.json.  Defaults to
        ``<repo-root>/bayes_lqo/oracle-config.json``.
    schema : str
        Postgres schema name used for predicate-value lookups (default "JOB").
    """

    def __init__(
        self,
        config_path: Optional[str] = None,
        schema: str = "JOB",
    ):
        if config_path is None:
            config_path = os.path.join(_ROOT, "oracle-config.json")
        with open(config_path) as f:
            cfg = json.load(f)["job_queue"]

        self._pg = psycopg.connect(
            host=cfg["host"],
            port=cfg["port"],
            dbname=cfg["database"],
            user=cfg["user"],
            password=cfg["password"],
            autocommit=True,
        )
        self._schema = schema
        self._predicate_graph = get_predicate_graph(IMDB_WORKLOAD_SET)
        all_tables = sorted(self._predicate_graph.nodes)
        self._codec = HashProbeStackMachineCodec(all_tables)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def resolve(self, query_dsl: str, plan_vector_str: str) -> ResolvedQuery:
        """
        Resolve a DSL query string and plan-vector string into SQL.

        Parameters
        ----------
        query_dsl : str
            e.g. ``"(complete_cast )(info_type (info random))(title )"``
        plan_vector_str : str
            The list literal from the CSV, e.g. ``"[1, 7, 1, 16, ...]"``

        Returns
        -------
        ResolvedQuery
        """
        plan_vector = ast.literal_eval(plan_vector_str)
        where_clauses, tables = self._build_where_parts(query_dsl)

        # Decode the plan vector into a join tree
        tree = self._codec.decode([(t, 1) for t in tables], plan_vector)
        join_order = _get_join_order(tree)
        sexp = _join_tree_sexp(tree)
        join_clause = tree.to_join_clause()

        where_str = "\n  AND ".join(where_clauses)

        default_sql = (
            f"SELECT count(*)\n"
            f"FROM {', '.join(tables)}\n"
            f"WHERE {where_str}"
        )

        adversarial_sql = (
            "SET disabled_optimizers = 'join_order,build_side_probe_side';\n\n"
            f"SELECT count(*)\nFROM {join_clause}\nWHERE {where_str};\n\n"
            "SET disabled_optimizers = '';"
        )

        import re
        filter_preds = [
            p for p in where_clauses
            if not re.match(r"\w+\.\w+\s*=\s*\w+\.\w+$", p.strip())
        ]
        join_preds = [
            p for p in where_clauses
            if re.match(r"\w+\.\w+\s*=\s*\w+\.\w+$", p.strip())
        ]

        return ResolvedQuery(
            default_sql=default_sql,
            adversarial_sql=adversarial_sql,
            tables=tables,
            join_order=join_order,
            sexp=sexp,
            where_clauses=where_clauses,
            filter_preds=filter_preds,
            join_preds=join_preds,
        )

    def resolve_row(self, row) -> ResolvedQuery:
        """Convenience wrapper that accepts a pandas Series (a CSV row)."""
        return self.resolve(row["query"], row["generated_plan"])

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_predicate_value(self, table: str, column: str, pred_name: str) -> str:
        with self._pg.cursor() as cur:
            cur.execute(
                "SELECT predicate_value FROM predicate_values "
                "WHERE schema=%s AND table_name=%s AND column_name=%s AND predicate_name=%s",
                (self._schema, table, column, pred_name),
            )
            row = cur.fetchone()
            if row is None:
                raise KeyError(
                    f"No stored predicate value for "
                    f"({self._schema}, {table}, {column}, {pred_name})"
                )
            return row[0]

    def _get_connected_tables(self, input_tables: list[str]) -> list[str]:
        with self._pg.cursor() as cur:
            cur.execute(
                "SELECT connected_tables FROM query_connected_tables "
                "WHERE schema=%s AND input_tables=%s",
                (self._schema, list(sorted(input_tables))),
            )
            row = cur.fetchone()
            if row is None:
                raise KeyError(
                    f"No stored connected tables for {sorted(input_tables)}"
                )
            return row[0]

    def _build_where_parts(self, query_dsl: str) -> tuple[list[str], list[str]]:
        tree = _parser.parse(query_dsl)
        where_clauses: list[str] = []
        dsl_tables: list[str] = []

        for selector in tree.children:
            table = str(selector.children[0])
            dsl_tables.append(table)
            for filt in selector.children[1:]:
                filt = filt.children[0]
                if filt.data == "int_filter":
                    col = str(filt.children[0])
                    op = str(filt.children[1].children[0])
                    pred_name = str(filt.children[2].children[0])
                    val = self._get_predicate_value(table, col, pred_name)
                    where_clauses.append(f"{table}.{col} {op} {val}")
                elif filt.data == "str_filter":
                    col = str(filt.children[0])
                    pred_name = str(filt.children[1].children[0])
                    val = self._get_predicate_value(table, col, pred_name)
                    escaped = val.replace("'", "''")
                    where_clauses.append(f"{table}.{col} = '{escaped}'")

        connected = self._get_connected_tables(dsl_tables)
        subgraph = self._predicate_graph.subgraph(connected)
        for e in subgraph.edges:
            where_clauses.append(subgraph.edges[e]["label"])

        return where_clauses, connected


# ---------------------------------------------------------------------------
# Pure tree helpers (no Postgres needed)
# ---------------------------------------------------------------------------

def _get_join_order(tree) -> list[str]:
    """Left-to-right leaf traversal of a JoinTree."""
    if isinstance(tree, JoinTreeLeaf):
        return [tree.table]
    return _get_join_order(tree.left) + _get_join_order(tree.right)


def _join_tree_sexp(tree) -> str:
    if isinstance(tree, JoinTreeLeaf):
        return tree.table
    return f"({_join_tree_sexp(tree.left)} ⋈ {_join_tree_sexp(tree.right)})"


# ---------------------------------------------------------------------------
# CLI: python adversarial_sql.py <csv> <rank>
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import argparse
    import pandas as pd

    ap = argparse.ArgumentParser(description="Resolve adversarial query SQL from a CSV row.")
    ap.add_argument("csv", help="Path to imdb_adversarial_absolute.csv")
    ap.add_argument("rank", type=int, help="0-based rank (row index after sorting by absolute_advantage_ms desc)")
    args = ap.parse_args()

    df = pd.read_csv(args.csv)
    df_sorted = df.sort_values("absolute_advantage_ms", ascending=False).reset_index(drop=True)
    row = df_sorted.iloc[args.rank]

    print(f"DSL:             {row['query']}")
    print(f"Default ms:      {row['default_time_ms']:,.0f}")
    print(f"Adversarial ms:  {row['generated_time_ms']:,.1f}")
    print(f"Relative adv:    {row['relative_advantage']:.1f}x")
    print()

    resolver = AdversarialSQLResolver()
    q = resolver.resolve_row(row)

    print("Tables:", q.tables)
    print("Join order:", q.join_order)
    print("S-expression:", q.sexp)
    print()
    print("--- DEFAULT SQL ---")
    print(q.default_sql)
    print()
    print("--- ADVERSARIAL SQL ---")
    print(q.adversarial_sql)
