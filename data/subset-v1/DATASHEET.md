# Prepared HUMMUS subset

Status: automated validation complete; manual review pending; not a frozen benchmark.

Source rows: 507335; eligible: 47887; selected: 5000.

See config.json for exact bounds, mapping and tolerances; audit.json for source/code hashes, first-failure counts and selected-subset distributions.

| Attribute | Minimum | 25th percentile | Median | 75th percentile | Maximum |
|---|---:|---:|---:|---:|---:|
| duration_minutes | 1.0 | 23.0 | 38.0 | 60.0 | 180.0 |
| nutrition_score | 0.0 | 0.25 | 0.5 | 0.625 | 1.0 |
| serving_size_g | 1.0 | 153.0 | 239.0 | 357.0 | 5753.0 |

## Limitations

- Duration is source duration, not separately verified prep/cook/active time.
- FSA is the supplied normalized dataset proxy, not a health outcome; not recomputed here.
- Nutrient values retain source units and documented per-serving basis. No per-100-g or energy-unit conversion is applied.
- Only the eight configured ingredient groups are canonicalized. Other names are retained as outside_vocabulary, not silently labeled canonical.
- No hidden composition inference, dietary classification or allergy-safety claim. Compound ingredients may contain undeclared groups.
- Olive oil is an explicit non-match for whole-olive preference. Exclusions have the same bounded group semantics, not biological ingredient ancestry.
- Empty normalization comments and mass checks reduce obvious errors but do not prove source truth. Automatic checks are not human validation.
- Duration bounds, complete-field requirements and tracked-group coverage bias selection. Sampling is seeded uniform reservoir sampling over eligible recipes, not all HUMMUS.
- No 600-case generation or dev/test assignment has been performed by this command.
