# Review of the 120-case DeepSeek live development run

Historical development record. Commands and status statements below describe that earlier stage. Use the [current run guide](../RUNNING.md) for execution.

**Review date:** 20 October 2026  
**Run:** `deepseek-benchmark-dev-120-001`  
**Dataset:** `benchmark-v2`, development split  
**Model requested and returned:** `deepseek-flash`  
**Configuration:** thinking disabled; 3,500 output tokens; two attempts per role; up to two calculator rounds

## Assessment

The run demonstrates that the benchmark can execute against the live DeepSeek API and produce largely correct, structured assessments. It also reveals specific problems that should be addressed before the final 400-case evaluation is enabled and the experiment is frozen.

The main weakness is the single judge's treatment of ties. The specialist system performs better on this run, but still produces one incorrect feasibility finding and loses one evaluation to malformed explanation output. Correct final decisions also conceal several errors in the underlying findings.

These are development results. They should guide changes to the prompts, provider handling, and reporting; they are not final estimates of benchmark performance.

## Results at a glance

Each of the 120 base cases was assessed in its original and reversed candidate order, giving 240 planned evaluations per system.

| Measure | Single judge | Specialist system |
|---|---:|---:|
| Completed evaluations | 240/240 | 239/240 |
| Correct decisions | 226/240 | 238/240 |
| Overall accuracy | 94.2% | 99.2% |
| Constraint cases | 48/48 | 47/48 |
| Dominance cases | 48/48 | 48/48 |
| Trade-off cases | 48/48 | 48/48 |
| Tie controls | 34/48 | 48/48 |
| Both candidates violate constraints | 48/48 | 47/48 |
| Stable candidate-order pairs, out of all planned pairs | 116/120 | 118/120 |

Original and reversed assessments are repeated observations of the same base cases, not independent samples. The specialist stability figure includes one incomplete pair: among its 119 complete pairs, 118 agree and one disagrees.

The run recorded 974 model calls: 972 completed calls and two connection errors. Usage reported by the provider totals 2,712,138 input tokens and 345,484 output tokens, or 3,057,622 tokens. Usage is unavailable for the two error calls. Monetary cost is unknown because pricing was not configured.

## Findings and recommended changes

### 1. The single judge confuses a tie with missing information

All 14 incorrect single-judge decisions should have been `tie` but were returned as `insufficient_information`. They affect nine distinct base cases. The judge's structured scores correctly show equality on the active objectives. It nevertheless treats missing priorities, or differences in inactive speed, as a reason to withhold a tie verdict.

Some responses contain a second inconsistency: the rationale explicitly concludes that the decision should be a tie while the JSON decision field remains `insufficient_information`.

For example, in `case-0e85e20cdb6056dc122a`, both candidates are feasible, both preference scores are 1.0, and both nutrition scores are 0.25. Their durations differ, but speed is inactive. The correct outcome is a tie regardless of the null priority ordering. Both candidate orders were labeled incorrectly.

**Recommended change:** strengthen the benchmark prompt with an explicit sequence:

1. Apply hard feasibility constraints.
2. Compare only active objectives.
3. If every active objective is equal, return `tie`, including when priorities are null.
4. If one candidate Pareto-dominates the other, select it.
5. Only a conflict between active objectives requires priorities; if these are absent, return `insufficient_information`.

Add a diagnostic that compares the single judge's decision with the decision implied by its own structured findings. Existing comparison diagnostics check score-versus-comparison agreement; they did not detect these 14 decision errors.

Preserve the original model decision when scoring this study. Replacing it with a calculated verdict would change the single-judge system being evaluated. Any such alternative should be defined and reported as a separate experimental condition.

**Relevant code:** [benchmark prompt](../../src/macro/ai_agents/prompts.py), [benchmark decision rules](../../src/macro/ai_agents/benchmark_schemas.py), and [runner](../../src/macro/evaluation/runner.py).

### 2. Malformed explanation output can exhaust repairs

