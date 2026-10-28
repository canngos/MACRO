# Current evaluation benchmark

120 development cases and 400 final test cases. See the [data guide](../../DATA_PREPARATION.md) for construction and the [evaluation policy](../../EVALUATION_POLICY.md) for reference labels.

| Stratum | Development | Final test |
|---|---:|---:|
| control_tie | 24 | 80 |
| both_violate | 24 | 80 |
| constraint_ingredient | 12 | 40 |
| constraint_duration_near | 6 | 20 |
| constraint_duration_clear | 6 | 20 |
| dominance_near | 12 | 40 |
| dominance_clear | 12 | 40 |
| tradeoff_resolved | 12 | 40 |
| tradeoff_unresolved | 12 | 40 |

## Files and boundaries

- dev/cases.jsonl and test/cases.jsonl are public judge inputs. Do not send the private directory or manifest to judges.
- private/*.references.jsonl are deterministic gold labels; private/source_map.json maps neutral recipe IDs to source evidence.
- No recipe is reused across any base cases. Exact semantic profiles and recipes are disjoint between development and test.
- Previously inspected pilot recipe IDs are excluded when configured. Review of source data is separate from inspecting test judge results.
- Every case has a factual explanation template. Both candidate orders belong to the same base case; they are not independent cases. Explanation manipulation is outside the course scope.
- Profile and recipe fields contain all evidence required by benchmark-policy-v1. Unknown dietary/hidden composition requirements are excluded.
- This is a deliberately stratified diagnostic benchmark, not a representative sample of natural user traffic.
- Generation made no model calls. References were checked against the deterministic policy in both orders. Completed model evaluations are described in [Results](../../RESULTS.md).
- Generation manifests retain their original draft/pending status. Later agent-performed source, leakage and development checks are preserved in the [DeepSeek readiness review](../../readiness/deepseek-final-400/REVIEW.md); independent human annotation is a separate activity.
- Hashes establish artifact identity, not factual correctness. Final inference requires a matching readiness record and its supporting files; see the [run guide](../../documentation/RUNNING.md#final-400-case-evaluation).
