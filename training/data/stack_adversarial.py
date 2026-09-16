"""
Stack adversarial query generation and training data collection.

Generates random queries over the Stack dataset (workload/stack/stack.duckdb),
obtains their DuckDB EXPLAIN plans, converts them to JoinTrees, and stores
the results in the StackQuery table of workload.db.

Usage:
    uv run python -m training.data.stack_adversarial collect -n 100
    uv run python -m training.data.stack_adversarial test
"""
import json
import random
from pathlib import Path
from typing import Optional

import duckdb
import networkx as nx
import typer

from logger.log import l
from training.data.duckdb_jointree import PlanHasEmptyResult, build_join_tree
from training.data.storage import StackQuery
from training.data.stack_workload import WorkloadSchema, WorkloadSpecDefinition

app = typer.Typer(no_args_is_help=True)

# ---------------------------------------------------------------------------
# Schema constants derived from workload/stack/schema.sql
# ---------------------------------------------------------------------------

# All tables in the stack dataset
ALL_TABLES = [
    "account",
    "answer",
    "badge",
    "comment",
    "post_link",
    "question",
    "site",
    "so_user",
    "tag",
    "tag_question",
]

# Join predicates for each FK edge (used to build the join graph and SQL)
# Format: (table_a, table_b, predicate_string)
FOREIGN_KEY_EDGES: list[tuple[str, str, str]] = [
    ("so_user",     "site",     "so_user.site_id = site.site_id"),
    ("so_user",     "account",  "so_user.account_id = account.id"),
    ("question",    "site",     "question.site_id = site.site_id"),
    ("question",    "so_user",  "question.site_id = so_user.site_id AND question.owner_user_id = so_user.id"),
    ("answer",      "site",     "answer.site_id = site.site_id"),
    ("answer",      "so_user",  "answer.site_id = so_user.site_id AND answer.owner_user_id = so_user.id"),
    ("answer",      "question", "answer.site_id = question.site_id AND answer.question_id = question.id"),
    ("comment",     "site",     "comment.site_id = site.site_id"),
    ("badge",       "site",     "badge.site_id = site.site_id"),
    ("badge",       "so_user",  "badge.site_id = so_user.site_id AND badge.user_id = so_user.id"),
    ("tag",         "site",     "tag.site_id = site.site_id"),
    ("tag_question","site",     "tag_question.site_id = site.site_id"),
    ("tag_question","tag",      "tag_question.site_id = tag.site_id AND tag_question.tag_id = tag.id"),
    ("tag_question","question", "tag_question.site_id = question.site_id AND tag_question.question_id = question.id"),
    ("post_link",   "site",     "post_link.site_id = site.site_id"),
    ("post_link",   "question", "post_link.site_id = question.site_id AND post_link.post_id_from = question.id"),
]

# High-cardinality text columns to skip when generating predicates
IGNORED_COLUMNS: set[tuple[str, str]] = {
    ("account",  "display_name"),
    ("account",  "location"),
    ("account",  "about_me"),
    ("account",  "website_url"),
    ("question", "body"),
    ("question", "title"),
    ("question", "tagstring"),
    ("answer",   "body"),
    ("answer",   "title"),
    ("comment",  "body"),
    ("badge",    "name"),
    ("tag",      "name"),
}

