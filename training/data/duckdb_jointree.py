"""
Join tree extraction from DuckDB EXPLAIN plans.

This module provides utilities for building join trees from DuckDB's JSON EXPLAIN output.
It analyzes the query plan to infer table aliases based on predicates and plan structure.
"""
import io
import pdb
import re
from collections import Counter
from dataclasses import dataclass
from functools import reduce
from operator import xor
from typing import Optional

import matplotlib.image as mpimg
import matplotlib.pyplot as plt
import pydot
import sqlglot
import sqlglot.expressions
from glom import glom

from optimization.codec.codec import JoinTree, JoinTreeBranch, JoinTreeLeaf
from logger.log import l
from oracle.oracle import _default_plan
from workload.workloads import WorkloadSpecDefinition


class PlanHasEmptyResult(Exception):
    """Raised when the EXPLAIN plan indicates the query will return no results."""
    pass


@dataclass(frozen=True)
class JoinTreeBuildState:
    """State maintained while traversing an EXPLAIN plan to build a join tree."""

    query: WorkloadSpecDefinition
    """The query we are building the join tree for"""

    plan: dict
    """The entire explain plan"""

    current_subplan: dict
    """The current subplan we are building the a join subtree for"""

    assigned_alias: dict[str, set[int]]
    """table name -> alias numbers that have already been assigned elsewhere"""

    subtree_forced_alias: dict[str, int]
    """table name -> alias it is forced to take in this subtree"""

    def with_new_assigned_aliases(
        self, *new_aliases: dict[str, set[int]]
    ) -> "JoinTreeBuildState":
        aliases = self.assigned_alias.copy()
        for source in new_aliases:
            for table, table_aliases in source.items():
                aliases.setdefault(table, set()).update(table_aliases)

        return JoinTreeBuildState(
            query=self.query,
            plan=self.plan,
            current_subplan=self.current_subplan,
            assigned_alias=aliases,
            subtree_forced_alias=self.subtree_forced_alias,
        )

    def with_forced_aliases(
        self, new_forced_aliases: dict[str, int]
    ) -> "JoinTreeBuildState":
        return JoinTreeBuildState(
            query=self.query,
            plan=self.plan,
            current_subplan=self.current_subplan,
            assigned_alias=self.assigned_alias,
            subtree_forced_alias={
                **self.subtree_forced_alias,
                **new_forced_aliases,
            },
        )

    def with_subplan(self, new_subplan: dict) -> "JoinTreeBuildState":
        return JoinTreeBuildState(
            query=self.query,
            plan=self.plan,
            current_subplan=new_subplan,
            assigned_alias=self.assigned_alias,
            subtree_forced_alias=self.subtree_forced_alias,
        )

    def visualize_plan(self, save_to: Optional[str] = None):
        """
        Visualize the entire DuckDB EXPLAIN plan as a graph.

        Args:
            save_to: Optional path to save the visualization. If not provided, saves to
                    'plan_visualization.png' in the current directory.
                    Supports .svg, .png, or other matplotlib formats.
        """
        graph = pydot.Dot()

        # Add the SQL query as a label at the top
        query_text = _default_plan(self.query)
        # Escape quotes and wrap long queries
        escaped_query = query_text.replace('"', '\\"').replace('\n', '\\n')
        if len(escaped_query) > 80:
            # Truncate very long queries
            escaped_query = escaped_query[:77] + "..."

        graph.set("label", f'Query: {escaped_query}')
        graph.set("labelloc", "t")

        # Build the plan graph recursively
        self._visualize_plan_node(graph, self.plan, node_id=0, parent_id=None)

        # Default to saving as PNG if no path provided
        if save_to is None:
            save_to = "plan_visualization.png"

        if save_to.endswith(".svg"):
            svg_str = graph.create_svg(prog="dot")
            with open(save_to, "wb") as f:
                f.write(svg_str)
            l.info(f"Plan visualization saved to {save_to}")
        elif save_to.endswith(".png"):
            png_str = graph.create_png(prog="dot")
            with open(save_to, "wb") as f:
                f.write(png_str)
            l.info(f"Plan visualization saved to {save_to}")
        else:
            # For other formats, use matplotlib
            png_str = graph.create_png(prog="dot")
            sio = io.BytesIO()
            sio.write(png_str)
            sio.seek(0)
            img = mpimg.imread(sio)

            plt.figure(figsize=(12, 8))
            plt.imshow(img, aspect="equal")
            plt.axis("off")
            plt.tight_layout()
            plt.savefig(save_to, bbox_inches="tight", dpi=150)
            plt.close()
            l.info(f"Plan visualization saved to {save_to}")

    def _visualize_plan_node(
        self, graph: pydot.Dot, node: dict, node_id: int, parent_id: Optional[int]
    ) -> int:
        """
        Recursively visualize a plan node and its children.

        Args:
            graph: The pydot graph to add nodes to
            node: The current plan node (dict from EXPLAIN JSON)
            node_id: The ID to assign to this node
            parent_id: The ID of the parent node (None for root)

        Returns:
            The next available node ID
        """
        node_type = node.get("name", "UNKNOWN")

        # Create label for this node
        if node_type in ["SEQ_SCAN ", "SEQ_SCAN"]:
            table_name = glom(node, "extra_info.Table", default="?")
            label = f"{table_name}"
        elif node_type == "EMPTY_RESULT":
            label = "<empty>"
        elif node_type in ["HASH_JOIN", "COMPARISON_JOIN"]:
            join_type = glom(node, "extra_info.Join Type", default="")
            if join_type:
                label = f"{node_type}\\n({join_type})"
            else:
                label = node_type
        elif node_type == "FILTER":
            label = "FILTER"
        else:
            label = node_type

        # Add this node to the graph
        graph.add_node(pydot.Node(node_id, label=label))

        # Connect to parent if exists
        if parent_id is not None:
            graph.add_edge(pydot.Edge(parent_id, node_id))

        # Process children
        next_id = node_id + 1
        if "children" in node:
            for child in node["children"]:
                next_id = self._visualize_plan_node(graph, child, next_id, node_id)

        return next_id


