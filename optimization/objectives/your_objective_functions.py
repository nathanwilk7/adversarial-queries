''' Define your objecive function(s) here
Note: All code assumes we seek to maximize f(x)
If you want to instead MINIMIZE the objecitve, multiple scores by -1 in 
your query_black_box() method 
''' 

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from dataclasses import dataclass
from typing import List, Tuple, Optional, Dict, Any
from datetime import datetime
import os
import csv
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

# Oracle imports for adversarial queries
from oracle.adversarial_queries import (
    AdversarialQueryOracle, AdversarialQueryInput, get_predicate_graph,
    DuckDBAdapter, PostgresAdapter,
)

# Default timeout for adversarial queries (30 seconds in ms)
TIMEOUT = 30000


class ObjectiveFunction:
    ''' Objective function f, we seek x that MAXIMIZE f(x)'''
    def __init__(self,):
        pass
    
    def __call__(self, x_list, timeouts_list=None):
        ''' Input 
                x_list: 
                    a LIST of input space items from the origianl input 
                    search space (i.e. list of aa seqs)
                timeouts_list:
                    option list of timeout values for each item in x_list 
                    amount of time we run oracle on that x before quitting and 
                    keeping it as a censored observation 
            Outputs 
                scores_list: 
                    a LIST of float values obtained by evaluating your 
                    objective function f on each x in x_list
                    or np.nan in the wherever x is an invalid input 
                censoring_list:
                    a LIST of int (0/1) values indicating whether 
                    or not each observation is censored 
                    (or a list of all 0's if the we are not censoring observations)
        '''
        if timeouts_list is None:
            scores_list, censoring_list = self.query_black_box(x_list)
        else:
            scores_list, censoring_list = self.query_black_box(x_list, timeouts_list)
        return scores_list, censoring_list


    def query_black_box(self, x_list):
        ''' Input 
                x_list: 
                    a LIST of input space items from the origianl input 
                    search space (i.e. list of aa seqs)
            Outputs 
                scores_list: 
                    a LIST of float values obtained by evaluating your 
                    objective function f on each x in x_list
                    or np.nan in the wherever x is an invalid input 
                censoring_list:
                    a LIST of int (0/1) values indicating whether 
                    or not each observation is censored 
                    (or a list of all 0's if the we are not censoring observations)
        '''
        raise NotImplementedError("Must implement method query_black_box() for the black box objective")



from workload.workloads import (
    OracleCodec,
    WorkloadSpec,
    # IMDB_WORKLOAD_SET,
    get_workload_set,
)
from oracle.oracle import (
    CompletedQuery,
    FailedQuery,
    TimedOutQuery,
    WorkloadInput,
    oracle_for_workload_cluster, 
)


VERBOSE_CALLBACK = False

def progress_callback(task_result):
    # Query completed successfully
    if isinstance(task_result, CompletedQuery):
        if VERBOSE_CALLBACK:
            print(f"SUCCESS: {task_result.spec.id} | {task_result.elapsed_secs} secs")
    # Query timed out
    elif isinstance(task_result, TimedOutQuery):
        if VERBOSE_CALLBACK:
            print(f"TIMEOUT: {task_result.spec.id}")
    # Query failed
    elif isinstance(task_result, FailedQuery):
        if VERBOSE_CALLBACK:
            print(f"FAILED: {task_result.spec.id}")
    # Unknown result type pls dont actually happen ;-;
    else:
        raise ValueError(f"Unknown task result type: {type(task_result)}")

    # Dictionary mapping from query id (string) to new timeout in seconds (float)
    return {}


