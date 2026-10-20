"""Versioned offline preparation of HUMMUS recipe evidence."""
import argparse
import ast
import csv
import json
import math
import random
import re
from collections import Counter
from pathlib import Path

from macro.shared.io import digest, file_hash, read_json, write_json, write_jsonl

NUTRIENTS = {
    "energy_source_cal": "calories [cal]",
    "energy_from_fat_source_cal": "caloriesFromFat [cal]",
    "fat_g": "totalFat [g]", "saturated_fat_g": "saturatedFat [g]",
    "cholesterol_mg": "cholesterol [mg]", "sodium_mg": "sodium [mg]",
    "carbohydrate_g": "totalCarbohydrate [g]", "fiber_g": "dietaryFiber [g]",
    "sugars_g": "sugars [g]", "protein_g": "protein [g]",
}
DESCRIPTORS = re.compile(r"^(?:(?:finely chopped|thinly sliced|chopped|sliced|diced|minced|large|small|medium|fresh|frozen|whole|raw)\s+)+")
PREPARATION = re.compile(r"^(?:(?:finely|thinly|roughly|coarsely|freshly)\s+)?(?:chopped|sliced|diced|minced|peeled|crushed|grated|washed|rinsed|drained|thawed|trimmed|seeded|pitted)(?:\s+and\s+(?:chopped|sliced|diced|peeled|seeded))?$")


class Rejected(ValueError):
    def __init__(self, reason, detail=None):
        super().__init__(reason)
        self.reason, self.detail = reason, detail


def numeric(row, key, positive=False):
    try:
        value = float(row[key])
    except (ValueError, TypeError, KeyError):
        raise Rejected("missing_or_invalid_numeric", key) from None
    if not math.isfinite(value) or value < 0 or (positive and value == 0):
        raise Rejected("missing_or_invalid_numeric", key)
    return value


def vocabulary(config):
    lookup = {}
    for group, aliases in config["normalization"]["aliases"].items():
        for alias in aliases:
            if alias in lookup and lookup[alias] != group:
                raise ValueError("Ingredient alias belongs to multiple groups")
            lookup[alias] = group
    # Includes plural aliases; whole words avoid treating e.g. coconut as a nut match.
    terms = set(lookup) | set(config["normalization"]["aliases"])
    mention = re.compile(r"\b(?:" + "|".join(re.escape(x) for x in sorted(terms, key=len, reverse=True)) + r")\b")
    return lookup, mention


def normalize_ingredient(raw, lookup, mention, non_matches):
    """Map documented groups only; retain every raw string and its mapping evidence."""
    text = " ".join(raw.casefold().split())
    if not text or not any(c.isalpha() for c in text):
        raise Rejected("malformed_ingredient", raw)
    if "$template" in text or re.search(r"\bor\b", text):
        raise Rejected("ambiguous_ingredient", raw)
    if text.count("(") != text.count(")") or text.startswith(("and ", "to ", "sub ")):
        raise Rejected("malformed_ingredient", raw)
    # Only remove explicitly recognized preparation notes. Never erase an ingredient
    # in parentheses or after a comma and then infer that it was absent.
    notes = re.findall(r"\(([^()]*)\)", text)
    body = re.sub(r"\([^()]*\)", "", text).strip()
    pieces = [x.strip() for x in body.split(",")]
    head = DESCRIPTORS.sub("", pieces[0])
    group = lookup.get(head)
    mentioned = bool(mention.search(text))
    if mentioned:
        if any(not PREPARATION.fullmatch(note.strip()) for note in notes + pieces[1:]):
            raise Rejected("unresolved_ingredient_note", raw)
        if head in non_matches:
            group = None
        elif group is None:
            raise Rejected("unmapped_tracked_ingredient", raw)
    return {"raw": raw, "normalized_name": head,
            "canonical_group": group,
            "mapping_status": "mapped" if group else "explicit_non_match" if head in non_matches else "outside_vocabulary"}


