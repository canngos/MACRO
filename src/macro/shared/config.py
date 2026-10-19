"""Runtime credentials; never include key values in logs or errors."""
import os
from pathlib import Path
from dotenv import dotenv_values


def api_key(config):
    provider = config.get("provider", "openai")
    names = {"openai": "OPENAI_API_KEY", "deepseek": "DEEPSEEK_API_KEY"}
    if provider not in names:
        raise ValueError(f"Unsupported provider: {provider}")
    name = names[provider]
    value = dotenv_values(Path.cwd() / ".env").get(name) or os.getenv(name)
    if not value:
        raise ValueError(f"{name} is missing; set it in the project's .env file")
    return value


def openai_api_key():
    # Compatibility with historical callers/tests; new runtime calls pass config.
    return api_key({"provider": "openai"})