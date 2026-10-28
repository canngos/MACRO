# Human evaluation

Two reviewers independently assess the same 50 cases without seeing model judgments or reference labels. Their task is to check the evidence, constraints, dominance and declared priorities. Personal food preferences must not become the reference answer.

## Create a blinded packet

From the repository folder, use a saved run that contains case and reference snapshots:

```powershell
.\.venv\Scripts\python.exe scripts/generate_human_evaluation.py --run-dir results/deepseek-final-400 --out human_evaluation/sample-50-seed-42 --per-class 10 --seed 42
```

Replace the run folder if your saved copy has a different name. Raw runs are not included in Git. This command makes no model calls and refuses an existing output folder.

The generator selects ten unique cases from each of the five categories and shows one randomized candidate order per case. Sampling does not select on model success or correctness. Keep the selected sample and seed fixed.

| Output | Purpose |
|---|---|
| `packet/evaluate.html` | Offline form with case evidence and rubric |
| `packet/cases.json` | Blinded case evidence |
| `packet/responses.csv` | Blank response sheet |
| `packet/README.md` | Reviewer instructions |
| `private/answer_key.json` | References, source case IDs and saved model judgments |
| `private/manifest.json` | Sampling and artifact identities |

Share only `packet/` with reviewers. Each reviewer uses a separate computer or browser profile and exports their responses before closing the form. Browser storage alone is not a reliable record. Collect independent responses before discussion.

## Report the human findings

Join responses to the private key by `sample_id`, preserving the displayed A/B order. Report reviewer agreement, agreement with references and models on the same 50 cases, missing responses, and the outcome of investigating disagreements. Record whether reference labels were confirmed or corrected and explain any corrections.

`insufficient_information` is a valid outcome for unresolved trade-offs. `unable_to_assess` records a review problem or uncertainty and must be reported separately. Agreement does not itself establish correctness; objective properties remain checked against recipe evidence and the fixed policy.

Generating the packet does not establish that annotation is complete. Completed responses and their analysis are separate study artifacts and are not included by default in this code repository.
