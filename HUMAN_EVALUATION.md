# Prepare the 50-case human evaluation

The generator draws **10 unique base cases from each of five categories**:
constraints, dominance, trade-offs, ties and both candidates violating constraints.
This balances benchmark categories, not A/B/tie verdict labels. One randomly chosen
candidate order is shown per case, so the packet contains 50 unique base cases.

Humans judge the recipe pair independently, before seeing model answers or reference
labels. This supports comparing human judgments with both the reference and each
system afterward. It is not a direct rating of the models' written rationales.

## Generate the packet

Run from the project folder. Replace `results/deepseek-final-400` with the saved run folder you want to sample:

```powershell
.\.venv\Scripts\python.exe scripts/generate_human_evaluation.py --run-dir results/deepseek-final-400 --out human_evaluation/sample-50-seed-42 --per-class 10 --seed 42
```

The default seed is fixed for reproducibility. Keep it fixed for the study; do not
try different seeds and select whichever gives favorable agreement. Sampling uses
the saved run snapshots and does not depend on correctness, disagreement or failures.
Failed or missing system judgments are retained in the private key, not excluded
from eligibility. The source results are never edited, and existing output folders
are rejected to protect collected annotations.

This needs only Python's standard library. It makes no API calls.

## Give the evaluators only the packet folder

```text
sample-50-seed-42/
  packet/                 Share this folder only
    evaluate.html         Offline evaluation form and rubric
    cases.json            Blinded case evidence
    responses.csv         Blank response sheet, if preferred
    README.md             Evaluator instructions
  private/                Keep away from evaluators until submission
    answer_key.json       Gold labels, case mapping and both model results
    manifest.json         Seed, sample balance and source/output fingerprints
  README.md               Researcher instructions
```

Open the form:

```powershell
Start-Process -FilePath (Resolve-Path -LiteralPath 'human_evaluation/sample-50-seed-42/packet/evaluate.html').Path
```

Each evaluator enters an anonymous rater code, assesses feasibility and the final
verdict, records confidence and a reason, and flags suspected evidence issues.
Explanation-support and disclosure fields are optional diagnostics with definitions
in the displayed rubric. The evaluator can download responses as CSV or JSON.

The form attempts to save answers in browser storage. Export before closing and
regularly while working, since local-file browser storage is not guaranteed.
For multiple evaluators, use the same unmodified packet on separate computers or
browser profiles; a shared profile could reveal another evaluator's saved answers.
Collect independent answers before discussion or adjudication.

`unable_to_assess` is a human assessment failure/uncertainty, distinct from
`insufficient_information`, which is a valid benchmark verdict for conflicting
objectives without priorities. Retain missing responses and unable-to-assess cases
in reporting rather than silently discarding them.

## After annotation

Join returned answers to `private/answer_key.json` by `sample_id`. Reference verdicts
under `reference_displayed` and model results already use the exact A/B order shown
to the evaluator. The original case ID, category and original reference are retained
privately for auditing. `model_results` contains both primary and raw decisions when
present in the source run.

Report agreement with the reference, agreement with each system, per-category
results, missing judgments, and inter-rater agreement when using multiple evaluators.
A single evaluator cannot establish inter-rater reliability. Generating this packet
does not establish that human review has occurred or replace the frozen final run.