def _try_simple_build(explain: dict, query: WorkloadSpecDefinition) -> Optional[JoinTree]:
    """
    Attempt to build a join tree using a simple traversal approach.

    This works for queries without table aliases (each table appears exactly once).
    Traverses the EXPLAIN plan recursively:
    - For scans: returns JoinTreeLeaf
    - For joins: recursively processes left/right subtrees
    - For other nodes: passes through to children

    Args:
        explain: DuckDB JSON EXPLAIN plan node
        query: Workload specification containing query metadata

    Returns:
        JoinTree if successful, None if unable to build (e.g., unsupported node type)
    """
    node_type = explain.get("name")

    # Handle table scans
    if node_type in ["SEQ_SCAN ", "SEQ_SCAN"]:
        table_name = glom(explain, "extra_info.Table", default=None)
        if not table_name:
            return None
        # For simple queries, each table appears exactly once, so alias is always 1
        return JoinTreeLeaf(table_name, alias=1)

    # Handle joins
    elif node_type in ["HASH_JOIN", "COMPARISON_JOIN"]:
        # Check for special MARK joins (rewritten IN clauses)
        if glom(explain, "extra_info.Join Type", default=None) == "MARK":
            left, right = explain["children"]
            if right.get("name") == "COLUMN_DATA_SCAN":
                return _try_simple_build(left, query)
            elif left.get("name") == "COLUMN_DATA_SCAN":
                return _try_simple_build(right, query)
            else:
                return None

        # Regular joins: recursively build left and right subtrees
        left, right = explain["children"]
        left_tree = _try_simple_build(left, query)
        right_tree = _try_simple_build(right, query)

        if left_tree is None or right_tree is None:
            return None

        return JoinTreeBranch(left=left_tree, right=right_tree, op=None)

    # Handle EMPTY_RESULT - use special marker instead of raising exception
    elif node_type == "EMPTY_RESULT":
        return JoinTreeLeaf("<EMPTY>", alias=1)

    # Pass through single-child nodes (FILTER, PROJECTION, etc.)
    elif "children" in explain and len(explain["children"]) == 1:
        child = explain["children"][0]
        return _try_simple_build(child, query)

    # Unknown node type or structure
    else:
        return None


