"""Deterministic reference policy for the current benchmark."""
import math

from .comparison import EPSILON

POLICY_VERSION = "benchmark-policy-v1"
GROUPS = frozenset(["tomato", "broccoli", "spinach", "mushroom", "onion", "garlic", "carrot", "olive"])
OBJECTIVES = frozenset(["preference", "nutrition", "speed"])
VERDICTS = frozenset(["A", "B", "tie", "insufficient_information", "both_violate"])


def number(value, name, positive=False):
    if type(value) not in (int, float) or not math.isfinite(value) or (positive and value <= 0):
        raise ValueError(f"{name} must be a finite {'positive ' if positive else ''}number")
    return value


def unique_list(value, name, allowed):
    if not isinstance(value, list) or any(not isinstance(x, str) or x not in allowed for x in value):
        raise ValueError(f"{name} must be a list drawn from {sorted(allowed)}")
    if len(set(value)) != len(value):
        raise ValueError(f"{name} contains duplicates")
    return value


def validate_profile(profile):
    fields = {"preferred_ingredients", "excluded_ingredients", "hard_max_duration_minutes", "objectives", "priorities"}
    if not isinstance(profile, dict) or set(profile) != fields:
        raise ValueError(f"profile must contain exactly {sorted(fields)}")
    preferred = unique_list(profile["preferred_ingredients"], "preferred_ingredients", GROUPS)
    excluded = unique_list(profile["excluded_ingredients"], "excluded_ingredients", GROUPS)
    if set(preferred) & set(excluded):
        raise ValueError("A group cannot be both preferred and excluded")
    limit = profile["hard_max_duration_minutes"]
    if limit is not None:
        number(limit, "hard_max_duration_minutes", positive=True)
    objectives = unique_list(profile["objectives"], "objectives", OBJECTIVES)
    if not objectives:
        raise ValueError("Declare at least one soft objective")
    if "preference" in objectives and not preferred:
        raise ValueError("The preference objective requires preferred ingredients")
    if preferred and "preference" not in objectives:
        raise ValueError("Preferred ingredients require an active preference objective")
    priorities = profile["priorities"]
    if priorities is not None:
        unique_list(priorities, "priorities", OBJECTIVES)
        if set(priorities) != set(objectives):
            raise ValueError("priorities must order every active objective exactly once, or be null")


def validate_recipe(recipe):
    if not isinstance(recipe, dict) or not isinstance(recipe.get("id"), str) or not recipe["id"]:
        raise ValueError("Recipe must have a nonempty string id")
    number(recipe.get("duration_minutes"), "duration_minutes", positive=True)
    score = number(recipe.get("nutrition_score"), "nutrition_score")
    if not 0 <= score <= 1 or abs(score * 8 - round(score * 8)) > EPSILON:
        raise ValueError("nutrition_score must be a normalized FSA value on the 0.125 grid")
    if recipe.get("nutrition_metric") != "hummus_normalized_fsa":
        raise ValueError("nutrition_metric must identify hummus_normalized_fsa")
    unique_list(recipe.get("canonical_ingredients"), "canonical_ingredients", GROUPS)


def evaluate_case(case):
    """Generate references from recipe/profile evidence, never explanation wording.

    Input uses the existing candidate_pool/recommendations layout but the new profile
    schema. Invalid benchmark evidence raises ValueError; it is not a trade-off.
    """
    if not isinstance(case, dict) or not isinstance(case.get("case_id"), str) or not case["case_id"]:
        raise ValueError("case_id must be a nonempty string")
    profile = case.get("profile")
    validate_profile(profile)
    pool, recommendations = case.get("candidate_pool"), case.get("recommendations")
    if not isinstance(pool, list) or len(pool) < 2:
        raise ValueError("candidate_pool must contain at least two recipes")
    for recipe in pool:
        validate_recipe(recipe)
    if len({r["id"] for r in pool}) != len(pool):
        raise ValueError("Recipe IDs must be unique")
    if not isinstance(recommendations, dict) or set(recommendations) != {"A", "B"}:
        raise ValueError("Exactly A and B recommendations are required")
    lookup = {r["id"]: (i, r) for i, r in enumerate(pool)}
    for slot in ["A", "B"]:
        item = recommendations[slot]
        if not isinstance(item, dict) or not isinstance(item.get("recipe_id"), str) or item["recipe_id"] not in lookup:
            raise ValueError("Recommendation must reference a recipe in the pool")
    if recommendations["A"]["recipe_id"] == recommendations["B"]["recipe_id"]:
        raise ValueError("Use distinct recipes; controls may have equal objective values")
    candidates = {}
    assessments = []
    objectives = profile["objectives"]
    for slot in ["A", "B"]:
        index, recipe = lookup[recommendations[slot]["recipe_id"]]
        base = f"/candidate_pool/{index}"
        groups = set(recipe["canonical_ingredients"])
        limit = profile["hard_max_duration_minutes"]
        violations = []
        if limit is not None and recipe["duration_minutes"] > limit + EPSILON:
            violations.append("duration")
        violations.extend("excluded:" + g for g in sorted(groups & set(profile["excluded_ingredients"])))
        scores = {}
        refs = [base + "/canonical_ingredients", base + "/duration_minutes",
                "/profile/excluded_ingredients", "/profile/hard_max_duration_minutes"]
        if "preference" in objectives:
            preferred = set(profile["preferred_ingredients"])
            scores["preference"] = len(groups & preferred) / len(preferred)
            refs.append("/profile/preferred_ingredients")
        if "nutrition" in objectives:
            scores["nutrition"] = recipe["nutrition_score"]
            refs.extend([base + "/nutrition_score", base + "/nutrition_metric"])
        if "speed" in objectives:
            # Negation places every objective on a higher-is-better orientation.
            scores["speed"] = -recipe["duration_minutes"]
        candidates[slot] = {"recipe_id": recipe["id"], "feasible": not violations,
                            "violations": violations, "objective_scores": scores}
        assessments.append({"candidate": slot, **candidates[slot], "evidence_references": refs})
    feasible = [s for s in ["A", "B"] if candidates[s]["feasible"]]
    comparisons = {}
    for objective in objectives:
        difference = candidates["A"]["objective_scores"][objective] - candidates["B"]["objective_scores"][objective]
        comparisons[objective] = "equal" if abs(difference) <= EPSILON else "A" if difference > 0 else "B"
    if not feasible:
        verdict, kind, reason = "both_violate", "both_violate", "Both recipes fail at least one hard constraint"
    elif len(feasible) == 1:
        verdict, kind, reason = feasible[0], "constraint", "Only one recipe satisfies all hard constraints"
    else:
        winners = set(comparisons.values()) - {"equal"}
        if not winners:
            verdict, kind, reason = "tie", "control_tie", "Feasible recipes are equal on every declared objective"
        elif len(winners) == 1:
            verdict, kind, reason = next(iter(winners)), "dominance", "One feasible recipe Pareto-dominates the other"
        else:
            kind = "tradeoff"
            if profile["priorities"] is None:
                verdict, reason = "insufficient_information", "Conflicting objectives without declared priorities"
            else:
                verdict = next(comparisons[o] for o in profile["priorities"] if comparisons[o] != "equal")
                reason = "First unequal objective in the declared priority ordering"
    return {"case_id": case["case_id"], "policy_version": POLICY_VERSION,
            "verdict": verdict, "case_type": kind, "reason": reason,
            "candidates": candidates, "objective_comparisons": comparisons,
            "per_criterion_assessments": assessments,
            "evidence_references": ["/profile/objectives", "/profile/priorities"] +
                sorted({ref for a in assessments for ref in a["evidence_references"]})}
