import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from macro.shared.config import api_key, openai_api_key


class CredentialTests(unittest.TestCase):
    def test_provider_credentials_are_isolated(self):
        for provider, name, other in [("openai", "OPENAI_API_KEY", "DEEPSEEK_API_KEY"),
                                      ("deepseek", "DEEPSEEK_API_KEY", "OPENAI_API_KEY")]:
            with self.subTest(provider=provider), tempfile.TemporaryDirectory() as folder, patch(
                "macro.shared.config.Path.cwd", return_value=Path(folder)
            ), patch.dict(os.environ, {other: "wrong-provider"}, clear=True):
                with self.assertRaisesRegex(ValueError, name):
                    api_key({"provider": provider})
                # A different provider's file credential must not be a fallback either.
                Path(folder, ".env").write_text(f"{other}=wrong-file-key\n", encoding="utf-8")
                with self.assertRaisesRegex(ValueError, name):
                    api_key({"provider": provider})
                os.environ[name] = "environment-key"
                self.assertEqual(api_key({"provider": provider}), "environment-key")
                Path(folder, ".env").write_text(f"{name}=file-key\n", encoding="utf-8")
                self.assertEqual(api_key({"provider": provider}), "file-key")
                self.assertEqual(os.environ[name], "environment-key")
                Path(folder, ".env").write_text(f"{name}=\n", encoding="utf-8")
                self.assertEqual(api_key({"provider": provider}), "environment-key")

    def test_unsupported_provider_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unsupported provider"):
            api_key({"provider": "unknown"})

    def test_dotenv_key_takes_precedence_without_mutating_environment(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, ".env").write_text('OPENAI_API_KEY="file-test-key"\n', encoding="utf-8")
            with patch("macro.shared.config.Path.cwd", return_value=Path(folder)), patch.dict(
                os.environ, {"OPENAI_API_KEY": "environment-test-key"}, clear=True
            ):
                self.assertEqual(openai_api_key(), "file-test-key")
                self.assertEqual(os.environ["OPENAI_API_KEY"], "environment-test-key")

    def test_environment_fallback_and_missing_key(self):
        with tempfile.TemporaryDirectory() as folder, patch(
            "macro.shared.config.Path.cwd", return_value=Path(folder)
        ), patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, r"\.env"):
                openai_api_key()
            os.environ["OPENAI_API_KEY"] = "environment-test-key"
            self.assertEqual(openai_api_key(), "environment-test-key")
