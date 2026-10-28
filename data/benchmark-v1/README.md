# Draft development and final-evaluation benchmark

120 development cases and 600 final test cases are the default configuration. See the manifest for actual counts.

| Stratum | Development | Final test |
|---|---:|---:|
| control_tie | 6 | 30 |
| both_violate | 6 | 30 |
| constraint_ingredient | 18 | 90 |
| constraint_duration_near | 9 | 45 |
| constraint_duration_clear | 9 | 45 |
| dominance_near | 18 | 90 |
| dominance_clear | 18 | 90 |
| tradeoff_resolved | 18 | 90 |
| tradeoff_unresolved | 18 | 90 |

## Files and boundaries

- dev/cases.jsonl and test/cases.jsonl are public judge inputs. Do not send the private directory or manifest to judges.
- private/*.references.jsonl are deterministic gold labels; private/source_map.json maps neutral recipe IDs to source evidence.
- No recipe is reused across any base cases. Exact semantic profiles and recipes are disjoint between development and test.
- Previously inspected pilot recipe IDs are excluded when configured. Review of source data is separate from inspecting test judge results.
- Every case has a factual template only. Future explanation variants and order swaps must inherit its split; they are not additional independent cases.
- Profile and recipe fields contain all evidence required by benchmark-policy-v1. Unknown dietary/hidden composition requirements are excluded.
- This is a deliberately stratified diagnostic benchmark, not a representative sample of natural user traffic.
- No LLM requests or model results were generated. References were checked against the deterministic policy in both orders.
- Pending: source/manual review, explanation variants and reviews, length/surface leakage checks and judge/runner/schema integration.
- Hashes establish artifact identity, not a completed test freeze. Do not claim final evaluation until outstanding checks pass and configuration is frozen.
