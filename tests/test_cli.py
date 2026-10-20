"""Command defaults and paid-execution gates; no provider requests."""
import contextlib
import io
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from macro.cli import main
from macro.evaluation.inputs import load_inputs
from macro.evaluation.runner import _run
from tests.fixtures import CONFIG

ROOT = Path(__file__).resolve().parents[1]


@patch('macro.shared.config.dotenv_values', return_value={})
class CommandTests(unittest.TestCase):
    def test_plan_defaults_to_all_120_dev_cases_without_provider_initialization(self, _dotenv):
        output = io.StringIO()
        with patch('sys.argv', ['macro', 'plan']), contextlib.redirect_stdout(output), \
                patch('macro.evaluation.runner.LiveProvider', side_effect=AssertionError('Provider initialized')):
            main()
        self.assertEqual(json.loads(output.getvalue())['total_initial_calls'], 960)

    def test_paid_command_requires_explicit_request_cap(self, _dotenv):
        with patch('sys.argv', ['macro', 'run', '--allow-paid-api']), \
                patch('macro.evaluation.runner.run') as run, contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as error:
                main()
            self.assertEqual(error.exception.code, 2)
            run.assert_not_called()

    def test_private_runner_also_rejects_missing_cap(self, _dotenv):
        with self.assertRaisesRegex(ValueError, 'explicit'):
            _run(ROOT / 'data/benchmark-v2/test', CONFIG, None, 'live')

    def test_archived_pilot_is_rejected_by_preflight(self, _dotenv):
        with self.assertRaisesRegex(ValueError, 'archival'):
            load_inputs(ROOT / 'data/pilot', None, CONFIG)


if __name__ == '__main__':
    unittest.main()