# site.site_name is treated as an enum (173 values) rather than free-text
SITE_NAMES = [
    '3dprinting', 'academia', 'ai', 'android', 'anime', 'apple', 'arduino',
    'askubuntu', 'astronomy', 'aviation', 'avp', 'beer', 'bicycles',
    'bioinformatics', 'biology', 'bitcoin', 'blender', 'boardgames', 'bricks',
    'buddhism', 'chemistry', 'chess', 'chinese', 'christianity', 'civicrm',
    'codegolf', 'codereview', 'coffee', 'cogsci', 'computergraphics',
    'conlang', 'cooking', 'craftcms', 'crafts', 'crypto', 'cs', 'cseducators',
    'cstheory', 'datascience', 'dba', 'devops', 'diy', 'drupal', 'dsp',
    'earthscience', 'ebooks', 'economics', 'electronics', 'elementaryos',
    'ell', 'emacs', 'engineering', 'english', 'eosio', 'es', 'esperanto',
    'ethereum', 'expatriates', 'expressionengine', 'fitness', 'freelancing',
    'french', 'gamedev', 'gaming', 'gardening', 'genealogy', 'german', 'gis',
    'graphicdesign', 'ham', 'hardwarerecs', 'health', 'hermeneutics',
    'hinduism', 'history', 'homebrew', 'hsm', 'interpersonal', 'iot', 'iota',
    'islam', 'italian', 'ja', 'japanese', 'joomla', 'judaism', 'korean',
    'languagelearning', 'latin', 'law', 'lifehacks', 'linguistics',
    'literature', 'magento', 'martialarts', 'math', 'matheducators',
    'mathematica', 'mathoverflow', 'mechanics', 'moderators', 'monero',
    'money', 'movies', 'music', 'musicfans', 'mythology', 'networkengineering',
    'opendata', 'opensource', 'or', 'outdoors', 'parenting', 'patents', 'pets',
    'philosophy', 'photo', 'physics', 'pm', 'poker', 'politics', 'portuguese',
    'pt', 'puzzling', 'quant', 'quantumcomputing', 'raspberrypi',
    'retrocomputing', 'reverseengineering', 'robotics', 'rpg', 'ru', 'rus',
    'russian', 'salesforce', 'scicomp', 'scifi', 'security', 'serverfault',
    'sharepoint', 'sitecore', 'skeptics', 'softwareengineering',
    'softwarerecs', 'sound', 'space', 'spanish', 'sports', 'sqa', 'stackapps',
    'stackoverflow', 'stats', 'stellar', 'superuser', 'sustainability', 'tex',
    'tezos', 'tor', 'travel', 'tridion', 'ukrainian', 'unix', 'ux',
    'vegetarianism', 'vi', 'webapps', 'webmasters', 'windowsphone',
    'woodworking', 'wordpress', 'workplace', 'worldbuilding', 'writers',
]

# ---------------------------------------------------------------------------
# Join graph (built once at module load)
# ---------------------------------------------------------------------------

def _build_join_graph() -> nx.Graph:
    G = nx.Graph()
    G.add_nodes_from(ALL_TABLES)
    for a, b, pred in FOREIGN_KEY_EDGES:
        # Multi-edges are fine here; networkx Graph keeps only one but the
        # predicate dict on the first edge is sufficient for our SQL builder.
        if not G.has_edge(a, b):
            G.add_edge(a, b, predicate=pred)
        # else: already connected, skip the second FK (e.g. last_editor_id)
    return G

JOIN_GRAPH = _build_join_graph()

# All columns per table (non-PK, non-FK) for WorkloadSchema
ALL_COLUMNS: dict[str, list[str]] = {
    "site":         ["site_name"],
    "account":      ["display_name", "location", "about_me", "website_url"],
    "so_user":      ["reputation", "creation_date", "last_access_date", "upvotes", "downvotes"],
    "question":     ["creation_date", "deletion_date", "score", "view_count", "body",
                     "last_edit_date", "last_activity_date", "title", "favorite_count",
                     "closed_date", "tagstring"],
    "answer":       ["creation_date", "deletion_date", "score", "view_count", "body",
                     "last_edit_date", "last_activity_date", "title"],
    "comment":      ["score", "body", "date"],
    "badge":        ["name", "date"],
    "tag":          ["name"],
    "tag_question": [],
    "post_link":    ["link_type", "date"],
}