class DatabaseObjective(ObjectiveFunction):
    ''' Database Oracles 
    ''' 
    def __init__(
        self, 
        workload_name,
        worst_runtime_observed=200, # worst runtime from init data, used to set score for OOM query plans
        timeout=100,
        which_language="aliases",
        oracle_max_bsz=10,
        so_future=None,
    ):
        super().__init__()
        # provision instances for new run 
        self.oracle_max_bsz = oracle_max_bsz
        self.which_language = which_language
        self.worst_runtime_observed = worst_runtime_observed 
        self.timeout = timeout 
        self.workload_name = workload_name
        workload_set_id = workload_name.split("_")[0]
        if workload_set_id == "CEB":
            workload_set_id = "CEB_3K" # FOR NOW ASSUME CEB 3K, not 13K
        elif workload_set_id == "STACK":
            assert so_future is not None, "Must provide so_future for STACK workload"
            if so_future:
                workload_set_id = "SO_FUTURE"
            else:
                workload_set_id = "SO_PAST"
        WORKLOAD_SET = get_workload_set(workload_set=workload_set_id) # JOB, CEB_3K, CEB_13K 
        self.workload_spec = WORKLOAD_SET.queries[workload_name]
        self.full_workload_spec = WorkloadSpec.from_definition(
            definition=self.workload_spec, 
            codec=self.get_codec(),
        )

    def get_codec(self,):
        ''' Sets var self.codec to specific codec for query language 
        '''
        if self.which_language == "join-order":
            codec = OracleCodec.JoinOrder
        elif self.which_language == "join-order-operators":
            codec = OracleCodec.JoinOrderOperators
        elif self.which_language == "aliases":
            codec = OracleCodec.Aliases
        else:
            assert 0, f"unknown lanugage: {self.which_language}"
        return codec

    def set_codec(self,):
        ''' Sets var self.codec to specific codec for query language associated with oracle
        '''
        assert NotImplementedError, "Must implement set_codec to set self.codec for specific DB Oracle"

    def query_black_box(self, x_list, timeouts_list=None):
        if timeouts_list is None:
            timeouts_list = [self.timeout]*len(x_list)

        self.total_non_parallel_runtime = 0.0 

        workloads = []
        for i in range(len(x_list)):
            encoded_query = x_list[i]
            timeout_secs = timeouts_list[i]

            wl_input = WorkloadInput(
                id=f"{i+1}",
                encoded_query=encoded_query,
                timeout_secs=timeout_secs,
            )
            workloads.append(wl_input)

        results = oracle_for_workload_cluster(
            workload=self.full_workload_spec, 
            workload_inputs=workloads,

        )

        scores_list, censoring_list = [], []
        for result in results:
            runtime = result.elapsed_secs  # should be ~same as self.timeout for timed-out queries
            score = -abs(runtime)

            self.total_non_parallel_runtime += runtime

            if isinstance(result, CompletedQuery):
                censoring_list.append(0)
            elif isinstance(result, TimedOutQuery):
                censoring_list.append(1)
            elif isinstance(result, FailedQuery):
                censoring_list.append(1)
                # Failures should get self.timeout*2 N seconds and be censored data
                #   this way they are counted as oracle calls still and oracle can learn that they are bad data points
                # score = timeout_secs * -2 
                ## Note: above creates an issue for non-timeout where we actually use very large timeout value...
                ## So instead let's make this no worse than the worst runtime observed in our init data 
                bad_runtime = min(self.worst_runtime_observed, result.spec.timeout_secs * 2)
                score = bad_runtime * -1
            else:
                assert 0, "result is not an instance of one of expected types"

            scores_list.append(score)

        return scores_list, censoring_list


@dataclass
class _ParsedInput:
    """Helper class for parsing query[SEP]plan input strings."""
    index: int
    query_string: str
    plan: Optional[List[int]]
    original_timeout_ms: int


