"""Provider selection and credentials; credentials never enter saved configuration."""
import os
from pathlib import Path

from dotenv import dotenv_values

OLLAMA_BASE_URL = "http://127.0.0.1:11434/v1"
OPENAI_BASE_URL = "https://api.openai.com/v1"


def provider_config(config):
    """Resolve the environment once so all judges in a run use the same provider."""
    values = dotenv_values(Path.cwd() / ".env")
    flag = values.get("IS_LOCAL_LLM", os.getenv("IS_LOCAL_LLM", "false"))
    flag = str(flag).strip().lower()
    if flag not in ("true", "false"):
        raise ValueError("IS_LOCAL_LLM must be true or false")
    resolved = dict(config)
    if flag == "true":
        model = values.get("LOCAL_LLM_MODEL", os.getenv("LOCAL_LLM_MODEL", ""))
        if not model or not model.strip():
            raise ValueError("LOCAL_LLM_MODEL is empty; set it to an installed Ollama model name from ollama list")
        resolved.update(provider="ollama", model=model.strip(), base_url=OLLAMA_BASE_URL,
                        reasoning_effort=None, temperature=0, pricing=None)
    else:
        resolved.update(provider="openai", base_url=OPENAI_BASE_URL)
    return resolved


def openai_api_key():
    """Read the working directory's .env, retaining environment compatibility."""
    key = dotenv_values(Path.cwd() / ".env").get("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")
    if not key:
        raise ValueError("OPENAI_API_KEY is missing; set it in the project's .env file")
    return key
