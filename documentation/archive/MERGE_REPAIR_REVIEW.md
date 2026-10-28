# Merge repair review

Historical development record. Commands and status statements below describe that earlier stage. Use the [current run guide](../RUNNING.md) for execution.

**Date:** 20 October 2026  
**Merged revision reviewed:** `a80f8d7`  
**Historical development run:** `deepseek-benchmark-dev-120-001`

## Outcome

The merge combined two incompatible versions of the CLI, provider adapter, and
benchmark contracts. The resulting application could not initialize its commands
or import several runtime modules. Repairs restore the DeepSeek development path
while retaining the current benchmark refactor and its separately reported raw
and guarded decisions.

The completed 120-case run is preserved as historical evidence. Rebuilding its
reports on a temporary copy retained 226/240 correct single-judge decisions,
238/240 correct specialist decisions, and 974 recorded calls. Checksums confirmed
that all 2,427 original run files were unchanged. The rebuilt report does not
claim that the newer constraint guardrail was applied to that historical run.

## Problems repaired

| Problem introduced or exposed by the merge | Repair |
|---|---|
| Duplicate CLI subcommands and duplicate argument registration prevented startup. | Consolidated command registration and retained `--split dev` / `--split test` with benchmark-root input. |
| An exception handler could call `run` a second time without the split argument. | Errors now exit once; regression coverage verifies that execution is not repeated. |
| Runner passed an undefined `split` to a function that did not accept it. | Propagated the optional split consistently through planning, loading, and execution. |
| DeepSeek was rejected by provider selection and could fall through to OpenAI credentials. | Restored DeepSeek selection, endpoint settings, and isolated credentials. An explicit configuration provider takes precedence over environment selection. |
| DeepSeek JSON/thinking settings existed but were bypassed by agent construction. | Connected them to the actual AG2 agent; restored missing reasoning-history imports and schema identity handling. |
| Schema calls referenced deleted helpers; an older schema/coordinator implementation remained alongside the current one. | Consolidated active validation in `schemas.py` and aggregation in `coordinator/aggregation.py`; the former benchmark module now reexports that contract. |
| The actual system prompt differed from the schema instructions saved in role records. | Agent construction and saved records now use the same complete provider prompt. |
| DeepSeek configurations lacked the current benchmark policy identifier and use a different token-limit setting. | Added the policy version to both configurations and validate the provider's applicable token field. |
| Stale tests imported removed pilot modules and generated the previous wire format. | Migrated those tests to current benchmark fixtures while retaining DeepSeek tool, repair, refusal, and thinking-protocol coverage. |
| New manifests omitted split metadata used by category reports; old runs were labeled as if they used new guardrails. | Reports accept both manifest layouts and describe guardrails only when saved evaluation records contain them. |
| Reasoning-token reporting disappeared during the merge. | Restored reported reasoning counts without adding them twice to completion usage. |
| Final-test inference could run despite the dataset's pending review/freeze status. | Restored rejection of live final-test execution, including split-folder input. Default commands now select development cases; final-test planning remains available. |

Existing uncommitted HTML-report improvements were retained.

## Contract and interpretation changes

New runs use `benchmark-assessment-v2` and `benchmark-judges-v2`. Attribute findings
record positive `duration_minutes`; the historical run recorded negative
`speed_score`. Schema versions distinguish these incompatible formats. Historical
responses are displayed as saved data rather than revalidated against the new schema.

The merged implementation also verifies hard constraints from public case facts
for both systems. New reports retain raw decisions and raw constraint-detection
metrics separately. This changes the experimental condition relative to the old
120-case run; results should not be pooled as though the systems were unchanged.
The coordinator now also uses the priorities in the public profile and records
whether the preference specialist extracted them correctly; its raw decision
means before the hard-constraint guardrail, not before every use of public facts.

The prompt now explicitly distinguishes equality on all active objectives from a
trade-off without priorities, and asks the judge to reconcile its final JSON
fields with its assessment. Live improvement from those instructions has not yet
been established.

## Verification

**Result:** all 91 offline tests passed in 150.9 seconds with
`python -m unittest discover -s tests`. Python compilation, `pip check`, and
`git diff --check` passed. Dataset files were unchanged.

- Full offline suite, including the 120-case development pipeline and the
  400-case pipeline with synthetic providers; no final cases sent to a model.
- Mocked installed AG2/OpenAI SDK requests for DeepSeek, including thinking,
  calculator continuations, bounded repairs, usage, and credential isolation.
- Ollama regression coverage and a mocked DeepInfra endpoint/schema check.
- Original 120-case development plan: 960 initial requests, 5,760 theoretical
  maximum requests, provider `deepseek`, model `deepseek-flash`.
- Historical report reconstruction and original-run checksum comparison.
- Python compilation, dependency consistency, and whitespace checks.

The test log is available locally at `tmp/merge-verified.log`. Offline synthetic
results verify implementation behavior, not model accuracy or live endpoint compatibility.

## Next development check

Use a fresh run ID because code, schema, and prompts changed. Do not resume the
old 120-case run with the repaired implementation. From `MACRO/`, with
`$taskPython` set to the installed environment's Python executable:

```powershell
& $taskPython -m macro plan --config configs/deepseek-pilot.json --cases data/benchmark-v2 --split dev --limit 1
# Paid live development check:
& $taskPython -m macro run --config configs/deepseek-pilot.json --cases data/benchmark-v2 --split dev --limit 1 --allow-paid-api --max-calls 48 --run-id deepseek-dev-merge-smoke-001
& $taskPython -m macro summarize results/deepseek-dev-merge-smoke-001
```

Review that smoke run before another full development run. The previous findings
on malformed explanation output, explanation disclosure definitions, and cost
configuration still need follow-up; merge repair alone does not resolve them.
Manual/source review, leakage checks, explanation-variant scope, and experiment
freeze remain prerequisites for enabling the final 400-case evaluation. No new
paid run or final-test model evaluation was launched during this repair.
