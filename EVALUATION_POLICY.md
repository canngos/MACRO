# Evaluation policy: benchmark-policy-v1

Defined 18 October 2026 for the new benchmark. The allocation was revised on 19 October 2026 to **400 final-test base cases plus 120 separate development cases (520 total)**, with equal coverage of the five case categories (80 test and 24 dev each). This supersedes the earlier 600-test-case draft, which is retained as benchmark-v1. Counts change the benchmark configuration, not these decision rules. Executable references are in `src/macro/shared/benchmark_policy.py`. The active prompts, schemas and fixed coordinator implement this version; historical pilot files are archival. No real benchmark inference or completed human review is claimed here.

## 1. Evaluation target and source of truth

Judge two fixed recipe recommendations against a synthetic user's explicit requirements. Do not generate or improve recommendations. Both methods receive identical recipe/profile evidence. The ground-truth recipe verdict is computed from the structured profile and dataset recipe attributes, not title, explanation style, model opinion or a hidden preference.

The data source is the versioned, provisionally prepared HUMMUS subset. Time is the supplied duration, not separately verified prep/cook/active time. Nutrition is the supplied normalized FSA dataset proxy (0-1 in steps of 0.125, higher preferred), not a health outcome. The other retained nutrient fields are supporting evidence, not additional objectives. Calorie/per-serving claims remain excluded until their source-unit and serving issues are resolved. Manual subset review remains pending; this policy does not certify source truth.

## 2. Profile schema

Every profile has exactly these fields:

```json
{
  "preferred_ingredients": ["garlic", "tomato"],
  "excluded_ingredients": ["mushroom"],
  "hard_max_duration_minutes": 30,
  "objectives": ["preference", "nutrition", "speed"],
  "priorities": ["nutrition", "speed", "preference"]
}
```

- Ingredient names must be distinct members of the eight documented groups: tomato, broccoli, spinach, mushroom, onion, garlic, carrot, olive. A preferred ingredient cannot also be excluded. Contradictory profiles are invalid input rather than test examples.
- `hard_max_duration_minutes` is a positive finite number or `null` for no hard time limit.
- `objectives` declares one or more distinct active objectives. Their list order does not imply priority.
- `priorities` is either a complete ordering of the active objectives (highest first), or `null` for no declared priorities. Partial, duplicate or contradictory orderings are rejected in v1, not silently completed.
- Preferred ingredients must be nonempty exactly when the preference objective is active. No weights are inferred. Soft dislikes are not represented in v1; do not silently convert a dislike into a hard exclusion.
- Natural-language requests generated later must express exactly this structured profile. Text/structure contradictions require correcting or rejecting the case before freeze. The current deterministic evaluator validates structured data; it does not parse free text.

## 3. Hard constraints

1. Excluded ingredient groups: a recipe fails when a declared excluded group appears in its documented canonical groups.
2. Strict time: a recipe fails when duration exceeds the stated maximum. The boundary is allowed: 20 minutes satisfies a 20-minute maximum.

Each failing recipe is infeasible regardless of its soft scores. If only one recipe is feasible, choose it. If both fail, return `both_violate`; do not choose the lesser violation. If neither fails, compare soft objectives.

Exclusion means absence under the declared bounded mapping, not proven absence from a biological ingredient family or hidden packaged-food composition. In particular, the whole-olive group does not include olive oil. Allergy, vegetarian/vegan, religious dietary and hidden sub-ingredient cases are outside v1 until separately verified evidence and rules exist. This is a documented scope reduction from the full plan, not completion of those requirements.

## 4. Soft objectives

| Objective | Computation | Preferred direction |
| --- | --- | --- |
| preference | Number of distinct preferred groups present / number of distinct preferred groups declared | Higher |
| nutrition | Supplied normalized FSA score | Higher |
| speed | Source duration in minutes; represented as negative minutes internally | Lower duration / higher internal score |

Ingredient quantities and repeated occurrences do not change preference scores. No title, popularity, rating, serving size or explanation-quality bonus is used.

Speed is active only if explicitly declared. A strict time limit does not automatically make the shorter feasible recipe better. Conversely, speed can be active without a hard limit (a soft preference for quicker recipes). A profile may deliberately declare both a hard maximum and speed: first enforce the maximum, then prefer shorter duration among feasible recipes when the comparison reaches that objective.

V1 soft time means **shorter is better**, without a target threshold or tolerance band. A request such as "around 30 minutes is equally good" needs a different explicit formula and must not be generated under this version.

All numeric comparisons use absolute tolerance 1e-9 solely for floating-point arithmetic, including the hard time boundary. This does not represent a meaningful cooking-time allowance. There is no weighted sum; priority outranks improvement magnitude.