def _count_empty_leaves(tree: JoinTree) -> int:
    """Count <EMPTY> leaf nodes in a JoinTree (without deduplication)."""
    if isinstance(tree, JoinTreeLeaf):
        return 1 if tree.table == "<EMPTY>" else 0
    elif isinstance(tree, JoinTreeBranch):
        return _count_empty_leaves(tree.left) + _count_empty_leaves(tree.right)
    else:
        return 0


def _collect_leaves_list(tree: JoinTree) -> list[JoinTreeLeaf]:
    """Collect all leaves as a list (without deduplication, unlike all_leaves())."""
    if isinstance(tree, JoinTreeLeaf):
        return [tree]
    elif isinstance(tree, JoinTreeBranch):
        return _collect_leaves_list(tree.left) + _collect_leaves_list(tree.right)
    else:
        return []


def _assign_remaining_aliases(
    tree: JoinTree, query_tables: list[tuple[str, int]]
) -> JoinTree:
    """
    Assign aliases to leaves that have alias=None.

    When we can't disambiguate which alias a table scan corresponds to from the
    EXPLAIN plan, we assign aliases arbitrarily from the remaining unassigned ones.

    Args:
        tree: JoinTree that may have leaves with alias=None
        query_tables: List of (table_name, alias) tuples from the query

    Returns:
        JoinTree with all aliases assigned
    """
    # Collect all assigned aliases by table
    assigned_by_table: dict[str, set[int]] = {}

    def collect_assigned(t: JoinTree):
        if isinstance(t, JoinTreeLeaf):
            if t.alias is not None and t.table != "<EMPTY>":
                assigned_by_table.setdefault(t.table, set()).add(t.alias)
        elif isinstance(t, JoinTreeBranch):
            collect_assigned(t.left)
            collect_assigned(t.right)

    collect_assigned(tree)

    # Build map of expected aliases per table
    expected_by_table: dict[str, list[int]] = {}
    for table, alias in query_tables:
        expected_by_table.setdefault(table, []).append(alias)

    # Compute remaining aliases per table
    remaining_by_table: dict[str, list[int]] = {}
    for table, expected in expected_by_table.items():
        assigned = assigned_by_table.get(table, set())
        remaining = [a for a in expected if a not in assigned]
        if remaining:
            remaining_by_table[table] = remaining

    # Assign remaining aliases to None leaves
    def assign(t: JoinTree) -> JoinTree:
        if isinstance(t, JoinTreeLeaf):
            if t.alias is None and t.table in remaining_by_table:
                remaining = remaining_by_table[t.table]
                if remaining:
                    alias = remaining.pop(0)
                    return JoinTreeLeaf(t.table, alias=alias)
            return t
        elif isinstance(t, JoinTreeBranch):
            return JoinTreeBranch(
                left=assign(t.left),
                right=assign(t.right),
                op=t.op,
            )
        else:
            return t

    return assign(tree)


