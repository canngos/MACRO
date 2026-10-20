# Source and manual review for the 400-case validation

Review date: 20 October 2026. Reviewer: Codex agent. Scope: all 1,040 recipes used by the 120 development and 400 final base cases. This is an agent-performed source review, not an independent human annotation study or verification of the original recipe publishers.

## Findings

- All 1,040 benchmark recipes match the saved subset and original local CSV records, including raw ingredient strings, duration, supplied nutrition proxy and source record numbers. No transcription mismatch was found. The CSV hash agrees with the generation manifest.
- Inspected all 399 distinct raw strings mapped to the eight tracked groups, plus the three distinct explicit olive-oil non-matches. These are normal singular/plural vegetable names, named mushroom varieties, whole-olive varieties and preparation descriptors. No wrong-group mapping was found in this inventory.
- The whole-olive objective intentionally excludes olive oil. Ketchup, stocks, sauces, packaged foods, shallots and hidden sub-ingredients do not activate undocumented aliases. These are bounded mapping semantics, not claims about biological ingredient absence or dietary safety.
- Manually recomputed 18 case verdicts: one case in every stratum in both splits, covering 36 recipes. All agreed with the saved references. The accompanying JSON includes the selected IDs and independently written reasons. Automated policy/template/swap checks additionally cover all 520 base cases.
- No case labels, profiles, recipe facts, explanation text or model settings were changed during review.

## Scope and limitations

Duration is the source's recorded duration, not independently verified active preparation time. The FSA value is the supplied normalized dataset proxy on a 0.125 grid, not a clinical or health judgment. This study compares fixed recipe recommendations; it includes sauces and other recipe types and does not certify complete-meal suitability. Ingredient quantities and other nutrition fields are not additional objectives.

The local CSV's identity is hashed, but upstream byte identity and original publisher claims have not been independently established. The source review is complete for the benchmark's 1,040 selected recipes; it does not claim full manual review of every recipe in the 5,000-record parent subset.

The raw generation manifests retain historical pending review flags. This dated, hash-bound review provides the later evidence without rewriting the source dataset or pretending an independent human study was performed.

Disposition: source correspondence and the selected benchmark's bounded ingredient mapping are acceptable for the stated controlled factual-base experiment, with the above limitations reported. Independent human annotation remains unperformed.
