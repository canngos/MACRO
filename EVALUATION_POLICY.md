# Evaluation policy

Policy identifier: `benchmark-policy-v1`. The task is to judge two fixed recipe recommendations against an explicit synthetic user profile.

## Evidence and objectives

The profile specifies preferred and excluded ingredient groups, an optional maximum duration, active objectives and an optional ordered list of priorities. Priorities, when provided, order every active objective. Objective-list order is not a priority.

The eight ingredient groups are tomato, broccoli, spinach, mushroom, onion, garlic, carrot and olive. A group cannot be both preferred and excluded. Only documented canonical groups are used; hidden ingredients and dietary requirements are not inferred.

| Criterion | Rule |
|---|---|
| Hard duration limit | Recorded duration must be at or below the stated maximum, if provided |
| Ingredient exclusion | No excluded canonical group may occur |
| Preference | Fraction of distinct preferred groups present; higher is better |
| Nutrition | Supplied normalized HUMMUS FSA score; higher is better |
| Speed | Shorter recorded recipe duration, only when explicitly active |

Nutrition is a dataset proxy, not a measured health outcome. Duration is the source recipe duration, not necessarily active preparation time. A hard time limit does not automatically activate speed as a soft objective. Numeric comparisons use tolerance `1e-9` for floating-point arithmetic.

## Decision order

1. **Hard constraints:** choose the only feasible candidate, or return `both_violate` if neither is feasible.
2. **Equality:** if both are feasible and equal on all active objectives, return `tie`.
3. **Dominance:** choose a candidate that is no worse on every active objective and strictly better on at least one. Priorities are unnecessary here.
4. **Declared priorities:** for a genuine trade-off, select the winner on the first unequal objective in the declared priority order. There is no weighted sum.
5. **Unresolved trade-off:** return `insufficient_information` when conflicting objectives have no declared priority ordering.

Outcomes are `A`, `B`, `tie`, `both_violate` and `insufficient_information`. Case categories are constraint, dominance, trade-off, tie control and both-violate control.

| Example | Outcome |
|---|---|
| Maximum 20 minutes; A takes 22 and B takes 20, with no other violation | B |
| A contains an excluded group; B exceeds the maximum duration | both_violate |
| Both feasible; A has higher preference and nutrition, speed inactive | A dominates |
| A has higher preference, B higher nutrition; no priorities | insufficient_information |
| Same trade-off, nutrition has highest priority | B |
| Equal preference/nutrition; A is faster but speed is inactive | tie |

## Coordinator and single judge

The [Python coordinator](src/macro/coordinator/aggregation.py) verifies hard constraints from public recipe facts. It derives soft comparisons from the specialists' reported preference, nutrition and duration values, using the profile's actual active objectives and priorities. Incorrect comparison labels or extracted priorities are diagnostics. There is no majority vote or discussion round.

The single judge receives the same hard-constraint guardrail. Its soft-objective decision remains model-generated. Raw decisions and findings are preserved for both systems. Comparing the two systems therefore includes the panel's fixed aggregation and additional model calls, as well as specialization.

Explanation support and trade-off disclosure are recorded separately and do not change the final choice. All three specialist outputs must nevertheless be valid; otherwise the panel returns `technical_failure`.

## References and scoring

[The reference policy](src/macro/shared/benchmark_policy.py) computes expected labels from public facts. Labels are stored separately and withheld from judges.

- Primary accuracy includes the shared hard-constraint guardrail. Raw accuracy uses decisions before that guardrail.
- Constraint precision and recall use raw candidate feasibility findings from completed evaluations. Report their coverage; missing assessments are not correct detections.
- Binary infeasibility, violation type and the exact excluded ingredient are different measures. A correct infeasible flag can still name the wrong reason.
- Overall accuracy includes technical failures in the planned denominator.
- Candidate-order stability compares canonical recipe choices across both orders; two equally wrong answers can still be stable.
- Both orders belong to one base case, not two independent samples.

Explanation manipulation and discussion rounds are outside the reduced RQ1/RQ2 scope.
