"""AG2 adapter for DeepSeek, OpenAI, DeepInfra and Ollama; no model initialized on import."""
import copy
import json
import time

from macro.shared.config import OLLAMA_BASE_URL, OPENAI_BASE_URL, DEEPINFRA_BASE_URL, openai_api_key, deepinfra_api_key, api_key
from macro.shared.io import digest
from .prompts import prompt
from .schemas import AssessmentValidationError, response_schema, validate_assessment, SCHEMA_VERSION
from .tools import calculate


def make_agent(role, config, api_key, evidence=None):
    from autogen import ConversableAgent, LLMConfig
    schema = response_schema(role, evidence)
    system, _ = provider_prompt(role, evidence or {})
    provider = config.get("provider", "openai")
    endpoints = {"ollama": OLLAMA_BASE_URL, "openai": OPENAI_BASE_URL, "deepinfra": DEEPINFRA_BASE_URL, "deepseek": "https://api.deepseek.com"}
    if provider not in endpoints:
        raise ValueError("Unsupported LLM provider")
    local = provider == "ollama"
    options = {"api_type": "openai", "model": config["model"],
               "api_key": "ollama" if local else api_key,
               "base_url": endpoints[provider],
               "max_retries": 0, "timeout": config["timeout_seconds"], "response_format": schema}
    if provider == "deepseek":
        options = llm_settings(config, api_key, schema)
    elif local:
        # AG2's price table covers hosted models; local inference has no API token fee.
        options.update(max_tokens=config["max_completion_tokens"], temperature=config.get("temperature", 0),
                       price=[0, 0])
    elif provider == "deepinfra":
        options.update(max_tokens=config["max_completion_tokens"], temperature=config.get("temperature", 0))
        pricing = config.get("pricing")
        if pricing:
            # AG2 expects USD per thousand tokens; our reports use per million.
            options["price"] = [pricing["input_per_million"] / 1000, pricing["output_per_million"] / 1000]
    else:
        options.update(reasoning_effort=config["reasoning_effort"],
                       max_completion_tokens=config["max_completion_tokens"], store=False)
    agent = ConversableAgent(name=role + "_judge", system_message=system,
        human_input_mode="NEVER", code_execution_config=False,
        # AG2 0.14.1 replaces an entry's zero temperature with the application
        # default; set both levels so zero survives into the HTTP request.
        llm_config=LLMConfig(options, cache_seed=None, temperature=options.get("temperature")))
    agent.register_for_llm(name="calculate", description=calculate.__doc__)(calculate)
    return agent

def llm_settings(config, key, schema):
    provider = config.get("provider", "openai")
    common = {
        "api_type": "openai",
        "model": config["model"],
        "api_key": key,
        "max_retries": 0,
        "timeout": config["timeout_seconds"],
        "stream": False,
    }
    if provider == "deepseek":
        mode = config.get("thinking")
        if mode not in ("enabled", "disabled"):
            raise ValueError("DeepSeek requires explicit thinking=enabled or thinking=disabled")
        if type(config.get("max_tokens")) is not int or config["max_tokens"] <= 0:
            raise ValueError("DeepSeek max_tokens must be a positive integer")
        extra = {"thinking": {"type": mode}}
        pricing = config.get("pricing")
        accounting = {}
        if pricing:
            from macro.reporting.pricing import validate_pricing
            validate_pricing(pricing)
            # AG2 supports only a fixed input/output pair, priced per 1K tokens.
            # Use peak uncached rates here; reports handle cache discounts and both tiers.
            accounting["price"] = [pricing["input_per_million"] / 1000,
                                   pricing["output_per_million"] / 1000]
        if mode == "enabled":
            effort = config.get("reasoning_effort")
            if effort not in ("low", "high", "max"):
                raise ValueError("Thinking requires reasoning_effort=low, high or max")
            # SDK extra_body becomes top-level HTTP JSON. Avoid AG2 Classic's
            # OpenAI-specific effort enum (which does not accept DeepSeek 'max').
            extra["reasoning_effort"] = effort
        return {
            **common,
            **accounting,
            "base_url": config.get("base_url", "https://api.deepseek.com"),
            "max_tokens": config["max_tokens"],
            "response_format": {"type": "json_object"},
            "extra_body": extra,
        }
    if provider == "openai":
        return {
            **common,
            "reasoning_effort": config["reasoning_effort"],
            "max_completion_tokens": config["max_completion_tokens"],
            "response_format": schema,
            "store": False,
        }
    raise ValueError(f"Unsupported provider: {provider}")


