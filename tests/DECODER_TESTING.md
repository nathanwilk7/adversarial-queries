# Local decoder regression tests

These tests run on an Apple Silicon CPU. They use real Torch 2.7.1,
Transformers 4.55.0, XGrammar 0.1.21 and the public Qwen tokenizer.
No model weights, OpenAI key or database are needed.

```bash
uv venv --python 3.11 /tmp/advq-decoder-test-env
uv pip install --python /tmp/advq-decoder-test-env/bin/python -r tests/requirements-decoder.txt
git clone --depth 1 --branch v0.10.1 https://github.com/vllm-project/vllm.git /tmp/advq-vllm-0.10.1
/tmp/advq-decoder-test-env/bin/python -c 'from huggingface_hub import snapshot_download; snapshot_download("Qwen/Qwen2.5-0.5B-Instruct", allow_patterns=["tokenizer*", "vocab.json", "merges.txt", "config.json"], local_dir="/tmp/advq-qwen-tokenizer")'
ADVQ_TOKENIZER_PATH=/tmp/advq-qwen-tokenizer VLLM_SOURCE=/tmp/advq-vllm-0.10.1 /tmp/advq-decoder-test-env/bin/python tests/test_v0_constraint_local.py
```

Reuse the environment, tokenizer and clone on later iterations; rerun only
the last command. The tested upstream tag resolves to
`aab549870df50edf0512f0a59b574f692f546465`.

Coverage: real upstream token-processor dispatch, native CPU bitmask application,
exact-output generation, valid queries and EOS, malformed log examples, random
logits, request cloning/serialization, and pristine/previously patched source
migration. The source repair is idempotent and rejects unexpected source.

Post-EOS scheduler callbacks are included: they reproduced the actual native
`GrammarMatcher has terminated ... next token mask` crash before its fix.
Tests also exercise duplicate callbacks and 40 concurrent sequence lifecycles
through EOS using the real matcher and upstream dispatch function.

These tests do not run the vLLM HTTP server, CUDA kernels, trained model or
database. Colab retains the exact-output canary, 40-output grammar preflight,
and strict BO validation to cover that remaining integration boundary.
