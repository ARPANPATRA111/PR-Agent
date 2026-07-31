# Nutrition Tracker

Nutrition values are approximate estimates, not laboratory measurements,
medical advice, diagnosis, or a substitute for a clinician or dietitian.
Recipes, brands, cooking fat, portion size, and regional preparation can change
the result substantially. The application never prescribes calorie or
macronutrient targets; users may enter only their own targets.

## Workflow

1. `/food DESCRIPTION` or `POST /api/v2/nutrition` stores the original text as
   an idempotent draft.
2. A configured `NutritionEstimationProvider` returns a strict schema. Extra,
   missing, negative, excessive, or malformed values are rejected before
   persistence.
3. Clear estimates are shown with per-item quantities, the word
   “approximately,” confidence, and visible assumptions.
4. Vague or unsupported portions remain drafts with a clarification question.
5. A user confirms, edits, saves the original as an unestimated food note, or
   deletes the draft.
6. Only confirmed meals contribute calories and macronutrients to summaries.

Provider timeouts and invalid provider payloads preserve the original draft.
They never trigger invented fallback values. Users can save the text without
estimates or enter calories and protein manually.

## Bounded reference provider

`NUTRITION_PROVIDER=reference` enables a deliberately small, versioned beta
table for paneer, milk, medium roti, medium banana, and boiled egg. Its purpose
is predictable parsing and offline behavior, not comprehensive food coverage.
Milk entered as “one glass” visibly uses the user's configurable serving
default (250 ml initially). Unsupported foods and missing quantities always ask
for clarification.

The bundled figures are generic serving estimates and must remain labeled as
approximate. A future database-backed provider should retain source record IDs,
dataset release, and retrieval time for every item. USDA FoodData Central is a
candidate public-domain source, but its API requires a data.gov key that must
remain server-side and must never be committed.

## Data and edit consistency

Per-item values use fixed-precision decimals. Meal totals are recalculated from
stored items after every create, edit, or delete; clients cannot write meal
totals directly. A serving-size edit must also provide updated calories and
protein because the system will not invent how those macros scale.

User edits set both the item and meal `user_modified` flags. Estimates preserve
provider name/version, confidence, visible assumptions, and only the normalized
result. Hidden reasoning or chain-of-thought fields are forbidden by strict
schemas.

## API and commands

The authenticated API provides preview, browse, view, confirm, manual save,
unestimated save, item edit/delete, meal delete, target preferences, and
date-range summary endpoints under `/api/v2/nutrition`.

Telegram commands are:

```text
/food DESCRIPTION
/confirmfood FOOD_ID
/savefoodnote FOOD_ID
/editfood FOOD_ID ITEM_ID QUANTITY UNIT CALORIES PROTEIN
/deletefood FOOD_ID
/nutrition [YYYY-MM-DD]
/nutritiontargets CALORIES PROTEIN [CARBS FAT]
```

Destructive and ambiguous natural-language transformations are intentionally
not performed in this deterministic phase.
