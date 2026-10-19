# MACRO team code guide

`python -m macro` and `macro` both enter `src/macro/cli.py`. Planning and evaluation default to `data/benchmark-v2/test` and `configs/benchmark-judges.json`. There is one active benchmark policy and no pilot runtime dispatcher.

## Where to work

| Responsibility | File under `src/macro/` |
|---|---|
| Parse, normalize and sample HUMMUS | `evaluate_case_generation/dataset.py` |
| Construct cases, split data and validate saved references | `evaluate_case_generation/benchmark.py` |
| Shared rubric and role prompts | `ai_agents/prompts.py` |
| Structured response format and evidence validation | `ai_agents/schemas.py` |
| Fresh AG2 agents, bounded tool rounds and requests | `ai_agents/agents.py` |
| Shared arithmetic tool | `ai_agents/tools.py` |
| Fixed aggregation and common constraint verification | `coordinator/aggregation.py` |
| Dataset/configuration preflight | `evaluation/inputs.py` |
| Original/reversed runs, budgets, request ledger and resume | `evaluation/runner.py` |
| Accuracy, constraint detection and order stability | `evaluation/metrics.py` |
| JSON, Markdown and HTML reports | `reporting/` |
| Deterministic reference policy and public-data validation | `shared/benchmark_policy.py` |
| Numeric tolerance, comparisons and candidate swapping | `shared/comparison.py` |
| File persistence and hashes | `shared/io.py` |

The same AG2 factory configures all four roles. Each receives the same public evidence, shared rubric and calculator access. Role instructions and schemas define their responsibilities. `BENCHMARK_PROMPT_VERSION`, `SCHEMA_VERSION`, `POLICY_VERSION` and `AGGREGATION_VERSION` identify different experiment components; they do not select competing policies.

## Execution flow

1. The input preflight verifies package hashes, references, policy versions and split separation.
2. The runner snapshots the experiment inputs and fingerprints all package modules.
3. For each case and candidate order, one single judge and three independent specialists return structured assessments.
4. The coordinator verifies hard constraints from public facts, then compares the specialists' reported scores on active objectives. Dominance precedes declared priorities; insufficient priorities can leave a trade-off unresolved. Explanation findings remain diagnostics. Missing or invalid specialists produce technical failure.
5. The single judge receives the same hard-constraint guardrail. Raw findings and raw decisions remain available for scoring.
6. Metrics compare saved judgments with private references; reports expose the evidence and responses for inspection.

The runner loads private references for experiment identity and scoring, but they never enter agent prompts or coordinator inputs. `shared/benchmark_policy.py` computes those references outside the judge path. The coordinator does not replace reported soft scores with reference answers.

## Boundaries to preserve

- Keep RQ1/RQ2 scope: fixed aggregation without discussion rounds or explanation manipulation.
- Paid requests belong in `ai_agents/agents.py`. Planning, data preparation, aggregation and saved-result reporting make no API calls.
- New runs require explicit paid acknowledgement and a request cap. Resume rejects changed code, settings or inputs; use a new run ID after a refactor.
- Internal fixtures stay in `tests/`. The user-facing run command always uses real judges.
- Historical datasets and experiment outputs are preserved. Reports retain read-only support for historical snapshots; old pilot prompts, schemas and aggregation are no longer executable.

`data/benchmark-v2/` is the active 400-test/120-development package. Historical pilot files also supply recipe IDs to exclude during generation. A new human-review sample must come from benchmark-v2; review is scheduled after inference, blind to model judgments.
