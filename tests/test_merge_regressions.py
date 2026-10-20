"""Merged provider, CLI, and historical-report contracts; no live inference."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from macro.cli import main
from macro.evaluation.runner import run
from macro.reporting.summary import summarize
from macro.shared.config import provider_config
from macro.shared.io import read_json, write_json, write_jsonl
from macro.shared.benchmark_policy import evaluate_case
from tests.fixtures import CONFIG, OfflineProvider, completion, fixture

ROOT = Path(__file__).resolve().parents[1]
DEEPSEEK = read_json(ROOT / 'configs/deepseek-pilot.json')


class MergeRegressionTests(unittest.TestCase):
    def test_explicit_deepseek_config_cannot_be_replaced_by_environment_provider(self):
        with patch('macro.shared.config.dotenv_values', return_value={'LLM_PROVIDER': 'deepinfra'}):
            self.assertEqual(provider_config(DEEPSEEK), DEEPSEEK)

    def test_original_development_plan_command_selects_deepseek_without_inference(self):
        output = io.StringIO()
        with patch('sys.argv', ['macro', 'plan', '--config', str(ROOT / 'configs/deepseek-pilot.json'),
                               '--cases', str(ROOT / 'data/benchmark-v2'), '--split', 'dev', '--limit', '120']), \
                patch('macro.shared.config.dotenv_values', return_value={}), \
                patch('macro.evaluation.runner.LiveProvider', side_effect=AssertionError('Inference forbidden')), \
                contextlib.redirect_stdout(output):
            main()
        result = json.loads(output.getvalue())
        self.assertEqual(result['provider'], 'deepseek')
        self.assertEqual(result['total_initial_calls'], 960)
        self.assertEqual(result['maximum_with_all_retries_and_tool_rounds'], 5760)

    def test_run_error_is_reported_once_and_never_retried_without_split(self):
        with patch('sys.argv', ['macro', 'run', '--config', str(ROOT / 'configs/deepseek-pilot.json'),
                               '--cases', 'data/benchmark-v2', '--split', 'dev',
                               '--limit', '1', '--max-calls', '48', '--allow-paid-api']), \
                patch('macro.shared.config.dotenv_values', return_value={}), \
                patch('macro.evaluation.runner.run', side_effect=ValueError('preflight failed')) as mocked, \
                contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as error:
                main()
        self.assertEqual(error.exception.code, 1)
        mocked.assert_called_once()
        self.assertEqual(mocked.call_args.args[-1], 'dev')

    def test_both_final_test_path_forms_reject_before_credentials_or_provider(self):
        for folder, split in [('data/benchmark-v2', 'test'), ('data/benchmark-v2/test', None)]:
            with self.subTest(folder=folder), \
                    patch('macro.evaluation.runner.api_key', side_effect=AssertionError('Credentials read')), \
                    patch('macro.evaluation.runner.LiveProvider', side_effect=AssertionError('Inference started')):
                with self.assertRaisesRegex(ValueError, 'Final test execution is disabled'):
                    run(folder, DEEPSEEK, limit=400, max_calls=19200, split=split)

    def test_deepinfra_keeps_its_endpoint_credentials_and_schema(self):
        from openai.resources.chat.completions import Completions
        from macro.ai_agents.agents import LiveProvider
        from macro.ai_agents.prompts import visible_case
        from macro.evaluation.runner import CallRecorder
        from macro.shared.config import DEEPINFRA_BASE_URL
        evidence = visible_case(fixture())
        raw = OfflineProvider().assess('single', evidence, 'fixture')['raw']
        with patch('macro.shared.config.dotenv_values', return_value={'LLM_PROVIDER': 'deepinfra'}):
            config = provider_config(CONFIG)
        requests = []
        def reply(client, **kwargs):
            self.assertEqual(str(client._client.base_url).rstrip('/'), DEEPINFRA_BASE_URL)
            self.assertEqual(client._client.api_key, 'deepinfra-test-key')
            requests.append(kwargs)
            response = completion(raw)
            response.model = config['model']
            return response
        with tempfile.TemporaryDirectory() as folder, \
                patch('macro.ai_agents.agents.deepinfra_api_key', return_value='deepinfra-test-key'), \
                patch('macro.ai_agents.agents.openai_api_key', side_effect=AssertionError('Wrong credential')), \
                patch('socket.socket.connect', side_effect=AssertionError('Network forbidden')), \
                patch.object(Completions, 'create', autospec=True, side_effect=reply):
            result = LiveProvider(config, CallRecorder(folder, 3)).assess('single', evidence, 'test_attempt-01')
        self.assertEqual(result['provider'], 'ag2_deepinfra')
        self.assertEqual(requests[0]['response_format']['type'], 'json_schema')
        self.assertEqual(requests[0]['max_tokens'], 3500)
        self.assertEqual(requests[0]['temperature'], 0)
        self.assertNotIn('reasoning_effort', requests[0])

    def test_historical_report_does_not_claim_guardrails_or_revalidate_old_wire_fields(self):
        case = fixture()
        ref = evaluate_case(case)
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            write_json(folder / 'manifest.json', {'mode': 'live', 'config': DEEPSEEK,
                       'policy_version': 'benchmark-policy-v1', 'split': 'dev',
                       'prompt_version': 'benchmark-v1-provider', 'schema_version': 'benchmark-assessment-v1'})
            write_jsonl(folder / 'cases.snapshot.jsonl', [case])
            write_jsonl(folder / 'references.snapshot.private.jsonl', [ref])
            (folder / 'calls').mkdir()
            for system in ('single', 'specialists'):
                write_json(folder / 'evaluations' / (system + '.json'),
                           {'case_id': case['case_id'], 'order': 'original', 'system': system,
                            'status': 'ok', 'decision': 'A', 'attributes': []})
            report = summarize(folder)
            self.assertNotIn('raw_metrics', report)
            self.assertNotIn('guardrails', report)
            self.assertEqual(report['metrics']['single']['overall_accuracy']['correct'], 1)
            self.assertIn('Overall accuracy', (folder / 'report.md').read_text())
            self.assertNotIn('Primary decisions use the shared', (folder / 'report.html').read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
