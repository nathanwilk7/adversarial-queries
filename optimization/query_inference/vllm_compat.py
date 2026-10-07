"""Version-specific V0 repair, independently testable without importing vLLM."""


def repair_v0_source(source):
    marker = '# ADVQ: V0 custom processors execute in _apply_logits_processors_single_seq.'
    if marker in source:
        return source
    original = '''        if isinstance(params, SamplingParams) \\
            and params.logits_processors:
            raise ValueError(
                "Logits processors are not supported in multi-step decoding")'''
    previous = original.replace(
        'and params.logits_processors:',
        'and params.logits_processors \\\n            and self.scheduler_config.num_scheduler_steps > 1:')
    matches = [block for block in (original, previous) if source.count(block) == 1]
    if len(matches) != 1:
        raise RuntimeError('Unexpected vLLM 0.10.1 V0 source; refusing compatibility repair')
    repaired = source.replace(matches[0], '        ' + marker, 1)
    compile(repaired, 'llm_engine.py', 'exec')
    return repaired
