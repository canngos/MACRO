"""Offline base-case generation and grouped development/final-test assignment."""
import argparse
import copy
import json
import random
from collections import Counter
from pathlib import Path
from macro.shared.io import artifact_matches

from macro.shared.benchmark_policy import GROUPS, POLICY_VERSION, evaluate_case, validate_recipe
from macro.shared.io import digest, file_hash, read_json, read_jsonl, write_json, write_jsonl

GENERATOR_VERSION = "benchmark-generator-v2"
STRATA = frozenset(["control_tie", "both_violate", "constraint_ingredient",
                   "constraint_duration_near", "constraint_duration_clear", "dominance_near",
                   "dominance_clear", "tradeoff_resolved", "tradeoff_unresolved"])


def profile_identity(profile):
    p = copy.deepcopy(profile)
    for field in ["preferred_ingredients", "excluded_ingredients", "objectives"]:
        p[field].sort()
    return digest(p)


def request(profile):
    priority = ("No priority ordering is specified." if profile["priorities"] is None else
                "Priority, highest first: " + " > ".join(profile["priorities"]) + ".")
    limit = profile["hard_max_duration_minutes"]
    return ("Compare the two fixed recipe recommendations. Preferred ingredient groups: " +
            ", ".join(profile["preferred_ingredients"]) + ". Excluded ingredient groups: " +
            (", ".join(profile["excluded_ingredients"]) or "none") + ". " +
            ("No hard duration limit. " if limit is None else f"Hard maximum duration: {limit:g} minutes, inclusive. ") +
            "Active objectives: " + ", ".join(profile["objectives"]) + ". " + priority +
            " Preference means the fraction of preferred groups present; higher FSA is preferred; speed, if active, means shorter duration. "
            "Use documented ingredient groups only; no hidden composition or dietary requirements are asserted.")


def factual_explanation(recipe):
    return (f"Duration: {recipe['duration_minutes']:g} minutes. Documented ingredient groups: " +
            ", ".join(recipe["canonical_ingredients"]) +
            f". Normalized HUMMUS FSA proxy: {recipe['nutrition_score']:g}; higher is preferred. "
            "This is a dataset proxy, not a health outcome.")


def make_case(a, b, stratum, rng):
    pool = [a, b]
    union = sorted(set(a["canonical_ingredients"]) | set(b["canonical_ingredients"]))
    excluded = []
    if stratum == "constraint_ingredient":
        difference = sorted(set(a["canonical_ingredients"]) ^ set(b["canonical_ingredients"]))
        if not difference:
            return None
        excluded = [rng.choice(difference)]
    choices = sorted(set(union) - set(excluded))
    if not choices:
        return None
    preferred = sorted(rng.sample(choices, rng.randint(1, min(3, len(choices)))))
    objectives = ["preference", "nutrition"]
    # Equal-score controls are intentionally two-objective controls; elsewhere both
    # two- and three-objective cases are generated, with independent objective choices.
    if stratum != "control_tie" and rng.random() < .5:
        objectives.append("speed")
    priorities = rng.sample(objectives, len(objectives)) if rng.random() < .5 else None
    if stratum == "tradeoff_resolved":
        priorities = rng.sample(objectives, len(objectives))
    elif stratum == "tradeoff_unresolved":
        priorities = None
    durations = [r["duration_minutes"] for r in pool]
    limit = max(durations) if rng.random() < .5 else None
    if stratum.startswith("constraint_duration"):
        gap = abs(durations[0] - durations[1])
        if stratum.endswith("near") and not 0 < gap <= 5:
            return None
        if stratum.endswith("clear") and gap < 15:
            return None
        limit = min(durations)
    elif stratum == "constraint_ingredient":
        limit = max(durations)
    elif stratum == "both_violate":
        if min(durations) <= 1:
            return None
        limit = max(1, int(min(durations) / 2))
    profile = {"preferred_ingredients": preferred, "excluded_ingredients": excluded,
               "hard_max_duration_minutes": limit, "objectives": objectives, "priorities": priorities}
    recommendations = {slot: {"recipe_id": r["id"], "explanation": factual_explanation(r)}
                       for slot, r in zip(["A", "B"], pool)}
    case = {"case_id": "case-" + digest([profile_identity(profile), sorted(r["id"] for r in pool)])[:20],
            "profile": profile, "request": request(profile),
            "candidate_pool": pool, "recommendations": recommendations}
    reference = evaluate_case(case)
    target = ("constraint" if stratum.startswith("constraint_") else "dominance" if stratum.startswith("dominance_")
              else "tradeoff" if stratum.startswith("tradeoff_") else stratum)
    if reference["case_type"] != target:
        return None
    if stratum == "dominance_near":
        if not 0 < abs(a["nutrition_score"] - b["nutrition_score"]) <= .125:
            return None
        if abs(reference["candidates"]["A"]["objective_scores"]["preference"] -
               reference["candidates"]["B"]["objective_scores"]["preference"]) > .5:
            return None
        if "speed" in objectives and abs(durations[0] - durations[1]) > 5:
            return None
    elif stratum == "dominance_clear" and abs(a["nutrition_score"] - b["nutrition_score"]) < .25:
        return None
    return case


