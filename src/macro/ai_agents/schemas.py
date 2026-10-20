import copy
import json
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from macro.shared.benchmark_policy import GROUPS

SCHEMA_VERSION = "benchmark-assessment-v1"

Comparison = Literal["A", "B", "equal"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class PreferenceFinding(StrictModel):
    candidate: Literal["A", "B"]
    preference_score: float = Field(ge=0, le=1)
    evidence: list[str]


class AttributeFinding(StrictModel):
    candidate: Literal["A", "B"]
    feasible: bool
    violations: list[str]
    nutrition_score: float = Field(ge=0, le=1)
    evidence: list[str]

    @model_validator(mode="after")
    def coherent(self):
        if self.feasible == bool(self.violations):
            raise ValueError("feasibility contradicts violation list")
        return self


class ExplanationFinding(StrictModel):
    candidate: Literal["A", "B"]
    supported: bool
    relevant_tradeoffs_disclosed: bool
    issues: list[str]
    evidence: list[str]


class ExplanationAssessment(StrictModel):
    findings: list[ExplanationFinding]
    rationale: str


Objective = Literal["preference", "nutrition", "speed"]


class BenchmarkAttributeFinding(AttributeFinding):
    duration_minutes: float = Field(gt=0)


class BenchmarkPreferenceAssessment(StrictModel):
    findings: list[PreferenceFinding]
    preference_comparison: Comparison
    priorities: list[Objective] | None
    rationale: str


class BenchmarkAttributeAssessment(StrictModel):
    findings: list[BenchmarkAttributeFinding]
    nutrition_comparison: Comparison
    speed_comparison: Comparison
    rationale: str


class BenchmarkSingleAssessment(StrictModel):
    preferences: list[PreferenceFinding]
    attributes: list[BenchmarkAttributeFinding]
    explanations: list[ExplanationFinding]
    preference_comparison: Comparison
    nutrition_comparison: Comparison
    speed_comparison: Comparison
    priorities: list[Objective] | None
    decision: Literal["A", "B", "tie", "insufficient_information", "both_violate"]
    rationale: str


SCHEMAS = {"single": BenchmarkSingleAssessment, "preference": BenchmarkPreferenceAssessment,
           "attribute": BenchmarkAttributeAssessment, "explanation": ExplanationAssessment}


def assessment_groups(role):
    return ["preferences", "attributes", "explanations"] if role == "single" else ["findings"]


def evidence_pointers(evidence):
    """Public evidence locations only; never expose reference labels or compute judgments."""
    pointers = ["/request", "/profile", "/candidate_pool", "/recommendations"]
    pointers += [f"/profile/{key}" for key in evidence["profile"]]
    for index, recipe in enumerate(evidence["candidate_pool"]):
        pointers += [f"/candidate_pool/{index}"]
        pointers += [f"/candidate_pool/{index}/{key}" for key in recipe]
    for candidate, recommendation in evidence["recommendations"].items():
        pointers += [f"/recommendations/{candidate}"]
        pointers += [f"/recommendations/{candidate}/{key}" for key in recommendation]
    return sorted(pointers)


def response_schema(role, evidence=None):
    """Wire schema requires both candidate keys; saved assessments retain the list format."""
    schema = schemas_for(evidence)[role].model_json_schema()
    for key in assessment_groups(role):
        finding_schema = schema["properties"][key]["items"]
        schema["properties"][key] = {
            "type": "object", "properties": {"A": copy.deepcopy(finding_schema), "B": copy.deepcopy(finding_schema)},
            "required": ["A", "B"], "additionalProperties": False,
            "description": "Assess BOTH displayed candidates, including every infeasible candidate."}
    for finding in schema["$defs"].values():
        properties = finding.get("properties", {})
        properties.pop("candidate", None)
        finding["required"] = [key for key in finding.get("required", []) if key != "candidate"]
        if "evidence" in properties:
            properties["evidence"]["minItems"] = 1
            if evidence is not None:
                properties["evidence"]["items"]["enum"] = evidence_pointers(evidence)
        if "violations" in properties:
            properties["violations"]["items"]["enum"] = ["duration"] + ["excluded:" + group for group in sorted(GROUPS)]
    return schema


class AssessmentValidationError(ValueError):
    """Safe local validation diagnostics; no provider exception strings or credentials."""
    def __init__(self, errors, raw):
        self.errors, self.raw = errors, raw
        super().__init__("; ".join(error["message"] for error in errors))


def pointer_exists(data, pointer):
    if not pointer.startswith("/"):
        return False
    try:
        for part in pointer.split("/")[1:]:
            part = part.replace("~1", "/").replace("~0", "~")
            if isinstance(data, list):
                if not part.isdigit() or (len(part) > 1 and part.startswith("0")):
                    return False
                data = data[int(part)]
            else:
                data = data[part]
        return True
    except (ValueError, IndexError, KeyError, TypeError):
        return False


def validate_assessment(role, raw, evidence):
    try:
        value = json.loads(raw) if isinstance(raw, str) else copy.deepcopy(raw)
    except (ValueError, TypeError):
        raise AssessmentValidationError([{"code": "invalid_json", "field": "/", "message": "Return a valid JSON object matching the response schema."}], raw) from None
    errors = []
    if isinstance(value, dict):
        for key in assessment_groups(role):
            group = value.get(key)
            if isinstance(group, dict):
                if set(group) != {"A", "B"}:
                    errors.append({"code": "candidate_coverage", "field": "/" + key,
                                   "message": f"{key} must contain both A and B, including infeasible candidates."})
                elif any(isinstance(finding, dict) and "candidate" in finding for finding in group.values()):
                    errors.append({"code": "extra_candidate_field", "field": "/" + key,
                                   "message": f"{key}: the A/B object keys identify candidates; omit an embedded candidate field."})
                else:
                    value[key] = [dict(group[slot], candidate=slot) if isinstance(group[slot], dict) else group[slot]
                                  for slot in ["A", "B"]]
    if errors:
        raise AssessmentValidationError(errors, raw)
    try:
        parsed = schemas_for(evidence)[role].model_validate(value)
    except ValidationError as exc:
        errors = [{"code": error["type"], "field": "/" + "/".join(map(str, error["loc"])),
                   "message": error["msg"]} for error in exc.errors(include_input=False, include_context=False, include_url=False)]
        raise AssessmentValidationError(errors, raw) from None
    result = parsed.model_dump()
    if "priorities" in result and result["priorities"] is not None:
        priorities = result["priorities"]
        if len(set(priorities)) != len(priorities) or set(priorities) != set(evidence["profile"]["objectives"]):
            errors.append({"code": "priority_order", "field": "/priorities",
                           "message": "Priorities must be null or order every active objective exactly once."})
    for key in assessment_groups(role):
        group = result[key]
        if len(group) != 2 or {f["candidate"] for f in group} != {"A", "B"}:
            errors.append({"code": "candidate_coverage", "field": "/" + key,
                           "message": f"{key}: Exactly one finding per candidate A/B is required, including infeasible candidates."})
        for finding in group:
            # Accept the old envelope prefix as syntax-only compatibility; never alter findings or scores.
            pointers = [x[5:] if x.startswith("/case/") else x for x in finding["evidence"]]
            if not pointers or not all(pointer_exists(evidence, x) for x in pointers):
                errors.append({"code": "evidence_pointer", "field": f"/{key}/{finding['candidate']}/evidence",
                               "message": "Evidence must reference existing JSON pointers in the supplied case; use /profile/... or /candidate_pool/... without prose."})
            else:
                finding["evidence"] = pointers
    if errors:
        raise AssessmentValidationError(errors, raw)
    return result
