"""Independent, alternating-order verification of completed BO candidates."""
import json
from statistics import median


def verify_candidate(oracle, item, repeats, timeout_ms):
    from oracle.adversarial_queries import AdversarialQueryInput

    plan = item['generated_plan']
    if isinstance(plan, str):
        plan = json.loads(plan)
    runs = []
    for repeat in range(repeats):
        order = ['default', 'generated'] if repeat % 2 == 0 else ['generated', 'default']
        pair = {}
        for name in order:
            request = AdversarialQueryInput(
                llm_output=item['query'], plan=None if name == 'default' else plan,
                timeout_ms=timeout_ms, db_schema='Stack', return_result=True,
            )
            try:
                response = oracle.query([request])[0].result
                pair[name] = {
                    'status': response.result,
                    'seconds': getattr(response, 'elapsed_secs', None),
                    'result': getattr(response, 'query_result', None),
                    'error': getattr(response, 'error', None),
                }
            except Exception as error:
                pair[name] = {'status': 'error', 'seconds': None, 'result': None, 'error': str(error)}
        complete = all(pair[n]['status'] == 'complete' for n in order)
        equivalent = None
        if complete and all(pair[n]['result'] is not None for n in order):
            # These oracle queries return SELECT COUNT(*). Compare the exact
            # scalar value, independently of the SQL expression's column label.
            values = [json.loads(pair[n]['result']) for n in ['default', 'generated']]
            if all(isinstance(v, list) and len(v) == 1 and isinstance(v[0], dict) and len(v[0]) == 1 for v in values):
                equivalent = list(values[0][0].values()) == list(values[1][0].values())
        advantage = pair['default']['seconds'] - pair['generated']['seconds'] if complete else None
        runs.append({'repeat': repeat + 1, 'execution_order': order, 'default_status': pair['default']['status'],
                     'generated_status': pair['generated']['status'], 'result_equivalent': equivalent,
                     'score_seconds': advantage, 'observations': pair})
        print(item['query'], 'repeat', repeat + 1, 'order', order, 'equivalent', equivalent, 'advantage', advantage, flush=True)
    valid = [r for r in runs if r['result_equivalent'] is True]
    advantages = [r['score_seconds'] for r in valid]
    return {**item, 'runs': runs, 'complete_repeats': sum(r['default_status'] == r['generated_status'] == 'complete' for r in runs),
            'equivalent_repeats': len(valid), 'result_mismatches': sum(r['result_equivalent'] is False for r in runs),
            'median_advantage_seconds': median(advantages) if advantages else None,
            'positive_complete_repeats': sum(v > 0 for v in advantages)}