# Column types for each filterable (non-ignored) column
# Used in generate_random_query to decide what kind of predicate to emit
_COLUMN_TYPES: dict[tuple[str, str], str] = {
    ("site",      "site_name"):         "ENUM",
    ("so_user",   "reputation"):        "INTEGER",
    ("so_user",   "creation_date"):     "TIMESTAMP",
    ("so_user",   "last_access_date"):  "TIMESTAMP",
    ("so_user",   "upvotes"):           "INTEGER",
    ("so_user",   "downvotes"):         "INTEGER",
    ("question",  "creation_date"):     "TIMESTAMP",
    ("question",  "deletion_date"):     "TIMESTAMP",
    ("question",  "score"):             "INTEGER",
    ("question",  "view_count"):        "INTEGER",
    ("question",  "last_edit_date"):    "TIMESTAMP",
    ("question",  "last_activity_date"):"TIMESTAMP",
    ("question",  "favorite_count"):    "INTEGER",
    ("question",  "closed_date"):       "TIMESTAMP",
    ("answer",    "creation_date"):     "TIMESTAMP",
    ("answer",    "deletion_date"):     "TIMESTAMP",
    ("answer",    "score"):             "INTEGER",
    ("answer",    "view_count"):        "INTEGER",
    ("answer",    "last_edit_date"):    "TIMESTAMP",
    ("answer",    "last_activity_date"):"TIMESTAMP",
    ("comment",   "score"):             "INTEGER",
    ("comment",   "date"):              "TIMESTAMP",
    ("post_link", "link_type"):         "INTEGER",
    ("post_link", "date"):              "TIMESTAMP",
}

# Filterable columns per table (everything not in IGNORED_COLUMNS)
_FILTERABLE_COLUMNS: dict[str, list[str]] = {}
for (tbl, col) in _COLUMN_TYPES:
    if (tbl, col) not in IGNORED_COLUMNS:
        _FILTERABLE_COLUMNS.setdefault(tbl, []).append(col)

# ---------------------------------------------------------------------------
# Query string generation
# ---------------------------------------------------------------------------

def _random_intval() -> str:
    kind = random.choice(["first", "median", "last", "mode", "number"])
    if kind == "number":
        return f"{random.randint(0, 1000):04d}"
    return kind


def _random_tsval() -> str:
    kind = random.choice(["first", "median", "last", "number"])
    if kind == "number":
        return f"{random.randint(0, 1000):04d}"
    return kind


def _filter_for_column(table: str, col: str) -> str:
    ctype = _COLUMN_TYPES[(table, col)]
    if ctype == "ENUM":
        # site.site_name
        val = random.choice(SITE_NAMES)
        return f'({col} "{val}")'
    elif ctype == "INTEGER":
        op = random.choice(["<", ">", "=", "!="])
        return f"({col} {op} {_random_intval()})"
    elif ctype == "TIMESTAMP":
        op = random.choice(["t<", "t>", "t=", "t!="])
        return f"({col} {op} {_random_tsval()})"
    else:
        raise ValueError(f"Unknown type {ctype} for {table}.{col}")


def generate_random_query(
    min_tables: int = 2,
    max_tables: Optional[int] = None,
) -> str:
    """
    Generate a random query string in the adversarial grammar format.

    The grammar encodes a set of table selectors with optional column predicates:
        (table1 (col op val)...)(table2 ...)...

    Returns a string suitable for parsing by decode_query_to_sql().
    """
    if max_tables is None:
        max_tables = len(ALL_TABLES)

    num_tables = random.randint(min_tables, min(max_tables, len(ALL_TABLES)))
    selected_tables = sorted(random.sample(ALL_TABLES, num_tables))

    parts = []
    for table in selected_tables:
        filterable = _FILTERABLE_COLUMNS.get(table, [])

        # Bias heavily towards few predicates
        rand_val = random.random()
        if rand_val < 0.7:
            num_filters = 0
        elif rand_val < 0.9:
            num_filters = 1
        else:
            num_filters = 2
        num_filters = min(num_filters, len(filterable))

        chosen_cols = random.sample(filterable, num_filters) if num_filters > 0 else []
        filter_str = "".join(_filter_for_column(table, c) for c in chosen_cols)
        parts.append(f"({table} {filter_str})")

    return "".join(parts)


# ---------------------------------------------------------------------------
# Query string → SQL
# ---------------------------------------------------------------------------