## 5. Decision order

### Implemented benchmark coordinator

The benchmark runner uses the single coordinator implementation in `src/macro/coordinator/aggregation.py`. This is a fixed Python coordinator, not another model call. It receives public case evidence and three validated, independent specialist assessments; private reference answers are not inputs.

Hard constraints are verified directly from public duration and canonical ingredient facts. The coordinator then derives comparisons from specialist-reported preference/nutrition/duration values, using only the profile's active objectives. It follows the decision order below and reads the priority ordering explicitly declared in the public profile. An incorrect priority extraction or comparison label is recorded as a diagnostic, not treated as a vote. Soft scores remain model-reported; aggregation does not guarantee correct LLM findings.

Explanation support/disclosure is a separate diagnostic and cannot overturn hard constraints or objective precedence. A missing or invalid specialist assessment produces `technical_failure`, not `insufficient_information`.

The same hard-constraint verification applies to the single judge. Both systems preserve raw decisions and raw feasibility findings. Constraint precision/recall uses those raw findings, while primary decision accuracy includes the common verification step; `raw_metrics` reports decisions before that step. This compares complete evaluator designs, including the panel's arithmetic aggregation and additional model calls.

1. Apply hard feasibility.
2. If both feasible and equal on every active objective, return `tie`.
3. If one is no worse on every active objective and better on at least one, it Pareto-dominates: choose it. Priorities are not needed.
4. Otherwise there is a genuine trade-off. With an explicit priority ordering, compare its first objective; if equal, continue to the next. Choose the first unequal objective's winner (lexicographic priority).
5. For a genuine trade-off without priorities, return `insufficient_information`. Do not invent weights, force a winner or call it a tie.

The final verdict vocabulary is `A`, `B`, `tie`, `insufficient_information`, `both_violate`. Pilot `unresolved` and `neither_feasible` correspond to the latter two meanings but remain unchanged in historical artifacts.

Case categories are `constraint`, `dominance`, `tradeoff`, `control_tie`, and `both_violate`. Trade-offs can be resolved or unresolved. Correct-vs-correct controls in v1 are two distinct feasible recipes equal on every active objective; merely being feasible does not imply a tie. Case-generation balance and control quotas are separate benchmark-design decisions.

## 6. Explanation assessment is a separate output

The explanation judge checks whether claims are supported by public evidence and whether relevant trade-offs are disclosed. These findings are diagnostic: they do not change recipe attributes or override the fixed decision policy. A truthful description of an infeasible recipe is not itself false.

The course project focuses on RQ1 and RQ2. Manipulating explanation length, persuasion or factuality, and adding discussion rounds, are outside this scope.

## 7. Validity and execution failures

Missing/nonfinite attributes, unknown ingredient groups, unrecognized nutrition metrics, invalid FSA values, contradictory profiles, duplicate recipe IDs and broken recommendation references are invalid benchmark inputs. The deterministic validator raises an error; these cases must be repaired or removed before freeze. Missing data is not a genuine preference trade-off.

Judge execution/schema failures are technical failures, not `insufficient_information`, ties or safe recipes. Preserve them and include them in planned evaluation coverage and accuracy denominators. Never drop them silently. Judge response schema/runner integration remains separate from this reference policy.

Reference outputs contain version, verdict, category, per-candidate feasibility and violations, active objective scores, comparisons, reasons and evidence pointers. Gold labels and categories remain private; public judge inputs contain only profile, request, recipe evidence and recommendation text. Each experiment must retain policy, data, prompt and configuration identities. No test-set result may influence subsequent development without acknowledging reuse.

## 8. Worked examples

| Situation | Result |
| --- | --- |
| Hard maximum 20; A is 22 minutes, B is 20; B has no other violation | B, regardless of A's nutrition/preference |
| A contains excluded mushroom; B exceeds the hard time limit | both_violate |
| Both feasible; A preference 1 and FSA 0.75, B preference 0.5 and FSA 0.5; speed inactive | A dominates |
| Both feasible; A matches more preferences, B has higher FSA; no priorities | insufficient_information |
| Same trade-off, priorities nutrition then preference | B |
| Both feasible; both FSA 0.5; A faster but B better preference match; priorities nutrition, speed, preference | A after equal nutrition |
| Hard maximum 30; A is 20 and B is 25; equal active preference/nutrition, speed inactive | tie |
| Same recipes, speed active and all other active objectives equal | A |

Before case generation, confirm that these scoped semantics match the study questions. Extending vocabulary, dietary evidence, objective formulas or priority semantics requires a new version and regenerated labels; never silently alter a frozen benchmark.