def _try_fill_empty(
    tree: JoinTree, missing_aliases: set[tuple[str, int]]
) -> JoinTree:
    """
    Try to fill <EMPTY> marker nodes with missing table aliases.

    When DuckDB detects that a join result will be empty (via zonemaps), it may
    skip parts of the join order. This function reconstructs the full join tree
    by inserting the missing tables at the <EMPTY> marker location.

    Args:
        tree: JoinTree that may contain <EMPTY> leaf nodes
        missing_aliases: Set of (table_name, alias) tuples that are missing

    Returns:
        Reconstructed JoinTree with missing aliases inserted at <EMPTY> location

    Raises:
        ValueError: If there are multiple <EMPTY> nodes (cross-join risk)
    """
    # Count <EMPTY> nodes by traversing (all_leaves() uses a set which deduplicates)
    empty_count = _count_empty_leaves(tree)

    if empty_count == 0:
        # No empty nodes, nothing to fill
        return tree
    elif empty_count > 1:
        # Multiple empty nodes - we can't safely reconstruct without risking cross joins
        raise ValueError(
            f"Cannot fill {empty_count} EMPTY_RESULT nodes - would require cross joins"
        )

    # Exactly one <EMPTY> node - safe to fill
    return _reconstruct_tree_with_missing_aliases(tree, missing_aliases)


def _reconstruct_tree_with_missing_aliases(
    tree: JoinTree, missing_aliases: set[tuple[str, int]]
) -> JoinTree:
    """
    Reconstruct a join tree by replacing <EMPTY> marker with missing aliases.

    Args:
        tree: JoinTree with exactly one <EMPTY> leaf
        missing_aliases: Set of (table_name, alias) tuples to insert

    Returns:
        Reconstructed JoinTree with missing aliases inserted at <EMPTY> location
    """
    if isinstance(tree, JoinTreeLeaf):
        if tree.table == "<EMPTY>":
            # Replace the empty node with the missing aliases
            if not missing_aliases:
                raise ValueError("Found <EMPTY> node but no missing aliases")

            # Sort for determinism (alphabetically by table name, then alias)
            aliases_list = sorted(missing_aliases)
            result: JoinTree = JoinTreeLeaf(aliases_list[0][0], alias=aliases_list[0][1])
            for table, alias in aliases_list[1:]:
                result = JoinTreeBranch(
                    left=result,
                    right=JoinTreeLeaf(table, alias=alias),
                    op=None,
                )
            return result
        else:
            return tree
    elif isinstance(tree, JoinTreeBranch):
        # Recursively reconstruct left and right subtrees
        new_left = _reconstruct_tree_with_missing_aliases(tree.left, missing_aliases)
        new_right = _reconstruct_tree_with_missing_aliases(tree.right, missing_aliases)
        return JoinTreeBranch(left=new_left, right=new_right, op=tree.op)
    else:
        raise ValueError(f"Unknown tree type: {type(tree)}")


def _reconstruct_tree_with_missing_tables(
    tree: JoinTree, missing_tables: set[str]
) -> JoinTree:
    """
    Reconstruct a join tree by replacing <EMPTY> marker with missing tables.

    When there's exactly one <EMPTY> node in the tree, we can insert the missing
    tables at that location since the join order doesn't matter for empty results.

    This is a convenience wrapper for queries without aliases (each table appears once).

    Args:
        tree: JoinTree with exactly one <EMPTY> leaf
        missing_tables: Set of table names that need to be inserted

    Returns:
        Reconstructed JoinTree with missing tables inserted at <EMPTY> location
    """
    # Convert table names to (table, alias=1) tuples
    missing_aliases = {(table, 1) for table in missing_tables}
    return _try_fill_empty(tree, missing_aliases)