def normalize_record(row, number, config, lexicon=None):
    if not row.get("recipe_id", "").isdigit() or not any(c.isalpha() for c in row.get("title", "")):
        raise Rejected("missing_identity")
    if row["recipe_id"] in config["excluded_recipe_ids"]:
        raise Rejected("known_incomplete_ingredient_record")
    duration = numeric(row, "duration", positive=True)
    bounds = config["duration_minutes"]
    if not bounds["min"] <= duration <= bounds["max"]:
        raise Rejected("duration_outside_bounds")
    score = numeric(row, "fsa_score")
    if score > 1 or abs(score * 8 - round(score * 8)) > 1e-8:
        raise Rejected("invalid_normalized_fsa")
    if row.get("normalization_comment", "missing").strip():
        raise Rejected("flagged_nutrient_normalization")
    serving = numeric(row, "servingSize [g]", positive=True)
    servings = numeric(row, "servingsPerRecipe", positive=True)
    nutrients = {name: numeric(row, column) for name, column in NUTRIENTS.items()}
    if nutrients["energy_source_cal"] == 0:
        raise Rejected("zero_energy")
    tolerance = config["rounding_tolerance_g"]
    if (nutrients["saturated_fat_g"] > nutrients["fat_g"] + tolerance
            or nutrients["sugars_g"] > nutrients["carbohydrate_g"] + tolerance
            or nutrients["fiber_g"] > nutrients["carbohydrate_g"] + tolerance):
        raise Rejected("inconsistent_nutrient_components")
    mass_limit = serving * (1 + config["mass_tolerance_fraction"]) + config["mass_tolerance_g"]
    macro_mass = sum(nutrients[k] for k in ["fat_g", "carbohydrate_g", "protein_g"])
    if (macro_mass > mass_limit or nutrients["sodium_mg"] / 1000 > mass_limit
            or nutrients["cholesterol_mg"] / 1000 > mass_limit):
        raise Rejected("nutrient_mass_exceeds_serving")
    try:
        ingredients = ast.literal_eval(row["ingredients"])
    except (ValueError, SyntaxError, TypeError, KeyError):
        raise Rejected("invalid_ingredients_structure") from None
    if not isinstance(ingredients, dict) or not ingredients:
        raise Rejected("invalid_ingredients_structure")
    lookup, mention = lexicon or vocabulary(config)
    evidence = []
    for section, entries in ingredients.items():
        if not isinstance(section, str) or not isinstance(entries, list) or not entries:
            raise Rejected("invalid_ingredients_structure")
        for entry in entries:
            if not isinstance(entry, (tuple, list)) or len(entry) != 2 or not isinstance(entry[0], str) or not isinstance(entry[1], str):
                raise Rejected("invalid_ingredients_structure")
            result = normalize_ingredient(entry[0], lookup, mention, config["normalization"]["non_matches"])
            evidence.append({"section": section, "quantity_source": entry[1], **result})
    groups = sorted({x["canonical_group"] for x in evidence if x["canonical_group"]})
    if not groups:
        raise Rejected("no_tracked_ingredient")
    return {"id": row["recipe_id"], "title": row["title"],
            "duration_minutes": duration, "time_basis": "source_duration_only",
            "ingredient_names": sorted({x["normalized_name"] for x in evidence}),
            "raw_ingredient_names": [x["raw"] for x in evidence],
            "canonical_ingredients": groups, "ingredient_evidence": evidence,
            "nutrition_score": score, "nutrition_metric": "hummus_normalized_fsa",
            "nutrition_source_values": nutrients, "serving_size_g": serving,
            "servings_per_recipe": servings,
            "source_url": row.get("recipe_url", ""), "source_record_number": number,
            "source_values": {k: row[k] for k in ["recipe_id", "title", "duration", "ingredients", "fsa_score", "normalization_comment", "servingSize [g]", "servingsPerRecipe", *NUTRIENTS.values()]},
            "dataset_version": config["version"],
            "normalization_version": config["normalization"]["version"]}


def distribution(values):
    values = sorted(values)
    return {"count": len(values), "min": values[0], "p25": values[int((len(values)-1)*.25)],
            "median": values[int((len(values)-1)*.5)], "p75": values[int((len(values)-1)*.75)], "max": values[-1]}


