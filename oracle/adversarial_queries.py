import asyncio
import json
import pdb
import selectors
import sys
import threading
import time
from dataclasses import dataclass
from queue import Queue
from typing import Any, Literal, Optional, Protocol, Union

import lark  # type: ignore
import networkx as nx  # type: ignore
import psycopg  # type: ignore

from optimization.codec.codec import (
    AliasesCodec,
    AliasOrderCodec,
    Codec,
    HashProbeStackMachineCodec,
    JoinTree,
    JoinTreeBranch,
    JoinTreeLeaf,
    SymbolTable,
)
from logger.log import l
from oracle.pg_celery_worker.pg_worker.config import get_config
from oracle.oracle import WorkloadInput as BayesQOWorkloadInput
from oracle.oracle import _default_plan, _resolve_codec
from oracle.pg_celery_worker.pg_worker import contracts
from oracle.structures import CompletedQuery as BayesQOCompletedQuery
from oracle.structures import FailedQuery as BayesQOFailedQuery
from oracle.structures import QueryExecutionSpec as BayesQOQueryExecutionSpec
from oracle.structures import QueryResult as BayesQOQueryResult
from oracle.structures import TimedOutQuery as BayesQOTimedOutQuery
from workload.workloads import WorkloadDefinitionSet, WorkloadSpec

# Global connection monitor thread and notification tracking
_monitor_thread: Optional[threading.Thread] = None
_completed_jobs: set[int] = set()  # Shared store of completed job IDs
_notification_condition = (
    threading.Condition()
)  # Wake all waiters when notifications arrive
_monitor_lock = threading.Lock()

# Global connection objects
_pg_conn: Optional[psycopg.Connection] = None
_pg_monitor_conn: Optional[psycopg.Connection] = None

# Thread-local storage for connections
_local = threading.local()


def _get_pg_connection() -> psycopg.Connection:
    """Get a connection to the PostgreSQL database"""
    if not hasattr(_local, "pg_conn") or _local.pg_conn.closed:
        cfg = get_config().job_queue
        _local.pg_conn = psycopg.connect(
            host=cfg.host,
            port=cfg.port,
            dbname=cfg.database,
            user=cfg.user,
            password=cfg.password,
            autocommit=True,
        )
    return _local.pg_conn


def _monitor_connection():
    """Monitor a dedicated connection for notifications"""
    sel = selectors.DefaultSelector()
    conn = None

    while True:
        try:
            # Create a fresh connection for monitoring (not from thread-local pool)
            cfg = get_config().job_queue
            conn = psycopg.connect(
                host=cfg.host,
                port=cfg.port,
                dbname=cfg.database,
                user=cfg.user,
                password=cfg.password,
                autocommit=True,
            )

            # Register for all job completion notifications
            with conn.cursor() as cur:
                cur.execute("LISTEN job_complete")

            # Register connection with selector
            sel.register(conn, selectors.EVENT_READ)

            while True:
                # Wait for OS to notify us of any events with a timeout
                events = sel.select(timeout=1.0)

                if not events:
                    continue

                # Process notifications if any
                for notify in conn.notifies():
                    job_id = int(notify.payload)
                    with _notification_condition:
                        _completed_jobs.add(job_id)
                        _notification_condition.notify_all()  # Wake all waiting tasks

        except Exception as e:
            l.error(f"Monitor connection error: {e}")
            time.sleep(1)  # Brief delay before reconnecting
            continue
        finally:
            if conn is not None:
                try:
                    sel.unregister(conn)
                except:
                    pass
                try:
                    conn.close()
                except:
                    pass
            conn = None


def ensure_monitor_thread():
    """Ensure the connection monitor thread is running"""
    global _monitor_thread
    with _monitor_lock:
        if _monitor_thread is None or not _monitor_thread.is_alive():
            _monitor_thread = threading.Thread(
                target=_monitor_connection,
                daemon=True,
            )
            _monitor_thread.start()


class OracleAdapter(Protocol):
    """Protocol for database engine adapters used by AdversarialQueryOracle."""

    def setup_statements(self) -> list[str]:
        """Returns engine-specific preamble statements for locked join-order execution."""
        ...


class DuckDBAdapter:
    """Adapter for DuckDB execution (default)."""

    def setup_statements(self) -> list[str]:
        return ["SET disabled_optimizers = 'join_order,build_side_probe_side'"]


class PostgresAdapter:
    """Adapter for PostgreSQL execution.

    No setup statements are needed: join_collapse_limit=1 is set globally in
    postgresql.conf on all worker machines, so explicit CROSS JOIN order is
    already honored without any per-query SET.
    """

    def setup_statements(self) -> list[str]:
        return []


@dataclass
class AdversarialQueryInput:
    """
    Adversarial query input for the oracle.
    """

    llm_output: str
    """VAE grammar-decoded query, e.g. (table (column value))"""

    plan: Optional[list[int]]
    """Encoded BO-selected plan for the query, e.g. [4, 7, 1] or None to execute the baseline plan"""

    timeout_ms: Optional[int]
    """Cancel the query and return a censored observation after this amount of time."""

    db_schema: Literal["JOB", "SQLStorm", "JOB-Complex", "Stack"]
    """Schema name: "JOB" for IMDB, "SQLStorm" for StackOverflow, "JOB-Complex", or "Stack" for Stack dataset"""

    return_result: bool = False
    """If True, return the query result (e.g. SELECT count(*)) alongside timing information."""