def split_summary(cases, references):
    return {"base_cases": len(cases), "strata": dict(Counter(r["stratum"] for r in references)),
            "case_types": dict(Counter(r["case_type"] for r in references)),
            "reference_verdicts": dict(Counter(r["verdict"] for r in references)),
            "active_objectives": dict(Counter("+".join(c["profile"]["objectives"]) for c in cases)),
            "recipes": len({r["id"] for c in cases for r in c["candidate_pool"]})}


def validate(cases_by_split, references_by_split, config):
    recipe_sets, profile_sets, case_sets = {}, {}, {}
    for split in ["dev", "test"]:
        cases, refs = cases_by_split[split], references_by_split[split]
        expected = sum(counts[split] for counts in config["strata"].values())
        if len(cases) != len(refs) or len(cases) != expected:
            raise ValueError("Split count mismatch")
        refmap = {r["case_id"]: r for r in refs}
        case_sets[split] = {c["case_id"] for c in cases}
        if len(refmap) != len(refs) or len(case_sets[split]) != len(cases) or set(refmap) != case_sets[split]:
            raise ValueError("Missing or duplicate case/reference IDs")
        observed = Counter(r["stratum"] for r in refs)
        if observed != Counter({k: v[split] for k, v in config["strata"].items() if v[split]}):
            raise ValueError("Stratum count mismatch")
        for c in cases:
            actual = evaluate_case(c)
            r = refmap[c["case_id"]]
            if any(actual[key] != r[key] for key in actual):
                raise ValueError("Reference does not match executable policy")
            if r["profile_id"] != profile_identity(c["profile"]):
                raise ValueError("Profile ID mismatch")
            if c["request"] != request(c["profile"]):
                raise ValueError("Request does not match structured profile")
            for slot in ["A", "B"]:
                recipe = next(x for x in c["candidate_pool"] if x["id"] == c["recommendations"][slot]["recipe_id"])
                if c["recommendations"][slot]["explanation"] != factual_explanation(recipe):
                    raise ValueError("Factual explanation does not match recipe")
            swapped = copy.deepcopy(c)
            swapped["recommendations"] = {"A": c["recommendations"]["B"], "B": c["recommendations"]["A"]}
            swapped_verdict = evaluate_case(swapped)["verdict"]
            if swapped_verdict != {"A": "B", "B": "A"}.get(actual["verdict"], actual["verdict"]):
                raise ValueError("Reference is not order-equivariant")
        ids = [r["id"] for c in cases for r in c["candidate_pool"]]
        profile_ids = [profile_identity(c["profile"]) for c in cases]
        if len(set(ids)) != len(ids) or len(set(profile_ids)) != len(profile_ids):
            raise ValueError("Recipe or profile reused within a split")
        recipe_sets[split], profile_sets[split] = set(ids), set(profile_ids)
    for sets in [recipe_sets, profile_sets, case_sets]:
        if sets["dev"] & sets["test"]:
            raise ValueError("Development/test overlap detected")
    return {"policy_labels_recomputed": True, "order_swap_reference_checks": True,
            "factual_template_checks": True, "recipe_overlap": 0, "profile_overlap": 0,
            "case_overlap": 0, "manual_review": "pending",
            "explanation_length_leakage_check": "pending", "surface_classifier_check": "pending"}


