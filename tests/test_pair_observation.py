"""CPU regression tests for Stack timeout filtering and budget accounting."""
import ast
import math
from pathlib import Path
import sys
import time
import csv
import logging
import os
from types import SimpleNamespace
import unittest
from unittest.mock import mock_open, patch

import numpy as np
import torch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from optimization.objectives.pair_observation import observation_kind, complete_pair_score


class PairObservationTests(unittest.TestCase):
    def test_restored_initialization_excludes_timeouts(self):
        tree = ast.parse((ROOT / 'optimization/scripts/adversarial_query_optimization.py').read_text())
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef))
        fn = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == '_load_from_oracle_log')
        ns = {'csv': csv, 'os': os, 'torch': torch, 'logger': logging.getLogger('test')}
        exec(compile(ast.Module(body=[fn], type_ignores=[]), 'initialization', 'exec'), ns)
        payload = ('query,generated_plan,default_plan_time_seconds,generated_plan_time_seconds,default_status,generated_status\n'
                   'q1,"[0,1]",30,30,timeout,timeout\n'
                   'q2,"[0,1]",3,2,complete,complete\n'
                   'q3,"[0,1]",2,3,complete,complete\n')
        obj = SimpleNamespace(schema='Stack', task_id='adversarial_query_abs', num_initialization_points=3)
        with patch.dict(os.environ, {'ADVQ_COMPLETE_PAIRS_ONLY': '1'}), patch('builtins.open', mock_open(read_data=payload)):
            ns[fn.name](obj, 'test.csv')
        self.assertEqual(obj.init_train_x, ['q2[SEP]0,1', 'q3[SEP]0,1'])
        self.assertEqual(obj.init_train_y.flatten().tolist(), [1, -1])
        self.assertEqual(obj.init_censoring.flatten().tolist(), [0, 0])

    def test_actual_objective_preserves_logs_but_filters_training(self):
        tree = ast.parse((ROOT / 'optimization/objectives/your_objective_functions.py').read_text())
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == '_BaseAdversarialQueryObjective')
        ns = {'ObjectiveFunction': object, 'TIMEOUT': 30000,
              'observation_kind': observation_kind, 'complete_pair_score': complete_pair_score,
              'AdversarialQueryInput': lambda **kw: SimpleNamespace(**kw),
              '_ParsedInput': lambda i, q, p, t: SimpleNamespace(index=i, query_string=q, plan=p, original_timeout_ms=t)}
        future = ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0)
        exec(compile(ast.fix_missing_locations(ast.Module(body=[future, cls], type_ignores=[])), 'objective', 'exec'), ns)
        obj = ns[cls.name].__new__(ns[cls.name])
        obj.schema = 'Stack'; obj.timeout_ms = 30000; obj.complete_pairs_only = True
        obj._normalize_timeouts = lambda n, _: [30] * n
        obj._default_fallback_seconds = lambda p: 30
        obj._generated_fallback_seconds = lambda d: 30
        obj._score = lambda d, g: d - g
        obj._source_tag = lambda: 'test'
        logged = []
        obj._log_to_csv = lambda **kw: logged.append(kw)
        for d in ['complete', 'timeout', 'error']:
            for g in ['complete', 'timeout', 'error']:
                def query(inputs, query_type):
                    status = d if query_type == 'default' else g
                    return [SimpleNamespace(type='time_query', result=SimpleNamespace(result=status, elapsed_secs=3 if query_type == 'default' else 2, error='test error'))]
                obj._query_oracle_with_retry = query
                scores, censored = obj.query_black_box(['(answer )(question )[SEP]0,1'])
                self.assertEqual(math.isfinite(scores[0]), d == g == 'complete')
                self.assertEqual(obj.last_call_details[0]['observation_kind'], observation_kind(d, g))
                self.assertEqual(obj.last_call_details[0]['used_for_training'], d == g == 'complete')
        self.assertEqual(len(logged), 9)

    def test_status_matrix(self):
        expected = {('complete', 'complete'): 'exact', ('timeout', 'complete'): 'lower_bound',
                    ('complete', 'timeout'): 'upper_bound', ('timeout', 'timeout'): 'unknown_difference'}
        for d in ['complete', 'timeout', 'error']:
            for g in ['complete', 'timeout', 'error']:
                self.assertEqual(observation_kind(d, g), expected.get((d, g), 'error'))
                score = complete_pair_score(30, 10, d, g)
                self.assertEqual(math.isfinite(score), d == g == 'complete')
        self.assertEqual(complete_pair_score(3, 5, 'complete', 'complete'), -2)

    def test_actual_latent_filter_budget_and_cache(self):
        # Run the actual class on CPU, omitting unrelated legacy DB imports.
        tree = ast.parse((ROOT / 'optimization/lolbo/latent_space_objective.py').read_text())
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'LatentSpaceObjective')
        ns = {'torch': torch, 'np': np, 'time': time}
        exec(compile(ast.Module(body=[cls], type_ignores=[]), 'latent', 'exec'), ns)
        obj = ns['LatentSpaceObjective'](init_vae=False, xs_to_scores_dict={}, xs_to_censoring_dict={})
        obj.objective_function = SimpleNamespace(count_all_oracle_attempts=True, total_non_parallel_runtime=0)
        obj.compute_constraints = lambda xs: None
        obj.query_oracle = lambda xs: ([float('nan') if x != 'exact' else 2.0 for x in xs], [0 if x == 'exact' else 1 for x in xs])
        points = torch.zeros(3, 2)
        result = obj(points, decoded_xs=['timeout', 'error', 'exact'])
        self.assertEqual(obj.num_calls, 3)
        self.assertEqual(result['decoded_xs'], ['exact'])
        self.assertEqual(result['scores'].tolist(), [2.0])
        result = obj(points, decoded_xs=['timeout', 'error', 'exact'])
        self.assertEqual(obj.num_calls, 3, 'Cached observations must not spend budget again')
        result = obj(torch.zeros(1, 2), decoded_xs=['another_timeout'])
        self.assertEqual(obj.num_calls, 4)
        self.assertEqual(len(result['scores']), 0)
        self.assertEqual(result['valid_zs'].shape, (0, 2))


if __name__ == '__main__':
    unittest.main(verbosity=2)
