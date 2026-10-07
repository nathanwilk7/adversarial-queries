"""Decode scalar predicate lookups without interactive debugger side effects."""
import json


def scalar_predicate_result(payload, key):
    try:
        rows = json.loads(payload)
    except (TypeError, json.JSONDecodeError) as error:
        raise RuntimeError(f'Invalid predicate lookup JSON for {key}: {payload!r}') from error
    if not isinstance(rows, list):
        raise RuntimeError(f'Expected predicate lookup rows for {key}, got {rows!r}')
    # MIN/MAX/mode with WHERE field IS NOT NULL returns zero rows for an
    # all-NULL column (or empty table). Treat it like an aggregate NULL result.
    if not rows:
        return None
    if len(rows) != 1 or not isinstance(rows[0], dict) or 'val' not in rows[0]:
        raise RuntimeError(f'Expected one val row for {key}, got {rows!r}')
    return rows[0]['val']