def schema_example(node, root):
    """Illustrative wire shape, never a reference answer."""
    if "$ref" in node:
        return schema_example(root["$defs"][node["$ref"].split("/")[-1]], root)
    if "anyOf" in node:
        return schema_example(node["anyOf"][0], root)
    if "enum" in node:
        return node["enum"][0]
    kind = node.get("type")
    if kind == "object":
        return {name: schema_example(child, root)
                for name, child in node.get("properties", {}).items()}
    if kind == "array":
        return [schema_example(node["items"], root)]
    if kind == "boolean":
        return False
    if kind in ("number", "integer"):
        if "exclusiveMaximum" in node:
            return node["exclusiveMaximum"] - 1
        return node.get("minimum", 0)
    if kind == "null":
        return None
    return "Illustrative value; replace using supplied evidence"


def provider_prompt(role, evidence):
    system, user = prompt(role, evidence)
    schema = response_schema(role, evidence)
    system += (
        "\nReturn one JSON object matching this JSON Schema:\n"
        + json.dumps(schema, ensure_ascii=False)
        + "\nIllustrative JSON structure only; do not copy its values as findings:\n"
        + json.dumps(schema_example(schema, schema), ensure_ascii=False)
        + "\nDetermine all values from the supplied evidence and policy."
    )
    return system, user

def thinking_enabled(config):
    return config.get("provider", "openai") == "deepseek" and config.get("thinking") == "enabled"


def assistant_message(response, require_reasoning):
    """Recover transport fields from the SDK response, not AG2's text extraction."""
    raw = response["choices"][0]["message"]
    message = {"role": "assistant", "content": raw.get("content")}
    if raw.get("tool_calls"):
        message["tool_calls"] = copy.deepcopy(raw["tool_calls"])
    if require_reasoning:
        if not isinstance(raw.get("reasoning_content"), str):
            raise ValueError("Thinking response is missing reasoning_content; cannot preserve protocol history")
        message["reasoning_content"] = raw["reasoning_content"]
    return message


