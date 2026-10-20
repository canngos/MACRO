# Final 400-case readiness review

Status: reviewed and frozen for the controlled factual-base experiment. No final model results were used for development or review. Source review is agent-performed, not an independent human annotation study.

## Development evidence

Latest run: `deepseek-dev-120-20261020-185704`.

| System | Completed / planned | Primary correct / planned | Raw correct / planned |
|---|---:|---:|---:|
| Single judge | 239/240 | 237/240 | 235/240 |
| Specialists | 240/240 | 240/240 | 240/240 |

One single-judge assessment exhausted malformed-JSON repairs. Keep it in planned denominators and retain the tested retry policy. Two single-judge hard-constraint decisions were corrected by the shared guardrail.

## Completed review

- [Source review](SOURCE_REVIEW.md): all 1,040 selected recipes match original local CSV evidence; inspected 399 mapped raw forms plus three explicit non-matches, and manually recomputed 18 stratified case verdicts. No mismatches found. The parent subset is not claimed to have full human review.
- [Leakage and scope review](LEAKAGE_AND_SCOPE_REVIEW.md): disjoint recipes/profiles/cases; factual templates; one identical fact-masked style across both splits. Length-only signal remains and is disclosed: 32.25% verdict prediction versus 25% majority baseline. No explanation variants are included.
- [Development acceptance](DEVELOPMENT_REVIEW.md): tested configuration and failure handling retained without additional judge tuning.
- [Automated checks](checks.json), [ingredient inventory](ingredient-review-inventory.json), and [sampled manual verdicts](manual-case-review.json) preserve supporting evidence.
- [Offline verification](offline-tests.log): 107 tests passed. Compilation, dependency consistency, and whitespace checks passed. The launcher was also checked to prevent worker creation when review or connectivity fails.

## Frozen experiment

The [readiness record](final-readiness.json) binds the exact dataset bytes, tested DeepSeek configuration, current package code, reviews and development evidence. Operational changes add final gating and reporting only; the tested prompts, schemas, model settings, coordinator and policy are unchanged.

The original dataset generation manifests retain their historical draft/pending fields. Later reviews are kept here and bound by hashes instead of rewriting the dataset or falsely marking a human annotation study complete.

[Final configuration](../../configs/deepseek-final-400.json): DeepSeek Flash, thinking disabled, 3,500-token response cap, two attempts, two calculator rounds. [Plan](final-plan.json): 400 cases in both orders, 800 planned evaluations per system, 3,200 initial requests and a 19,200-request maximum. This is a request cap, not a monetary limit.

Final inference is allowed only with this approved record. Any frozen artifact change requires review and a new freeze; a changed judge/policy configuration requires development validation. Final results must not be used to tune the same frozen benchmark without disclosing test reuse.
