import json
import os
import pdb
import pickle
import sys

import psycopg
import typer
from tqdm import tqdm

from optimization.codec.codec import (
    AliasesCodec,
    AliasOrderCodec,
    HashProbeStackMachineCodec,
    JoinOperator,
    JoinTree,
    JoinTreeBranch,
    JoinTreeLeaf,
)
from oracle.oracle import OracleCodec, WorkloadInput, _default_plan
from training.data.codec import build_join_tree as build_join_tree_pg
from workload.workloads import WorkloadDefinitionSet, get_workload_set

app = typer.Typer(no_args_is_help=True)


@app.command()
def plan_adversarial_queries(
    query_json_path: str = typer.Option(
        ..., help="Path to the JSON file containing the queries."
    ),
    schema_file_path: str = typer.Option(..., help="Path to the schema file."),
    output_path: str = typer.Option(..., help="Path to save the adversarial queries."),
):
    from oracle.duckdb.client import DuckDBOracle
    from oracle.duckdb.contracts import PreparedQuery
    from training.data.duckdb import build_join_tree

    planned = []
    oracle = DuckDBOracle("http://localhost:8000")
    oracle.load(
        "/home/jtao/phd/projects/column-oracles/datafusion-oracle/data", in_memory=True
    )

    queries = json.load(open(query_json_path, "r"))
    encoded_queries = {}

    # Load the pickled WorkloadDefinitionSet if it exists
    containing_dir = os.path.dirname(query_json_path)
    pickled = os.path.join(
        os.path.dirname(query_json_path),
        os.path.basename(query_json_path).replace(".json", ".pkl"),
    )
    if os.path.exists(pickled):
        workload_set, encoded_queries = pickle.load(open(pickled, "rb"))
    else:
        # Create the WorkloadDefinitionSet
        queries_sql: dict[str, tuple[str, list]] = {}
        for i, workload in enumerate(queries):
            sql = workload["sql"]
            params = workload["params"]
            queries_sql[str(i)] = (sql, params)
            encoded_queries[str(i)] = workload["string"]

        workload_set = WorkloadDefinitionSet(
            schema_file_path,
            queries_sql,
            db="",
            db_user="",
            prewarm=False,
            infer_join_keys_from_queries=False,
            pg_hint_plan_join_order=False,
        )
        pickle.dump(
            (workload_set, encoded_queries),
            open(pickled, "wb"),
        )

    # codec = AliasOrderCodec(workload_set.tables)
    codec = HashProbeStackMachineCodec(workload_set.tables)
    for workload in tqdm(workload_set.queries.values(), "Planning queries"):
        # "string" (encoded query), "sql" (template with "?" placeholders),
        # "params" (list of params), "count" (# output rows)

        # Plan the query
        default_query = _default_plan(workload)
        explain = json.loads(
            oracle.execute_query(
                [
                    "PRAGMA explain_output = 'physical_only'",
                    PreparedQuery(
                        sql=f"EXPLAIN (FORMAT JSON) {default_query}",
                        params=workload.params,
                    ),
                ]
            )[1].at[0, "explain_value"]
        )[0]
        join_tree = build_join_tree(explain, workload)

        encoded_query = encoded_queries[workload.name]
        encoded_plan = codec.encode(join_tree)

        # Round trip the encoded plan
        join_clause = join_tree.to_join_clause()
        decoded = workload.query_template.format(join_clause)
        rt_explain = json.loads(
            oracle.execute_query(
                [
                    "PRAGMA explain_output = 'physical_only'",
                    "SET disabled_optimizers = 'join_order,build_side_probe_side'",
                    PreparedQuery(
                        sql=f"EXPLAIN (FORMAT JSON) {decoded}",
                        params=workload.params,
                    ),
                    "SET disabled_optimizers = ''",
                ]
            )[2].at[0, "explain_value"]
        )[0]
        rt_join_tree = build_join_tree(rt_explain, workload)
        if not join_tree.equal(rt_join_tree):
            tqdm.write(
                f"Join tree for query {workload.name} does not match after round trip"
            )
            pdb.set_trace()

        # Check timing
        # baseline = 0
        # for _ in range(3):
        #     baseline += oracle.query_default(workload)
        # baseline /= 3

        # encoded = 0
        # workload_spec = WorkloadSpec.from_definition(workload, OracleCodec.AliasOrder)
        # for _ in range(3):
        #     match oracle.query_encoded(
        #         workload_spec, WorkloadInput("timing_test", encoded_plan, baseline * 2)
        #     ):
        #         case CompletedQuery(_, elapsed_secs):
        #             encoded += elapsed_secs
        #         case TimedOutQuery(_, elapsed_secs):
        #             tqdm.write(
        #                 f"Query {workload.name} timed out after {elapsed_secs} seconds but was expected to finish in {baseline} seconds"
        #             )
        #             pdb.set_trace()
        #         case FailedQuery(_, elapsed_secs, error):
        #             tqdm.write(f"Error executing query {workload.name}: {error}")
        #             pdb.set_trace()

        # if max(encoded, baseline) / min(encoded, baseline) > 2:
        #     tqdm.write(
        #         f"Query {workload.name} took {encoded} seconds to execute but was expected to finish in {baseline} seconds"
        #     )
        #     pdb.set_trace()

        # planned.append({"encoded_query": encoded_query, "encoded_plan": encoded_plan})
        planned.append(encoded_plan)

    with open(output_path, "w") as f:
        for plan in planned:
            f.write(",".join(str(symbol) for symbol in plan) + "\n")
        # json.dump(planned, f)


