"""Provider selection and credentials; credentials never enter saved configuration."""
import os
from pathlib import Path
from dotenv import dotenv_values

OLLAMA_BASE_URL = "http://127.0.0.1:11434/v1"
OPENAI_BASE_URL = "https://api.openai.com/v1"
DEEPINFRA_BASE_URL = "https://api.deepinfra.com/v1/openai"
DEEPINFRA_MODEL = "Qwen/Qwen3.5-9B"
DEEPINFRA_PRICING = {
    "input_per_million": 0.10, "output_per_million": 0.15,
    "currency": "USD", "date": "2026-10-19",
    "source": "https://deepinfra.com/Qwen/Qwen3.5-9B",
}


def provider_config(config):
    """Resolve the environment once so all judges in a run use the same provider."""
    values = dotenv_values(Path.cwd() / ".env")
    provider = config.get("provider") or values.get("LLM_PROVIDER", os.getenv("LLM_PROVIDER", ""))
    provider = str(provider or "").strip().lower()
    if not provider:
        # Preserve existing .env files; explicit provider selection takes precedence.
        flag = str(values.get("IS_LOCAL_LLM", os.getenv("IS_LOCAL_LLM", "false"))).strip().lower()
        if flag not in ("true", "false"):
            raise ValueError("IS_LOCAL_LLM must be true or false")
        provider = "ollama" if flag == "true" else "openai"
    if provider not in ("ollama", "openai", "deepinfra", "deepseek"):
        raise ValueError("LLM_PROVIDER must be ollama, openai, deepinfra or deepseek")
    resolved = dict(config)
    if provider == "ollama":
        model = values.get("LOCAL_LLM_MODEL", os.getenv("LOCAL_LLM_MODEL", ""))
        if not model or not model.strip():
            raise ValueError("LOCAL_LLM_MODEL is empty; set it to an installed Ollama model name from ollama list")
        resolved.update(provider="ollama", model=model.strip(), base_url=OLLAMA_BASE_URL,
                        reasoning_effort=None, temperature=0, pricing=None)
    elif provider == "deepinfra":
        model = values.get("DEEPINFRA_MODEL", os.getenv("DEEPINFRA_MODEL", DEEPINFRA_MODEL))
        if not model or not model.strip():
            raise ValueError("DEEPINFRA_MODEL is empty; use Qwen/Qwen3.5-9B")
        # Never carry OpenAI's model or prices into a hosted Qwen run.
        resolved.update(provider=provider, model=model.strip(), base_url=DEEPINFRA_BASE_URL,
                        reasoning_effort=None, temperature=0,
                        pricing=dict(DEEPINFRA_PRICING) if model.strip() == DEEPINFRA_MODEL else None)
    elif provider == "deepseek":
        if config.get("provider") != "deepseek":
            raise ValueError("DeepSeek requires an explicit DeepSeek config with model, thinking and max_tokens")
        resolved.update(provider="deepseek", base_url=config.get("base_url", "https://api.deepseek.com"))
    else:
        resolved.update(provider="openai", base_url=OPENAI_BASE_URL)
    return resolved


def openai_api_key():
    """Read the working directory's .env, retaining environment compatibility."""
    return _api_key("OPENAI_API_KEY")


def deepinfra_api_key():
    return _api_key("DEEPINFRA_API_KEY")


def _api_key(name):
    key = dotenv_values(Path.cwd() / ".env").get(name) or os.getenv(name)
    if not key or not key.strip():
        raise ValueError(f"{name} is missing; set it in the project's .env file")
    return key.strip()


def api_key(config):
    names = {"openai": "OPENAI_API_KEY", "deepseek": "DEEPSEEK_API_KEY", "deepinfra": "DEEPINFRA_API_KEY"}
    provider = config.get("provider", "openai")
    if provider not in names:
        raise ValueError(f"Unsupported provider: {provider}")
    return _api_key(names[provider])