def generate(subset, out, config, pilot=None):
    out, subset = Path(out), Path(subset)
    if out.exists():
        raise ValueError("Output directory exists; preserve it and use a new version")
    if config["policy_version"] != POLICY_VERSION or set(config["strata"]) != STRATA:
        raise ValueError("Unknown policy version or strata")
    for counts in config["strata"].values():
        if set(counts) != {"dev", "test"} or any(type(n) is not int or n < 0 for n in counts.values()):
            raise ValueError("Each stratum requires nonnegative integer dev/test counts")
    if type(config["max_attempts_per_case"]) is not int or config["max_attempts_per_case"] <= 0:
        raise ValueError("max_attempts_per_case must be positive")
    source = subset / "recipes.jsonl"
    source_hash = file_hash(source)
    audit = read_json(subset / "audit.json")
    if not artifact_matches(source, audit["recipes_sha256"], legacy_newlines=audit.get("schema_version") == "dataset-v1"):
        raise ValueError("Subset hash mismatch")
    dataset_config = read_json(subset / "config.json")
    if digest(dataset_config) != audit["config_sha256"]:
        raise ValueError("Subset configuration hash mismatch")
    if set(dataset_config["normalization"]["aliases"]) != set(GROUPS):
        raise ValueError("Subset vocabulary differs from policy")
    excluded = set()
    pilot_hash = None
    if config["exclude_pilot_recipes"]:
        if pilot is None:
            raise ValueError("Supply pilot cases to exclude previously inspected recipes")
        pilot_hash = file_hash(pilot)
        excluded = {r["id"] for c in read_jsonl(pilot) for r in c["candidate_pool"]}
    records = read_jsonl(source)
    if len({r["id"] for r in records}) != len(records):
        raise ValueError("Duplicate source recipe IDs")
    source_map = {}
    available = []
    for r in records:
        validate_recipe(r)
        if r["id"] in excluded:
            continue
        neutral = "recipe-" + digest([config["version"], r["id"]])[:20]
        source_map[neutral] = {"source_recipe_id": r["id"], "source_record_number": r["source_record_number"],
                               "source_url": r["source_url"], "source_title": r["title"]}
        available.append({"id": neutral, **{k: r[k] for k in ["duration_minutes", "nutrition_score", "nutrition_metric",
                                                         "ingredient_names", "raw_ingredient_names", "canonical_ingredients"]}})
    total = sum(sum(v.values()) for v in config["strata"].values())
    if len(available) < 2 * total:
        raise ValueError("Not enough recipes for a benchmark without recipe reuse")
    rng = random.Random(config["seed"])
    layout_rng = random.Random(config["seed"] + 1)
    cases_by_split, refs_by_split = {"dev": [], "test": []}, {"dev": [], "test": []}
    profiles = set()
    attempts, rejections = Counter(), Counter()
    for stratum, counts in config["strata"].items():
        accepted = []
        for _ in range(sum(counts.values())):
            for attempt in range(config["max_attempts_per_case"]):
                attempts[stratum] += 1
                a, b = rng.sample(available, 2)
                candidate = make_case(a, b, stratum, rng)
                if candidate is None:
                    rejections[stratum + ":relationship_or_margin"] += 1
                    continue
                pid = profile_identity(candidate["profile"])
                if pid in profiles:
                    rejections[stratum + ":duplicate_profile"] += 1
                    continue
                profiles.add(pid)
                used = {a["id"], b["id"]}
                available = [r for r in available if r["id"] not in used]
                accepted.append(candidate)
                break
            else:
                raise ValueError(f"Bounded generation failed for {stratum}; no rules relaxed, no files written")
        layout_rng.shuffle(accepted)
        for split, selected in [("dev", accepted[:counts["dev"]]), ("test", accepted[counts["dev"]:])]:
            # Balance A/B winners within each stratum/split, randomizing assignment.
            # Pool positions are independently shuffled and never reveal the label.
            winners = ["A", "B"] * (len(selected) // 2)
            if len(selected) % 2:
                winners.append(layout_rng.choice(["A", "B"]))
            layout_rng.shuffle(winners)
            for c, desired in zip(selected, winners):
                current = evaluate_case(c)["verdict"]
                if current in ["A", "B"] and current != desired:
                    c["recommendations"] = {"A": c["recommendations"]["B"], "B": c["recommendations"]["A"]}
                layout_rng.shuffle(c["candidate_pool"])
                reference = evaluate_case(c)
                refs_by_split[split].append({**reference, "stratum": stratum,
                                            "profile_id": profile_identity(c["profile"])})
                cases_by_split[split].append(c)
    for split in ["dev", "test"]:
        layout_rng.shuffle(cases_by_split[split])
        layout_rng.shuffle(refs_by_split[split])
    validation = validate(cases_by_split, refs_by_split, config)
    # All checks precede publication. Refuse pre-existing output paths; no historical
    # pilot, source subset or saved experiment is overwritten.
    out.mkdir(parents=True, exist_ok=False)
    hashes = {}
    for split in ["dev", "test"]:
        write_jsonl(out / split / "cases.jsonl", cases_by_split[split])
        write_jsonl(out / "private" / (split + ".references.jsonl"), refs_by_split[split])
        for relative in [f"{split}/cases.jsonl", f"private/{split}.references.jsonl"]:
            hashes[relative] = file_hash(out / relative)
    used_ids = {r["id"] for split in cases_by_split.values() for c in split for r in c["candidate_pool"]}
    write_json(out / "private" / "source_map.json", {k: source_map[k] for k in sorted(used_ids)})
    hashes["private/source_map.json"] = file_hash(out / "private/source_map.json")
    write_json(out / "config.json", config)
    manifest = {"version": config["version"], "generator_version": GENERATOR_VERSION,
                "policy_version": POLICY_VERSION, "status": "draft_not_frozen",
                "subset_sha256": source_hash, "subset_source_sha256": audit["source_sha256"],
                "subset_manual_review": audit["manual_review_status"], "pilot_cases_sha256": pilot_hash,
                "excluded_pilot_recipe_ids": sorted(excluded), "config_sha256": digest(config),
                "generator_code_sha256": file_hash(__file__),
                "policy_code_sha256": file_hash(Path(__file__).parents[1] / "shared" / "benchmark_policy.py"),
                "hashes": hashes, "selection_attempts": dict(attempts), "rejections": dict(rejections),
                "splits": {s: split_summary(cases_by_split[s], refs_by_split[s]) for s in ["dev", "test"]},
                "validation": validation, "variants": "concise factual base only; explanation variants outside RQ1/RQ2 scope",
                "split_inheritance": "All future variants and A/B orders inherit the base case split",
                "execution": "No LLM calls; evaluate with the matching benchmark judge configuration"}
    write_json(out / "manifest.json", manifest)
    write_json(out / "validation.json", validation)
    lines = ["# Draft development and final-evaluation benchmark", "",
             f"{len(cases_by_split['dev'])} development cases and {len(cases_by_split['test'])} final test cases. Counts are configured independently.", "",
             "| Stratum | Development | Final test |", "|---|---:|---:|"]
    for stratum, counts in config["strata"].items():
        lines.append(f"| {stratum} | {counts['dev']} | {counts['test']} |")
    lines += ["", "## Files and boundaries", "",
              "- dev/cases.jsonl and test/cases.jsonl are public judge inputs. Do not send the private directory or manifest to judges.",
              "- private/*.references.jsonl are deterministic gold labels; private/source_map.json maps neutral recipe IDs to source evidence.",
              "- No recipe is reused across any base cases. Exact semantic profiles and recipes are disjoint between development and test.",
              "- Previously inspected pilot recipe IDs are excluded when configured. Review of source data is separate from inspecting test judge results.",
              "- Every case has a factual template only. Future explanation variants and order swaps must inherit its split; they are not additional independent cases.",
              "- Profile and recipe fields contain all evidence required by benchmark-policy-v1. Unknown dietary/hidden composition requirements are excluded.",
              "- This is a deliberately stratified diagnostic benchmark, not a representative sample of natural user traffic.",
              "- No LLM requests or model results were generated. References were checked against the deterministic policy in both orders.",
              "- Pending: source/manual review and length/surface leakage checks. Human case review remains blind to LLM judgments. Explanation variants are outside RQ1/RQ2 scope.",
              "- Hashes establish artifact identity, not a completed test freeze. Do not claim final evaluation until outstanding checks pass and configuration is frozen.", ""]
    (out / "README.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"splits": manifest["splits"], "validation": validation}), flush=True)
    return manifest


def verify_saved(out):
    out = Path(out)
    manifest = read_json(out / "manifest.json")
    config = read_json(out / "config.json")
    if digest(config) != manifest["config_sha256"]:
        raise ValueError("Configuration hash mismatch")
    for path, expected in manifest["hashes"].items():
        from macro.shared.io import artifact_matches
        # The two committed draft packages hashed CRLF checkout bytes. Accept only
        # the equivalent LF/CRLF serialization; every other byte change still fails.
        if not artifact_matches(out / path, expected, legacy_newlines=manifest["version"] in ("benchmark-v1", "benchmark-v2")):
            raise ValueError("Artifact hash mismatch: " + path)
    if manifest["policy_version"] != POLICY_VERSION:
        raise ValueError("Policy version mismatch")
    return validate({s: read_jsonl(out / s / "cases.jsonl") for s in ["dev", "test"]},
                    {s: read_jsonl(out / "private" / (s + ".references.jsonl")) for s in ["dev", "test"]}, config)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subset", default="data/subset-v1")
    parser.add_argument("--out", default="data/benchmark-v2")
    parser.add_argument("--config", default="configs/benchmark-v2.json")
    parser.add_argument("--pilot", default="data/pilot/cases.jsonl")
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    if args.verify_only:
        print(json.dumps(verify_saved(args.out)))
    else:
        generate(args.subset, args.out, read_json(args.config), args.pilot)


if __name__ == "__main__":
    main()
