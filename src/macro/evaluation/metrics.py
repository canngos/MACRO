"""Accuracy, constraint detection, consistency and candidate-order metrics."""
from collections import Counter

from macro.shared.policy import canonical_decision, swapped


def fraction(numerator, denominator):
    return {"correct": numerator, "total": denominator, "rate": numerator / denominator if denominator else None}


def compute(cases, references, results):
    refs = {r["case_id"]: r for r in references}
    benchmark = bool(references and references[0].get("policy_version") == "benchmark-policy-v1")
    report = {}
    for system in ["single", "specialists"]:
        expected = len(cases) * 2
        coverage = 0
        failures = Counter()
        comparison_warnings = Counter()
        consistency_checked = consistency_failed = 0
        tp = fp = fn = tn = checked_flags = 0
        subtypes = {name: {key: 0 for key in ["tp", "fp", "fn", "tn", "observed_flags"]}
                    for name in ["duration", "ingredient_exclusion"]}
        types = {k: [0, 0] for k in (["constraint", "dominance", "tradeoff", "control_tie", "both_violate"] if benchmark else ["constraint", "dominance", "tradeoff"])}
        alignment = [0, 0]
        unresolved_expected = [0, 0]
        outcomes = Counter()
        stable = stable_complete = 0
        for original in cases:
            cid = original["case_id"]
            ref = refs[cid]
            expected_verdict = ref["verdict"] if benchmark else ref["decision"]
            expected_canonical = canonical_decision(original, expected_verdict)
            decisions = []
            for order in ["original", "reversed"]:
                case = original if order == "original" else swapped(original)
                result = results.get((cid, order, system))
                if result is not None and "comparison_diagnostics" in result:
                    consistency_checked += 1
                    consistency_failed += bool(result["comparison_diagnostics"])
                    comparison_warnings.update(d["criterion"] for d in result["comparison_diagnostics"])
                if result is None:
                    failures["missing"] += 1
                    decisions.append(None)
                elif result["status"] not in ["ok", "inconsistent_findings"]:
                    failures[result["status"]] += 1
                    decisions.append(None)
                else:
                    coverage += 1
                    decision = canonical_decision(case, result["decision"])
                    decisions.append(decision)
                    outcomes[result["decision"]] += 1
                    if result["status"] == "inconsistent_findings":
                        failures["inconsistent_findings"] += 1
                    predicted = {x["candidate"]: x for x in result.get("attributes", [])}
                    for slot in ["A", "B"]:
                        if slot not in predicted:
                            continue
                        recipe = case["recommendations"][slot]["recipe_id"]
                        canonical_slot = next(k for k in ["A", "B"] if original["recommendations"][k]["recipe_id"] == recipe)
                        actual_violation = not ref["candidates"][canonical_slot]["feasible"]
                        pred_violation = not predicted[slot]["feasible"]
                        tp += actual_violation and pred_violation
                        fp += not actual_violation and pred_violation
                        fn += actual_violation and not pred_violation
                        tn += not actual_violation and not pred_violation
                        checked_flags += 1
                        if "violations" in predicted[slot] and "violations" in ref["candidates"][canonical_slot]:
                            actual = ref["candidates"][canonical_slot]["violations"]
                            guessed = predicted[slot]["violations"]
                            for name in subtypes:
                                truth = "duration" in actual if name == "duration" else any(x.startswith("excluded:") for x in actual)
                                guess = "duration" in guessed if name == "duration" else any(x.startswith("excluded:") for x in guessed)
                                key = "tp" if truth and guess else "fn" if truth else "fp" if guess else "tn"
                                subtypes[name][key] += 1
                                subtypes[name]["observed_flags"] += 1
                # Full planned denominators include missing/error outcomes as not correct.
                types[ref["case_type"]][1] += 1
                correct = bool(result and result["status"] == "ok" and decisions[-1] == expected_canonical)
                types[ref["case_type"]][0] += correct
                priority_declared = original["profile"]["priorities"] is not None if benchmark else original["profile"]["priority"] != "unspecified"
                if ref["case_type"] == "tradeoff" and priority_declared:
                    alignment[1] += 1
                    alignment[0] += correct
                if expected_verdict == ("insufficient_information" if benchmark else "unresolved"):
                    unresolved_expected[1] += 1
                    # An inconsistent assessment is not a correct insufficient-priority explanation.
                    unresolved_expected[0] += bool(correct and result and result["status"] == "ok")
            stable_complete += all(x is not None for x in decisions)
            stable += all(x is not None for x in decisions) and decisions[0] == decisions[1]
        report[system] = {
            "evaluation_coverage": fraction(coverage, expected), "diagnostic_counts": dict(failures),
            "comparison_consistency": {"checked_evaluations": consistency_checked,
                "evaluations_with_warnings": consistency_failed, "warnings_by_criterion": dict(comparison_warnings),
                "note": "Warnings do not invalidate a decision. Missing historical diagnostics are not counted as consistent."},
            "accuracy_by_type": {k: fraction(*v) for k, v in types.items()},
            "constraint_detection": {"unit": "candidate violation flag, both orders (repeated observations)",
                "tp": tp, "fp": fp, "fn": fn, "tn": tn, "observed_flags": checked_flags, "planned_flags": expected * 2,
                "precision": tp / (tp + fp) if tp + fp else None, "recall": tp / (tp + fn) if tp + fn else None,
                "note": "Precision/recall use available flags; missing flags are exposed through coverage, not silently labelled safe."},
            "declared_priority_alignment": fraction(*alignment),
            "constraint_subtype_diagnostics": subtypes,
            "correct_insufficient_priority_outcomes": fraction(*unresolved_expected),
            "unresolved_frequency": {"count": outcomes["insufficient_information" if benchmark else "unresolved"], "completed": coverage, "rate": outcomes["insufficient_information" if benchmark else "unresolved"] / coverage if coverage else None},
            "outcomes": dict(outcomes), "candidate_order_stability": fraction(stable, len(cases)),
            "complete_order_pairs": stable_complete}
        if benchmark:
            report[system]["overall_accuracy"] = fraction(sum(v[0] for v in types.values()), expected)
            rates = [v[0] / v[1] for v in types.values() if v[1]]
            report[system]["macro_category_accuracy"] = sum(rates) / len(rates) if rates else None
    return report