class _BaseAdversarialQueryObjective(ObjectiveFunction):
    """Internal base class for adversarial query objectives.

    Consolidates parsing, retries, extraction, timeouts, and bookkeeping.
    Concrete subclasses specify scoring and logging semantics.
    """

    ORACLE_MAX_RETRIES = 3
    ORACLE_RETRY_DELAY = 2.0  # seconds

    def __init__(self, workload_name: str = "JOB", timeout_ms: int = TIMEOUT, schema: str = "JOB",
                 db_backend: str = "duckdb"):
        # `schema` doubles as both the workload-set selector AND the
        # AdversarialQueryInput.db_schema value sent to the worker. The
        # worker's pydantic contract requires "JOB"/"SQLStorm"/"JOB-Complex"/
        # "Stack". The grammar registry uses "IMDB" for the same database —
        # do NOT pass "IMDB" here; the dataclass layer will silently swallow
        # it and the worker will then reject with a literal_error.
        # See bayes_lqo/SCHEMA_NAMING.md for the full mapping.
        super().__init__()
        self.workload_name = workload_name
        self.timeout_ms = timeout_ms
        self.schema = schema
        self.db_backend = db_backend

        # Build oracle - use correct workload set for schema. Any non-Storm/
        # non-Stack value (e.g. "JOB" or legacy "IMDB") loads the JOB
        # workload, which covers Grammars 1-4.
        if schema == "SQLStorm":
            workload_set = get_workload_set("SQLStorm")
        elif schema == "Stack":
            workload_set = get_workload_set("Stack")
        else:
            workload_set = get_workload_set("JOB")
        predicate_graph = get_predicate_graph(workload_set)
        if db_backend == "postgres":
            adapter = PostgresAdapter()
        elif db_backend == "duckdb":
            adapter = DuckDBAdapter()
        else:
            raise ValueError(f"unknown db_backend={db_backend!r}; expected 'duckdb' or 'postgres'")
        self.oracle = AdversarialQueryOracle(predicate_graph, adapter=adapter)

        self.last_call_details: List[Dict[str, Any]] = []
        self.total_non_parallel_runtime = 0.0

    # ---------- Hooks subclasses must override ----------
    def _normalize_timeouts(self, n: int, timeouts_list: Optional[List[float]]) -> List[float]:
        raise NotImplementedError

    def _default_fallback_seconds(self, p: _ParsedInput) -> float:
        raise NotImplementedError

    def _generated_fallback_seconds(self, default_time_seconds: float) -> float:
        raise NotImplementedError

    def _log_to_csv(self, query: str, default_time_seconds: Optional[float],
                    default_status: str, generated_time_seconds: Optional[float],
                    generated_status: str, plan: List[int]) -> None:
        raise NotImplementedError

    def _score(self, default_time_seconds: float, generated_time_seconds: float) -> float:
        raise NotImplementedError

    def _source_tag(self) -> str:
        raise NotImplementedError

    def _print_default_query_exception_header(self, e: Exception) -> None:
        print(f"{type(e).__name__} caught in default oracle query: {e}")
        print("Treating all inputs as timed out")

    # ---------- Shared helpers ----------
    def _init_csv_log(self, csv_path: str, headers: List[str], ensure_dir: bool) -> None:
        if not os.path.exists(csv_path):
            if ensure_dir:
                os.makedirs(os.path.dirname(csv_path), exist_ok=True)
            with open(csv_path, 'w', newline='') as csvfile:
                csv.writer(csvfile).writerow(headers)

    def _parse_input(self, x: str) -> Tuple[str, Optional[List[int]]]:
        """Parse query[SEP]plan format into query string and plan list."""
        if '[SEP]' in x:
            left, right = x.split('[SEP]', 1)
            query_string = left.strip()
            plan_str = right.strip().strip('[]')
            try:
                if ',' in plan_str:
                    plan = [int(p.strip()) for p in plan_str.split(',')]
                else:
                    plan = [int(p) for p in plan_str.split()] if plan_str else None
            except ValueError:
                plan = None
        else:
            query_string, plan = x.strip(), None
        return query_string, plan

    def _extract_time_status(self, result, fallback_seconds: float) -> Tuple[float, str, int]:
        """Robustly extract (time_seconds, status, censored[0/1]) from oracle result."""
        try:
            if getattr(result, "type", None) == "time_query":
                inner = getattr(result, "result", None)
                if inner is not None:
                    inner_result = getattr(inner, "result", None)
                    if inner_result == "error":
                        err_msg = getattr(inner, "error", "Unknown error")
                        if ("Could not set lock" in err_msg) or ("Conflicting lock" in err_msg):
                            print(f"WARNING: DuckDB lock conflict detected: {err_msg[:100]}")
                        return float(fallback_seconds), "error", 1
                    if hasattr(inner, "elapsed_secs"):
                        t = float(inner.elapsed_secs)
                        status = inner_result if inner_result else "ok"
                        return t, status, (1 if status == "timeout" else 0)
        except Exception as e:
            print(f"WARNING: Exception in _extract_time_status: {e}")
        return float(fallback_seconds), "error", 1

    def _query_oracle_with_retry(self, oracle_inputs, max_retries=3, retry_delay=2.0, query_type="query"):
        """Submit queries with per-query retry on DuckDB lock errors."""
        def _make_mock_error_result(msg: str):
            class _MockError:
                def __init__(self, message: str):
                    self.type = 'time_query'
                    self.result = type('MockResult', (), {
                        'result': 'error',
                        'error': message
                    })()
            return _MockError(msg)

        def _is_lock_error(result) -> bool:
            if getattr(result, "type", None) != "time_query":
                return False
            inner = getattr(result, "result", None)
            if inner is None:
                return False
            if getattr(inner, "result", None) != "error":
                return False
            msg = getattr(inner, "error", "")
            return ("Could not set lock" in msg) or ("Conflicting lock" in msg)

        def _query_one(single_input):
            for attempt in range(max_retries + 1):
                try:
                    res_list = self.oracle.query([single_input])
                    res = res_list[0]
                    if _is_lock_error(res) and attempt < max_retries:
                        print(f"RETRY {attempt + 1}/{max_retries}: lock error in {query_type} query; retrying after {retry_delay}s")
                        time.sleep(retry_delay)
                        continue
                    return res
                except Exception as e:
                    if attempt < max_retries:
                        print(f"RETRY {attempt + 1}/{max_retries}: Exception in {query_type} query: {e}; retrying after {retry_delay}s")
                        time.sleep(retry_delay)
                        continue
                    print(f"FAILED: {query_type} query failed after {max_retries} retries: {e}")
                    return _make_mock_error_result(str(e))

        try:
            max_workers = int(os.environ.get("ORACLE_CONCURRENCY", "8"))
        except Exception:
            max_workers = 8
        max_workers = max(1, min(max_workers, len(oracle_inputs)))

        results = [None] * len(oracle_inputs)
        with ThreadPoolExecutor(max_workers=max_workers) as ex:
            future_to_idx = {ex.submit(_query_one, inp): idx for idx, inp in enumerate(oracle_inputs)}
            for fut in as_completed(future_to_idx):
                idx = future_to_idx[fut]
                try:
                    results[idx] = fut.result()
                except Exception as e:
                    print(f"WARNING: unexpected exception surfaced from worker for {query_type} query: {e}")
                    results[idx] = _make_mock_error_result(str(e))

        return results

    @staticmethod
    def _mock_timeout_result(timeout_seconds: float):
        class _Mock:
            def __init__(self, secs: float):
                self.type = 'time_query'
                self.result = type('MockResult', (), {
                    'elapsed_secs': secs,
                    'result': 'timeout'
                })()
        return _Mock(timeout_seconds)

    def query_black_box(self, x_list: List[str], timeouts_list: Optional[List[float]] = None
                        ) -> Tuple[List[float], List[int]]:
        """Main entry point: evaluate queries with default and generated plans."""
        timeouts_sec = self._normalize_timeouts(len(x_list), timeouts_list)
        parsed_inputs: List[_ParsedInput] = []
        default_inputs = []
        for i, x in enumerate(x_list):
            q, plan = self._parse_input(x)
            t_ms = int(abs(timeouts_sec[i]) * 1000)
            parsed_inputs.append(_ParsedInput(i, q, plan, t_ms))
            default_inputs.append(AdversarialQueryInput(llm_output=q, plan=None, timeout_ms=t_ms, db_schema=self.schema))

        # Execute defaults
        try:
            default_raw = self._query_oracle_with_retry(default_inputs, query_type="default")
        except Exception as e:
            self._print_default_query_exception_header(e)
            default_raw = [
                self._mock_timeout_result(self._default_fallback_seconds(p)) for p in parsed_inputs
            ]

        # Extract default times/status
        default_results: List[Dict[str, Any]] = []
        for i, (p, r) in enumerate(zip(parsed_inputs, default_raw)):
            t_sec, status, cens = self._extract_time_status(r, self._default_fallback_seconds(p))
            if t_sec < 0:
                print(f"ERROR: Negative default time detected: {t_sec}")
                t_sec = abs(t_sec)
            default_results.append({
                'time_seconds': t_sec, 'status': status, 'censored': cens, 'plan': None
            })

        # Build generated inputs (if plan provided)
        generated_inputs, mapping = [], []
        for i, p in enumerate(parsed_inputs):
            if p.plan is None:
                continue
            dsecs = default_results[i]['time_seconds']
            min_t = 10.0 * dsecs
            max_t = self.timeout_ms / 1000.0
            orig_t = p.original_timeout_ms / 1000.0
            if min_t <= orig_t <= max_t:
                gen_t = orig_t
            else:
                gen_t = min(min_t, max_t)
            generated_inputs.append(
                AdversarialQueryInput(llm_output=p.query_string, plan=p.plan, timeout_ms=int(gen_t * 1000), db_schema=self.schema)
            )
            mapping.append(i)

        # Execute generated
        gen_results: List[Dict[str, Any]] = []
        if generated_inputs:
            try:
                gen_raw = self._query_oracle_with_retry(generated_inputs, query_type="generated")
            except Exception as e:
                print(f"{type(e).__name__} caught in generated oracle query: {e}")
                print("Treating all generated inputs as timed out")
                gen_raw = [
                    self._mock_timeout_result(self._generated_fallback_seconds(default_results[idx]['time_seconds']))
                    for idx in mapping
                ]
            for orig_idx, r in zip(mapping, gen_raw):
                fallback = self._generated_fallback_seconds(default_results[orig_idx]['time_seconds'])
                g_secs, g_status, g_cens = self._extract_time_status(r, fallback)
                if g_secs < 0:
                    print(f"ERROR: Negative generated time detected: {g_secs}")
                    g_secs = abs(g_secs)
                gen_results.append({
                    'original_index': orig_idx, 'time_seconds': g_secs,
                    'status': g_status, 'censored': g_cens,
                    'plan': parsed_inputs[orig_idx].plan
                })

        # Score + censoring
        gen_by_idx = {r['original_index']: r for r in gen_results}
        scores_list: List[float] = []
        censoring_list: List[int] = []
        self.total_non_parallel_runtime = 0.0
        self.last_call_details = []

        for i in range(len(x_list)):
            d = default_results[i]
            if i in gen_by_idx:
                g = gen_by_idx[i]
                self._log_to_csv(
                    query=parsed_inputs[i].query_string,
                    default_time_seconds=d['time_seconds'], default_status=d['status'],
                    generated_time_seconds=g['time_seconds'], generated_status=g['status'],
                    plan=g['plan']
                )
                score = self._score(d['time_seconds'], g['time_seconds'])
                cens = max(d['censored'], g['censored'])
                self.total_non_parallel_runtime += (d['time_seconds'] + g['time_seconds'])
                d_ms = d['time_seconds'] * 1000.0
                g_ms = g['time_seconds'] * 1000.0
                self.last_call_details.append({
                    'query': parsed_inputs[i].query_string,
                    'generated_plan': g['plan'],
                    'default_time_ms': d_ms, 'generated_time_ms': g_ms,
                    'absolute_advantage_ms': d_ms - g_ms,
                    'relative_advantage': (d_ms / g_ms) if g_ms > 0 else None,
                    'timeout_ms': self.timeout_ms, 'source': self._source_tag()
                })
            else:
                score = -d['time_seconds']
                cens = d['censored']
                self.total_non_parallel_runtime += d['time_seconds']
                d_ms = d['time_seconds'] * 1000.0
                self.last_call_details.append({
                    'query': parsed_inputs[i].query_string,
                    'generated_plan': None,
                    'default_time_ms': d_ms, 'generated_time_ms': None,
                    'absolute_advantage_ms': None, 'relative_advantage': None,
                    'timeout_ms': self.timeout_ms, 'source': self._source_tag()
                })
            scores_list.append(score)
            censoring_list.append(cens)

        return scores_list, censoring_list


