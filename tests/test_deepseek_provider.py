"""DeepSeek adapter protocol checks through installed AG2; no service requests."""
import json
import socket
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

import httpx
from openai import APIStatusError
from openai.resources.chat.completions import Completions
from openai.types.chat import ChatCompletion
from openai.types.completion_usage import CompletionTokensDetails

from macro.ai_agents.agents import LiveProvider, llm_settings
from macro.ai_agents.prompts import visible_case
from macro.ai_agents.schemas import AssessmentValidationError
from macro.evaluation.runner import _run, CallRecorder
from macro.shared.io import read_json, write_jsonl
from macro.shared.policy import findings
from tests.fixtures import OfflineProvider
from tests.test_pilot import fixture


CONFIG = {"provider": "deepseek", "model": "deepseek-flash",
          "base_url": "https://api.deepseek.com", "thinking": "disabled",
          "max_tokens": 3500, "timeout_seconds": 120, "max_attempts": 2,
          "max_tool_rounds": 2, "pricing": None}


def completion(content=None, finish="stop", tools=None, refusal=None, reasoning=None):
    response = ChatCompletion.model_validate({
        "id": "mock", "object": "chat.completion", "created": 0,
        "model": "deepseek-returned-model",
        "choices": [{"index": 0, "finish_reason": finish, "message": {
            "role": "assistant", "content": content, "tool_calls": tools, "refusal": refusal}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150}})
    if reasoning is not None:
        response.choices[0].message.reasoning_content = reasoning
        response.usage.completion_tokens_details = CompletionTokensDetails(reasoning_tokens=20)
    return response


def tool(name="calculate", arguments='{"operation":"divide","values":[1,2]}'):
    return [{"id": "t1", "type": "function", "function": {"name": name, "arguments": arguments}}]


class DeepSeekWireTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.folder = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.stack.enter_context(patch("macro.ai_agents.agents.api_key", return_value="offline-placeholder"))
        self.stack.enter_context(patch.object(socket, "create_connection", side_effect=AssertionError("Network forbidden")))
        self.sdk = self.stack.enter_context(patch.object(Completions, "create"))
        self.evidence = visible_case(fixture())
        self.recorder = CallRecorder(self.folder / "calls", 30)

    def raw(self, role="single"):
        return OfflineProvider().assess(role, self.evidence, "fixture")["raw"]

    def assess(self, role="single", **kwargs):
        return LiveProvider(CONFIG, self.recorder).assess(role, self.evidence, "offline-check", **kwargs)

    def ledger(self):
        return [read_json(p) for p in self.recorder.folder.glob("*.json")]

    def test_json_contract_for_every_role(self):
        for role in ["single", "preference", "attribute", "explanation"]:
            with self.subTest(role=role):
                self.sdk.return_value = completion(self.raw(role))
                record = self.assess(role)
                wire = self.sdk.call_args.kwargs
                self.assertEqual(wire["response_format"], {"type": "json_object"})
                self.assertEqual(wire["max_tokens"], 3500)
                self.assertEqual(wire["extra_body"]["thinking"]["type"], "disabled")
                for field in ["store", "max_completion_tokens", "reasoning_effort"]:
                    self.assertNotIn(field, wire)
                self.assertEqual(wire["messages"][0]["content"], record["system_prompt"])
                self.assertIn("JSON Schema", record["system_prompt"])
                self.assertEqual(record["status"], "ok")
                self.assertEqual(record["provider"], "ag2_deepseek")
        for row in self.ledger():
            self.assertEqual(row["provider"], "deepseek")
            self.assertEqual(row["base_url"], CONFIG["base_url"])
            self.assertEqual(row["requested_model"], CONFIG["model"])
            self.assertEqual(row["returned_model"], "deepseek-returned-model")
            self.assertEqual(row["thinking"], "disabled")
            self.assertEqual(row["usage"]["total_tokens"], 150)

    def test_calculator_continuation_and_usage(self):
        self.sdk.side_effect = [completion(finish="tool_calls", tools=tool()), completion(self.raw())]
        record = self.assess()
        self.assertEqual(record["tool_calls"][0]["result"], {"value": .5})
        messages = self.sdk.call_args.kwargs["messages"]
        self.assertEqual(messages[-2]["tool_calls"][0]["id"], "t1")
        self.assertEqual(messages[-1]["tool_call_id"], "t1")
        self.assertEqual(json.loads(messages[-1]["content"]), {"value": .5})
        rows = self.ledger()
        self.assertEqual(len(rows), 2)
        self.assertEqual(sum(row["usage"]["total_tokens"] for row in rows), 300)
        self.assertEqual(sum(len(row.get("executed_tools", [])) for row in rows), 1)

    def test_maximum_tool_rounds(self):
        self.sdk.return_value = completion(finish="tool_calls", tools=tool())
        with self.assertRaisesRegex(ValueError, "Tool-round limit"):
            self.assess()
        self.assertEqual(self.sdk.call_count, 3)
        self.assertEqual(len(self.ledger()), 3)
        self.assertEqual(sum(len(row.get("executed_tools", [])) for row in self.ledger()), 2)

    def test_unknown_tools_and_invalid_arguments(self):
        self.sdk.return_value = completion(finish="tool_calls", tools=tool(name="unknown"))
        with self.assertRaisesRegex(ValueError, "Unexpected tool"):
            self.assess()
        for arguments in ['{', '{"values":[true]}', '[1,2]']:
            with self.subTest(arguments=arguments):
                self.sdk.side_effect = [completion(finish="tool_calls", tools=tool(arguments=arguments)), completion(self.raw())]
                record = self.assess()
                self.assertEqual(record["tool_calls"][0]["result"], {"error": "invalid calculator arguments"})

    def test_empty_malformed_and_invalid_schema_are_failures(self):
        for raw in ["", None, "{", "{}"]:
            with self.subTest(raw=raw):
                self.sdk.return_value = completion(raw)
                with self.assertRaises(AssessmentValidationError):
                    self.assess()
        self.assertEqual(len(self.ledger()), 4)

    def test_incomplete_filtered_unknown_and_refusal_are_failures(self):
        for finish, refusal in [("length", None), ("content_filter", None), ("provider_failure", None), ("stop", "refused")]:
            with self.subTest(finish=finish, refusal=refusal):
                response = completion(self.raw(), refusal=refusal)
                # SDK responses can retain provider extensions without strict validation.
                response.choices[0].finish_reason = finish
                self.sdk.return_value = response
                with self.assertRaisesRegex(ValueError, "finish_reason=" + finish):
                    self.assess()
        self.assertEqual(len(self.ledger()), 4)

    def test_failed_schema_repair_is_bounded_by_runner(self):
        invalid = json.loads(self.raw())
        del invalid["attributes"]["B"]
        self.sdk.return_value = completion(json.dumps(invalid))
        data = self.folder / "data"
        write_jsonl(data / "cases.jsonl", [fixture()])
        write_jsonl(data / "references.private.jsonl", [{"case_id": "fixture", **findings(fixture())}])
        # Keep generated experiment artifacts inside the temporary directory.
        import os
        previous = Path.cwd()
        try:
            os.chdir(self.folder)
            result = _run(data, CONFIG, lambda recorder: LiveProvider(CONFIG, recorder),
                          "offline", limit=1, run_id="repair", max_calls=100)
            rows = [read_json(p) for p in (result / "roles").glob("*.json")]
            single = [row for row in rows if row["role"] == "single"]
            self.assertEqual(len(single), 4)  # Two attempts in each order.
            self.assertTrue(all(row["status"] == "technical_failure" for row in single))
            self.assertTrue(all(row["assessment"] is None for row in single))
            self.assertEqual(self.sdk.call_count, 16)
            repair = self.sdk.call_args_list[1].kwargs["messages"][-1]
            self.assertEqual(json.loads(repair["content"])["validation_errors"][0]["code"], "candidate_coverage")
        finally:
            os.chdir(previous)

    def test_http_error_is_recorded_without_secret_text(self):
        response = httpx.Response(429, request=httpx.Request("POST", CONFIG["base_url"]))
        self.sdk.side_effect = APIStatusError("secret-provider-error", response=response, body=None)
        with self.assertRaises(APIStatusError):
            self.assess()
        row, = self.ledger()
        self.assertEqual(row["http_status"], 429)
        self.assertEqual(row["status"], "error")
        self.assertIsNone(row["usage"])
        self.assertNotIn("secret-provider-error", json.dumps(row))
        self.assertNotIn("offline-placeholder", json.dumps(row))
        self.assertEqual(self.sdk.call_count, 1)

    def test_thinking_requires_explicit_valid_mode(self):
        for thinking in [None, "invalid", True]:
            with self.subTest(thinking=thinking), self.assertRaisesRegex(ValueError, "thinking=disabled"):
                llm_settings({**CONFIG, "thinking": thinking}, "placeholder", {})


THINKING_CONFIG = {**CONFIG, "thinking": "enabled", "reasoning_effort": "high",
                   "max_tokens": 16384, "timeout_seconds": 180}


class DeepSeekThinkingTests(unittest.TestCase):
    setUp = DeepSeekWireTests.setUp
    raw = DeepSeekWireTests.raw
    ledger = DeepSeekWireTests.ledger

    def assess(self, role="single", **kwargs):
        return LiveProvider(THINKING_CONFIG, self.recorder).assess(role, self.evidence, "thinking-check", **kwargs)

    def test_every_role_sends_explicit_thinking_and_effort(self):
        for role in ["single", "preference", "attribute", "explanation"]:
            with self.subTest(role=role):
                self.sdk.return_value = completion(self.raw(role), reasoning="private-reasoning-marker")
                record = self.assess(role)
                wire = self.sdk.call_args.kwargs
                self.assertEqual(wire["extra_body"], {"thinking": {"type": "enabled"}, "reasoning_effort": "high"})
                self.assertEqual(wire["max_tokens"], 16384)
                self.assertEqual(wire["response_format"], {"type": "json_object"})
                self.assertNotIn("private-reasoning-marker", json.dumps(record))
                self.assertTrue(all(m["role"] != "assistant" for m in wire["messages"]))
        for row in self.ledger():
            self.assertEqual(row["thinking"], "enabled")
            self.assertEqual(row["reasoning_effort"], "high")
            self.assertEqual(row["usage"]["completion_tokens_details"]["reasoning_tokens"], 20)

    def test_effort_and_token_validation(self):
        for effort in ["low", "high", "max"]:
            settings = llm_settings({**THINKING_CONFIG, "reasoning_effort": effort}, "fake", {})
            self.assertEqual(settings["extra_body"]["reasoning_effort"], effort)
        for effort in [None, "medium", "invalid"]:
            with self.assertRaisesRegex(ValueError, "reasoning_effort"):
                llm_settings({**THINKING_CONFIG, "reasoning_effort": effort}, "fake", {})
        for tokens in [True, 0, -1, 1.5]:
            with self.assertRaisesRegex(ValueError, "max_tokens"):
                llm_settings({**THINKING_CONFIG, "max_tokens": tokens}, "fake", {})

    def test_multiple_tool_turns_preserve_all_assistant_reasoning(self):
        second_tools = tool()
        second_tools[0]["id"] = "t2"
        self.sdk.side_effect = [completion(finish="tool_calls", tools=tool(), reasoning="marker-one"),
                                completion(finish="tool_calls", tools=second_tools, reasoning="marker-two"),
                                completion(self.raw(), reasoning="marker-final")]
        record = self.assess()
        wire = self.sdk.call_args.kwargs["messages"]
        assistants = [m for m in wire if m["role"] == "assistant"]
        self.assertEqual([m["reasoning_content"] for m in assistants], ["marker-one", "marker-two"])
        self.assertEqual([m["tool_call_id"] for m in wire if m["role"] == "tool"], ["t1", "t2"])
        self.assertEqual(len(record["tool_calls"]), 2)
        self.assertEqual(sum(r["usage"]["total_tokens"] for r in self.ledger()), 450)
        self.assertNotIn("marker-final", record["raw"])

    def test_tool_and_final_reasoning_survive_json_roundtrip_repair(self):
        self.sdk.side_effect = [completion(finish="tool_calls", tools=tool(), reasoning="tool-marker"),
                                completion("{}", reasoning="invalid-final-marker")]
        with self.assertRaises(AssessmentValidationError) as caught:
            self.assess()
        exc = caught.exception
        feedback = json.loads(json.dumps({"validation_errors": exc.errors, "raw": exc.raw,
                                          "repair_context": exc.repair_context}))
        self.sdk.side_effect = None
        self.sdk.return_value = completion(self.raw(), reasoning="corrected-marker")
        self.assess(feedback=feedback)
        wire = self.sdk.call_args.kwargs["messages"]
        self.assertEqual([m["reasoning_content"] for m in wire if m["role"] == "assistant"],
                         ["tool-marker", "invalid-final-marker"])
        self.assertEqual(sum(m["role"] == "tool" for m in wire), 1)
        self.assertEqual(sum(len(r.get("executed_tools", [])) for r in self.ledger()), 1)
        with self.assertRaisesRegex(ValueError, "matching saved"):
            self.assess("attribute", feedback=feedback)
        changed = json.loads(json.dumps(self.evidence))
        changed["profile"]["max_duration_minutes"] += 1
        with self.assertRaisesRegex(ValueError, "matching saved"):
            LiveProvider(THINKING_CONFIG, self.recorder).assess("single", changed, "other-case", feedback=feedback)

    def test_missing_reasoning_fails_before_tool_execution(self):
        self.sdk.return_value = completion(finish="tool_calls", tools=tool())
        with self.assertRaisesRegex(ValueError, "missing reasoning_content"):
            self.assess()
        self.assertEqual(self.sdk.call_count, 1)
        self.assertFalse(any(r.get("executed_tools") for r in self.ledger()))

    def test_empty_reasoning_is_retained_and_truncation_stays_failure(self):
        self.sdk.side_effect = [completion(finish="tool_calls", tools=tool(), reasoning=""),
                                completion(self.raw(), reasoning="")]
        self.assess()
        self.assertEqual(self.sdk.call_args.kwargs["messages"][-2]["reasoning_content"], "")
        self.sdk.side_effect = None
        self.sdk.return_value = completion("{}", finish="length", reasoning="partial")
        with self.assertRaisesRegex(ValueError, "finish_reason=length"):
            self.assess()

    def test_runner_persists_repair_history_and_reports_usage_without_reasoning(self):
        data = self.folder / "data"
        write_jsonl(data / "cases.jsonl", [fixture()])
        write_jsonl(data / "references.private.jsonl", [{"case_id": "fixture", **findings(fixture())}])
        count = 0
        def reply(**kwargs):
            nonlocal count
            count += 1
            if count == 1:
                return completion("{}", reasoning="saved-private-marker")
            role = next(r for r in ["preference", "attribute", "explanation"]
                        if f"independent {r} specialist" in kwargs["messages"][0]["content"]) if "structured single judge" not in kwargs["messages"][0]["content"] else "single"
            return completion(self.raw(role), reasoning="final-private-marker")
        self.sdk.side_effect = reply
        import os
        previous = Path.cwd()
        try:
            os.chdir(self.folder)
            out = _run(data, THINKING_CONFIG, lambda recorder: LiveProvider(THINKING_CONFIG, recorder),
                       "offline", limit=1, run_id="thinking", max_calls=100)
            records = [read_json(p) for p in (out / "roles").glob("*.json")]
            failed = next(r for r in records if r["status"] != "ok")
            self.assertEqual(failed["repair_context"]["messages"][-1]["reasoning_content"], "saved-private-marker")
            self.assertEqual(count, 9)
            report = (out / "report.html").read_text(encoding="utf-8")
            self.assertNotIn("saved-private-marker", report)
            self.assertNotIn("final-private-marker", report)
            summary = read_json(out / "summary.json")
            self.assertEqual(summary["costs"]["reported_reasoning_tokens"], 180)
            self.assertEqual(summary["costs"]["calls_with_reasoning_token_breakdown"], 9)
            self.assertEqual(summary["costs"]["completion_tokens"], 450)  # Reasoning not added twice.
        finally:
            os.chdir(previous)
