"""Adversarial Query Optimization — LOLBO for adversarial query generation."""

import logging
import sys
from pathlib import Path
logging.getLogger("sqlglot").setLevel(logging.ERROR)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
import fire
from optimization.scripts.optimize import Optimize
from optimization.lolbo.adversarial_query_vae_objective import AdversarialQueryVAEObjective
import torch
import json
from utils.set_seed import set_seed
import math
import os
from datetime import datetime
import csv
import wandb

logger = logging.getLogger(__name__)


class AdversarialQueryOptimization(Optimize):
    """
    Run LOLBO Optimization for Adversarial Query Generation
    """
    def __init__(
        self,
        path_to_plan_vae_statedict="../../training/plan_vae/checkpoints/best_64.ckpt",
        path_to_query_vae_model="../query_inference/epoch_0",
        path_to_mapping_layer="../query_inference/mapping_layer_epoch_0.pt",
        grammar_name="imdb_full_21table",
        query_dim=256,
        plan_dim=64,
        task_specific_args=[],
        constraint_function_ids=[],
        constraint_thresholds=[],
        constraint_types=[],
        api_base_url="http://localhost:8000/v1",
        api_model_name=None,
        # `schema` is propagated all the way down to AdversarialQueryInput.db_schema,
        # which the worker's pydantic contract validates against
        # Literal["JOB", "SQLStorm", "JOB-Complex", "Stack"]. Use the worker-side
        # name — for IMDB grammars (Grammar 1–4) that's "JOB", NOT "IMDB".
        # See bayes_lqo/SCHEMA_NAMING.md for the full mapping.
        schema: str = "JOB",
        timeout_ms: int = 30000,
        init_log_path: str = None,
        db_backend: str = "duckdb",
        **kwargs,
    ):
        self.path_to_plan_vae_statedict = path_to_plan_vae_statedict
        self.path_to_query_vae_model = path_to_query_vae_model
        self.path_to_mapping_layer = path_to_mapping_layer
        self.grammar_name = grammar_name
        self.query_dim = query_dim
        self.plan_dim = plan_dim
        self.dim = query_dim + plan_dim
        self.task_specific_args = task_specific_args
        self.constraint_function_ids = constraint_function_ids
        self.constraint_thresholds = constraint_thresholds
        self.constraint_types = constraint_types
        self.api_base_url = api_base_url
        self.api_model_name = api_model_name
        self.schema = schema
        self.timeout_ms = timeout_ms
        self.init_log_path = init_log_path
        self.db_backend = db_backend
        if db_backend not in ("duckdb", "postgres"):
            raise ValueError(f"--db_backend must be 'duckdb' or 'postgres', got {db_backend!r}")

        # Override task_id for adversarial queries
        self.task_id = kwargs.get('task_id', None)
        kwargs['workload_name'] = f'ADVERSARIAL_QUERY_{schema.upper()}'

        super().__init__(**kwargs)

        # Add args to method args dict for logging
        self.method_args['opt1'] = locals()
        del self.method_args['opt1']['self']

    def initialize_objective(self):
        '''Initialize the adversarial query objective'''
        self.objective = AdversarialQueryVAEObjective(
            task_id=self.task_id,
            path_to_plan_vae_statedict=self.path_to_plan_vae_statedict,
            path_to_query_vae_model=self.path_to_query_vae_model,
            path_to_mapping_layer=self.path_to_mapping_layer,
            grammar_name=self.grammar_name,
            query_dim=self.query_dim,
            plan_dim=self.plan_dim,
            task_specific_args=self.task_specific_args,
            constraint_function_ids=self.constraint_function_ids,
            constraint_thresholds=self.constraint_thresholds,
            constraint_types=self.constraint_types,
            api_base_url=self.api_base_url,
            api_model_name=self.api_model_name,
            schema=self.schema,
            db_backend=self.db_backend,
            timeout_ms=self.timeout_ms,
        )

        self.init_train_z = self.compute_train_zs()

        # Compute initial constraint values
        self.init_train_c = self.objective.compute_constraints(self.init_train_x)

        return self

    def compute_train_zs(self, bsz=100):
        '''Compute latent codes for initial training data'''
        init_zs = []
        self.objective.plan_vae.eval()

        n_batches = math.ceil(len(self.init_train_x) / bsz)
        for i in range(n_batches):
            start_idx = i * bsz
            end_idx = min((i + 1) * bsz, len(self.init_train_x))
            xs_batch = self.init_train_x[start_idx:end_idx]

            zs, _ = self.objective.vae_forward(xs_batch)
            init_zs.append(zs.detach().cpu())

        if init_zs:
            return torch.cat(init_zs, dim=0)
        else:
            return torch.randn(len(self.init_train_x), self.dim)

    def start_wandb(self):
        '''Start wandb tracking'''
        tags = [self.schema.lower(), "ADVERSARIAL_QUERY", self.grammar_name]

        if self.track_with_wandb:
            config_dict = {k: v for method_dict in self.method_args.values() for k, v in method_dict.items()}
            self.tracker = wandb.init(
                project=self.wandb_project_name,
                entity=self.wandb_entity,
                config=config_dict,
                tags=tags,
            )
            self.wandb_run_name = wandb.run.name
        else:
            self.tracker = None
            self.wandb_run_name = 'no-wandb-tracking'

        return self

    def load_train_data(self):
        if self.schema == "SQLStorm":
            self._load_train_data_csv()
        elif self.schema == "Stack":
            self._load_train_data_stack()
        else:
            self._load_train_data_jsonl()

    def _load_train_data_stack(self):
        """Load Stack init data, using precomputed oracle logs if available.

        Priority:
        1. If --init_log_path is set, load from that oracle log CSV (no oracle calls needed)
        2. Otherwise, load from stack_results.csv and evaluate via oracle
        """
        script_dir = os.path.dirname(__file__)

        # Check for precomputed oracle log (from a previous run)
        init_log_path = getattr(self, 'init_log_path', None)
        if init_log_path and os.path.exists(init_log_path):
            logger.info(f"Loading precomputed Stack init from oracle log: {init_log_path}")
            self._load_from_oracle_log(init_log_path)
            return

        # Fall back to evaluating from stack_results.csv
        results_csv = os.path.join(script_dir, '../objectives/stack_results.csv')
        if not os.path.exists(results_csv):
            raise FileNotFoundError(f"Could not find Stack init data at {results_csv}")

        logger.info(f"Loading Stack init data from: {results_csv}")

        init_rows = []
        with open(results_csv, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                query_string = row.get('query_string', '')
                encoded_plan_str = row.get('encoded_plan', '')
                try:
                    encoded_plan = [int(x.strip()) for x in encoded_plan_str.split(',') if x.strip()]
                except ValueError:
                    continue

                init_rows.append({
                    'query': query_string,
                    'generated_plan': encoded_plan,
                    'default_time_ms': None,
                    'generated_time_ms': None,
                    'source': 'stack_csv',
                    'timeout_ms': 30000,
                })

        if len(init_rows) > self.num_initialization_points:
            init_rows = init_rows[:self.num_initialization_points]

        logger.info(f"Loaded {len(init_rows)} Stack init rows, all need oracle evaluation")

        # Build x_list — all rows need evaluation
        x_list = []
        for row in init_rows:
            plan = row['generated_plan']
            if not plan:
                continue
            plan_str = ','.join(map(str, plan))
            combined = f"{row['query']}[SEP]{plan_str}"
            x_list.append(combined)

        # Evaluate all via the oracle
        from optimization.objectives.your_objective_functions import OBJECTIVE_FUNCTIONS_DICT
        oracle_obj = OBJECTIVE_FUNCTIONS_DICT[self.task_id](
            *self.task_specific_args,
            schema=self.schema,
            db_backend=self.db_backend,
            timeout_ms=self.timeout_ms,
        )
        batch_size = 10
        all_scores = []
        all_censoring = []
        for i in range(0, len(x_list), batch_size):
            batch = x_list[i:i+batch_size]
            logger.info(f"Oracle init batch {i//batch_size + 1}/{(len(x_list)-1)//batch_size + 1} ({len(batch)} queries)")
            bs, bc = oracle_obj.query_black_box(batch)
            all_scores.extend(bs)
            all_censoring.extend(bc)

        if not x_list:
            raise ValueError("No valid Stack initialization points found")

        self.init_train_x = x_list
        self.num_initialization_points = len(x_list)
        self.init_train_y = torch.tensor(all_scores).float().unsqueeze(-1)
        self.init_censoring = torch.tensor(all_censoring).float().unsqueeze(-1)

        logger.info(f"Stack init complete: {len(x_list)} points, score range=({self.init_train_y.min().item():.4f}, {self.init_train_y.max().item():.4f}), censored={self.init_censoring.sum().item():.0f}/{len(x_list)}")

    def _load_from_oracle_log(self, log_path):
        """Load init data from a previous run's oracle log CSV.

        Supports both formats:
        - rel logs: columns include default_plan_time_ms, generated_plan_time_ms, speedup_ratio
        - abs logs: columns include default_plan_time_seconds, generated_plan_time_seconds
        """
        init_rows = []
        with open(log_path, 'r') as f:
            reader = csv.DictReader(f)
            headers = reader.fieldnames
            is_abs = 'default_plan_time_seconds' in headers

            for row in reader:
                query = row.get('query', '')
                plan_str = row.get('generated_plan', '')
                ds = row.get('default_status', '')
                gs = row.get('generated_status', '')

                # Parse plan from string like "[5, 4, 7]"
                plan_str_clean = plan_str.strip().strip('"').strip('[]')
                try:
                    plan = [int(x.strip()) for x in plan_str_clean.split(',') if x.strip()]
                except ValueError:
                    continue

                if is_abs:
                    dt = float(row.get('default_plan_time_seconds', 0))
                    gt = float(row.get('generated_plan_time_seconds', 0))
                    dt_ms = dt * 1000
                    gt_ms = gt * 1000
                else:
                    dt_ms = float(row.get('default_plan_time_ms', 0))
                    gt_ms = float(row.get('generated_plan_time_ms', 0))

                init_rows.append({
                    'query': query,
                    'plan': plan,
                    'default_time_ms': dt_ms,
                    'generated_time_ms': gt_ms,
                    'default_status': ds,
                    'generated_status': gs,
                })

        if len(init_rows) > self.num_initialization_points:
            init_rows = init_rows[:self.num_initialization_points]

        x_list = []
        scores = []
        censoring = []

        for row in init_rows:
            plan_str = ','.join(map(str, row['plan']))
            combined = f"{row['query']}[SEP]{plan_str}"
            x_list.append(combined)

            dt_ms = row['default_time_ms']
            gt_ms = row['generated_time_ms']
            ds = row['default_status']
            gs = row['generated_status']

            # Score must match what query_black_box() returns in the live oracle.
            dt_s = dt_ms / 1000.0
            gt_s = gt_ms / 1000.0
            # The live oracle always applies the objective to its recorded
            # times, including timeout/error fallback times, and marks the
            # observation as censored separately.  Reproduce that exactly when
            # restoring a log so the surrogate sees the same y values.
            if self.task_id == 'adversarial_query_abs':
                score = dt_s - gt_s
            elif dt_s > 0 and gt_s > 0:
                score = dt_s / gt_s
            else:
                score = 0.0

            is_censored = 1 if (ds == 'timeout' or gs == 'timeout' or ds == 'error' or gs == 'error') else 0
            scores.append(score)
            censoring.append(is_censored)

        if not x_list:
            raise ValueError(f"No valid init points found in {log_path}")

        self.init_train_x = x_list
        self.num_initialization_points = len(x_list)
        self.init_train_y = torch.tensor(scores).float().unsqueeze(-1)
        self.init_censoring = torch.tensor(censoring).float().unsqueeze(-1)

        logger.info(f"Loaded {len(x_list)} precomputed init points from {log_path}, "
                    f"score range=({self.init_train_y.min().item():.4f}, {self.init_train_y.max().item():.4f}), "
                    f"censored={self.init_censoring.sum().item():.0f}/{len(x_list)}")

    def _load_train_data_csv(self):
        """Load initialization data from sqlstorm_results.csv.

        The sqlstorm_results.csv contains pre-computed runtime data:
        - query_string: The SQLStorm query
        - encoded_plan: Comma-separated plan encoding
        - runtime_ms: Execution time in milliseconds
        - status: 'complete' or 'timeout'

        For adversarial_query_rel scoring, we use a baseline runtime estimate
        since the CSV only contains generated plan runtimes.
        """
        script_dir = os.path.dirname(__file__)

        # Primary path: schema-specific results CSV in objectives/
        if self.schema == "Stack":
            results_csv = os.path.join(script_dir, '../objectives/stack_results.csv')
        else:
            results_csv = os.path.join(script_dir, '../objectives/sqlstorm_results.csv')

        if not os.path.exists(results_csv):
            raise FileNotFoundError(f"Could not find results CSV at {results_csv}")

        logger.info(f"Loading init data from: {results_csv}")

        # Load CSV data
        init_rows = []
        with open(results_csv, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                query_string = row.get('query_string', '')
                encoded_plan_str = row.get('encoded_plan', '')
                runtime_ms_str = row.get('runtime_ms', '')
                status = row.get('status', 'complete')

                try:
                    encoded_plan = [int(x.strip()) for x in encoded_plan_str.split(',') if x.strip()]
                except ValueError:
                    continue

                try:
                    runtime_ms = float(runtime_ms_str)
                except ValueError:
                    runtime_ms = 30000.0  # Default to timeout

                init_rows.append({
                    'query': query_string,
                    'generated_plan': encoded_plan,
                    'generated_time_ms': runtime_ms,
                    'status': status,
                })

        logger.info(f"Loaded {len(init_rows)} rows from CSV")

        # Limit to num_initialization_points
        if len(init_rows) > self.num_initialization_points:
            init_rows = init_rows[:self.num_initialization_points]
            logger.info(f"Limited to {self.num_initialization_points} initialization points")

        # Build x_list and scores
        x_list = []
        scores = []
        censoring = []

        for row in init_rows:
            plan = row['generated_plan']
            if not plan:
                continue

            plan_str = ','.join(map(str, plan))
            combined = f"{row['query']}[SEP]{plan_str}"
            x_list.append(combined)

            generated_time_ms = row['generated_time_ms']
            status = row['status']

            score = -generated_time_ms / 1000.0

            scores.append(score)
            censoring.append(1 if status == 'timeout' else 0)

        if not x_list:
            raise ValueError("No valid initialization points found in CSV")

        self.init_train_x = x_list
        self.num_initialization_points = len(x_list)
        self.init_train_y = torch.tensor(scores).float().unsqueeze(-1)
        self.init_censoring = torch.tensor(censoring).float().unsqueeze(-1)

        logger.info(f"Prepared {len(x_list)} init points, score range=({self.init_train_y.min().item():.4f}, {self.init_train_y.max().item():.4f}), censored={self.init_censoring.sum().item():.0f}/{len(x_list)}")

        return self

    def _load_train_data_jsonl(self):
        """Load initialization data, always logging precomputed rows and producing a merged snapshot.

        Steps:
          1. Load aggregated init JSONL if present, else fall back to shuffled_training.json.
          2. Identify rows missing runtime info and evaluate only those.
          3. Always write a precomputed log CSV (even if 0 oracle calls).
          4. Write a filled JSONL if new evaluations occurred.
          5. Write a merged aggregated snapshot with timestamp (never overwrites originals).
        """
        script_dir = os.path.dirname(__file__)
        agg_path = os.path.join(script_dir, '../workload/adversarial-benchmark/aggregated_init_30s_timeout.jsonl')
        shuffled_path = os.path.join(script_dir, '../workload/adversarial-benchmark/shuffled_training.json')

        # 1. Load rows
        init_rows = []
        used_agg = os.path.exists(agg_path)
        if used_agg:
            with open(agg_path, 'r') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        init_rows.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        else:
            with open(shuffled_path, 'r') as f:
                data = json.load(f)
            for entry in data:
                init_rows.append({
                    'query': entry['encoded_query'],
                    'generated_plan': entry['encoded_plan'],
                    'default_time_ms': None,
                    'generated_time_ms': None,
                    'absolute_advantage_ms': None,
                    'relative_advantage': None,
                    'source': 'shuffled_fallback',
                    'timeout_ms': 30000,
                })

        if len(init_rows) > self.num_initialization_points:
            init_rows = init_rows[:self.num_initialization_points]

        # 2. Partition into precomputed vs missing
        x_list = []
        existing_scores = []
        existing_censoring = []
        rows_missing = []
        idx_missing = []
        for idx, row in enumerate(init_rows):
            plan = row.get('generated_plan')
            if plan is None:
                continue
            plan_str = ','.join(map(str, plan))
            combined = f"{row['query']}[SEP]{plan_str}"
            x_list.append(combined)
            dt = row.get('default_time_ms')
            gt = row.get('generated_time_ms')
            if dt is not None and gt is not None:
                if self.task_id == 'adversarial_query_rel':
                    score = (dt / gt) if gt > 0 else 0.0
                elif self.task_id == 'adversarial_query_abs':
                    score = (dt - gt) / 1000.0
                else:
                    score = -gt / 1000.0
                existing_scores.append(score)
                existing_censoring.append(0)
            else:
                rows_missing.append(combined)
                idx_missing.append(idx)

        logger.info(f"Loaded {len(init_rows)} rows (used aggregated: {used_agg}), {len(rows_missing)} need evaluation")

        # Helper: log precomputed rows
        def log_precomputed(rows, rel_task: bool):
            script_dir = os.path.dirname(__file__)
            log_dir = os.path.join(script_dir, 'oracle_logs_rel' if rel_task else 'oracle_logs_abs')
            os.makedirs(log_dir, exist_ok=True)
            ts = datetime.now().isoformat()
            if rel_task:
                path = os.path.join(log_dir, f"{ts}_adversarial_query_precomputed_init.csv")
                header = ['timestamp','query','default_plan','default_plan_time_ms','generated_plan','generated_plan_time_ms','generated_plan_advantage_ms','speedup_ratio','default_status','generated_status']
            else:
                path = os.path.join(log_dir, f"{ts}_absolute_time_precomputed_init.csv")
                header = ['timestamp','query','default_plan','default_plan_time_seconds','generated_plan','generated_plan_time_seconds','absolute_improvement_seconds','default_status','generated_status']
            with open(path, 'w', newline='') as f:
                w = csv.writer(f)
                w.writerow(header)
                for r in rows:
                    dt = r.get('default_time_ms')
                    gt = r.get('generated_time_ms')
                    if dt is None or gt is None:
                        continue
                    plan = r.get('generated_plan')
                    adv_ms = None
                    speed = None
                    if gt > 0:
                        adv_ms = dt - gt
                        speed = dt / gt
                    if rel_task:
                        w.writerow([datetime.now().isoformat(), r.get('query'), 'default', dt, json.dumps(plan), gt, adv_ms, speed, 'precomputed','precomputed'])
                    else:
                        dt_s = dt/1000.0
                        gt_s = gt/1000.0
                        abs_imp = dt_s - gt_s
                        w.writerow([datetime.now().isoformat(), r.get('query'), 'default', dt_s, json.dumps(plan), gt_s, abs_imp, 'precomputed','precomputed'])
            logger.info(f"Precomputed log written: {path}")
            return path

        rel_task = (self.task_id == 'adversarial_query_rel')
        try:
            log_precomputed(init_rows, rel_task)
        except Exception as e:
            logger.warning(f"Failed to write precomputed log: {e}")

        # 3. Evaluate missing rows
        if rows_missing:
            from optimization.objectives.your_objective_functions import OBJECTIVE_FUNCTIONS_DICT
            oracle_obj = OBJECTIVE_FUNCTIONS_DICT[self.task_id](*self.task_specific_args)
            batch_size = 10
            new_scores = []
            new_censor = []
            for i in range(0, len(rows_missing), batch_size):
                batch = rows_missing[i:i+batch_size]
                logger.info(f"Oracle batch {i//batch_size + 1}/{(len(rows_missing)-1)//batch_size + 1}")
                bs, bc = oracle_obj.query_black_box(batch)
                new_scores.extend(bs)
                new_censor.extend(bc)
            details = getattr(oracle_obj, 'last_call_details', [])
            if details and len(details) == len(rows_missing):
                for local_i, global_idx in enumerate(idx_missing):
                    d = details[local_i]
                    init_rows[global_idx].update({
                        'default_time_ms': d.get('default_time_ms'),
                        'generated_time_ms': d.get('generated_time_ms'),
                        'absolute_advantage_ms': d.get('absolute_advantage_ms'),
                        'relative_advantage': d.get('relative_advantage'),
                        'filled_timestamp': datetime.now().isoformat(),
                        'source_filled': d.get('source','oracle_fill'),
                    })
            existing_scores.extend(new_scores)
            existing_censoring.extend(new_censor)

            # 4. Write filled file
            filled_dir = os.path.join(script_dir, '../workload/adversarial-benchmark/filled_initializations')
            os.makedirs(filled_dir, exist_ok=True)
            filled_path = os.path.join(filled_dir, f"aggregated_init_30s_timeout_filled_{datetime.now().strftime('%Y%m%dT%H%M%S')}.jsonl")
            with open(filled_path,'w') as f_out:
                for r in init_rows:
                    f_out.write(json.dumps(r)+'\n')
            logger.info(f"Filled init file written: {filled_path}")

        # 5. Always write merged snapshot
        def completeness(row):
            return sum(1 for k in ('default_time_ms','generated_time_ms','absolute_advantage_ms','relative_advantage') if row.get(k) is not None)
        merged_map = {}
        original_rows = []
        if os.path.exists(agg_path):
            with open(agg_path,'r') as f_in:
                for line in f_in:
                    line=line.strip()
                    if not line:
                        continue
                    try:
                        original_rows.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        for src_list in (original_rows, init_rows):
            for rr in src_list:
                key = (rr.get('query'), tuple(rr.get('generated_plan')) if rr.get('generated_plan') is not None else None)
                existing = merged_map.get(key)
                if (existing is None) or (completeness(rr) > completeness(existing)):
                    merged_map[key] = rr
        merged_rows = list(merged_map.values())
        merged_path = os.path.join(os.path.dirname(agg_path), f"aggregated_init_30s_timeout_merged_{datetime.now().strftime('%Y%m%dT%H%M%S')}.jsonl")
        with open(merged_path,'w') as f_out:
            for rr in merged_rows:
                f_out.write(json.dumps(rr)+'\n')
        logger.info(f"Merged aggregated file written: {merged_path} (rows={len(merged_rows)})")

        if not existing_scores:
            raise ValueError("No valid initialization points (plans) found.")

        self.init_train_x = x_list
        self.num_initialization_points = len(x_list)
        self.init_train_y = torch.tensor(existing_scores).float().unsqueeze(-1)
        self.init_censoring = torch.tensor(existing_censoring).float().unsqueeze(-1)
        logger.info(f"Prepared {self.init_train_y.shape[0]} init points, score range=({self.init_train_y.min().item():.4f}, {self.init_train_y.max().item():.4f})")

        return self


if __name__ == "__main__":
    fire.Fire(AdversarialQueryOptimization)