def build_join_tree(explain: dict, query: WorkloadSpecDefinition) -> JoinTree:
    """
    Build a join tree from a DuckDB EXPLAIN plan.

    Args:
        explain: DuckDB JSON EXPLAIN plan (from EXPLAIN (FORMAT JSON) query)
        query: Workload specification containing query metadata

    Returns:
        JoinTree representing the join structure with resolved table aliases

    Raises:
        ValueError: If the plan has multiple EMPTY_RESULT nodes (would require cross joins)
    """
    # Check if query has no aliases (each table appears exactly once)
    has_no_aliases = all(count == 1 for _, count in query.query_tables)

    if has_no_aliases:
        # Try simple build first
        simple_tree = _try_simple_build(explain, query)
        if simple_tree is not None:
            # Check for <EMPTY> markers and validate
            all_leaves = simple_tree.all_leaves()
            empty_leaves = [leaf for leaf in all_leaves if leaf.table == "<EMPTY>"]

            # Count how many <EMPTY> nodes we have
            if len(empty_leaves) > 1:
                # Can't handle multiple empty nodes - fall back to complex method
                raise ValueError(
                    f"Query has {len(empty_leaves)} EMPTY_RESULT nodes, cannot reconstruct"
                )

            # Get actual tables in the tree (excluding <EMPTY>)
            tree_tables = {leaf.table for leaf in all_leaves if leaf.table != "<EMPTY>"}
            query_tables = {table for table, _ in query.query_tables}

            if tree_tables == query_tables:
                # Simple build succeeded and is complete
                return simple_tree
            elif len(empty_leaves) == 1:
                # We have exactly one <EMPTY> node - can reconstruct
                missing_tables = query_tables - tree_tables

                # if len(missing_tables) > 2:
                #     l.warning(
                #         f"{query.name}: Reconstructing join tree with {len(missing_tables)} "
                #         f"missing tables at EMPTY_RESULT node: {missing_tables}"
                #     )

                # Reconstruct the tree by inserting missing tables at <EMPTY> location
                reconstructed_tree = _reconstruct_tree_with_missing_tables(
                    simple_tree, missing_tables
                )
                return reconstructed_tree

    # Fall back to the complex predicate-based approach
    join_tree, state = _from_predicate_forced_aliases(
        explain,
        JoinTreeBuildState(
            query=query,
            plan=explain,
            current_subplan=explain,
            assigned_alias={},
            subtree_forced_alias={},
        ),
    )

    # Check for <EMPTY> markers and try to fill them
    # Use list to avoid deduplication (all_leaves() returns a set)
    all_leaves_list = _collect_leaves_list(join_tree)
    empty_count = sum(1 for leaf in all_leaves_list if leaf.table == "<EMPTY>")

    if empty_count > 0:
        # Count how many scans of each table exist in the tree (excluding <EMPTY>)
        # This includes scans with alias=None
        present_table_counts: Counter[str] = Counter(
            leaf.table for leaf in all_leaves_list if leaf.table != "<EMPTY>"
        )

        # Count how many scans of each table we expect
        expected_table_counts: Counter[str] = Counter(
            table for table, _ in query.query_tables
        )

        # For each table, determine how many more aliases we need to add
        # If we have 2 movie_info scans in tree and expect 2, we don't add any
        # If we have 0 info_type scans in tree and expect 2, we add both aliases
        missing_aliases: set[tuple[str, int]] = set()
        for table, expected_count in expected_table_counts.items():
            present_count = present_table_counts[table]  # Counter returns 0 for missing keys
            if present_count < expected_count:
                # We need to add (expected_count - present_count) aliases for this table
                # Get all aliases for this table from the query
                all_table_aliases = [a for t, a in query.query_tables if t == table]
                # Add the ones we're missing (take from the end to leave earlier ones for None leaves)
                num_to_add = expected_count - present_count
                aliases_to_add = all_table_aliases[-num_to_add:]
                missing_aliases.update((table, a) for a in aliases_to_add)

        # Try to fill the empty nodes
        join_tree = _try_fill_empty(join_tree, missing_aliases)

    # Assign remaining aliases to leaves that couldn't be disambiguated
    join_tree = _assign_remaining_aliases(join_tree, query.query_tables)

    if any(
        leaf.alias is None for leaf in join_tree.all_leaves() if leaf.table != "<EMPTY>"
    ):
        l.warning(f"{query.name} has unassigned aliases")

    return join_tree