def _parse_query_string(query_str: str) -> dict[str, list[tuple[str, str, str]]]:
    """
    Parse a query string into {table: [(col, op_or_strop, val), ...]} dict.

    Supports:
      integer predicates:   (col <|>|=|!= intval)
      timestamp predicates: (col t<|t>|t=|t!= tsval)
      enum predicates:      (col "value")
    """
    import re
    result: dict[str, list[tuple[str, str, str]]] = {}

    # Match top-level table selectors: (tablename ...content...)
    for table_match in re.finditer(r'\((\w+)\s+((?:[^()]*|\([^()]*\))*)\)', query_str):
        table = table_match.group(1)
        content = table_match.group(2).strip()
        predicates: list[tuple[str, str, str]] = []

        # Match sub-predicates
        for pred in re.finditer(r'\((\w+)\s+("([^"]+)"|(\S+)\s+(\S+))\)', content):
            col = pred.group(1)
            if pred.group(3) is not None:
                # enum: (col "value")
                predicates.append((col, "=", pred.group(3)))
            else:
                op  = pred.group(4)
                val = pred.group(5)
                predicates.append((col, op, val))

        result[table] = predicates

    return result


def _resolve_intval(table: str, col: str, val_str: str, con: duckdb.DuckDBPyConnection) -> Optional[object]:
    """Resolve a symbolic intval (first/median/last/mode/NNNN) to a concrete value."""
    if val_str.isdigit():
        return int(val_str)
    if val_str == "first":
        row = con.execute(f"SELECT MIN({col}) FROM {table}").fetchone()
    elif val_str == "last":
        row = con.execute(f"SELECT MAX({col}) FROM {table}").fetchone()
    elif val_str == "median":
        row = con.execute(f"SELECT MEDIAN({col}) FROM {table}").fetchone()
    elif val_str == "mode":
        row = con.execute(f"SELECT MODE({col}) FROM {table}").fetchone()
    else:
        return None
    return row[0] if row else None


def _resolve_tsval(table: str, col: str, val_str: str, con: duckdb.DuckDBPyConnection) -> Optional[object]:
    """Resolve a symbolic tsval to a concrete timestamp."""
    if val_str.isdigit():
        # treat as year offset from min date + N days
        row = con.execute(f"SELECT MIN({col}) + INTERVAL ({val_str}) DAY FROM {table}").fetchone()
        return row[0] if row else None
    if val_str == "first":
        row = con.execute(f"SELECT MIN({col}) FROM {table}").fetchone()
    elif val_str == "last":
        row = con.execute(f"SELECT MAX({col}) FROM {table}").fetchone()
    elif val_str == "median":
        row = con.execute(f"SELECT MEDIAN({col}) FROM {table}").fetchone()
    else:
        return None
    return row[0] if row else None


def query_tables(query_str: str) -> Optional[list[str]]:
    """
    Return the full list of tables (including Steiner-tree intermediates) for
    a query string, without resolving any predicate values.

    Returns None if the tables cannot be connected via the FK graph.
    """
    from networkx.algorithms import approximation as approx

    parsed = _parse_query_string(query_str)
    if not parsed:
        return None

    try:
        steiner = approx.steiner_tree(JOIN_GRAPH, list(parsed.keys()))
    except Exception:
        return None

    return list(steiner.nodes)


