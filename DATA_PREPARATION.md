# Data preparation and case construction

HUMMUS supplies recipe attributes. MACRO constructs recommendation pairs and synthetic user profiles programmatically; the pairs are not supplied by a trained recommender.

## Recipe subset

The preparation script filters incomplete or inconsistent records, retains source values for inspection, and samples 5,000 eligible recipes with a fixed seed. The saved audit records 507,335 source rows, 47,887 eligible rows and 5,000 selected recipes.

The benchmark uses source duration, normalized HUMMUS FSA nutrition scores and eight ingredient groups: tomato, broccoli, spinach, mushroom, onion, garlic, carrot and olive.

Ingredient mapping uses documented aliases and preparation words. Ambiguous tracked forms such as `broth (contains garlic)` are rejected. Original ingredient strings and mapping evidence are retained. Olive oil does not count as whole olive. The mapping does not establish hidden-ingredient absence or allergy safety.

Checks cover missing values, duration bounds, score validity, serving information and nutrient consistency. The FSA score is retained from HUMMUS rather than recomputed. Duration is not split into preparation and cooking time. The subset is filtered for this benchmark and is not representative of all recipes or users.

## Constructing cases

1. Sample two unused recipes from the prepared subset.
2. Construct a profile with preferred/excluded groups, a duration limit, active objectives and optional priorities. Recipe attributes stay unchanged.
3. Compute the reference label under the [fixed policy](EVALUATION_POLICY.md).
4. Keep the case only if it matches the intended category and difficulty conditions; otherwise try another combination.
5. Add factual explanation templates, assign neutral recipe IDs and balance A/B winners where applicable. Randomize candidate-pool positions independently.

Duration-violation cases set the limit to the shorter recipe's duration. Near cases have a positive duration gap of at most five minutes; clear cases have a gap of at least fifteen minutes. Dominance and trade-off cases must satisfy their respective relationships on the profile's active objectives.

## Current benchmark

| Case category | Development | Test |
|---|---:|---:|
| Constraint violation | 24 | 80 |
| Dominance | 24 | 80 |
| Genuine trade-off | 24 | 80 |
| Tie control | 24 | 80 |
| Both violate | 24 | 80 |
| **Total** | **120** | **400** |

Test trade-offs contain 40 cases with declared priorities and 40 without. No recipe or exact semantic profile is reused across accepted cases or across the two splits. Previously inspected pilot recipes are excluded. The 400 test cases use 800 distinct recipes; evaluating both orders repeats these cases.

Public cases are in `data/benchmark-v2/dev/` and `test/`. The `private/` directory holds reference labels and the mapping back to source recipes. Only public case evidence is sent to judges. Private here means withheld from judges, not encrypted.

## Validation and reproduction

Validate the supplied benchmark without model calls:

```powershell
.\.venv\Scripts\python.exe -m macro validate --cases data/benchmark-v2
```

The raw HUMMUS CSV is not included in Git. To prepare a new package, obtain the source data from the [HUMMUS project](https://gitlab.com/felix134/connected-recipe-data-set) and use new output directories:

```powershell
.\.venv\Scripts\python.exe -m macro audit --source pp_recipes/pp_recipes.csv --out data/subset-new
.\.venv\Scripts\python.exe -m macro generate --subset data/subset-new --config configs/benchmark-v2.json --out data/benchmark-new
```

Both commands refuse existing output directories. The original source digest and filter settings are retained in `data/subset-v1/audit.json` and `config.json`.

The generated manifests retain their original review status. The later [DeepSeek readiness review](readiness/deepseek-final-400/REVIEW.md) records agent-performed source and leakage checks separately. It is not a substitute for independent human annotation. An explanation-length signal remained in that review and is a documented benchmark limitation. Older data packages are historical and must not be mixed into the current test set.