def _from_predicate_forced_aliases(
    explain: dict, state: JoinTreeBuildState
) -> tuple[JoinTree, JoinTreeBuildState]:
    """
    Recursively build join tree by inferring table aliases from predicates.

    This function traverses the EXPLAIN plan and attempts to determine which
    table alias each scan corresponds to by matching predicates against the
    original query.
    """
    node_type = explain.get("name")

    # I don't know why DuckDB adds a space at the end of SEQ_SCAN
    if node_type in ["SEQ_SCAN ", "SEQ_SCAN"]:
        table_name = glom(explain, "extra_info.Table", default=None)
        if not table_name:
            raise ValueError(f"Table name not found in explain plan: {explain}")

        # If the table only appears once in the query, we can just use that alias
        table_aliases = [alias for table, alias in state.query.query_tables if table == table_name]
        if len(table_aliases) == 1:
            return JoinTreeLeaf(table_name, alias=table_aliases[0]), state

        forced_alias = state.subtree_forced_alias.get(table_name)

        if not forced_alias:
            # Oftentimes, identifying predicates are pushed down to the scan level
            predicate_str = glom(explain, "extra_info.Predicate", default=None) or glom(
                explain, "extra_info.Filters", default=None
            )
            if predicate_str:
                # Try to infer what alias is forced by this predicate
                possible_alias = _match_aliases_from_predicate(predicate_str, state)
                if len(possible_alias) == 1:
                    table, forced_alias = next(iter(possible_alias))
                    assert table == table_name
                elif len(possible_alias) == 0:
                    # No forced alias
                    pass
                else:
                    raise ValueError(
                        f"Somehow multiple aliases for {table_name} in {predicate_str}"
                    )

        if forced_alias:
            assigned_aliases = state.assigned_alias.get(table_name, set())
            assert forced_alias not in assigned_aliases

            return JoinTreeLeaf(
                table=table_name, alias=forced_alias
            ), state.with_new_assigned_aliases({table_name: set([forced_alias])})

        return JoinTreeLeaf(table_name, alias=None), state

    elif node_type == "FILTER":
        predicate_str = glom(explain, "extra_info.Expression", default=None)
        possible_forced_aliases = _match_aliases_from_predicate(predicate_str, state)
        new_forced_aliases = {}
        for table, forced_alias in possible_forced_aliases:
            if _plan_has_table_once(explain, table):
                new_forced_aliases[table] = forced_alias

        child = explain["children"][0]
        subtree_state = state.with_forced_aliases(new_forced_aliases).with_subplan(
            child
        )
        join_tree, new_state = _from_predicate_forced_aliases(child, subtree_state)

        return join_tree, state.with_new_assigned_aliases(
            {
                table: set([forced_alias])
                for table, forced_alias in new_state.subtree_forced_alias.items()
            }
        )

    elif node_type == "HASH_JOIN" or node_type == "COMPARISON_JOIN":
        left, right = explain["children"]

        # DuckDB rewrites "IN" clauses to this kind of join against a vector of
        # the comparison literals
        if glom(explain, "extra_info.Join Type", default=None) == "MARK":
            if right.get("name") == "COLUMN_DATA_SCAN":
                return _from_predicate_forced_aliases(left, state.with_subplan(left))
            elif left.get("name") == "COLUMN_DATA_SCAN":
                return _from_predicate_forced_aliases(right, state.with_subplan(right))
            else:
                pdb.set_trace()

        left_tree, left_state = _from_predicate_forced_aliases(
            left, state.with_subplan(left)
        )
        right_tree, right_state = _from_predicate_forced_aliases(
            right, left_state.with_subplan(right)
        )

        return JoinTreeBranch(
            left=left_tree, right=right_tree, op=None
        ), state.with_new_assigned_aliases(
            left_state.assigned_alias,
            right_state.assigned_alias,
        )

    elif "children" in explain and len(explain["children"]) == 1:
        # Unknown single-child node, just pass through it
        child = explain["children"][0]
        return _from_predicate_forced_aliases(child, state.with_subplan(child))

    elif node_type == "EMPTY_RESULT":
        # Return a marker node - caller will fill in missing tables
        return JoinTreeLeaf("<EMPTY>", alias=1), state

    else:
        raise ValueError(f"Unknown plan node type: {node_type}")