parsing_grammar = """

start: selector+
selector: "(" ident " " filter* ")"
?ident: /[a-zA-Z0-9_]+/
filter: int_filter | str_filter | ts_filter | enum_filter
int_filter: "(" ident " " intop " " intval ")"
str_filter: "(" ident " " strop ")"
ts_filter: "(" ident " " tsop " " tsval ")"
enum_filter: "(" ident " " quoted_string ")"

!intop: "<" | ">" | "=" | "!="
!tsop: "t<" | "t>" | "t=" | "t!="
!strop: "most_popular" | "random"

!intval: "first" | "median" | "last" | "mode" | /[0-9]{4}/
!tsval: "first" | "median" | "last" | /[0-9]{4}/

quoted_string: ESCAPED_STRING

%import common.ESCAPED_STRING
"""
g = lark.Lark(parsing_grammar)


class AdversarialQueryOracle:
    predicate_values: dict[tuple[str, str, Union[str, int]], str]
    """(table, column, llm predicate value) -> actual query predicate value"""

    join_predicate_graph: nx.Graph
    """Nodes are table names, edges are string join predicates"""

    codec: Codec

    def __init__(self, join_predicate_graph: nx.Graph, adapter: OracleAdapter = DuckDBAdapter()):
        self.predicate_values = {}
        self.join_predicate_graph = join_predicate_graph
        self.adapter = adapter
        tables = list(sorted(self.join_predicate_graph.nodes))
        # self.codec = AliasOrderCodec(tables)
        self.codec = HashProbeStackMachineCodec(tables)

    def query(
        self, inputs: list[AdversarialQueryInput]
    ) -> list[contracts.TimeQueryResult]:
        """Process a batch of adversarial query inputs in parallel"""
        results = asyncio.run(self.__query_batch(inputs))
        return results

    async def __query_batch(
        self, inputs: list[AdversarialQueryInput]
    ) -> list[contracts.TimeQueryResult]:
        """Internal async method to handle batch processing"""
        tasks = [self.__query_one(input, i) for i, input in enumerate(inputs)]
        results = await asyncio.gather(*tasks)
        return results

    async def __query_one(
        self, input: AdversarialQueryInput, task_id: int
    ) -> contracts.TimeQueryResult:
        """Process a single adversarial query input"""
        l.debug(f"🔵 Task {task_id}: Starting query processing")

        # Step 1: Parse the LLM-decoded output
        l.debug(f"🔵 Task {task_id}: Parsing LLM output and resolving predicates")
        sql_template, params, tables = await self.__decode_query_template(
            input.llm_output, input.db_schema, task_id
        )
        l.debug(f"🔵 Task {task_id}: Resolved tables: {tables}")

        # Step 2: Handle the plan (BO or baseline)
        # When decoding the plan, the appropriate join order should be chosen,
        # but the ? parameters should be left as-is.
        timeout_secs = input.timeout_ms / 1000 if input.timeout_ms is not None else 60
        if input.plan is not None:
            sql = self.__decode_plan(sql_template, tables, input.plan, input.db_schema)
            request = contracts.TimeQueryRequest(
                query=[
                    *self.adapter.setup_statements(),
                    contracts.PreparedQuery(sql=sql, params=params),
                ],
                timeout_secs=timeout_secs,
                db_schema=input.db_schema,
                return_result=input.return_result,
            )
            l.debug(f"🔵 Task {task_id}: Using adversarial plan")
        else:
            sql = self.__baseline_plan(sql_template, tables)
            request = contracts.TimeQueryRequest(
                query=[
                    contracts.PreparedQuery(sql=sql, params=params),
                ],
                timeout_secs=timeout_secs,
                db_schema=input.db_schema,
                return_result=input.return_result,
            )
            l.debug(f"🔵 Task {task_id}: Using baseline plan")

        # Step 3: Insert the task into the job queue
        l.debug(f"🔵 Task {task_id}: Submitting to job queue")
        task = QueryTask(request)
        task.submit()

        # Step 4: Wait for the result and return it (run in thread pool to avoid blocking)
        l.debug(f"🔵 Task {task_id}: Waiting for database result")
        result = await asyncio.to_thread(task.result)

        if isinstance(result, contracts.TimeQueryResponse) and not isinstance(
            result.result, contracts.QueryErrorResponse
        ):
            l.info(f"✅ Task {task_id}: Completed in {result.result.elapsed_secs:.2f}s")
        else:
            l.info(f"✅ Task {task_id}: Completed")
        return result

    def __decode_plan(
        self,
        query_template: str,
        tables: list[str],
        encoded_plan: list[int],
        db_schema: Literal["JOB", "SQLStorm", "JOB-Complex", "Stack"],
    ) -> str:
        """Decode an integer plan encoding into a concrete SQL FROM clause.

        For historical reasons, our integer encoding is *total*: any list of integers
        decodes to some join tree over the tables in the query (via hash-probing).

        For SQLStorm specifically, some decoded join trees can introduce *intermediate*
        CROSS JOINs (i.e., joining two components that have no join predicate between
        them yet). With DuckDB join-order optimization disabled, those intermediate
        cross products can explode and trigger runtime errors (OOM, etc.).

        To keep the adversarial loop stable, we use a join-graph-constrained decoder
        for SQLStorm that deterministically "repairs" any invalid join step into a
        join step that has at least one join predicate between the two sides.

        JOB keeps the original decoding behavior unchanged.
        """

        if db_schema in ("SQLStorm", "Stack"):
            try:
                tree = self.__decode_plan_tree_join_graph_safe(tables, encoded_plan)
            except Exception as e:
                # Safety fallback: never fail decoding; revert to the original codec.
                l.error(
                    "Join-graph-safe decoding failed; falling back to unconstrained decode. Error: %s",
                    e,
                )
                tree = self.codec.decode([(t, 1) for t in tables], encoded_plan)
        else:
            tree = self.codec.decode([(t, 1) for t in tables], encoded_plan)

        return query_template.format(tree.to_join_clause())

    def __trees_joinable(self, left: JoinTree, right: JoinTree) -> bool:
        """Return True iff there exists at least one join predicate edge between the two sides."""

        left_tables = left.tables()
        right_tables = right.tables()
        for u in left_tables:
            for v in right_tables:
                if self.join_predicate_graph.has_edge(u, v):
                    return True
        return False

    def __decode_plan_tree_join_graph_safe(
        self, tables: list[str], encoded_plan: list[int]
    ) -> JoinTree:
        """Decode an integer list into a *no-intermediate-cross-join* join tree.

        This is a SQLStorm-only regularization: every join step must join two components
        that share at least one edge in the schema join graph.

        The mapping remains *total* (SELFIES-like): any integer list deterministically
        decodes to some valid tree.
        """

        if len(tables) == 0:
            raise ValueError("Cannot decode a plan for an empty table set")
        if len(tables) == 1:
            return JoinTreeLeaf(tables[0])

        # NOTE: This oracle always uses a StackMachineCodec variant today.
        # We intentionally reach into these attributes to reuse the exact same
        # symbol universe & hash-probing behavior as the existing decoder.
        base_table_symbols = getattr(self.codec, "base_table_symbols")
        symbol_resolver = getattr(self.codec, "symbol_resolver")

        query_tables = list(tables)
        needed_tables = set(query_tables)
        symbol_table = SymbolTable(base_table_symbols, query_tables)

        encoded = list(encoded_plan)
        if encoded == []:
            encoded = [0, 1]
        if len(encoded) % 2 != 0:
            encoded.append(0)

        joins = [encoded[i : i + 2] for i in range(0, len(encoded), 2)]

        new_tree: JoinTree | None = None
        for left_symbol, right_symbol in joins:
            left_tree = symbol_resolver.resolve_symbol(symbol_table, left_symbol)
            reduced = symbol_table.without(left_tree)

            # If there is nothing left to join, we're already done.
            if len(reduced.tree_to_symbols) == 0:
                new_tree = left_tree
                break

            # Candidate components that are joinable with the chosen left side.
            joinable_candidates = [
                t for t in reduced.tree_to_symbols.keys() if self.__trees_joinable(left_tree, t)
            ]

            # Try the original hash-probe resolution first.
            right_tree = symbol_resolver.resolve_symbol(reduced, right_symbol)

            # If that choice would create an intermediate cross join, deterministically
            # map to a joinable component instead.
            if joinable_candidates and (not self.__trees_joinable(left_tree, right_tree)):
                joinable_candidates = sorted(
                    joinable_candidates, key=lambda t: tuple(sorted(t.tables()))
                )
                right_tree = joinable_candidates[hash(right_symbol) % len(joinable_candidates)]

            new_tree = JoinTreeBranch(left_tree, right_tree, op=None)
            symbol_table = symbol_table.with_join(left_tree, right_tree, new_tree)

            if needed_tables.issubset(new_tree.tables()):
                break

        if new_tree is None:
            # Extremely defensive fallback; should not happen.
            new_tree = JoinTreeLeaf(query_tables[0])

        # If the encoded plan was too short, attach remaining tables *joinably*.
        remaining = set(query_tables) - set(new_tree.tables())
        seed_idx = 0
        while remaining:
            current = new_tree.tables()
            joinable_tables = sorted(
                [
                    t
                    for t in remaining
                    if any(self.join_predicate_graph.has_edge(t, u) for u in current)
                ]
            )

            if joinable_tables:
                seed = encoded_plan[seed_idx] if seed_idx < len(encoded_plan) else seed_idx
                seed_idx += 1
                chosen = joinable_tables[hash(seed) % len(joinable_tables)]
            else:
                # If the query join graph is disconnected (shouldn't happen if connected_tables
                # is computed correctly), we cannot avoid a cross join.
                chosen = sorted(remaining)[0]

            new_tree = JoinTreeBranch(new_tree, JoinTreeLeaf(chosen), op=None)
            remaining.remove(chosen)

        return new_tree

    def __baseline_plan(self, sql_template: str, tables: list[str]) -> str:
        formatted = sql_template.format(", ".join(tables))
        return formatted

    async def __lookup_predicate_value(self, key, sql, db_schema: Literal["JOB", "SQLStorm", "JOB-Complex", "Stack"]):
        if key in self.predicate_values:
            l.debug(f"🔵 Using cached value for {key}")
            return self.predicate_values[key]

        table_name, column_name, predicate_name = key
        # Try looking up the value in the predicate values table
        l.debug(f"🔵 Looking up value for {key}")
        lookup_query = (
            """
            SELECT predicate_value
            FROM predicate_values
            WHERE schema = %s AND
                table_name = %s AND
                column_name = %s AND
                predicate_name = %s
            """,
            (db_schema, table_name, column_name, predicate_name),
        )
        result = await self.__lookup(lookup_query)
        if result is not None:
            self.predicate_values[key] = result
            return result

        l.debug(f"🔵 Running SQL to get value for {key}")
        task = QueryTask(
            contracts.RunSQLRequest(query=[sql], db_schema=db_schema),
        )
        task.submit()
        result = await asyncio.to_thread(task.result)
        if isinstance(result, contracts.RunSQLResponse) and isinstance(
            result.result, contracts.RunSQLCompleteResponse
        ):
            # Handle JSON-serialized pandas DataFrame output from df.to_json()
            try:
                # Parse the JSON string from df.to_json()
                df_json = json.loads(result.result.df_json)

                if isinstance(df_json, list):
                    if len(df_json) == 1:
                        output = df_json[0]["val"]
                    else:
                        import pdb
                        pdb.set_trace()
                        raise RuntimeError(
                            f"Query returned {len(df_json)} rows, expected exactly 1: {df_json}"
                        )
                else:
                    raise RuntimeError(f"Unexpected output format: {df_json}")
            except json.JSONDecodeError as e:
                raise RuntimeError(f"Failed to parse JSON: {result.output}, error: {e}")

            if output is None:
                # DuckDB returns None if the literal value is the empty string
                output = "''"

            # Update cache and predicate_values table
            l.debug(f"🔵 Got {key} = {repr(output)}")
            self.predicate_values[key] = output
            insert_query = (
                """
                INSERT INTO predicate_values (schema, table_name, column_name, predicate_name, predicate_value)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (db_schema, table_name, column_name, predicate_name, output),
            )
            output = await self.__insert_or_lookup(insert_query, lookup_query, output)
            return output
        else:
            import pdb

            pdb.set_trace()
            raise RuntimeError(f"Failed to get value for {key}")

    async def __get_int_value(self, table_name, field, value, db_schema: Literal["JOB", "SQLStorm", "JOB-Complex", "Stack"]):
        key = (table_name, field, value)
        if value == "first":
            sql = f"SELECT {field} AS val FROM {table_name} WHERE {field} is not null ORDER BY {field} LIMIT 1"
        elif value == "median":
            sql = f"SELECT median({field}) AS val FROM {table_name}"
        elif value == "last":
            sql = f"SELECT {field} AS val FROM {table_name} WHERE {field} is not null ORDER BY {field} DESC LIMIT 1"
        elif value == "mode":
            sql = f"SELECT {field} AS val FROM {table_name} WHERE {field} is not null GROUP BY {field} ORDER BY count(*) DESC LIMIT 1"
        else:
            p = int(value) / 1000
            sql = f"SELECT quantile_disc({field}, {p}) AS val FROM {table_name}"
        return await self.__lookup_predicate_value(key, sql, db_schema)

    async def __get_str_value(self, table_name, field, str_val, db_schema: Literal["JOB", "SQLStorm", "JOB-Complex", "Stack"]):
        key = (table_name, field, str_val)
        if str_val == "most_popular":
            sql = f"SELECT {field} AS val FROM {table_name} GROUP BY {field} ORDER BY count(*) DESC LIMIT 1"
        elif str_val == "random":
            # For deterministic results, instead of random,
            # return the value with the median number of occurrences
            sql = f"""
            SELECT {field} AS val
            FROM (
                SELECT {field}, COUNT(*) AS cnt
                FROM {table_name}
                GROUP BY {field}
            ) sub
            ORDER BY cnt
            OFFSET (SELECT COUNT(*)/2 FROM (SELECT COUNT(*) FROM {table_name} GROUP BY {field}) t)
            LIMIT 1
            """
        else:
            raise ValueError()
        return await self.__lookup_predicate_value(key, sql, db_schema)

    async def __get_timestamp_value(self, table_name, field, value, db_schema: Literal["JOB", "SQLStorm", "JOB-Complex", "Stack"]):
        key = (table_name, field, value)
        if value == "first":
            sql = f"SELECT {field} AS val FROM {table_name} WHERE {field} is not null ORDER BY {field} LIMIT 1"
        elif value == "median":
            sql = f"SELECT median({field}) AS val FROM {table_name}"
        elif value == "last":
            sql = f"SELECT {field} AS val FROM {table_name} WHERE {field} is not null ORDER BY {field} DESC LIMIT 1"
        else:
            # Quantile (4-digit number between 0000 and 1000)
            p = int(value) / 1000
            sql = f"SELECT quantile_disc({field}, {p}) AS val FROM {table_name}"
        return await self.__lookup_predicate_value(key, sql, db_schema)

    async def __resolve_predicate(
        self,
        table_name,
        field,
        operator,
        pred_type,
        value,
        db_schema: Literal["JOB", "SQLStorm", "JOB-Complex", "Stack"],
        task_id: int,
        predicate_index: int,
    ):
        l.debug(
            f"🔸 Task {task_id}.{predicate_index}: Resolving {pred_type} predicate {table_name}.{field}"
        )
        start_time = time.time()

        if pred_type == "int":
            rvalue = await self.__get_int_value(table_name, field, value, db_schema)
            end_time = time.time()
            l.debug(
                f"🔸 Task {task_id}.{predicate_index}: Resolved in {end_time - start_time:.2f}s"
            )
            return f"{table_name}.{field} {operator} {rvalue}"
        elif pred_type == "timestamp":
            rvalue = await self.__get_timestamp_value(table_name, field, value, db_schema)
            end_time = time.time()
            l.debug(
                f"🔸 Task {task_id}.{predicate_index}: Resolved in {end_time - start_time:.2f}s"
            )
            return f"{table_name}.{field} {operator} TIMESTAMP '{rvalue}'"
        elif pred_type == "enum":
            # Enum values are already the literal string, no lookup needed
            end_time = time.time()
            l.debug(
                f"🔸 Task {task_id}.{predicate_index}: Resolved in {end_time - start_time:.2f}s"
            )
            return (f"{table_name}.{field} = ?", value)
        else:  # str
            rvalue = await self.__get_str_value(table_name, field, value, db_schema)
            end_time = time.time()
            l.debug(
                f"🔸 Task {task_id}.{predicate_index}: Resolved in {end_time - start_time:.2f}s"
            )
            return (f"{table_name}.{field} = ?", rvalue)

    async def __decode_query_template(
        self, llm_output: str, db_schema: Literal["JOB", "SQLStorm", "JOB-Complex", "Stack"], task_id: int = -1
    ) -> tuple[str, list[str], list[str]]:
        t = g.parse(llm_output)

        tables_involved = []
        filter_predicates = []
        parameters = []

        # create all the WHERE clause predicates that aren't joins
        predicate_tasks = []
        for selector in t.children:
            table_name = str(selector.children[0])

            assert table_name not in tables_involved
            tables_involved.append(table_name)

            for filt in selector.children[1:]:
                filt = filt.children[0]
                if filt.data == "int_filter":
                    field = str(filt.children[0])
                    operator = str(filt.children[1].children[0])
                    value = str(filt.children[2].children[0])
                    predicate_tasks.append((table_name, field, operator, "int", value))
                elif filt.data == "str_filter":
                    field = str(filt.children[0])
                    str_val = str(filt.children[1].children[0])
                    predicate_tasks.append((table_name, field, None, "str", str_val))
                elif filt.data == "ts_filter":
                    field = str(filt.children[0])
                    # Convert timestamp operator (t<, t>, t=, t!=) to regular operator (<, >, =, !=)
                    ts_operator = str(filt.children[1].children[0])
                    operator = ts_operator[1:]  # Remove the 't' prefix
                    value = str(filt.children[2].children[0])
                    predicate_tasks.append((table_name, field, operator, "timestamp", value))
                elif filt.data == "enum_filter":
                    field = str(filt.children[0])
                    # Extract the string value from the quoted string (remove surrounding quotes)
                    enum_val = str(filt.children[1].children[0])[1:-1]  # Remove quotes
                    predicate_tasks.append((table_name, field, None, "enum", enum_val))
                else:
                    raise ValueError(f"Unknown filter type: {filt.data}")

        # Execute all predicate value lookups in parallel
        if predicate_tasks:
            l.debug(
                f"🔀 Task {task_id}: Resolving {len(predicate_tasks)} predicates in parallel"
            )
            predicate_start = time.time()
            predicate_results = await asyncio.gather(
                *[
                    self.__resolve_predicate(*task, db_schema, task_id, i)
                    for i, task in enumerate(predicate_tasks)
                ]
            )
            predicate_end = time.time()
            l.debug(
                f"🔀 Task {task_id}: Predicate resolution completed in {predicate_end - predicate_start:.2f}s"
            )
        else:
            predicate_results = []

        # Build where clause and parameters from results
        for result in predicate_results:
            if isinstance(result, tuple):
                filter_predicates.append(result[0])
                parameters.append(result[1])
            else:
                filter_predicates.append(result)

        # figure out the minimum set of tables we need to join and add predicates
        # to the WHERE clause for them
        # subgraph = nx.approximation.steiner_tree(
        #     self.join_predicate_graph, tables_involved
        # )
        connected_tables, join_predicates = await self.__resolve_joins(tables_involved, db_schema)

        query_template = f"""
        SELECT count(*)
        FROM {{}}
        WHERE {" AND ".join(filter_predicates + join_predicates) }
        """
        return (query_template, parameters, connected_tables)

    async def __lookup(self, lookup_query):
        lookup_sql, lookup_params = lookup_query
        with _get_pg_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(lookup_sql, lookup_params)
                result = cur.fetchone()
                if result is None:
                    return None
                return result[0]

    async def __insert_or_lookup(self, insert_query, lookup_query, inserted_value):
        with _get_pg_connection() as conn:
            with conn.cursor() as cur:
                try:
                    insert_sql, insert_params = insert_query
                    cur.execute(insert_sql, insert_params)
                    return inserted_value
                except psycopg.errors.UniqueViolation:
                    pass

        result = await self.__lookup(lookup_query)
        assert result is not None
        l.debug(f"🔀 Insert of {inserted_value} failed, found {result} instead")
        return result

    async def __resolve_joins(self, tables: list[str], db_schema: Literal["JOB", "SQLStorm", "JOB-Complex", "Stack"]) -> tuple[list[str], list[str]]:
        """
        Given the tables from the LLM, return the set of tables to join and the
        set of predicates to add to the WHERE clause.
        """
        lookup_query = (
            """
            SELECT connected_tables
            FROM query_connected_tables
            WHERE schema = %s AND input_tables = (%s)
            """,
            (db_schema, list(sorted(tables))),
        )

        connected_tables = await self.__lookup(lookup_query)
        if connected_tables is None:
            l.debug(f"🔀 No connected tables found, using Steiner tree")
            subgraph = nx.approximation.steiner_tree(self.join_predicate_graph, tables)
            connected_tables = list(subgraph.nodes)

            insert_query = (
                """
                INSERT INTO query_connected_tables (schema, input_tables, connected_tables)
                VALUES (%s, %s, %s)
                """,
                (db_schema, list(sorted(tables)), connected_tables),
            )
            connected_tables = await self.__insert_or_lookup(
                insert_query, lookup_query, connected_tables
            )
        else:
            l.debug(f"🔵 Precomputed connected tables: {connected_tables}")

        subgraph = self.join_predicate_graph.subgraph(connected_tables)
        predicates = list(sorted([subgraph.edges[e]["label"] for e in subgraph.edges]))
        return (connected_tables, predicates)


def duckdb_bayesqo_oracle(
    workload: WorkloadSpec,
    workload_inputs: list[BayesQOWorkloadInput],
    db_schema: Literal["JOB", "SQLStorm", "JOB-Complex", "Stack"] = "JOB",
) -> list[BayesQOQueryResult]:
    """Used for running BayesQO-generated plans against duckdb"""
    codec = _resolve_codec(workload)

    tasks = []
    for w in workload_inputs:
        join_tree = codec.decode(workload.query_tables, w.encoded_query)
        join_clause = join_tree.to_join_clause()
        sql = workload.query_template.format(join_clause)

        task = QueryTask(
            contracts.TimeQueryRequest(
                query=[
                    "SET disabled_optimizers = 'join_order,build_side_probe_side'",
                    contracts.PreparedQuery(sql=sql, params=[]),
                ],
                timeout_secs=w.timeout_secs,
                db_schema=db_schema,
            )
        )
        task.submit()
        tasks.append(task)

    results = []
    for w, task in zip(workload_inputs, tasks):
        result = task.result()
        if not isinstance(result, contracts.TimeQueryResponse):
            raise RuntimeError(f"Unexpected result type: {type(result)}")

        execution_spec = BayesQOQueryExecutionSpec(
            id=w.id,
            query=sql,
            timeout_secs=w.timeout_secs,
        )
        results.append(
            convert_to_bayesqo_result(
                execution_spec,
                result.result,
            )
        )
    return results


def duckdb_bayesqo_default(
    workload: WorkloadSpec,
    db_schema: Literal["JOB", "SQLStorm", "JOB-Complex", "Stack"] = "JOB",
    timeout_secs: int = 60,
) -> BayesQOQueryResult:
    sql = _default_plan(workload)
    task = QueryTask(
        contracts.TimeQueryRequest(
            query=[sql],
            timeout_secs=timeout_secs,
            db_schema=db_schema,
        )
    )
    task.submit()
    result = task.result()
    if not isinstance(result, contracts.TimeQueryResponse):
        raise RuntimeError(f"Unexpected result type: {type(result)}")

    execution_spec = BayesQOQueryExecutionSpec(
        id="default",
        query=sql,
        timeout_secs=10,
    )
    return convert_to_bayesqo_result(execution_spec, result.result)


def convert_to_bayesqo_result(
    spec: BayesQOQueryExecutionSpec, result: contracts.TimeQueryResult
) -> BayesQOQueryResult:
    match result:
        case contracts.QueryCompleteResponse(elapsed_secs=elapsed_secs, query_result=query_result):
            return BayesQOCompletedQuery(
                spec=spec,
                elapsed_secs=elapsed_secs,
                query_result=query_result,
            )
        case contracts.QueryTimeoutResponse(elapsed_secs=elapsed_secs):
            return BayesQOTimedOutQuery(
                spec=spec,
                elapsed_secs=elapsed_secs,
            )
        case contracts.QueryErrorResponse(error=error):
            return BayesQOFailedQuery(
                spec=spec,
                elapsed_secs=-1,
                error=error,
            )


class QueryTask:
    _request: contracts.RequestType
    _status: Literal["issued", "in-progress", "complete"]

    _id: Optional[int]
    _result: Optional[contracts.ResponseType]
    _client_start_time: Optional[float]

    def __init__(self, request: contracts.RequestType):
        self._request = request
        self._status = "not-submitted"

        self._id = None
        self._result = None
        self._client_start_time = None

    def submit(self):
        assert self._status == "not-submitted"
        self._client_start_time = time.time()

        # Extract schema from the request
        schema = self._request.db_schema

        with _get_pg_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO template_jobs (request, status, issued_at, schema)
                    VALUES (%s, 'issued', now(), %s)
                    RETURNING id
                    """,
                    (json.dumps(self._request.model_dump(by_alias=True)), schema),
                )
                self._id = cur.fetchone()[0]
                l.info(f"Submitted job ID {self._id}")
                self._status = "issued"
                # Notify workers of new job
                cur.execute("NOTIFY new_job")
        return self._id

    def _log_timing_info(self, issued_at, finished_at):
        """Log timing information for a completed job"""
        client_end_time = time.time()
        client_duration = client_end_time - self._client_start_time
        server_duration = (finished_at - issued_at).total_seconds()

        # l.debug(f"\nTiming for job {self._id}:")
        # l.debug(f"  Client-side duration: {client_duration:.2f}s")
        # l.debug(f"  Server-side duration: {server_duration:.2f}s")
        # l.debug(f"  Network/queue overhead: {(client_duration - server_duration):.2f}s")

    def status(self):
        if self._status == "not-submitted":
            return "not-submitted"
        with _get_pg_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT status, result, issued_at, finished_at FROM template_jobs WHERE id=%s",
                    (self._id,),
                )
                row = cur.fetchone()
                if not row:
                    raise RuntimeError(
                        f"Job id {self._id} not found in template_jobs table."
                    )
                status, result, issued_at, finished_at = row
                self._status = status
                if result is not None:
                    self._result = contracts.Response.validate_python(result)
                return status

    def _check_job_status(self, discovery_method: str = "unknown") -> bool:
        """Check job status and update internal state. Returns True if job is complete."""
        with _get_pg_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT status, result, issued_at, finished_at 
                    FROM template_jobs 
                    WHERE id=%s""",
                    (self._id,),
                )
                row = cur.fetchone()
                if row:
                    status, result, issued_at, finished_at = row
                    self._status = status
                    if result is not None:
                        self._result = contracts.Response.validate_python(result)
                    if status == "complete":
                        l.debug(
                            f"Job {self._id}: Completion discovered via {discovery_method}"
                        )
                        self._log_timing_info(issued_at, finished_at)

                        # Clean up completed job ID to prevent memory leak
                        if discovery_method == "NOTIFY":
                            with _notification_condition:
                                _completed_jobs.discard(self._id)

                        return True
        return False

    def result(self):
        """Wait for job to finish using LISTEN/NOTIFY with polling fallback"""
        ensure_monitor_thread()

        last_poll_time = time.time()  # Initialize to current time, not 0
        POLL_INTERVAL = 1.0  # Poll every 1 second as fallback (reduced from 10s)

        try:
            while self._status != "complete":
                # Check for notification first
                with _notification_condition:
                    # Wait for any notification with short timeout
                    _notification_condition.wait(timeout=0.1)  # Increased from 0.01 to reduce CPU

                    # Check if our job completed
                    if self._id in _completed_jobs:
                        last_poll_time = (
                            time.time()
                        )  # Reset poll timer - we got notification activity
                        if self._check_job_status("NOTIFY"):
                            break

                # Only poll if enough time has elapsed since last poll attempt
                current_time = time.time()
                if current_time - last_poll_time >= POLL_INTERVAL:
                    if self._check_job_status("polling"):
                        break
                    last_poll_time = current_time

        except KeyboardInterrupt:
            # Exit immediately on Ctrl+C without cleanup
            sys.exit(1)

        return self._result


def queries_equivalent(llm_output1: str, llm_output2: str) -> bool:
    """Given two LLM outputs, return True if they are equivalent.

    e.g.
    - (a (col1 > mode)) == (a (col1 > mode))
    - (a (col1 > last))(b (col2 = first)) == (b (col2 = first))(a (col1 > last))
    - (a (col1 > last))(b (col2 = first)) != (b (col2 > first))(a (col1 = last))
    """
    t1 = g.parse(llm_output1)
    t2 = g.parse(llm_output2)

    def extract_predicates(t: lark.Tree) -> set[tuple[str, str]]:
        predicates = set()
        for selector in t.children:
            table_name = str(selector.children[0])
            for filt in selector.children[1:]:
                filt = filt.children[0]
                if filt.data == "int_filter":
                    field = str(filt.children[0])
                    operator = str(filt.children[1].children[0])
                    value = str(filt.children[2].children[0])
                    predicates.add((table_name, f"{field} {operator} {value}"))
                elif filt.data == "str_filter":
                    field = str(filt.children[0])
                    str_val = str(filt.children[1].children[0])
                    predicates.add((table_name, f"{field} = {str_val}"))
        return predicates

    predicates1 = extract_predicates(t1)
    predicates2 = extract_predicates(t2)
    return predicates1 == predicates2


def get_predicate_graph(workload_set: WorkloadDefinitionSet):
    # Use the workload_set's join_graph directly instead of accessing via a query
    # This allows it to work even when there are no queries in the workload set
    db_graph = workload_set.join_graph

    # label edges with join predicates
    def get_edge_label(u, v):
        edge = db_graph.edges[u, v]
        return f"{edge['table']}.{edge['attr']} = {edge['referenced_table']}.{edge['referenced_attr']}"

    predicate_graph = nx.Graph()
    for node in db_graph.nodes:
        predicate_graph.add_node(node)
    for u, v in db_graph.edges:
        predicate_graph.add_edge(u, v, label=get_edge_label(u, v))

    return predicate_graph


def test_adversarial_queries():
    from workload.workloads import get_workload_set

    predicate_graph = get_predicate_graph(get_workload_set("JOB"))
    oracle = AdversarialQueryOracle(predicate_graph)

    with open("workload/adversarial-benchmark/queries.json") as f:
        queries = json.load(f)

    # Process queries in batches of 5 (10 total with default + adversarial versions)
    batch_size = 5
    # for i in range(0, len(queries), batch_size):
    # batch_queries = queries[i : i + batch_size]
    for query in queries:
        batch_queries = [query] * 5

        # Create both default and adversarial versions for each query in the batch
        batch_inputs = []
        query_info = []  # Keep track of which is which for logging

        for query in batch_queries:
            # Default version
            batch_inputs.append(
                AdversarialQueryInput(
                    llm_output=query["string"],
                    plan=None,
                    timeout_ms=10_000,
                    db_schema="JOB",
                )
            )
            query_info.append((query["string"], "default"))

            # Adversarial version
            batch_inputs.append(
                AdversarialQueryInput(
                    llm_output=query["string"],
                    plan=[0, 0, 0],
                    timeout_ms=5_000,
                    db_schema="JOB",
                )
            )
            query_info.append((query["string"], "adversarial"))

        # Submit all queries in this batch simultaneously
        results = oracle.query(batch_inputs)

        # Log results
        for (query_string, version), result in zip(query_info, results):
            l.info(f"Query: {query_string}")
            l.info(f"Version: {version}")
            l.info(f"Result: {result}")
            l.info("---")


def test_bayesqo_duckdb():
    """
    Test BayesQO oracle calls against the DuckDB worker cluster.
    Tests both JOB and JOB-Complex workloads with default and encoded plans.
    """
    from workload.workloads import OracleCodec, WorkloadSpec, get_workload_set

    from .oracle import WorkloadInput
    from .structures import CompletedQuery, FailedQuery, TimedOutQuery

    # Test both JOB and JOB-Complex workloads
    # workload_sets = ["JOB", "JOB-Complex"]
    workload_sets = ["Stack-on-SQLStorm"]

    for workload_set_name in workload_sets:
        l.info(f"Testing workload set: {workload_set_name}")

        workload_set = get_workload_set(workload_set_name)

        # Determine the appropriate db_schema for contract requests
        db_schema: Literal["JOB", "SQLStorm", "JOB-Complex", "Stack"]
        if workload_set_name == "JOB":
            db_schema = "JOB"
        elif workload_set_name == "JOB-Complex":
            db_schema = "JOB-Complex"
        elif workload_set_name == "SQLStorm":
            db_schema = "SQLStorm"
        elif workload_set_name == "Stack-on-SQLStorm":
            db_schema = "SQLStorm"
        else:
            db_schema = "JOB"  # default fallback

        total_queries = len(workload_set.queries)
        successful_default = 0
        successful_encoded = 0
        failed_queries = []

        for idx, (query_name, workload_def) in enumerate(workload_set.queries.items(), 1):
            l.info(f"\n{'-'*80}")
            l.info(f"[{idx}/{total_queries}] Testing query: {query_name}")
            l.info(f"{'-'*80}")

            try:
                # Create workload spec
                workload = WorkloadSpec.from_definition(workload_def, OracleCodec.AliasOrder)

                # Test 1: Default plan (no encoding)
                l.info(f"  Running default plan...")
                default_result = duckdb_bayesqo_default(workload, db_schema)

                # Check default result
                if not isinstance(default_result, CompletedQuery):
                    error_msg = f"Default plan failed for {query_name}"
                    if isinstance(default_result, FailedQuery):
                        error_msg += f": {default_result.error}"
                    elif isinstance(default_result, TimedOutQuery):
                        error_msg += ": Timed out"
                    l.error(error_msg)
                    failed_queries.append((query_name, "default", error_msg))
                    continue

                l.info(f"  ✓ Default plan completed in {default_result.elapsed_secs:.2f}s")
                successful_default += 1

                # Test 2: Encoded plan with dummy plan [0]
                # Use default plan's runtime as timeout for encoded plan
                timeout_secs = default_result.elapsed_secs
                l.info(f"  Running encoded plan [0] with timeout {timeout_secs:.2f}s...")

                workload_input = WorkloadInput(workload, [0], timeout_secs)
                encoded_result = duckdb_bayesqo_oracle(workload, [workload_input], db_schema)[0]

                # Check encoded result
                match encoded_result:
                    case CompletedQuery(_, elapsed):
                        l.info(f"  ✓ Encoded plan completed in {elapsed:.2f}s (default: {default_result.elapsed_secs:.2f}s)")
                        successful_encoded += 1
                    case TimedOutQuery(_, elapsed):
                        error_msg = f"Encoded plan timed out after {elapsed:.2f}s (default: {default_result.elapsed_secs:.2f}s)"
                        l.warning(f"  ⚠ {error_msg}")
                        failed_queries.append((query_name, "encoded", error_msg))
                    case FailedQuery(_, elapsed, error):
                        error_msg = f"Encoded plan failed: {error} (default: {default_result.elapsed_secs:.2f}s)"
                        l.error(f"  ✗ {error_msg}")
                        failed_queries.append((query_name, "encoded", error_msg))

            except Exception as e:
                error_msg = f"Exception while testing {query_name}: {str(e)}"
                l.error(f"  ✗ {error_msg}")
                failed_queries.append((query_name, "exception", error_msg))
                import traceback
                traceback.print_exc()

        # Summary for this workload set
        l.info("\n" + "="*80)
        l.info(f"Summary for {workload_set_name}:")
        l.info(f"  Total queries: {total_queries}")
        l.info(f"  Successful default plans: {successful_default}/{total_queries}")
        l.info(f"  Successful encoded plans: {successful_encoded}/{total_queries}")

        if failed_queries:
            l.info(f"\n  Failed queries ({len(failed_queries)}):")
            for query_name, plan_type, error in failed_queries:
                l.info(f"    - {query_name} ({plan_type}): {error}")
        else:
            l.info("  ✓ All queries executed successfully!")
        l.info("="*80 + "\n")


if __name__ == "__main__":
    # test_adversarial_queries()
    # test_bayesqo_duckdb()
    pass
