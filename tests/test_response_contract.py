"""Regression checks for the live smoke run's invalid pointers and omitted candidates."""
import copy
import json
import os
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from macro.shared.io import read_json, write_jsonl
from macro.ai_agents.agents import LiveProvider
from macro.shared.comparison import swapped
from macro.ai_agents.prompts import prompt, visible_case
from macro.evaluation.runner import CallRecorder, _run
from macro.ai_agents.schemas import AssessmentValidationError, assessment_groups, response_schema, validate_assessment
from tests.fixtures import OfflineProvider, as_wire, CONFIG, fixture, completion, write_fixture_package


class ResponseContractTests(unittest.TestCase):
    def setUp(self):
        self.evidence = visible_case(fixture())
        self.record = OfflineProvider().assess("single", self.evidence, "test")

    def test_schema_requires_both_candidate_keys_and_exact_public_paths(self):
        for role in ["single", "preference", "attribute", "explanation"]:
            schema = response_schema(role, self.evidence)
            for key in assessment_groups(role):
                pair = schema["properties"][key]
                self.assertEqual(pair["type"], "object")
                self.assertEqual(pair["required"], ["A", "B"])
                self.assertFalse(pair["additionalProperties"])
            for definition in schema["$defs"].values():
                self.assertNotIn("candidate", definition["properties"])
                allowed = definition["properties"]["evidence"]["items"]["enum"]
                self.assertIn("/profile/priorities", allowed)
                self.assertIn("/candidate_pool/1/nutrition_score", allowed)
                self.assertNotIn("/case/profile/priorities", allowed)
                self.assertNotIn("/references/winner", allowed)

    def test_direct_case_packet_and_reversed_mapping(self):
        reversed_case = visible_case(swapped(fixture()))
        system, user = prompt("preference", reversed_case)
        self.assertEqual(json.loads(user), reversed_case)
        self.assertIn("Displayed A: recipe_id=2; recipe facts at /candidate_pool/1", system)
        self.assertIn("Displayed B: recipe_id=1; recipe facts at /candidate_pool/0", system)

    def test_envelope_pointer_compatibility_preserves_original_judgment(self):
        raw = copy.deepcopy(self.record["assessment"])
        raw["decision"] = "B"  # A wrong judgment must remain wrong; only pointer syntax is normalized.
        for key in assessment_groups("single"):
            for finding in raw[key]:
                finding["evidence"] = ["/case" + pointer for pointer in finding["evidence"]]
        normalized = validate_assessment("single", raw, self.evidence)
        self.assertEqual(normalized["decision"], "B")
        self.assertEqual(normalized["attributes"], self.record["assessment"]["attributes"])
        self.assertTrue(raw["attributes"][0]["evidence"][0].startswith("/case/"))
        raw["attributes"][0]["evidence"] = ["/case/profile/priorities contains a stated priority"]
        with self.assertRaises(AssessmentValidationError) as error:
            validate_assessment("single", raw, self.evidence)
        self.assertEqual(error.exception.errors[0]["code"], "evidence_pointer")
        self.assertEqual(error.exception.raw, raw)

    def test_missing_b_is_rejected_and_not_filled_from_case_data(self):
        for role in ["preference", "attribute", "explanation"]:
            raw = json.loads(OfflineProvider().assess(role, self.evidence, "test")["raw"])
            del raw["findings"]["B"]
            with self.assertRaises(AssessmentValidationError) as error:
                validate_assessment(role, raw, self.evidence)
            self.assertEqual(error.exception.errors[0]["code"], "candidate_coverage")
            self.assertNotIn("B", error.exception.raw["findings"])
        legacy = copy.deepcopy(self.record["assessment"])
        legacy["preferences"] = legacy["preferences"][:1]
        with self.assertRaises(AssessmentValidationError) as error:
            validate_assessment("single", legacy, self.evidence)
        self.assertEqual(error.exception.errors[0]["code"], "candidate_coverage")

    def test_wire_keys_cannot_silently_override_candidate_identity(self):
        raw = as_wire("single", self.record["assessment"])
        raw["attributes"]["A"]["candidate"] = "B"
        with self.assertRaises(AssessmentValidationError) as error:
            validate_assessment("single", raw, self.evidence)
        self.assertEqual(error.exception.errors[0]["code"], "extra_candidate_field")

    def test_mocked_ag2_sends_keyed_schema_and_local_retry_feedback(self):
        from openai.resources.chat.completions import Completions
        raw = json.loads(OfflineProvider().assess("attribute", self.evidence, "test")["raw"])
        del raw["findings"]["B"]
        with self.assertRaises(AssessmentValidationError) as error:
            validate_assessment("attribute", raw, self.evidence)
        feedback = {"validation_errors": error.exception.errors, "raw": raw}
        valid = OfflineProvider().assess("attribute", self.evidence, "test")["raw"]
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {"OPENAI_API_KEY": "offline-test-placeholder"}), patch.object(socket, "create_connection", side_effect=AssertionError("Network forbidden")), patch.object(Completions, "create", return_value=completion(valid)) as sdk:
            record = LiveProvider(CONFIG, CallRecorder(folder, 3)).assess("attribute", self.evidence, "test", feedback=feedback)
            self.assertEqual(len(record["assessment"]["findings"]), 2)
            kwargs = sdk.call_args.kwargs
            wire = kwargs["response_format"]["json_schema"]["schema"]
            self.assertEqual(wire["properties"]["findings"]["required"], ["A", "B"])
            self.assertEqual(json.loads(kwargs["messages"][1]["content"]), self.evidence)
            self.assertEqual(kwargs["messages"][-2]["role"], "assistant")
            correction = json.loads(kwargs["messages"][-1]["content"])
            self.assertEqual(correction["validation_errors"][0]["code"], "candidate_coverage")

    def test_runner_saves_validation_details_and_repairs_targeted_failures(self):
        calls = []
        class RetryFixture:
            def assess(self, role, evidence, tag, feedback=None):
                order = "original" if "_original_" in tag else "reversed"
                target = (order == "original" and role == "single") or (order == "reversed" and role in ["preference", "attribute"])
                calls.append((order, role, feedback))
                record = OfflineProvider().assess(role, evidence, tag)
                if target and feedback is None:
                    raw = json.loads(record["raw"])
                    group = assessment_groups(role)[0]
                    del raw[group]["B"]
                    validate_assessment(role, raw, evidence)
                if target:
                    assert feedback["validation_errors"][0]["code"] == "candidate_coverage"
                return record
        previous = Path.cwd()
        with tempfile.TemporaryDirectory() as folder, patch.object(socket, "create_connection", side_effect=AssertionError("Network forbidden")):
            try:
                os.chdir(folder)
                write_fixture_package("data")
                path = _run("data/test", CONFIG, lambda recorder: RetryFixture(), "offline", limit=1, max_calls=240, run_id="repair-test")
                self.assertEqual(len(calls), 11)  # 8 initial role assessments, 3 bounded repairs.
                failed = read_json(path/"roles/fixture_original_single_01.json")
                self.assertEqual(failed["error_type"], "AssessmentValidationError")
                self.assertEqual(failed["validation_errors"][0]["code"], "candidate_coverage")
                self.assertNotIn("B", failed["raw"]["preferences"])
                report = read_json(path/"summary.json")
                for system in ["single", "specialists"]:
                    self.assertEqual(report["metrics"][system]["evaluation_coverage"]["correct"], 2)
                    self.assertEqual(report["metrics"][system]["diagnostic_counts"], {})
                count = len(calls)
                _run("data/test", CONFIG, lambda recorder: RetryFixture(), "offline", limit=1, max_calls=240, run_id="repair-test")
                self.assertEqual(len(calls), count)
            finally:
                os.chdir(previous)


if __name__ == "__main__":
    unittest.main()