def make_operators_hash_join(join_tree: JoinTree) -> JoinTree:
    match join_tree:
        case JoinTreeBranch(left, right, _):
            return JoinTreeBranch(
                make_operators_hash_join(left),
                make_operators_hash_join(right),
                JoinOperator.HashJoin,
            )
        case JoinTreeLeaf(table, alias):
            return JoinTreeLeaf(table, alias)
        case _:
            raise ValueError(f"Unknown join tree type: {type(join_tree)}")


@app.command()
def job_initializations():
    from oracle.duckdb.client import DuckDBOracle
    from training.data.duckdb import build_join_tree

    oracle = DuckDBOracle("http://localhost:8000")
    # oracle.load(
    #     "/home/jtao/phd/projects/column-oracles/datafusion-oracle/data", in_memory=True
    # )
    workload_set = get_workload_set("JOB")
    codec = AliasesCodec(workload_set.tables)
    for workload in workload_set.queries.values():
        default_query = _default_plan(workload)
        explain = json.loads(
            oracle.execute_query(
                [
                    "PRAGMA explain_output = 'physical_only'",
                    f"EXPLAIN (FORMAT JSON) {default_query}",
                ]
            )[1].at[0, "explain_value"]
        )[0]
        join_tree = build_join_tree(explain, workload)
        if any(leaf.alias is None for leaf in join_tree.all_leaves()):
            print(f"{workload.name} has unassigned aliases", file=sys.stderr)
            continue
        join_tree = make_operators_hash_join(join_tree)
        encoded_plan = codec.encode(join_tree)
        print(f"{workload.name};{','.join(str(symbol) for symbol in encoded_plan)}")


@app.command()
def plan_adversarial_queries_pg(
    query_json_path: str = typer.Option(
        ..., help="Path to the JSON file containing the queries (string/sql/params/count)."
    ),
    schema_file_path: str = typer.Option(..., help="Path to the schema file."),
    output_path: str = typer.Option(..., help="Path to write the encoded plans (one per line)."),
    pg_db: str = typer.Option("imdb", help="Local Postgres database name."),
    pg_user: str = typer.Option("imdb", help="Local Postgres user."),
    pg_password: str = typer.Option("imdb", help="Local Postgres password."),
    pg_host: str = typer.Option("localhost", help="Postgres host."),
    pg_port: int = typer.Option(5432, help="Postgres port."),
):
    """Plan adversarial queries using the local PostgreSQL optimizer and encode with HashProbeStackMachineCodec."""
    queries = json.load(open(query_json_path, "r"))

    pickled = os.path.join(
        os.path.dirname(query_json_path),
        os.path.basename(query_json_path).replace(".json", ".pkl"),
    )
    encoded_queries = {}
    if os.path.exists(pickled):
        workload_set, encoded_queries = pickle.load(open(pickled, "rb"))
    else:
        queries_sql: dict[str, tuple[str, list]] = {}
        for i, workload in enumerate(queries):
            queries_sql[str(i)] = (workload["sql"], workload["params"])
            encoded_queries[str(i)] = workload["string"]
        workload_set = WorkloadDefinitionSet(
            schema_file_path,
            queries_sql,
            db="",
            db_user="",
            prewarm=False,
            infer_join_keys_from_queries=False,
            pg_hint_plan_join_order=False,
        )
        pickle.dump((workload_set, encoded_queries), open(pickled, "wb"))

    codec = HashProbeStackMachineCodec(workload_set.tables)
    failed = 0

    # Resume support: output is a JSONL file keyed by query name so we can
    # skip already-completed queries on restart.
    completed: dict[str, list[int]] = {}
    if os.path.exists(output_path):
        with open(output_path) as f:
            for line in f:
                entry = json.loads(line)
                completed[entry["query"]] = entry["plan"]
        tqdm.write(f"Resuming: {len(completed)} queries already done.")

    with (
        open(output_path, "a") as out_f,
        psycopg.connect(dbname=pg_db, user=pg_user, password=pg_password, host=pg_host, port=pg_port, autocommit=True) as conn,
    ):
        with conn.cursor() as cur:
            for workload in tqdm(workload_set.queries.values(), "Planning queries"):
                if workload.name in completed:
                    continue

                default_query = _default_plan(workload).replace("?", "%s")
                try:
                    cur.execute(
                        f"EXPLAIN (FORMAT JSON) {default_query}",
                        workload.params or None,
                    )
                    explain = cur.fetchone()[0][0]
                    join_tree = build_join_tree_pg(explain["Plan"])
                    encoded_plan = codec.encode(join_tree)

                    out_f.write(json.dumps({"query": workload.name, "plan": encoded_plan}) + "\n")
                    out_f.flush()
                except Exception as e:
                    tqdm.write(f"Failed on query {workload.name}: {e}")
                    failed += 1

    tqdm.write(f"Done: {len(completed)} previously done, {failed} skipped.")


if __name__ == "__main__":
    app()
