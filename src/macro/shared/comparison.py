"""Numeric comparison and candidate identity helpers; no reference-label calculation."""
import copy

EPSILON = 1e-9


def compare(a, b):
    return "equal" if abs(a - b) <= EPSILON else "A" if a > b else "B"


def swapped(case):
    result = copy.deepcopy(case)
    result["recommendations"] = {"A": result["recommendations"]["B"], "B": result["recommendations"]["A"]}
    return result


def canonical_decision(case, decision):
    return case["recommendations"][decision]["recipe_id"] if decision in ["A", "B"] else decision