def _plan_has_table_once(explain: dict, target_table: str) -> bool:
    """Check if the explain plan has exactly one occurrence of a table."""
    if explain["name"] in ["SEQ_SCAN ", "SEQ_SCAN"]:
        return glom(explain, "extra_info.Table", default=None) == target_table
    elif "children" in explain:
        return reduce(
            xor,
            (
                _plan_has_table_once(child, target_table)
                for child in explain["children"]
            ),
        )
    else:
        l.warning(f"Unknown plan leaf node: {explain}")
        return False


def _plan_has_table(explain: dict, target_table: str) -> bool:
    """Check if the explain plan has any occurrence of a table."""
    if explain["name"] in ["SEQ_SCAN ", "SEQ_SCAN"]:
        return glom(explain, "extra_info.Table", default=None) == target_table
    elif "children" in explain:
        return any(
            _plan_has_table(child, target_table) for child in explain["children"]
        )
    else:
        return False


def _identify_table_for_column(col: str, state: JoinTreeBuildState) -> str:
    """
    Identify which table a column belongs to based on the schema and query context.

    If multiple tables have the same column, uses the schema and current subplan
    to disambiguate.
    """
    candidate_tables = []
    query = state.query
    for table, columns in query.schema.all_columns.items():
        # Skip if the table is not in the query
        if not any(table == t for t, _ in query.query_tables):
            continue

        # Find tables in this query that have this column
        if col in columns and _query_has_column(query, table, col):
            candidate_tables.append(table)

    if not candidate_tables:
        raise ValueError(f"Column {col} not found in schema")
    elif len(candidate_tables) == 1:
        return candidate_tables[0]
    else:
        # We have to figure out what table this column belongs to based on the
        # schema and, in the worst case, looking at the rest of the explain
        # below this
        present_tables = set()
        for table in candidate_tables:
            if _plan_has_table(state.current_subplan, table):
                present_tables.add(table)
        if len(present_tables) == 1:
            return next(iter(present_tables))

        # We don't currently do the looking in the explain thing
        # Implement this if it ever comes up
        pdb.set_trace()
        raise ValueError(f"Ambiguous column {col} could be one of {candidate_tables}")


def _query_has_column(query: WorkloadSpecDefinition, table: str, col: str) -> bool:
    """Check if the query references a column anywhere"""
    parsed = sqlglot.parse_one(_default_plan(query))
    for col_ref in parsed.find_all(sqlglot.expressions.Column):
        if col_ref.name == col and col_ref.table.startswith(table):
            return True
    return False


def _extract_non_join_predicates(
    query: WorkloadSpecDefinition,
) -> dict[tuple[str, int], set[tuple[str, sqlglot.Expression]]]:
    """
    Given a query, extract all of the non-join predicates and the columns
    they reference, which help identify table aliases
    """
    default_query = _default_plan(query)
    parsed = sqlglot.parse_one(default_query)
    where = parsed.find(sqlglot.expressions.Where)
    if not where:
        raise ValueError("No WHERE clause in default query")

    identifying_predicates: dict[
        tuple[str, int], set[tuple[str, sqlglot.Expression]]
    ] = {}

    for node in where.this.flatten(unnest=True):
        if (
            isinstance(node, sqlglot.expressions.EQ)
            and isinstance(node.this, sqlglot.expressions.Column)
            and isinstance(node.expression, sqlglot.expressions.Column)
        ):
            # Skip join predicates
            continue

        for col_ref in node.find_all(sqlglot.expressions.Column):
            col = col_ref.name
            if (col_ref.table, 1) in query.query_tables:
                table = col_ref.table
                alias = 1
            else:
                match = re.match(r"([a-zA-Z_]+)(\d+)", col_ref.table)
                if not match:
                    raise ValueError(f"Could not parse table name from {col_ref.table}")
                table = match.group(1)
                alias = int(match.group(2))
            identifying_predicates.setdefault((table, alias), set()).add((col, node))

    return identifying_predicates