class AdversarialQueryObjective(_BaseAdversarialQueryObjective):
    """Adversarial query objective scoring by relative speedup.
    Score = default_time / generated_time (higher is better)
    """

    def __init__(
        self,
        workload_name: str = "JOB",
        timeout_ms: int = TIMEOUT,
        csv_log_path: str = f"./oracle_logs_rel/{datetime.now().isoformat()}_adversarial_query_results.csv",
        worst_case_penalty: float = 2.0,
        schema: str = "JOB",
        db_backend: str = "duckdb",
    ):
        super().__init__(workload_name=workload_name, timeout_ms=timeout_ms, schema=schema,
                         db_backend=db_backend)
        self.csv_log_path = csv_log_path
        self.worst_case_penalty = worst_case_penalty
        self._init_csv_log(
            csv_path=self.csv_log_path,
            headers=[
                'timestamp', 'query', 'default_plan', 'default_plan_time_ms',
                'generated_plan', 'generated_plan_time_ms',
                'generated_plan_advantage_ms', 'speedup_ratio',
                'default_status', 'generated_status'
            ],
            ensure_dir=True
        )

    def _normalize_timeouts(self, n: int, timeouts_list: Optional[List[float]]) -> List[float]:
        if timeouts_list is None:
            secs = [self.timeout_ms / 1000.0] * n
        else:
            secs = [abs(t) for t in timeouts_list]
            if any(t > 1000 for t in secs):
                secs = [t / 1000.0 for t in secs]
        return secs

    def _default_fallback_seconds(self, p: _ParsedInput) -> float:
        # Error/timeout fallback equals the per-query timeout — no penalty inflation,
        # so a failed default plan can't manufacture a fake "advantage" against a
        # working generated plan.
        return p.original_timeout_ms / 1000.0

    def _generated_fallback_seconds(self, default_time_seconds: float) -> float:
        # Same fix on the generated side — failed generated plans are recorded as
        # taking exactly the timeout, not 2× the default.
        return self.timeout_ms / 1000.0

    def _print_default_query_exception_header(self, e: Exception) -> None:
        print(f"{type(e).__name__} caught in default oracle query: {e}")
        print("Treating all inputs as timed out")

    def _log_to_csv(self, query, default_time_seconds, default_status,
                    generated_time_seconds, generated_status, plan):
        with open(self.csv_log_path, 'a', newline='') as csvfile:
            writer = csv.writer(csvfile)
            d_ms = None if default_time_seconds is None else default_time_seconds * 1000.0
            g_ms = None if generated_time_seconds is None else generated_time_seconds * 1000.0
            if d_ms is None or g_ms is None:
                adv_ms, speedup = None, None
            else:
                adv_ms = d_ms - g_ms
                speedup = d_ms / g_ms if g_ms > 0 else (float('inf') if d_ms > 0 else 1.0)
            writer.writerow([
                datetime.now().isoformat(), query, 'default', d_ms,
                json.dumps(plan), g_ms, adv_ms, speedup,
                default_status, generated_status
            ])

    def _score(self, default_time_seconds: float, generated_time_seconds: float) -> float:
        if default_time_seconds > 0 and generated_time_seconds > 0:
            return default_time_seconds / generated_time_seconds
        return 0.0

    def _source_tag(self) -> str:
        return 'oracle_rel'


