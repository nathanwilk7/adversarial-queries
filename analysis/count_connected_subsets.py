"""
count_connected_subsets.py — Count distinct Steiner-resolved join sets possible
in the IMDB (JOB) PK-FK join graph.

A "join set" is any connected subset of tables in the join graph; this is exactly
the set of node sets that can arise from Steiner-tree resolution of any query.

Usage:
    uv run python analysis/count_connected_subsets.py
"""

import itertools

import networkx as nx

from workload.schema import build_join_graph

SCHEMA = "workload/job/schema.sql"

if __name__ == "__main__":
    G = build_join_graph(SCHEMA)
    nodes = sorted(G.nodes)
    n = len(nodes)
    print(f"Graph: {n} nodes, {G.number_of_edges()} edges")
    print(f"Is tree: {nx.is_tree(G)}, extra edges (cycles): {G.number_of_edges() - n + 1}")
    print()

    total = 0
    for size in range(1, n + 1):
        cnt = sum(
            1 for subset in itertools.combinations(nodes, size)
            if nx.is_connected(G.subgraph(subset))
        )
        total += cnt
        print(f"  size {size:2d}: {cnt:>8,} connected subsets")

    print(f"\nTotal distinct connected subsets: {total:,}")
