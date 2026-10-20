"""Fixed benchmark aggregation and a shared hard-constraint guardrail."""
from macro.ai_agents.schemas import SCHEMAS
from macro.shared.comparison import EPSILON, compare

AGGREGATION_VERSION = "benchmark-fixed-v1"


def comparisons(preferences, attributes, reported, objectives):
    pref = {x["candidate"]: x for x in preferences}
    attr = {x["candidate"]: x for x in attributes}
    scores = {"preference": [pref[s]["preference_score"] for s in ("A", "B")],
              "nutrition": [attr[s]["nutrition_score"] for s in ("A", "B")],
              "speed": [-attr[s]["duration_minutes"] for s in ("A", "B")]}
    derived, warnings = {}, []
    for objective in objectives:
        field = objective + "_comparison"
        derived[field] = compare(*scores[objective])
        if derived[field] != reported[field]:
            warnings.append({"code": "score_comparison_mismatch", "criterion": objective,
                             "reported": reported[field], "derived": derived[field],
                             "scores": dict(zip(("A", "B"), scores[objective]))})
    return derived, warnings


def choose(feasible, derived, priorities):
    valid = [s for s in ("A", "B") if feasible[s]]
    if not valid:
        return "both_violate", "Both candidates fail hard constraints"
    if len(valid) == 1:
        return valid[0], "Hard constraints take precedence"
    winners = set(derived.values()) - {"equal"}
    if not winners:
        return "tie", "Equal on all active objectives"
    if len(winners) == 1:
        return next(iter(winners)), "Pareto dominance on active objectives"
    if priorities is None:
        return "insufficient_information", "Conflicting objectives without declared priorities"
    return next(derived[o + "_comparison"] for o in priorities if derived[o + "_comparison"] != "equal"), "First unequal objective in declared priorities"


def verified_constraints(case):
    profile = case["profile"]
    pool = {r["id"]: r for r in case["candidate_pool"]}
    findings = {}
    for slot in ("A", "B"):
        recipe = pool[case["recommendations"][slot]["recipe_id"]]
        cap = profile["hard_max_duration_minutes"]
        violations = ["duration"] if cap is not None and recipe["duration_minutes"] > cap + EPSILON else []
        violations += ["excluded:" + g for g in sorted(set(profile["excluded_ingredients"]) & set(recipe["canonical_ingredients"]))]
        findings[slot] = {"feasible": not violations, "violations": violations}
    return findings


def guard_single(result, case):
    """Preserve raw judge findings/decision, overriding only verified hard failures."""
    if result["status"] != "ok":
        return result
    verified = verified_constraints(case)
    result["raw_decision"] = result["decision"]
    valid = [s for s, f in verified.items() if f["feasible"]]
    if len(valid) < 2:
        result["decision"] = valid[0] if valid else "both_violate"
    result["verified_constraints"] = verified
    result["guardrail_changed_decision"] = result["decision"] != result["raw_decision"]
    return result


def aggregate(records, case):
    failure = {"status": "technical_failure", "decision": None,
               "aggregation_version": AGGREGATION_VERSION,
               "trace": ["A specialist output is missing or invalid"]}
    try:
        if any(records.get(role, {}).get("status") != "ok" for role in ("preference", "attribute", "explanation")):
            return failure
        pref, attr, expl = [SCHEMAS[role].model_validate(records[role]["assessment"]).model_dump()
                            for role in ("preference", "attribute", "explanation")]
        if any(sorted(x["candidate"] for x in a["findings"]) != ["A", "B"] for a in (pref, attr, expl)):
            return failure
        profile = case["profile"]
        reported = {"preference_comparison": pref["preference_comparison"],
                    "nutrition_comparison": attr["nutrition_comparison"], "speed_comparison": attr["speed_comparison"]}
        derived, warnings = comparisons(pref["findings"], attr["findings"], reported, profile["objectives"])
        raw, _ = choose({x["candidate"]: x["feasible"] for x in attr["findings"]}, derived, profile["priorities"])
        verified = verified_constraints(case)
        decision, reason = choose({s: f["feasible"] for s, f in verified.items()}, derived, profile["priorities"])
        return {"status": "ok", "decision": decision, "raw_decision": raw,
                "aggregation_version": AGGREGATION_VERSION, "attributes": attr["findings"],
                "preferences": pref["findings"], "explanations": expl["findings"],
                "reported_comparisons": reported, "derived_comparisons": derived,
                "comparison_diagnostics": warnings, "verified_constraints": verified,
                "guardrail_changed_decision": decision != raw,
                "priority_extraction_matches": pref["priorities"] == profile["priorities"],
                "trace": ["Hard constraints verified from public facts", reason],
                "diagnostics": [x["candidate"] + ": explanation issue" for x in expl["findings"]
                                if not x["supported"] or not x["relevant_tradeoffs_disclosed"]]}
    except (ValueError, TypeError, KeyError, StopIteration):
        return failure