def decode_query_to_sql(
    query_str: str,
    con: duckdb.DuckDBPyConnection,
) -> Optional[tuple[str, list, list[str]]]:
    """
    Decode a grammar query string into (sql, params, tables).

    Uses a Steiner tree over the FK graph to find the minimal set of join
    predicates connecting the requested tables, then builds a SQL query with
    WHERE-clause predicates for the requested column filters.

    Returns None if the query cannot be decoded (e.g. tables not connected).
    """
    from networkx.algorithms import approximation as approx

    parsed = _parse_query_string(query_str)
    if not parsed:
        return None

    requested_tables = list(parsed.keys())

    # Find minimal connected subgraph (Steiner tree)
    try:
        steiner = approx.steiner_tree(JOIN_GRAPH, requested_tables)
    except Exception as e:
        l.warning(f"Could not find Steiner tree for {requested_tables}: {e}")
        return None

    tables_in_query = list(steiner.nodes)

    # Collect join predicates from Steiner tree edges
    join_predicates: list[str] = []
    for a, b in steiner.edges:
        pred = JOIN_GRAPH[a][b]["predicate"]
        join_predicates.append(pred)

    # Collect column predicates
    col_predicates: list[str] = []
    params: list = []
    for table, preds in parsed.items():
        for col, op, val in preds:
            ctype = _COLUMN_TYPES.get((table, col))
            if ctype == "ENUM":
                col_predicates.append(f"{table}.{col} = ?")
                params.append(val)
            elif ctype == "INTEGER":
                actual_op = op  # <, >, =, !=
                resolved = _resolve_intval(table, col, val, con)
                if resolved is None:
                    continue
                col_predicates.append(f"{table}.{col} {actual_op} ?")
                params.append(resolved)
            elif ctype == "TIMESTAMP":
                # strip leading 't' from timestamp ops
                actual_op = op[1:]  # t< -> <, t> -> >, etc.
                resolved = _resolve_tsval(table, col, val, con)
                if resolved is None:
                    continue
                col_predicates.append(f"{table}.{col} {actual_op} ?")
                params.append(resolved)

    all_predicates = join_predicates + col_predicates
    where_clause = " AND ".join(all_predicates) if all_predicates else "1=1"
    from_clause = ", ".join(tables_in_query)
    sql = f"SELECT COUNT(*) FROM {from_clause} WHERE {where_clause}"

    return sql, params, tables_in_query


# ---------------------------------------------------------------------------
# Plan collection
# ---------------------------------------------------------------------------

def _get_explain_plan(
    sql: str,
    params: list,
    con: duckdb.DuckDBPyConnection,
) -> Optional[dict]:
    """Run EXPLAIN (FORMAT JSON) and return the parsed plan dict."""
    try:
        con.execute("PRAGMA explain_output = 'physical_only'")
        rows = con.execute(f"EXPLAIN (FORMAT JSON) {sql}", params).fetchall()
        if rows:
            return json.loads(rows[0][1])[0]
    except Exception as e:
        l.warning(f"EXPLAIN failed: {e}")
    return None


def _make_workload_spec(
    sql: str,
    params: list,
    tables_in_query: list[str],
) -> WorkloadSpecDefinition:
    """Build a WorkloadSpecDefinition for use with build_join_tree."""
    query_join_graph = JOIN_GRAPH.subgraph(tables_in_query).copy()
    schema = WorkloadSchema(
        all_columns=ALL_COLUMNS,
        db_join_graph=JOIN_GRAPH,
        query_join_graph=query_join_graph,
    )
    return WorkloadSpecDefinition(
        name="stack_adversarial",
        all_tables=sorted(ALL_TABLES),
        query_tables=[(t, 1) for t in tables_in_query],
        query_template=sql,
        schema=schema,
        db="",
        db_user="",
        prewarm=False,
        pg_hint_plan_join_order=False,
        params=params,
    )


def collect_query_plans(num_queries: int) -> None:
    db_path = Path(__file__).resolve().parents[2] / "workload/stack/stack.duckdb"
    con = duckdb.connect(str(db_path), read_only=True)

    seen: set[str] = {r.query_string for r in StackQuery.select(StackQuery.query_string)}
    already = len(seen)
    if already >= num_queries:
        l.info(f"Already have {already} queries, target is {num_queries}, nothing to do")
        con.close()
        return

    collected = already
    skipped_duplicates = 0
    skipped_errors = 0

    while collected < num_queries:
        query_str = generate_random_query(min_tables=2, max_tables=7)

        if query_str in seen:
            skipped_duplicates += 1
            continue

        l.info(f"[{collected + 1}/{num_queries}] Generated: {query_str}")

        decoded = decode_query_to_sql(query_str, con)
        if decoded is None:
            l.warning("Could not decode query, skipping")
            skipped_errors += 1
            continue

        sql, params, tables_in_query = decoded

        explain = _get_explain_plan(sql, params, con)
        if explain is None:
            l.warning("EXPLAIN failed, skipping")
            skipped_errors += 1
            continue

        workload_spec = _make_workload_spec(sql, params, tables_in_query)

        try:
            join_tree = build_join_tree(explain, workload_spec)
        except PlanHasEmptyResult:
            l.warning("Plan has empty result, skipping")
            skipped_errors += 1
            continue
        except Exception as e:
            l.warning(f"build_join_tree failed: {e}")
            skipped_errors += 1
            continue

        StackQuery.create(
            query_string=query_str,
            explain_json=json.dumps(explain),
        )
        seen.add(query_str)
        collected += 1
        l.info(f"Stored query {collected}/{num_queries} (tables: {tables_in_query})")

    l.info(
        f"Done: total={collected}, new={collected - already}, "
        f"skipped_duplicates={skipped_duplicates}, "
        f"skipped_errors={skipped_errors}"
    )
    con.close()


