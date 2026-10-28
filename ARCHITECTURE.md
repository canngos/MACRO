# Architecture

`python -m macro` enters [src/macro/cli.py](src/macro/cli.py). The default split is `data/benchmark-v2/dev`; the default configuration is `configs/benchmark-judges.json`.

## Evaluation flow

1. Validate the dataset, configuration and reference-label identities.
2. Save snapshots and record the code, prompt, schema and model settings.
3. Evaluate each case in original and reversed recommendation order. A fresh AG2 agent is created for each role and attempt. Specialists see no other judge's answer.
4. Validate structured responses and evidence pointers, allowing bounded retries and calculator calls.
5. Apply the fixed coordinator to the three specialist assessments. Apply the same public-fact hard-constraint guardrail to the single judge's decision.
6. Compare decisions with private references and generate HTML, Markdown and JSON reports.

Both systems receive the same public evidence, rubric and calculator access. Private reference labels are used for scoring, never included in prompts or coordinator inputs. The coordinator uses model-reported soft scores; it does not substitute reference scores.

## Code map

| Module under `src/macro/` | Responsibility |
|---|---|
| `evaluate_case_generation/dataset.py` | Filter HUMMUS and normalize documented ingredient groups |
| `evaluate_case_generation/benchmark.py` | Construct pairs, profiles and development/test splits |
| `ai_agents/prompts.py` | Shared policy, role prompts and public-input whitelist |
| `ai_agents/schemas.py` | Structured findings and evidence-pointer validation |
| `ai_agents/agents.py` | AG2 agents, provider calls, response handling and tool rounds |
| `ai_agents/tools.py` | Shared arithmetic calculator |
| `coordinator/aggregation.py` | Fixed aggregation and shared hard-constraint checks |
| `evaluation/inputs.py` | Dataset and configuration checks |
| `evaluation/runner.py` | Both orders, call budgets, snapshots and resume |
| `evaluation/readiness.py` | Check the frozen record before final-test inference |
| `evaluation/metrics.py` | Accuracy, constraint detection, coverage and stability |
| `reporting/` | Saved-result summaries, cost estimates and HTML reports |
| `shared/benchmark_policy.py` | Deterministic reference labels |
| `shared/config.py` | Provider and credential selection |
| `shared/comparison.py`, `shared/io.py` | Comparisons, order swaps, persistence and hashes |

## Failure handling and reproducibility

An invalid or missing specialist output makes the panel evaluation a `technical_failure`. This differs from a valid `insufficient_information` judgment. Failures remain in overall accuracy and coverage denominators.

The runner saves each request and assessment. Repeating a run ID resumes only when code, configuration and inputs match; changed experiments require a new ID. Interrupted requests with uncertain completion require explicit retry acknowledgement because they may already have been billed.

Dataset and experiment hashes establish identity, not factual correctness. The [evaluation policy](EVALUATION_POLICY.md) explains how reference labels are calculated.