def prepare(source, out, config):
    out = Path(out)
    if out.exists():
        raise ValueError("Output directory already exists; use a new versioned path")
    if type(config["subset_size"]) is not int or config["subset_size"] <= 0:
        raise ValueError("subset_size must be a positive integer")
    source_hash = file_hash(source)
    lexicon = vocabulary(config)
    rng = random.Random(config["seed"])
    reasons, details, seen, selected = Counter(), Counter(), set(), []
    eligible = total = 0
    with Path(source).open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        required = {"recipe_id", "title", "duration", "ingredients", "fsa_score", "normalization_comment", "servingSize [g]", "servingsPerRecipe", *NUTRIENTS.values()}
        if not required <= set(reader.fieldnames or []):
            raise ValueError("Source is missing required columns: " + str(sorted(required - set(reader.fieldnames or []))))
        for total, row in enumerate(reader, 1):
            identity = row.get("recipe_id", "")
            if identity in seen:
                reasons["duplicate_recipe_id"] += 1
                continue
            seen.add(identity)
            try:
                record = normalize_record(row, total, config, lexicon)
            except Rejected as exc:
                reasons[exc.reason] += 1
                if exc.detail:
                    details[(exc.reason, exc.detail)] += 1
                continue
            eligible += 1
            if len(selected) < config["subset_size"]:
                selected.append(record)
            else:
                index = rng.randrange(eligible)
                if index < len(selected):
                    selected[index] = record
            if total % 100000 == 0:
                print(f"Read {total} source records; {eligible} eligible", flush=True)
    if len(selected) != config["subset_size"]:
        raise ValueError(f"Only {eligible} eligible recipes; required {config['subset_size']}. No rules relaxed and no subset written.")
    if file_hash(source) != source_hash:
        raise ValueError("Source changed during preparation; no subset written")
    selected.sort(key=lambda r: int(r["id"]))
    stats = {key: distribution([r[key] for r in selected]) for key in ["duration_minutes", "nutrition_score", "serving_size_g"]}
    stats["nutrients"] = {key: distribution([r["nutrition_source_values"][key] for r in selected]) for key in NUTRIENTS}
    stats["ingredient_group_recipe_counts"] = dict(sorted(Counter(g for r in selected for g in r["canonical_ingredients"]).items()))
    stats["score_recipe_counts"] = dict(sorted(Counter(str(r["nutrition_score"]) for r in selected).items()))
    out.mkdir(parents=True, exist_ok=False)
    write_jsonl(out / "recipes.jsonl", selected)
    write_json(out / "config.json", config)
    report = {"schema_version": config["version"], "source_file": str(Path(source).resolve()),
              "source_sha256": source_hash, "source_bytes": Path(source).stat().st_size,
              "source_rows": total, "eligible_rows": eligible, "selected_rows": len(selected),
              "first_exclusion_reason_counts": dict(reasons), "distributions": stats,
              "recipes_sha256": file_hash(out / "recipes.jsonl"), "config_sha256": digest(config),
              "preparation_code_sha256": file_hash(__file__),
              "manual_review_status": "pending", "benchmark_freeze_status": "not_frozen",
              "provenance_limit": "Local CSV hashed; upstream byte identity is not established."}
    write_json(out / "audit.json", report)
    write_json(out / "review_queue.json", {"note": "Top 100 first-failure details, not an exhaustive ingredient vocabulary or manual review record.",
               "items": [{"reason": reason, "source_text_or_field": text, "count": count} for (reason, text), count in details.most_common(100)]})
    lines = ["# Prepared HUMMUS subset", "", "Status: automated validation complete; manual review pending; not a frozen benchmark.", "",
             f"Source rows: {total}; eligible: {eligible}; selected: {len(selected)}.", "",
             "See config.json for exact bounds, mapping and tolerances; audit.json for source/code hashes, first-failure counts and selected-subset distributions.", "",
             "| Attribute | Minimum | 25th percentile | Median | 75th percentile | Maximum |", "|---|---:|---:|---:|---:|---:|"]
    for key in ["duration_minutes", "nutrition_score", "serving_size_g"]:
        d = stats[key]
        lines.append(f"| {key} | {d['min']} | {d['p25']} | {d['median']} | {d['p75']} | {d['max']} |")
    lines += ["", "## Limitations", "", "- Duration is source duration, not separately verified prep/cook/active time.",
              "- FSA is the supplied normalized dataset proxy, not a health outcome; not recomputed here.",
              "- Nutrient values retain source units and documented per-serving basis. No per-100-g or energy-unit conversion is applied.",
              "- Only the eight configured ingredient groups are canonicalized. Other names are retained as outside_vocabulary, not silently labeled canonical.",
              "- No hidden composition inference, dietary classification or allergy-safety claim. Compound ingredients may contain undeclared groups.",
              "- Olive oil is an explicit non-match for whole-olive preference. Exclusions have the same bounded group semantics, not biological ingredient ancestry.",
              "- Empty normalization comments and mass checks reduce obvious errors but do not prove source truth. Automatic checks are not human validation.",
              "- Duration bounds, complete-field requirements and tracked-group coverage bias selection. Sampling is seeded uniform reservoir sampling over eligible recipes, not all HUMMUS.",
              "- This command prepares source recipes; case generation and development/test assignment are separate steps.", ""]
    (out / "DATASHEET.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ["source_rows", "eligible_rows", "selected_rows", "recipes_sha256"]}), flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--out", default="data/subset-v1")
    parser.add_argument("--config", default="configs/dataset-v1.json")
    args = parser.parse_args()
    prepare(args.source, args.out, read_json(args.config))


if __name__ == "__main__":
    main()
