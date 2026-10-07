# Stack diagnostic timeout policy

For the absolute objective `default_seconds - generated_seconds`:

| Default | Generated | Observation |
| --- | --- | --- |
| complete | complete | Exact difference |
| timeout | complete | Lower bound |
| complete | timeout | Upper bound |
| timeout | timeout | Unknown difference; zero is not a bound |
| error | any | No runtime observation |
| any | error | No runtime observation |

The existing GP likelihood has one global censoring direction. It cannot
represent this mixture correctly. The Stack diagnostic run therefore uses
only completed pairs for training (`ADVQ_COMPLETE_PAIRS_ONLY=1`, the default
for Stack's absolute objective). This discards useful one-sided observations;
it is not an implementation of a mixed/interval-censored likelihood and is
not claimed to reproduce the paper's method exactly.

Every attempted pair remains in the oracle CSV and counts toward the BO
evaluation budget, even when its score is NaN and excluded from the surrogate.
Cached results do not spend the budget again. Initialization still attempts
only the requested number of pairs, retains completed pairs, and stops with
an explicit error if fewer than two complete. Restored oracle logs use the
same filtering rule. Other objectives retain their previous behavior.

The CSV's historical `absolute_improvement_seconds` field still contains the
difference of recorded/capped times. It is an exact score only when both
statuses are `complete`; phase diagnostics expose the status pairs.

Run the local policy, real objective bookkeeping, cache/budget and initialization
regressions with:

```bash
/tmp/advq-decoder-test-env/bin/python tests/test_pair_observation.py
```