# ---------------------------------------------------------------------------
# Grammar generation
# ---------------------------------------------------------------------------

def generate_grammar() -> str:
    """
    Generate a Lark grammar for the stack dataset in the same format as
    experiments/restricted_grammar.lark.

    Structure per table:
      {table}_filtered: {table}_selector  ("{other_table} ")? ...
      {table}_selector: "(table " filter1 ")" | "(table " filter2 ")" | ...
      {table}_{col}_filter: "(col " <terminal> ")"

    Terminals added beyond the base grammars:
      tsop  - timestamp comparison operators
      tsval - timestamp values (symbolic or 4-digit offset)
      enumval_{table}_{col} - inline alternation for enum columns
    """
    lines: list[str] = []

    # start: one or more table selectors in any combination
    all_selector_alts = " | ".join(f"{t}_selector" for t in ALL_TABLES)
    lines.append(f"start: ({all_selector_alts})+")
    lines.append("")

    for table in ALL_TABLES:
        filterable = _FILTERABLE_COLUMNS.get(table, [])

        # {table}_selector: zero or more filter predicates (each optional)
        if filterable:
            filter_terms = " ".join(f"{table}_{col}_filter?" for col in filterable)
            lines.append(f'{table}_selector: "({table} " {filter_terms} ")"')
        else:
            lines.append(f'{table}_selector: "({table} )"')

        # per-column filter rules
        for col in filterable:
            ctype = _COLUMN_TYPES[(table, col)]
            if ctype == "ENUM":
                lines.append(f'{table}_{col}_filter: "({col} \\"" enumval_{table}_{col} "\\")"')
            elif ctype == "INTEGER":
                lines.append(f'{table}_{col}_filter: "({col} " intop " " intval ")"')
            elif ctype == "TIMESTAMP":
                lines.append(f'{table}_{col}_filter: "({col} " tsop " " tsval ")"')

        lines.append("")

    # Shared terminals
    lines += [
        'intop: "<" | ">" | "=" | "!="',
        "",
        'intval: "first" | "median" | "last" | "mode" | int int int int',
        'int: "0" | "1" | "2" | "3" | "4" | "5" | "6" | "7" | "8" | "9"',
        "",
        'tsop: "t<" | "t>" | "t=" | "t!="',
        'tsval: "first" | "median" | "last" | int int int int',
        "",
    ]

    # Enum terminal for site.site_name
    site_alts = " | ".join(f'"{s}"' for s in SITE_NAMES)
    lines.append(f"enumval_site_site_name: {site_alts}")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

@app.command()
def grammar(
    output: str = typer.Option(
        "workload/stack/stack.lark",
        "--output", "-o",
        help="Path to write the Lark grammar file",
    ),
):
    """Write the Lark grammar for the stack dataset to a file."""
    text = generate_grammar()
    out_path = Path(output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text)
    print(f"Wrote grammar to {out_path}")


@app.command()
def collect(
    num_queries: int = typer.Option(
        ..., "--num-queries", "-n", help="Number of queries to collect"
    ),
):
    """Collect random Stack queries and their DuckDB EXPLAIN plans."""
    collect_query_plans(num_queries)


