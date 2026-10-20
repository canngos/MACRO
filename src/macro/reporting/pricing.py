"""Estimates for recorded usage; never substitutes for a provider invoice."""
import math


def validate_pricing(pricing):
    for key in ("input_per_million", "output_per_million", "currency", "date", "source"):
        if key not in pricing:
            raise ValueError("Pricing must include rates, currency, date and official source")
    tiers = [pricing]
    if pricing.get("off_peak") is not None:
        tiers.append(pricing["off_peak"])
    for tier in tiers:
        if "cached_input_per_million" in pricing and "cached_input_per_million" not in tier:
            raise ValueError("Each pricing tier must include cached_input_per_million")
        for key in ("input_per_million", "output_per_million"):
            value = tier.get(key)
            if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
                raise ValueError(f"Pricing {key} must be a finite nonnegative number")
        cached = tier.get("cached_input_per_million", tier["input_per_million"])
        if type(cached) not in (int, float) or not math.isfinite(cached) or not 0 <= cached <= tier["input_per_million"]:
            raise ValueError("Cached input price must be nonnegative and no greater than uncached input price")
    if len(tiers) == 2:
        for key in ("input_per_million", "cached_input_per_million", "output_per_million"):
            if tiers[1].get(key, tiers[1]["input_per_million"]) > tiers[0].get(key, tiers[0]["input_per_million"]):
                raise ValueError("Off-peak rates cannot exceed peak rates")


def _tokens(value):
    return value if type(value) is int and value >= 0 else None


def cache_usage(calls):
    """Resolve cache counts without assuming absent metadata means a cache miss."""
    hit = miss = unknown = 0
    for call in calls:
        usage = call.get("usage") or {}
        total = _tokens(usage.get("prompt_tokens"))
        if total is None:
            continue
        details = usage.get("prompt_tokens_details") or {}
        cached = _tokens(usage.get("prompt_cache_hit_tokens"))
        if cached is None:
            cached = _tokens(details.get("cached_tokens"))
        uncached = _tokens(usage.get("prompt_cache_miss_tokens"))
        if cached is None and uncached is not None:
            cached = total - uncached
        if uncached is None and cached is not None:
            uncached = total - cached
        if cached is None or uncached is None or min(cached, uncached) < 0 or cached + uncached != total:
            unknown += total
        else:
            hit += cached
            miss += uncached
    return {"cache_hit_tokens": hit, "cache_miss_tokens": miss,
            "input_tokens_without_cache_breakdown": unknown}


def estimate(calls, pricing):
    if not pricing:
        return {"currency_estimate": None}
    validate_pricing(pricing)
    prompt = sum((c.get("usage") or {}).get("prompt_tokens", 0) or 0 for c in calls)
    output = sum((c.get("usage") or {}).get("completion_tokens", 0) or 0 for c in calls)
    if "cached_input_per_million" not in pricing:
        return {"currency_estimate": (prompt * pricing["input_per_million"] + output * pricing["output_per_million"]) / 1e6,
                "note": "Uncached-input estimate for known usage only; unknown calls omitted and cache discounts not applied."}
    cache = cache_usage(calls)
    hit, miss, unknown = (cache[k] for k in ("cache_hit_tokens", "cache_miss_tokens", "input_tokens_without_cache_breakdown"))

    def cost(tier, unknown_as_cached=False):
        cached = tier["cached_input_per_million"]
        unknown_rate = cached if unknown_as_cached else tier["input_per_million"]
        return (hit * cached + miss * tier["input_per_million"] + unknown * unknown_rate + output * tier["output_per_million"]) / 1e6

    peak = cost(pricing)
    off_peak = pricing.get("off_peak", pricing)
    return {**cache, "currency_estimate": peak,
            "currency_estimate_lower": cost(off_peak, unknown_as_cached=True),
            "currency_estimate_upper": peak,
            "off_peak_currency_estimate": cost(off_peak),
            "peak_currency_estimate": peak,
            "note": f"{pricing['currency']} token-cost estimates for recorded usage only, not an invoice. "
                    "currency_estimate uses peak rates; unknown cache tokens are treated as misses. "
                    "Range uses all off-peak to all peak rates and accounts for unknown cache splits. "
                    "No billing period or Chinese public holiday is inferred from request timestamps. "
                    "Calls without usage are omitted; their cost is unknown."}