def _match_aliases_from_predicate(
    predicate_str: str,
    state: JoinTreeBuildState,
) -> set[tuple[str, int]]:
    """
    Match table aliases by comparing predicates in the EXPLAIN plan to the original query.

    Returns a set of (table_name, alias) tuples that can be inferred from the predicate.
    """
    aliases: set[tuple[str, int]] = set()
    ambiguous_tables: set[str] = set()

    identifying_predicates = _extract_non_join_predicates(state.query)
    try:
        parsed = sqlglot.parse_one(predicate_str)
    except TypeError:
        pdb.set_trace()
        return aliases
    except (sqlglot.errors.ParseError, sqlglot.errors.TokenError) as e:
        # DuckDB sometimes just gives unusable predicates
        return aliases
    if isinstance(parsed, sqlglot.expressions.Paren):
        # DuckDB sometimes parentheses around the predicate
        parsed = parsed.this

    for col_ref in parsed.find_all(sqlglot.expressions.Column):
        col = col_ref.name

        # Skip sideways information passing predicates
        if (
            any(
                isinstance(col_ref.parent, comparison)
                for comparison in [
                    sqlglot.expressions.EQ,
                    sqlglot.expressions.GT,
                    sqlglot.expressions.LT,
                    sqlglot.expressions.GTE,
                    sqlglot.expressions.LTE,
                    sqlglot.expressions.Between,
                ]
            )
            and "id" in col
        ):
            continue

        table = _identify_table_for_column(col, state)

        if table in ambiguous_tables:
            # We have previously given up on resolving aliases for this table due to ambiguity
            continue

        # Now that we know which table this predicate is for, we try to resolve
        # the alias by comparing to aliases that occur in predicates in the
        # base query
        predicate = col_ref.parent

        predicate_literals = set(
            literal.this for literal in predicate.find_all(sqlglot.expressions.Literal)
        )
        simplified_predicate_literals = set(
            literal.replace("%", "")
            for literal in predicate_literals
            if isinstance(literal, str)
        )
        if not predicate_literals:
            # Sometimes there are no literals (e.g., NULL checks)
            continue
        found_alias = False
        for (
            candidate_table,
            candidate_alias,
        ), candidate_exprs in identifying_predicates.items():
            if table != candidate_table or table in ambiguous_tables:
                continue

            for candidate_col, candidate_expr in candidate_exprs:
                if candidate_col != col:
                    continue

                candidate_literals = set(
                    literal.this
                    for literal in candidate_expr.find_all(sqlglot.expressions.Literal)
                )
                # Other annoying cases of DuckDB rewriting expressions
                simplified_candidate_literals = set(
                    literal.replace("%", "")
                    for literal in candidate_literals
                    if isinstance(literal, str)
                )

                # We just look for any intersection of the literals
                if (predicate_literals & candidate_literals) or (
                    # Try to catch rewritten LIKE expressions
                    (simplified_predicate_literals & simplified_candidate_literals)
                    and (
                        predicate.find(sqlglot.expressions.Anonymous) is not None
                        or predicate.find(sqlglot.expressions.Like) is not None
                    )
                ):
                    # We have a match
                    if not (table, candidate_alias) in aliases and any(
                        existing_table == table for existing_table, _ in aliases
                    ):
                        ambiguous_tables.add(table)
                        aliases = {(t, a) for t, a in aliases if t != table}
                        break

                    found_alias = True
                    aliases.add((table, candidate_alias))
                    break
        if not found_alias:
            state.visualize_plan('debug.png')
            pdb.set_trace()

    return aliases
