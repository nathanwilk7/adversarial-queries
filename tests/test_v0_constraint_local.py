"""Real CPU token-mask regression checks; no model weights or GPU required.

ADVQ_TOKENIZER_PATH=/tmp/advq-qwen-tokenizer VLLM_SOURCE=/tmp/advq-vllm-0.10.1 \
  /tmp/advq-decoder-test-env/bin/python tests/test_v0_constraint_local.py
"""
import ast
import copy
import importlib.util
import inspect
import pickle
import os
from pathlib import Path
import sys
import unittest
from concurrent.futures import ThreadPoolExecutor

import torch
from transformers import AutoTokenizer, AutoConfig
from lark import Lark

ROOT = Path(__file__).resolve().parents[1]


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


processor = load('advq_test_processor', 'optimization/query_inference/v0_constraint.py')
compat = load('advq_test_compat', 'optimization/query_inference/vllm_compat.py')


class DecoderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = os.environ['ADVQ_TOKENIZER_PATH']
        cls.tokenizer = AutoTokenizer.from_pretrained(path, local_files_only=True)
        cls.vocab_size = AutoConfig.from_pretrained(path, local_files_only=True).vocab_size
        source = ROOT.joinpath('grammars/stack.lark').read_text()
        cls.parser = Lark(source, parser='lalr')
        cls.grammar = '\n'.join(('root' if name.strip() == 'start' else name.strip()) + ' ::= ' + expr.strip()
                                for line in source.splitlines() if line.strip()
                                for name, expr in [line.split(':', 1)])
        # Execute the pinned V0's real dispatch function with real tensors.
        upstream = Path(os.environ['VLLM_SOURCE'])
        tree = ast.parse((upstream / 'vllm/model_executor/layers/logits_processor.py').read_text())
        fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_apply_logits_processors_single_seq')
        ns = {'torch': torch, 'inspect': inspect}
        exec(compile(ast.Module(body=[fn], type_ignores=[]), 'upstream_dispatch', 'exec'), ns)
        cls.dispatch = staticmethod(ns[fn.name])

    def step(self, p, history, preferred=None):
        logits = torch.zeros(self.vocab_size)
        if preferred is not None:
            logits[preferred] = 100
        return self.dispatch(logits, [p], history, [1, 2, 3])

    def test_exact_output_canary(self):
        p = processor.StackGrammarProcessor('root ::= "(answer )(question )"')
        history = []
        for _ in range(64):
            masked = self.step(p, history)
            token = int(masked.argmax())
            if token == self.tokenizer.eos_token_id:
                break
            history.append(token)
        self.assertEqual(self.tokenizer.decode(history), '(answer )(question )')

    def test_valid_queries_and_eos(self):
        for query in ['(answer )(question )', '(answer (score != 0938))(question )(tag_question )', '(site (site_name "robotics"))']:
            p = processor.StackGrammarProcessor(self.grammar)
            history = []
            for token in self.tokenizer.encode(query, add_special_tokens=False):
                logits = self.step(p, history, token)
                self.assertTrue(torch.isfinite(logits[token]), (query, history, token))
                history.append(token)
            self.assertTrue(torch.isfinite(self.step(p, history)[self.tokenizer.eos_token_id]))
            self.parser.parse(self.tokenizer.decode(history))

    def test_async_calls_after_eos(self):
        # V0's asynchronous output processing can sample again before the
        # completed sequence is removed. Include EOS in the next input history.
        p = processor.StackGrammarProcessor('root ::= "(answer )(question )"')
        history = self.tokenizer.encode('(answer )(question )', add_special_tokens=False)
        self.step(p, history)
        history.append(self.tokenizer.eos_token_id)
        for _ in range(3):
            logits = self.step(p, history)
            allowed = torch.isfinite(logits).nonzero().flatten().tolist()
            self.assertEqual(allowed, [self.tokenizer.eos_token_id])
            # Duplicate scheduler callbacks must be idempotent too.
            self.assertTrue(torch.equal(logits, self.step(p, history)))
            history.append(self.tokenizer.eos_token_id)

    def test_concurrent_sequences_through_termination(self):
        grammar = 'root ::= "(answer )(question )"'
        processor._compiled(grammar, self.vocab_size)
        tokens = self.tokenizer.encode('(answer )(question )', add_special_tokens=False)

        def decode(_):
            p = processor.StackGrammarProcessor(grammar)
            history = []
            for token in tokens + [self.tokenizer.eos_token_id] * 3:
                logits = self.step(p, history, token)
                self.assertTrue(torch.isfinite(logits[token]))
                history.append(token)
            logits = self.step(p, history)
            self.assertEqual(torch.isfinite(logits).nonzero().flatten().tolist(), [self.tokenizer.eos_token_id])

        with ThreadPoolExecutor(max_workers=8) as executor:
            list(executor.map(decode, range(40)))

    def test_invalid_outputs_are_blocked(self):
        for query in ['(_answer )(badge )', '(answer (score != median)(deletion_date t< last))', '(question (view_count = median)(creation_date t> first))']:
            p = processor.StackGrammarProcessor(self.grammar)
            history = []
            blocked = False
            for token in self.tokenizer.encode(query, add_special_tokens=False):
                if not torch.isfinite(self.step(p, history, token)[token]):
                    blocked = True
                    break
                history.append(token)
            self.assertTrue(blocked, query)

    def test_request_state_isolation(self):
        p = processor.StackGrammarProcessor(self.grammar)
        self.step(p, [])
        q = copy.deepcopy(p)
        self.assertIsNone(q.matcher)
        self.assertEqual(q.processed, [])
        q = p.clone()
        self.assertIsNone(q.matcher)
        self.assertEqual(q.processed, [])
        # API server serializes the processor before the engine initializes it.
        q = pickle.loads(pickle.dumps(q))
        self.assertTrue(torch.isfinite(self.step(q, [])).any())

    def test_random_logits_remain_grammatical(self):
        generator = torch.Generator().manual_seed(44)
        for _ in range(20):
            p = processor.StackGrammarProcessor(self.grammar)
            history = []
            for step in range(256):
                logits = torch.randn(self.vocab_size, generator=generator)
                # Encourage termination after exploring several random tokens.
                if step > 12:
                    logits[self.tokenizer.eos_token_id] = 100
                logits = self.dispatch(logits, [p], history, [])
                token = int(logits.argmax())
                if token == self.tokenizer.eos_token_id:
                    break
                history.append(token)
            else:
                self.fail('Random grammar walk failed to terminate')
            self.parser.parse(self.tokenizer.decode(history))

    def test_upstream_repair_and_cli(self):
        upstream = Path(os.environ['VLLM_SOURCE'])
        source = (upstream / 'vllm/engine/llm_engine.py').read_text()
        fixed = compat.repair_v0_source(source)
        self.assertEqual(compat.repair_v0_source(fixed), fixed)
        self.assertNotIn('num_scheduler_steps', fixed)
        bootstrap = ROOT.joinpath('genadversarialqueriesbo_resume.py').read_text()
        self.assertNotIn('"--num-scheduler-steps"', bootstrap)
        # Previous broken patch must also migrate automatically.
        previous = source.replace('and params.logits_processors:', 'and params.logits_processors \\\n            and self.scheduler_config.num_scheduler_steps > 1:')
        self.assertEqual(compat.repair_v0_source(previous), fixed)


if __name__ == '__main__':
    unittest.main(verbosity=2)
