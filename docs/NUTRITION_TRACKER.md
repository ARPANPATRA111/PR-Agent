# Nutrition tracker

Food text first creates an editable draft. The configured provider returns
typed items, quantities, calories, macronutrients, confidence, and visible
assumptions. The server validates that response and recalculates meal totals
from items. Users may edit item values, enter values manually, confirm a draft,
save it as unestimated, or delete it; daily totals update immediately.

Reference estimates use a small validated food reference set and a configurable
default milk serving. Values are approximate because recipes, brands, cooking,
and serving sizes vary. Low-confidence or ambiguous estimates remain drafts
and ask for clarification.

If the provider times out, is disabled, or returns invalid data, the original
food text remains in a safe draft and the bot does not crash. No hidden model
reasoning is stored or returned.

This feature is a personal logging aid, not medical advice. It does not
diagnose disease, prescribe diets, recommend weight loss, or replace a
qualified clinician or dietitian.
