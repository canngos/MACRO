# Benchmark results

Three recorded experiments evaluated the same 400 cases in both candidate orders:
**800 pair judgments per system and model**, representing 400 base cases.

| Model | Single correct / 800 | Panel correct / 800 | Stable cases single / panel | Failed evaluations single / panel |
|---|---:|---:|---:|---:|
| GPT-5-nano | 732 (91.50%) | 788 (98.50%) | 346 / 389 | 0 / 0 |
| Qwen3.5:9b, local Ollama | 697 (87.125%) | 772 (96.50%) | 333 / 372 | 10 / 27 |
| DeepSeek-flash | 773 (96.625%) | 800 (100%) | 389 / 400 | 0 / 0 |

Accuracy includes the shared hard-constraint guardrail and counts technical failures
as unsuccessful outcomes. Stability requires matching canonical decisions in both
orders; stable decisions can still be wrong.

## Required evaluation measures

| Model / system | Dominance correct / 160 | Priority alignment / 80 | Correct unresolved trade-offs / 80 | Constraint precision / recall | Candidate flags observed / 1,600 |
|---|---:|---:|---:|---:|---:|
| GPT single | 149 | 75 | 70 | 97.73% / 98.54% | 1,600 |
| GPT panel | 156 | 78 | 76 | 97.93% / 98.54% | 1,600 |
| Qwen single | 155 | 77 | 20 | 100% / 100% | 1,580 |
| Qwen panel | 158 | 79 | 75 | 100% / 100% | 1,546 |
| DeepSeek single | 138 | 80 | 79 | 99.79% / 99.58% | 1,600 |
| DeepSeek panel | 160 | 80 | 80 | 99.79% / 99.79% | 1,600 |

Constraint precision/recall uses raw feasibility findings from completed evaluations,
before the guardrail. Qwen's 100% applies only to available flags, not every planned
assessment. Exact violation reasons can still be wrong. The 1,600 observations are
400 cases times two candidates times two orders, not 1,600 independent recipes.

| Entire run | Model requests | Reported tokens | Elapsed span, first to last request |
|---|---:|---:|---:|
| GPT-5-nano | 3,201 | 10,118,769 | About 7 h 8 min |
| Local Qwen | 3,298 | 9,547,430 | About 18 h 48 min |
| DeepSeek-flash | 3,390 | 11,099,461 | About 2 h 51 min |

Tokens, latency and money are different measures. Deployments, reasoning settings
and tokenizers differ; these numbers do not establish intrinsic model speed. Usage
includes retries and tool follow-ups.

## Interpretation

The complete panel system improved accuracy and stability in all three experiments.
This comparison changes both inference budget and decision procedure, so it does not
isolate specialization. The shared hard-constraint guardrail also contributes to
system accuracy; DeepSeek's panel was 798/800 correct before it and 800/800 afterward.

OpenAI and Qwen used prompt/schema v1; DeepSeek used v2, including clearer policy
instructions and different structured-output handling. Compare these as recorded
configurations, not a controlled model-only ranking. Current code implements the
newer contract. The benchmark is deliberately constructed from synthetic profiles,
bounded ingredient groups and factual explanation templates; it does not establish
performance on arbitrary user requests or manipulated explanations.

## Evidence included with the code

[benchmark-results.json](documentation/benchmark-results.json) preserves selected
metrics, per-system usage, run names, prompt/schema versions and hashes of the source
summary/manifest files. It was extracted from `openai-benchmark-400-01`,
`ollama-benchmark-400-01` and `deepseek-final-400`; no models were rerun.

This compact summary is included in Git. Raw response logs, run snapshots and completed
human annotations are separate submission artifacts, not part of the default clone.
The historical DeepSeek source/development review in `readiness/` was performed by
an agent and must not be presented as the two-reviewer human study.