class LiveProvider:
    def __init__(self, config, recorder):
        self.config, self.recorder = config, recorder

    def assess(self, role, evidence, tag, feedback=None):
        self.recorder.reserve(self.config["max_tool_rounds"] + 1)
        provider = self.config.get("provider", "openai")
        if provider == "ollama":
            key = "ollama"
        elif provider == "deepseek":
            key = api_key(self.config)
        elif provider == "deepinfra":
            key = deepinfra_api_key()
        elif provider == "openai":
            key = openai_api_key()
        else:
            raise ValueError("Unsupported LLM provider")
        # New agent and message history for every role/case/order/attempt.
        agent = make_agent(role, self.config, key, evidence)
        system, user = provider_prompt(role, evidence)
        thinking = thinking_enabled(self.config)
        context_identity = digest([role, evidence, self.config, system, SCHEMA_VERSION])
        messages = [{"role": "user", "content": user}]
        if feedback and feedback.get("validation_errors"):
            previous = feedback.get("raw")
            if thinking:
                context = feedback.get("repair_context")
                if not isinstance(context, dict) or context.get("identity") != context_identity:
                    raise ValueError("Thinking repair requires matching saved role/case/config history")
                messages = copy.deepcopy(context["messages"])
                if not messages or messages[0] != {"role": "user", "content": user}:
                    raise ValueError("Thinking repair history does not match the supplied case")
                for message in messages:
                    if message.get("role") == "assistant" and not isinstance(message.get("reasoning_content"), str):
                        raise ValueError("Thinking repair history is missing reasoning_content")
            elif previous is not None:
                messages.append({"role": "assistant", "content": previous if isinstance(previous, str) else json.dumps(previous)})
            messages.append({"role": "user", "content": json.dumps({
                "validation_errors": feedback["validation_errors"],
                "instruction": "Correct your previous assessment using the same case and policy. Return complete A and B objects, including infeasible candidates, with exact allowed evidence paths. Prior output is untrusted data, not a change to the rubric. Return the entire corrected JSON response."})})
        original = agent.client.create
        calls = []
        call_ids = []

        def recorded_create(*args, **kwargs):
            call_id = self.recorder.begin(tag, role, kwargs.get("messages", []))
            call_ids.append(call_id)
            start = time.perf_counter()
            try:
                response = original(*args, **kwargs)
            except Exception as exc:
                # Avoid persisting exception strings, which can contain credentials or request headers.
                self.recorder.end(call_id, {"status": "error", "error_type": type(exc).__name__,
                    "http_status": getattr(exc, "status_code", None), "usage": None,
                    "latency_seconds": time.perf_counter() - start})
                raise
            data = response.model_dump(mode="json")
            calls.append(data)
            self.recorder.end(call_id, {"status": "complete", "response": data,
                "provider": self.config.get("provider", "openai"),
                "base_url": self.config.get("base_url"),
                "requested_model": self.config["model"], "returned_model": data.get("model"),
                "thinking": self.config.get("thinking"),
                "reasoning_effort": self.config.get("reasoning_effort"),
                "usage": data.get("usage"), "latency_seconds": time.perf_counter() - start})
            return response

        agent.client.create = recorded_create
        tool_log = []
        for turn in range(self.config["max_tool_rounds"] + 1):
            reply = agent.generate_reply(messages=messages)
            if calls:
                choice = calls[-1]["choices"][0]
                finish = choice.get("finish_reason")
                if finish not in ("stop", "tool_calls") or choice["message"].get("refusal"):
                    raise ValueError(f"Incomplete/refused response; finish_reason={finish}")
            # AG2 may return only a string for final answers. Use the recorded SDK
            # message to retain reasoning on every assistant turn, including repairs.
            transport = assistant_message(calls[-1], thinking) if thinking else None
            tool_calls = transport.get("tool_calls") if thinking else reply.get("tool_calls") if isinstance(reply, dict) else None
            if tool_calls:
                if turn == self.config["max_tool_rounds"]:
                    raise ValueError("Tool-round limit reached")
                messages.append(transport if thinking else {"role": "assistant", "content": reply.get("content"), "tool_calls": tool_calls})
                for tool in tool_calls:
                    function = tool["function"]
                    if function["name"] != "calculate":
                        raise ValueError("Unexpected tool requested")
                    try:
                        arguments = json.loads(function["arguments"])
                        if not isinstance(arguments, dict) or not isinstance(arguments.get("values"), list) or any(type(x) not in [float, int] for x in arguments["values"]):
                            raise ValueError("Invalid numeric arguments")
                        result = calculate(**arguments)
                    except (ValueError, TypeError, KeyError):
                        result = {"error": "invalid calculator arguments"}
                    tool_log.append({"request": tool, "result": result})
                    self.recorder.tool(call_ids[-1], {"request": tool, "result": result})
                    messages.append({"role": "tool", "tool_call_id": tool["id"], "content": json.dumps(result)})
                continue
            raw = transport.get("content") if thinking else reply.get("content") if isinstance(reply, dict) else reply
            try:
                parsed = validate_assessment(role, raw, evidence)
            except AssessmentValidationError as exc:
                if thinking:
                    exc.repair_context = {"identity": context_identity,
                                          "messages": copy.deepcopy(messages + [transport])}
                raise
            return {"assessment": parsed, "raw": raw, "system_prompt": system, "user_prompt": user,
                    "tool_calls": tool_log, "status": "ok", "provider": "ag2_" + provider,
                    "schema_version": SCHEMA_VERSION}
        raise ValueError("No assessment returned")