The specialist evaluation for `case-c60873edd5e239523bbc`, original order, failed because both explanation attempts returned JSON followed by DeepSeek `DSML` closing tags. The provider reported `finish_reason: stop`, and no structured tool call was present in those responses. This was not recorded as output truncation.

There were six failed role attempts due to assessment validation across the run: five invalid-JSON attempts from the explanation role and one single-judge response with an unexpected `decision_note` field. Together with two connection errors, these account for eight failed role attempts; retries recovered all but the final explanation attempt above.

**Recommended change:** test removing the calculator from the explanation specialist, whose assigned assessment requires no arithmetic. Currently every role receives the calculator. Make invalid-JSON repair instructions explicitly request a complete replacement JSON object with no trailing text, tool markup, or additional fields. Keep strict validation and preserve failed responses for inspection.

Disabling the explanation tool is a proposed mitigation, not a proven diagnosis of the DSML output. Verify it on development cases. Increasing the output token limit is not supported by these failures, since they finished with `stop` rather than a length limit.

**Relevant code:** [agent setup and repair handling](../../src/macro/ai_agents/agents.py) and [assessment validation](../../src/macro/ai_agents/schemas.py).

### 3. Correct rationales do not guarantee correct structured fields

The specialist system's one incorrect completed verdict came from `case-6b7dbef84e1eff1d3ec4`, original order. The hard time limit is 27 minutes; candidate A takes 75 minutes and candidate B takes 55 minutes. Both therefore violate the duration constraint.

The attribute specialist marked B as feasible with an empty violation list, causing the coordinator to select B. Its rationale correctly recognized that 55 exceeds 27 and that both candidates violate the constraint, but the structured fields were not corrected.

Two additional mistakes did not change the final verdict:

| Case and order | Finding error | Why decision accuracy missed it |
|---|---|---|
| `case-e4ccab640e6469f68794`, reversed | Attribute specialist added `excluded:tomato` despite an empty exclusion list. | Both candidates already violated the duration constraint. |
| `case-42c7fb02cb68d848ba1c`, reversed | Single judge reported A's preference coverage as 1/3 instead of 2/3. | B still won under the active objectives. |

**Recommended change:** strengthen the final field-check instruction so that the JSON findings and decision reflect the model's final assessment. Extend offline diagnostics to compare reported preference scores, feasibility flags, and violation lists with the reference evidence. Report these errors even when the final decision is correct.

These factual checks belong in evaluation reporting. Automatically repairing model findings from case facts during inference would add deterministic assistance and change the evaluated system. Do not extract an alternative answer from prose rationales to overwrite saved fields.

**Relevant code:** [prompts](../../src/macro/ai_agents/prompts.py), [schemas](../../src/macro/ai_agents/schemas.py), and [evaluation metrics](../../src/macro/evaluation/metrics.py).

### 4. Explanation support and disclosure need clearer definitions

In `case-e76aabc82490a54dd164`, reversed order, the single judge marked both explanations unsupported because they did not explicitly say that the recipes exceeded the hard duration limit. The explanations accurately stated their durations. Omission of an explicit constraint warning does not make the stated duration false.

Disclosure judgments also vary: some responses accept factual attribute listings as sufficient disclosure, while others require explicit comparisons or warnings.

**Recommended change:** distinguish factual support from disclosure in the rubric. Define whether disclosure requires an explicit statement of a constraint failure or trade-off, or whether presenting the relevant facts is sufficient. Apply that definition consistently to both systems and document it before freezing the study.

Current explanation findings are diagnostics and do not override recipe verdicts. This run does not establish explanation-assessment accuracy from final decision accuracy alone.

### 5. Reporting should expose hidden errors and separate missingness from disagreement

The current headline report is useful for decision accuracy but omits several distinctions needed to assess reliability:

- Score/comparison agreement does not establish that a decision follows the reported findings.
- A correct decision can contain wrong scores or invented violations.
- An incomplete candidate-order pair is different from two completed assessments that disagree.
- Overall unresolved frequency mixes expected insufficient-information outcomes with erroneous abstentions on tie cases.

