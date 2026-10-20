# Leakage and final scope review

Reviewer: Codex agent. Date: 20 October 2026. Scope: the existing 400 factual-base cases in both orders; no additional explanation variants or factuality/disclosure accuracy study.

## Evidence and disposition

The verified benchmark has disjoint recipes, semantic profiles and case IDs between development and final splits. No previous pilot recipe is included. Gold labels/categories and source titles are excluded by the public-input whitelist; no final model judgments have been collected or used for tuning.

Every explanation is the same factual template. After masking only the three supplied factual components (duration, canonical ingredient list and nutrition proxy), both splits have exactly one identical template. A fact-masked surface classifier reduces to the majority baseline: 25% for verdict and 20% for category. No label-specific persuasive or stylistic template was found.

A length-only threshold classifier fitted on development metadata nevertheless predicts final reference verdicts at 32.25% versus the 25% majority baseline, and categories at 28% versus 20%. Its chosen feature is the character-length difference between explanations. This is a measurable potential shortcut, associated with the stratified case construction and differing factual content; it is not evidence that the model used that shortcut. It must be disclosed, and the study must not claim complete elimination of surface or length confounding.

Disposition: accept with the stated limitation for the narrow controlled factual-base benchmark. Do not regenerate or length-pad explanations, change the sampled cases, or tune judge settings using this test metadata. Such changes would require a new dataset/development cycle. Do not claim explanation-style robustness or isolation of specialization from extra computation.

Manual source review is documented separately in SOURCE_REVIEW.md. Independent human annotation has not been performed. The dataset generation metadata remains unchanged; the freeze record binds these later reviews to the exact artifacts.