def _tables_in_explain(plan: dict) -> set[str]:
    """Recursively collect all table names appearing in SEQ_SCAN nodes."""
    tables: set[str] = set()
    node_type = plan.get("name", "")
    if node_type in ("SEQ_SCAN", "SEQ_SCAN "):
        t = plan.get("extra_info", {}).get("Table")
        if t:
            tables.add(t)
    for child in plan.get("children", []):
        tables |= _tables_in_explain(child)
    return tables


@app.command()
def test():
    """
    Generate and decode a few random queries and verify that every table
    present in the query also appears in the EXPLAIN plan and the JoinTree.
    """
    db_path = Path(__file__).resolve().parents[2] / "workload/stack/stack.duckdb"
    con = duckdb.connect(str(db_path), read_only=True)

    passed = 0
    failed = 0

    for i in range(5):
        query_str = generate_random_query(min_tables=2, max_tables=3)
        print(f"\n[{i+1}] query_str: {query_str}")
        decoded = decode_query_to_sql(query_str, con)
        if decoded is None:
            print("  FAIL: could not decode")
            failed += 1
            continue
        sql, params, tables = decoded
        expected = set(tables)
        print(f"  expected tables: {sorted(expected)}")

        explain = _get_explain_plan(sql, params, con)
        if explain is None:
            print("  FAIL: EXPLAIN failed")
            failed += 1
            continue

        explain_tables = _tables_in_explain(explain)
        explain_missing = expected - explain_tables
        if explain_missing:
            print(f"  FAIL: tables missing from EXPLAIN: {explain_missing}")
            failed += 1
            continue
        print(f"  EXPLAIN tables ok: {sorted(explain_tables)}")

        spec = _make_workload_spec(sql, params, tables)
        try:
            jt = build_join_tree(explain, spec)
        except Exception as e:
            print(f"  FAIL: build_join_tree raised: {e}")
            failed += 1
            continue

        jt_tables = jt.tables()
        jt_missing = expected - jt_tables
        if jt_missing:
            print(f"  FAIL: tables missing from JoinTree: {jt_missing}")
            failed += 1
            continue
        print(f"  JoinTree tables ok: {sorted(jt_tables)}")
        print("  PASS")
        passed += 1

    print(f"\n{passed}/5 passed, {failed}/5 failed")
    con.close()


@app.command()
def dump(
    output: str = typer.Option(
        ..., "--output", "-o", help="Path to write the CSV file"
    ),
):
    """
    Encode all stored plans with HashProbeStackMachineCodec and write a CSV
    with columns: query_string, encoded_plan.

    Rows where build_join_tree fails are skipped with a warning.
    """
    import csv
    from optimization.codec.codec import HashProbeStackMachineCodec

    codec = HashProbeStackMachineCodec(sorted(ALL_TABLES))

    out_path = Path(output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    rows = list(StackQuery.select())
    l.info(f"Encoding {len(rows)} stored plans...")

    skipped = 0
    written = 0

    with open(out_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["query_string", "encoded_plan"])

        for row in rows:
            explain = json.loads(row.explain_json)
            query_str = row.query_string

            # Reconstruct the full intended table list (including Steiner-tree
            # intermediates) so build_join_tree knows which tables are missing
            # when DuckDB emits EMPTY_RESULT for zero-row predicates.
            all_tables = query_tables(query_str)
            if all_tables is None:
                l.warning(f"Could not resolve tables, skipping: {query_str}")
                skipped += 1
                continue

            spec = _make_workload_spec("", [], all_tables)

            try:
                jt = build_join_tree(explain, spec)
            except Exception as e:
                l.warning(f"build_join_tree failed, skipping: {e}")
                skipped += 1
                continue

            if any(leaf.table == "<EMPTY>" for leaf in jt.all_leaves()):
                l.warning(f"JoinTree has unresolved <EMPTY> leaves, skipping: {query_str}")
                skipped += 1
                continue

            encoded = codec.encode(jt)
            encoded_str = ",".join(str(s) for s in encoded)
            writer.writerow([query_str, encoded_str])
            written += 1

    l.info(f"Wrote {written} rows to {out_path} (skipped {skipped})")


if __name__ == "__main__":
    app()