**Recommended change:** add decision-versus-findings diagnostics, criterion-level finding accuracy, and a verdict confusion table. Show complete-pair order agreement alongside planned-pair coverage. Separate correct insufficient-information outcomes from unnecessary abstentions.

Configure pricing with its currency, effective date, and official source. Report usage and estimated cost by system, including retry and tool-follow-up calls. Preserve cache-hit and cache-miss counts, which are present in the saved DeepSeek usage records. Any estimate should state its pricing assumptions and the two calls with unknown usage.

The earlier AutoGen unknown-model pricing warning is consistent with missing local pricing metadata. It does not mean these successful requests were free or that the API model identifier was invalid.

**Relevant code:** [metrics](../../src/macro/evaluation/metrics.py) and [report generation](../../src/macro/reporting/summary.py).

## Interpretation of the specialist advantage

The specialist system exceeds the single judge by 12 correct decisions across 240 planned evaluations, or five percentage points. All 14 single-judge errors concern tie handling; the specialist system gets those tie evaluations right but loses two evaluations elsewhere.

This supports a narrow finding: the specialist pipeline handles ties more reliably in this development run. It does not isolate the effect of specialization. The panel uses three initial model calls per case/order and a deterministic coordinator; the single judge uses one initial call and supplies its own decision.

If the study aims to attribute improvement specifically to specialization, consider a separately defined comparison using the same deterministic decision rules on single-judge findings, and an appropriate computation-matched baseline. Preserve the existing result as the result of the original systems.

## Work required before the final evaluation

The saved dataset remains `draft_not_frozen`. Its recorded readiness checks still list manual review, explanation-length leakage checks, and surface-classifier checks as pending. Source/subset manual review is also pending, and the scope remains factual base explanations with the planned variant package unfinished.

Recommended sequence:

1. Implement the prompt, output-handling, and reporting changes described above, with offline regression checks for the observed failures.
2. Validate changed behavior on development cases under a fresh run ID. Review both final decisions and underlying findings. A targeted check is useful during development; a full development rerun should assess the configuration selected for freezing.
3. Complete and record source/manual review and leakage checks. Decide whether the final study includes factual base explanations only or explanation variants, and complete the work required by that scope.
4. Record the selected prompts, schemas, aggregation rules, configuration, model identity/date, dataset hashes, source revision, and review evidence.
5. Replace the unconditional final-test rejection with a checked readiness path. Update final-run status and report wording while retaining integrity checks, resume checks, and explicit paid-run acknowledgement.
6. Run the final 400-case evaluation only after readiness and freeze are complete.

The manifest's `live_gate_passed` value is currently written as `false` when a run is created and is not updated by a review workflow. It should not be interpreted as an automatically assessed failure of this completed run. Readiness needs explicit evidence and a meaningful recorded status.

## Evidence and review scope

This review used the saved case and private reference snapshots, manifest, summary, evaluation records, role attempts, and raw call records. All 120 reference verdicts were independently recomputed from the saved public case facts and agreed with the saved verdicts. Current package source hashes matched the run manifest at review time.

The review identified findings and proposed changes. It did not change prompts, code, dataset labels, saved results, or readiness flags, and did not launch additional model calls or evaluate the final-test cases.

Primary records:

- Run summary (`results/deepseek-benchmark-dev-120-001/summary.json`, external run artifact)
- Run manifest (`results/deepseek-benchmark-dev-120-001/manifest.json`, external run artifact)
- Human-readable run report (`results/deepseek-benchmark-dev-120-001/report.html`, external run artifact)
- Case snapshot (`results/deepseek-benchmark-dev-120-001/cases.snapshot.jsonl`, external run artifact)
- Private reference snapshot (`results/deepseek-benchmark-dev-120-001/references.snapshot.private.jsonl`, external run artifact)
- [Dataset readiness checks](../../data/benchmark-v2/validation.json)
- [Dataset manifest](../../data/benchmark-v2/manifest.json)

The private references are linked for local audit purposes and should remain separate from material supplied to model judges.
