# Phase 1: recipe attributes and preparation

This is the first version of the data contract for the benchmark. The current allocation, revised 19 October 2026, is **400 final-test base cases plus 120 separate development cases**, balanced across five case categories. This supersedes the previous 600-final-case allocation without changing the 5,000-recipe subset. Recipe preparation itself makes no judge calls and generates no case labels; the separate benchmark generator constructs cases and assigns these splits.

## Attribute decisions

| Attribute | Decision | Use |
| --- | --- | --- |
| Recipe ID, source URL, source row | Retain source identity and provenance | Verification and reproducibility; later use neutral public IDs for judging |
| Title | Retain as source metadata | Review; not a preference score or label |
| Duration in minutes | Use HUMMUS `duration`, initially 1-180 minutes inclusive as in the pilot | Later strict limit or soft speed objective, as specified by a profile |
| Prep/cook time | Not separately available in the local CSV | Do not invent a split or describe duration as active prep time |
| Original ingredients | Retain names, section, quantity text and source serialization | Evidence for deterministic mapping and human review |
| Normalized ingredient groups | Use the pilot's eight groups with versioned explicit aliases | Bounded preference and exclusion checks |
| Nutrition score | Supplied normalized HUMMUS FSA score, 0-1, higher preferred | One nutrition proxy objective; not a health outcome |
| Nutrition values | Retain all ten source nutrient/energy fields plus serving size and servings per recipe | Completeness/plausibility checks, provenance and future claim verification |
| WHO/Nutri-Score | Not used as additional objectives in this version | Avoid redundant nutrition objectives; source file remains available |
| Preference-match score | Compute later against each generated profile | It is not a fixed recipe attribute |
| Dietary labels | Not inferred from tags or incomplete ingredient composition | Needs a separate evidence-backed specification before dietary cases |

The source documentation describes nutrition fields as per serving and permits normalized scores. Energy columns are retained under `energy_source_cal` and `energy_from_fat_source_cal` with original strings in `source_values`; this pipeline does not silently relabel `cal` as kcal or convert to per-100-g quantities. The supplied FSA score is retained rather than recomputed.

## Normalization semantics

The configuration in `configs/dataset-v1.json` is a frozen snapshot of the initial ingredient vocabulary. It is independent of the pilot policy module so later pilot edits do not silently change this preparation run.

- Normalize casing/whitespace and remove a bounded list of leading preparation/size words. For example, `chopped fresh garlic` maps to `garlic`.
- Match only explicit aliases. Preserve `raw`, `normalized_name`, `canonical_group` and `mapping_status` for every ingredient.
- Strip parenthetical/comma notes only for a tracked match when the note is a recognized preparation operation. Reject cases such as `broth (contains garlic)` rather than discarding the parenthesis and labeling garlic absent.
- Reject alternative ingredients (`or`), malformed structures and tracked ingredient forms without a documented mapping. A top-frequency review queue identifies where to add reviewed mappings next.
- Preserve outside-vocabulary names without claiming they are canonical. This is group normalization, not complete normalization of every food ingredient.
- Olive oil is an explicit non-match to the whole-olive preference group. Exclusions use these same bounded semantics. This is not an allergy or ingredient-ancestry rule.
- General compound-product composition is unknown: sauces, stocks, spice mixes and packaged foods can contain undeclared ingredients. A recipe passing this pipeline is not proof of biological absence. Hidden sub-ingredient benchmark cases require separately verified composition evidence.

## Filtering decisions

Require numeric identity, an alphabetic title, duration within bounds, a finite FSA score on the 0.125 grid, an empty source normalization warning, a structured non-empty ingredient list, at least one mapped group, positive serving size/count and finite nonnegative values for all ten nutrition fields. Exclude zero-energy records and the five known incomplete pilot ingredient records.

Apply internal consistency checks: saturated fat cannot exceed fat; sugars or fiber cannot individually exceed carbohydrate, allowing 0.5 g rounding tolerance. Fat + carbohydrate + protein cannot exceed serving mass plus 5% and 2 g tolerance. Sugar/fiber are not added again. Sodium/cholesterol are converted from mg to g only for mass comparisons. These are engineering screens, not nutritional guidance; tolerances are explicit initial decisions and should be sensitivity-checked. No arbitrary upper calorie threshold or macro-to-energy conversion is applied while source energy units remain unresolved.

Sample 5,000 eligible recipes with seeded reservoir sampling. Missing counts and rejection counts use the **first failed check**, not all simultaneous defects. The sample is uniform over the eligible pool, not representative of all HUMMUS. Restricting time, mapping vocabulary and completeness introduces selection bias.

## Reproduce

From `MACRO/`, using the project Python environment:

```powershell
python -m macro.evaluate_case_generation.dataset --source ../pp_recipes/pp_recipes.csv --config configs/dataset-v1.json --out data/subset-v1
```

The command refuses an existing output directory, refuses fewer than 5,000 eligible rows, checks that the source hash did not change while reading, and does not relax rules to reach the target. Outputs:

- `recipes.jsonl`: recipes with source values and ingredient mapping evidence.
- `config.json`: the exact configuration snapshot.
- `audit.json`: source/code/config/subset hashes, exclusion counts, subset quartiles and ingredient/score distributions.
- `review_queue.json`: top first-failure details for mapping review; not a completed human review.
- `DATASHEET.md`: generated summary and limitations.

Automated validation and manual validation are separate. The generated subset remains marked **manual review pending** and **not frozen**. Retain the old `data/subset/` and `data/pilot/` for historical experiments. The 20-case pilot generator is intentionally not modified by this phase.

## Review and benchmark preparation

### First full run, 17 October 2026

The source contains 507,335 rows; 47,887 passed the configured automated filters and 5,000 were selected. Median duration is 38 minutes and median FSA proxy is 0.5. All 5,000 selected IDs are unique; each saved record's retained source values reproduce its normalized attributes. The subset/config hashes and exclusion accounting were checked. Eight new preparation tests and six existing pilot reference tests passed.

The selected serving-size distribution ranges from 1 g to 5,753 g. Inspection of the largest records found bulk preparations reported as a single serving (for example, recipe 219328, pickles; recipe 111457, curry broth). Large values are not automatically proof of broken data, but these records require review before per-serving claims or a final verified-subset designation. The first pass intentionally records this uncertainty rather than silently inventing serving counts or calling automated filtering human verification.

Review sample ingredient evidence and rejected forms; decide whether eight-group coverage is sufficient and add mappings with tests where justified. Resolve energy-unit provenance before calorie claims. Add verified compound composition/dietary evidence if those case types remain in scope. Formalize soft-time/profile priority rules and controls; then generalize case generation, review variants, and create grouped dev/test splits. This preparation command alone does not complete those tasks.

Source: [HUMMUS upstream documentation](https://gitlab.com/felix134/connected-recipe-data-set/-/raw/master/README.md), inspected 17 October 2026. The local source hash identifies the CSV; upstream byte identity is not established.
