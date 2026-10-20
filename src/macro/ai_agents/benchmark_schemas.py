"""Benchmark wire contracts, separate from the historical pilot."""
from typing import Literal

from pydantic import Field, model_validator

from .schemas import StrictModel, AttributeFinding, ExplanationAssessment, ExplanationFinding

VERSION = "benchmark-assessment-v1"
Objective = Literal["preference", "nutrition", "speed"]
Comparison = Literal["A", "B", "equal"]


class ProfileExtraction(StrictModel):
    objectives: list[Objective] = Field(min_length=1)
    priorities: list[Objective] | None

    @model_validator(mode="after")
    def complete_order(self):
        if len(set(self.objectives)) != len(self.objectives):
            raise ValueError("Objectives must be distinct")
        if self.priorities is not None and (len(self.priorities) != len(self.objectives)
                                            or set(self.priorities) != set(self.objectives)):
            raise ValueError("Priorities must order all active objectives exactly once, or be null")
        return self


class PreferenceFinding(StrictModel):
    candidate: Literal["A", "B"]
    preference_score: float | None = Field(description="Fraction of preferred groups present; null when preference is inactive")
    evidence: list[str]

    @model_validator(mode="after")
    def bounded(self):
        if self.preference_score is not None and not 0 <= self.preference_score <= 1:
            raise ValueError("Preference score must be between zero and one")
        return self


class BenchmarkAttributeFinding(AttributeFinding):
    speed_score: float = Field(lt=0, description="Negative duration in minutes, even when speed is inactive")


class PreferenceAssessment(ProfileExtraction):
    findings: list[PreferenceFinding]
    preference_comparison: Comparison | None
    rationale: str


class AttributeAssessment(StrictModel):
    findings: list[BenchmarkAttributeFinding]
    nutrition_comparison: Comparison
    speed_comparison: Comparison
    rationale: str


class SingleAssessment(ProfileExtraction):
    preferences: list[PreferenceFinding]
    attributes: list[BenchmarkAttributeFinding]
    explanations: list[ExplanationFinding]
    preference_comparison: Comparison | None
    nutrition_comparison: Comparison
    speed_comparison: Comparison
    decision: Literal["A", "B", "tie", "insufficient_information", "both_violate"]
    rationale: str


SCHEMAS = {"single": SingleAssessment, "preference": PreferenceAssessment,
           "attribute": AttributeAssessment, "explanation": ExplanationAssessment}


def comparisons(preferences, attributes, reported, objectives):
    """Arithmetic on model findings only; never read case facts or private labels."""
    from macro.shared.policy import compare
    derived, warnings = {}, []
    for objective in objectives:
        findings = preferences if objective == "preference" else attributes
        values = {row["candidate"]: row[objective + "_score"] for row in findings}
        if any(values.get(slot) is None for slot in ["A", "B"]):
            raise ValueError("An active objective requires both numeric scores")
        field = objective + "_comparison"
        derived[field] = compare(values["A"], values["B"])
        if reported.get(field) != derived[field]:
            warnings.append({"code": "score_comparison_mismatch", "criterion": objective,
                             "reported": reported.get(field), "derived": derived[field], "scores": values})
    return derived, warnings


def choose(feasible_a, feasible_b, derived, priorities):
    if not feasible_a and not feasible_b:
        return "both_violate", "Both reported infeasible"
    if feasible_a != feasible_b:
        return ("A" if feasible_a else "B"), "Reported feasibility takes precedence"
    winners = set(derived.values()) - {"equal"}
    if not winners:
        return "tie", "All active objective scores equal"
    if len(winners) == 1:
        return next(iter(winners)), "Pareto dominance on active objectives"
    if priorities is None:
        return "insufficient_information", "Trade-off without declared priorities"
    return next(derived[o + "_comparison"] for o in priorities if derived[o + "_comparison"] != "equal"), "Declared lexicographic priority"


def aggregate(records):
    failure = {"status": "technical_failure", "decision": None, "trace": ["Missing or invalid benchmark specialist findings"]}
    try:
        if any(records.get(r, {}).get("status") != "ok" for r in ["preference", "attribute", "explanation"]):
            return failure
        pref, attr, expl = [SCHEMAS[r].model_validate(records[r]["assessment"]).model_dump()
                            for r in ["preference", "attribute", "explanation"]]
        if any(sorted(f["candidate"] for f in a["findings"]) != ["A", "B"] for a in [pref, attr, expl]):
            return failure
        reported = {"preference_comparison": pref["preference_comparison"],
                    "nutrition_comparison": attr["nutrition_comparison"], "speed_comparison": attr["speed_comparison"]}
        derived, warnings = comparisons(pref["findings"], attr["findings"], reported, pref["objectives"])
        af = {f["candidate"]: f for f in attr["findings"]}
        decision, reason = choose(af["A"]["feasible"], af["B"]["feasible"], derived, pref["priorities"])
    except (ValueError, TypeError, KeyError):
        return failure
    return {"status": "ok", "decision": decision, "attributes": attr["findings"],
            "preferences": pref["findings"], "explanations": expl["findings"],
            "objectives": pref["objectives"], "priorities": pref["priorities"],
            "aggregation_version": VERSION, "reported_comparisons": reported,
            "derived_comparisons": derived, "comparison_diagnostics": warnings, "trace": [reason]}
