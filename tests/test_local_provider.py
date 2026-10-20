"""Ollama selection, AG2 serialization and experiment identity without inference."""
import contextlib
import io
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from macro.ai_agents.agents import LiveProvider
from macro.ai_agents.prompts import visible_case
from macro.cli import main
from macro.evaluation.runner import CallRecorder, run, _run
from macro.shared.config import provider_config, OLLAMA_BASE_URL
from macro.shared.io import read_json
from tests.fixtures import CONFIG, OfflineProvider, completion, fixture, write_fixture_package


class LocalProviderTests(unittest.TestCase):
    def local_config(self, model='test-local:8b'):
        with patch('macro.shared.config.dotenv_values', return_value={
                'IS_LOCAL_LLM': 'true', 'LOCAL_LLM_MODEL': model}):
            return provider_config(CONFIG)

    def test_selection_and_blank_values_never_fall_back_to_openai(self):
        with patch.dict(os.environ, {'IS_LOCAL_LLM': 'true', 'LOCAL_LLM_MODEL': 'environment-model'}):
            with patch('macro.shared.config.dotenv_values', return_value={'IS_LOCAL_LLM': 'false'}):
                self.assertEqual(provider_config(CONFIG)['provider'], 'openai')
            with patch('macro.shared.config.dotenv_values', return_value={}):
                self.assertEqual(provider_config(CONFIG)['model'], 'environment-model')
            for value in ('', None, ' '):
                with patch('macro.shared.config.dotenv_values', return_value={
                        'IS_LOCAL_LLM': 'true', 'LOCAL_LLM_MODEL': value}):
                    with self.assertRaisesRegex(ValueError, 'LOCAL_LLM_MODEL'):
                        provider_config(CONFIG)
        with patch('macro.shared.config.dotenv_values', return_value={'IS_LOCAL_LLM': 'tru'}):
            with self.assertRaisesRegex(ValueError, 'true or false'):
                provider_config(CONFIG)

    def test_local_overrides_model_and_pricing_without_mutating_config(self):
        config = {**CONFIG, 'pricing': {'input_per_million': 100}}
        with patch('macro.shared.config.dotenv_values', return_value={
                'IS_LOCAL_LLM': ' TRUE ', 'LOCAL_LLM_MODEL': ' local-model '}):
            actual = provider_config(config)
        self.assertEqual(actual['model'], 'local-model')
        self.assertEqual(actual['base_url'], OLLAMA_BASE_URL)
        self.assertIsNone(actual['pricing'])
        self.assertIsNone(actual['reasoning_effort'])
        self.assertEqual(config['model'], CONFIG['model'])
        self.assertIsNotNone(config['pricing'])

    def test_cli_local_run_does_not_require_paid_acknowledgement(self):
        with patch('macro.shared.config.dotenv_values', return_value={
                'IS_LOCAL_LLM': 'true', 'LOCAL_LLM_MODEL': 'test-local:8b'}), \
                patch('sys.argv', ['macro', 'run', '--limit', '1', '--max-calls', '24']), \
                patch('macro.evaluation.runner.run') as mocked:
            main()
        self.assertEqual(mocked.call_args.args[1]['provider'], 'ollama')
        self.assertEqual(mocked.call_args.args[1]['model'], 'test-local:8b')

    def test_local_run_never_reads_openai_key(self):
        with patch('macro.evaluation.runner.openai_api_key', side_effect=AssertionError('OpenAI credential read')), \
                patch('macro.evaluation.runner._run') as mocked:
            run('unused', self.local_config(), max_calls=24)
        self.assertEqual(mocked.call_args.args[1]['provider'], 'ollama')
        self.assertEqual(mocked.call_args.args[3], 'live')

    def test_ag2_local_requests_keep_schema_tools_usage_and_local_endpoint(self):
        from openai.resources.chat.completions import Completions
        evidence = visible_case(fixture())
        config = self.local_config()
        for role in ('single', 'preference', 'attribute', 'explanation'):
            raw = OfflineProvider().assess(role, evidence, 'test')['raw']
            requests = []
            def reply(client, **kwargs):
                requests.append(kwargs)
                self.assertEqual(str(client._client.base_url).rstrip('/'), OLLAMA_BASE_URL)
                self.assertEqual(client._client.api_key, 'ollama')
                if len(requests) == 1:
                    result = completion(None)
                    result.model = config['model']
                    result.choices[0].finish_reason = 'tool_calls'
                    from openai.types.chat.chat_completion_message_function_tool_call import ChatCompletionMessageFunctionToolCall
                    result.choices[0].message.tool_calls = [ChatCompletionMessageFunctionToolCall(
                        id='calculator-1', type='function', function={'name': 'calculate', 'arguments': '{"operation":"divide","values":[1,2]}'})]
                    return result
                result = completion(raw)
                result.model = config['model']
                return result
            with tempfile.TemporaryDirectory() as folder, \
                    patch('macro.ai_agents.agents.openai_api_key', side_effect=AssertionError('OpenAI credential read')), \
                    patch('autogen.oai.client.OpenAIClient.cost', side_effect=AssertionError('Hosted price lookup for local model')), \
                    patch.object(Completions, 'create', autospec=True, side_effect=reply):
                record = LiveProvider(config, CallRecorder(folder, 3)).assess(role, evidence, 'local_attempt-01')
                self.assertEqual(record['provider'], 'ag2_ollama')
                self.assertEqual(record['tool_calls'][0]['result'], {'value': .5})
                self.assertEqual(sum(read_json(p)['usage']['total_tokens'] for p in Path(folder).glob('*.json')), 300)
            self.assertEqual(len(requests), 2)
            for request in requests:
                self.assertEqual(request['model'], config['model'])
                self.assertEqual(request['max_tokens'], config['max_completion_tokens'])
                self.assertEqual(request['response_format']['type'], 'json_schema')
                self.assertIn('tools', request)
                self.assertNotIn('reasoning_effort', request)
                self.assertNotIn('max_completion_tokens', request)
                self.assertNotIn('store', request)
                self.assertNotIn('price', request)  # AG2 accounting only; not sent to Ollama.

    def test_provider_and_model_are_saved_and_cannot_change_on_resume(self):
        previous = Path.cwd()
        with tempfile.TemporaryDirectory() as folder, contextlib.redirect_stdout(io.StringIO()):
            try:
                os.chdir(folder)
                cases = write_fixture_package('data')
                config = self.local_config()
                factory = lambda recorder: OfflineProvider()
                result = _run(cases, config, factory, 'offline', run_id='local-test', max_calls=24)
                manifest = read_json(result / 'manifest.json')
                self.assertEqual(manifest['config']['provider'], 'ollama')
                summary = read_json(result / 'summary.json')
                self.assertEqual(summary['model'], config['model'])
                self.assertIn('Local Ollama', summary['costs']['note'])
                self.assertIsNone(summary['costs']['currency_estimate'])
                for changed in ({**config, 'model': 'another-model'}, {**config, 'provider': 'openai'}):
                    with self.assertRaisesRegex(ValueError, 'new run ID'):
                        _run(cases, changed, factory, 'offline', run_id='local-test', max_calls=24)
            finally:
                os.chdir(previous)


if __name__ == '__main__':
    unittest.main()