class AbsoluteTimeImprovementObjective(_BaseAdversarialQueryObjective):
    """Adversarial query objective scoring by absolute time improvement.
    Score = default_time - generated_time (higher is better)
    """

    def __init__(
        self,
        workload_name: str = "JOB",
        timeout_ms: int = TIMEOUT,
        csv_log_path: str = f"./oracle_logs_abs/{datetime.now().isoformat()}_absolute_time_results.csv",
        failure_penalty_seconds: Optional[float] = None,
        schema: str = "JOB",
        db_backend: str = "duckdb",
    ):
        super().__init__(workload_name=workload_name, timeout_ms=timeout_ms, schema=schema,
                         db_backend=db_backend)
        self.csv_log_path = csv_log_path
        # Default failure_penalty_seconds to the per-query timeout (not 300s) so a
        # failed plan doesn't manufacture a fake advantage. Override only if you want
        # the old inflated-sentinel behaviour.
        self.failure_penalty_seconds = (
            failure_penalty_seconds if failure_penalty_seconds is not None else timeout_ms / 1000.0
        )
        self._init_csv_log(
            csv_path=self.csv_log_path,
            headers=[
                'timestamp', 'query', 'default_plan', 'default_plan_time_seconds',
                'generated_plan', 'generated_plan_time_seconds',
                'absolute_improvement_seconds', 'default_status', 'generated_status'
            ],
            ensure_dir=True
        )

    def _normalize_timeouts(self, n: int, timeouts_list: Optional[List[float]]) -> List[float]:
        if timeouts_list is None:
            secs = [self.timeout_ms / 1000.0] * n
        else:
            secs = [abs(t) for t in timeouts_list]
            secs = [max(t, 1.0) for t in secs]
        return secs

    def _default_fallback_seconds(self, p: _ParsedInput) -> float:
        return self.failure_penalty_seconds

    def _generated_fallback_seconds(self, default_time_seconds: float) -> float:
        return self.failure_penalty_seconds

    def _log_to_csv(self, query, default_time_seconds, default_status,
                    generated_time_seconds, generated_status, plan):
        with open(self.csv_log_path, 'a', newline='') as csvfile:
            writer = csv.writer(csvfile)
            if default_time_seconds is not None and generated_time_seconds is not None:
                abs_improve = default_time_seconds - generated_time_seconds
            else:
                abs_improve = None
            writer.writerow([
                datetime.now().isoformat(), query, 'default', default_time_seconds,
                json.dumps(plan), generated_time_seconds, abs_improve,
                default_status, generated_status
            ])

    def _score(self, default_time_seconds: float, generated_time_seconds: float) -> float:
        return default_time_seconds - generated_time_seconds

    def _source_tag(self) -> str:
        return 'oracle_abs'


'''Objective functions with unique string identifiers 
identifiers can be passed in when running LOL-BO --task_id arg
whcih specifies which objective function to use 
--task_specific_args can be used to specify a list of args 
passed into the init of any of these objectives when they are initialized 
'''
OBJECTIVE_FUNCTIONS_DICT = {
    'db': DatabaseObjective,
    'adversarial_query_rel': AdversarialQueryObjective,
    'adversarial_query_abs': AbsoluteTimeImprovementObjective,
}


if __name__ == "__main__":
    # Test new oracle_for_workload_cluster
    fake_vae_strings = [
        [0, 0, 0],
        [0, 1, 2],
        [0],
        [0, 0, 0, 0, 0, 0],
        [0, 3]
    ]
    obj = OBJECTIVE_FUNCTIONS_DICT["db"](workload_name="JOB_9D", worst_runtime_observed=200)
    scores_list, censoring_list = obj.query_black_box(x_list=fake_vae_strings, timeouts_list=[100,100,100,100,100])
    print(scores_list, censoring_list)
