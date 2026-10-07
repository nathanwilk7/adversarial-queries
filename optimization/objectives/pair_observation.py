"""Observation semantics for the difference default_time - generated_time."""


def observation_kind(default_status, generated_status):
    pair = default_status, generated_status
    if pair == ('complete', 'complete'):
        return 'exact'
    if pair == ('timeout', 'complete'):
        return 'lower_bound'
    if pair == ('complete', 'timeout'):
        return 'upper_bound'
    if pair == ('timeout', 'timeout'):
        return 'unknown_difference'
    return 'error'


def complete_pair_score(default_seconds, generated_seconds, default_status, generated_status):
    """Conservative diagnostic policy: only exact pairs train the surrogate.

    A single one-sided censoring flag cannot represent both bound directions
    and unbounded differences. Keep all such attempts in logs and the budget,
    but return NaN so the existing latent-objective filter excludes them.
    """
    if observation_kind(default_status, generated_status) == 'exact':
        return default_seconds - generated_seconds
    return float('nan')
