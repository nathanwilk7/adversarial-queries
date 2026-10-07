"""Explicit grammar masking for vLLM 0.10.1's prompt-embedding V0 engine.

V0 accepts guided_decoding in SamplingParams but never consumes it. Its custom
logits processor API is still supported. Initialize native objects lazily in
the engine process so API-server serialization does not pickle XGrammar state.
"""
from functools import lru_cache
import os


@lru_cache(maxsize=4)
def _compiled(grammar, vocab_size):
    import xgrammar as xgr
    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(
        os.environ.get('ADVQ_TOKENIZER_PATH', '/content/advq-artifacts/stack-query-decoder'),
        local_files_only=True)
    info = xgr.TokenizerInfo.from_huggingface(tokenizer, vocab_size=vocab_size)
    return xgr.GrammarCompiler(info).compile_grammar(grammar)


class StackGrammarProcessor:
    def __init__(self, grammar):
        self.grammar = grammar
        self.matcher = None
        self.processed = []
        self.mask = None

    def __deepcopy__(self, memo):
        return type(self)(self.grammar)

    def clone(self):
        # SamplingParams.clone bypasses deepcopy for custom processors unless
        # they implement this hook. Never share a native matcher across requests.
        return type(self)(self.grammar)

    def __call__(self, token_ids, logits):
        import xgrammar as xgr
        if self.matcher is None:
            self.matcher = xgr.GrammarMatcher(_compiled(self.grammar, logits.shape[-1]))
            self.mask = xgr.allocate_token_bitmask(1, logits.shape[-1])
        # V0 passes generated tokens only. Each request owns its matcher.
        if list(token_ids[:len(self.processed)]) != self.processed:
            raise RuntimeError('Grammar processor received non-monotonic token history')
        for token in token_ids[len(self.processed):]:
            if not self.matcher.accept_token(token):
                raise RuntimeError(f'Grammar rejected generated token {token}')
            self.processed.append(token)
        self.matcher.fill_next_token_bitmask(self.mask)
        xgr.apply_token_bitmask_inplace(logits.unsqueeze(0), self.mask.to(logits.device))
        return logits
