"""Provider-independent, validated nutrition estimation."""

from abc import ABC, abstractmethod
from decimal import Decimal, ROUND_HALF_UP
import re
from typing import Any

from pydantic import ValidationError

from domain.schemas import EstimatedNutritionItem, NutritionEstimate


class NutritionProviderError(Exception):
    """A provider failed without producing safe structured output."""


class NutritionProviderUnavailable(NutritionProviderError):
    pass


class InvalidNutritionProviderResponse(NutritionProviderError):
    pass


class NutritionEstimationProvider(ABC):
    @abstractmethod
    def estimate(
        self,
        description: str,
        *,
        default_milk_serving_ml: Decimal,
        measurement_system: str,
    ) -> NutritionEstimate:
        """Return validated, visible nutrition estimates or clarification."""


class UnavailableNutritionProvider(NutritionEstimationProvider):
    def estimate(
        self,
        description: str,
        *,
        default_milk_serving_ml: Decimal,
        measurement_system: str,
    ) -> NutritionEstimate:
        del description, default_milk_serving_ml, measurement_system
        raise NutritionProviderUnavailable(
            "Nutrition estimation provider is unavailable."
        )


def get_nutrition_provider(name: str) -> NutritionEstimationProvider:
    if name == "reference":
        return ReferenceNutritionProvider()
    return UnavailableNutritionProvider()


def validate_provider_payload(payload: Any) -> NutritionEstimate:
    """Reject raw/malformed provider output before it reaches persistence."""
    try:
        return NutritionEstimate.model_validate(payload)
    except ValidationError as exc:
        raise InvalidNutritionProviderResponse(
            "Nutrition provider returned an invalid structured response."
        ) from exc


NUMBER_WORDS = {
    "a": Decimal("1"),
    "an": Decimal("1"),
    "one": Decimal("1"),
    "two": Decimal("2"),
    "three": Decimal("3"),
    "four": Decimal("4"),
    "five": Decimal("5"),
    "six": Decimal("6"),
    "seven": Decimal("7"),
    "eight": Decimal("8"),
    "nine": Decimal("9"),
    "ten": Decimal("10"),
}
NUMBER_PATTERN = (
    r"(?P<number>\d+(?:\.\d+)?|a|an|one|two|three|four|five|six|seven|"
    r"eight|nine|ten)"
)


def _number(value: str) -> Decimal:
    normalized = value.lower()
    if normalized in NUMBER_WORDS:
        return NUMBER_WORDS[normalized]
    return Decimal(value)


def _rounded(value: Decimal, places: str) -> Decimal:
    return value.quantize(Decimal(places), rounding=ROUND_HALF_UP)


class ReferenceNutritionProvider(NutritionEstimationProvider):
    """Small versioned reference dataset for the bounded beta food parser.

    Values are estimates from a configured reference table, never generated
    from memory or inferred by an LLM. Unsupported or ambiguous portions
    produce clarification instead of invented quantities.
    """

    provider_name = "bundled_reference"
    provider_version = "2026.07"

    _per_100 = {
        "paneer": {
            "calories": Decimal("265"),
            "protein": Decimal("18.3"),
            "carbohydrate": Decimal("1.2"),
            "fat": Decimal("20.8"),
        },
        "whole milk": {
            "calories": Decimal("61"),
            "protein": Decimal("3.2"),
            "carbohydrate": Decimal("4.8"),
            "fat": Decimal("3.3"),
        },
    }
    _per_item = {
        "medium roti": {
            "grams": Decimal("40"),
            "calories": Decimal("120"),
            "protein": Decimal("3.5"),
            "carbohydrate": Decimal("22"),
            "fat": Decimal("2.5"),
        },
        "medium banana": {
            "grams": Decimal("118"),
            "calories": Decimal("105"),
            "protein": Decimal("1.3"),
            "carbohydrate": Decimal("27"),
            "fat": Decimal("0.4"),
        },
        "boiled egg": {
            "grams": Decimal("50"),
            "calories": Decimal("78"),
            "protein": Decimal("6.3"),
            "carbohydrate": Decimal("0.6"),
            "fat": Decimal("5.3"),
        },
    }

    def estimate(
        self,
        description: str,
        *,
        default_milk_serving_ml: Decimal,
        measurement_system: str,
    ) -> NutritionEstimate:
        del measurement_system
        if re.search(r"-\s*\d", description):
            raise ValueError("Food quantity cannot be negative.")
        segments = [
            segment.strip(" .")
            for segment in re.split(r"\s*,\s*|\s+\band\b\s+", description.lower())
            if segment.strip(" .")
        ]
        items: list[EstimatedNutritionItem] = []
        missing: list[str] = []

        for segment in segments:
            item = self._parse_segment(segment, default_milk_serving_ml)
            if item is None:
                missing.append(segment)
            else:
                items.append(item)

        if missing or not items:
            names = ", ".join(missing) if missing else description
            return NutritionEstimate(
                items=items,
                visible_assumptions=[
                    assumption
                    for item in items
                    for assumption in item.visible_assumptions
                ],
                provider_name=self.provider_name,
                provider_version=self.provider_version,
                confidence=Decimal("0.35") if items else Decimal("0.1"),
                clarification_required=True,
                clarification_question=(
                    "Please provide a quantity and serving size for: " f"{names[:500]}."
                ),
            )

        assumptions = [
            assumption for item in items for assumption in item.visible_assumptions
        ]
        confidence = min(
            (item.confidence or Decimal("0.5") for item in items),
            default=Decimal("0.5"),
        )
        return NutritionEstimate(
            items=items,
            visible_assumptions=assumptions,
            provider_name=self.provider_name,
            provider_version=self.provider_version,
            confidence=confidence,
        )

    def _parse_segment(
        self,
        segment: str,
        default_milk_serving_ml: Decimal,
    ) -> EstimatedNutritionItem | None:
        if "paneer" in segment:
            match = re.search(
                NUMBER_PATTERN + r"\s*(?:g|gram|grams)\b",
                segment,
            )
            if not match:
                return None
            grams = _number(match.group("number"))
            return self._per_100_item(segment, "paneer", grams, "g", [])

        if "milk" in segment:
            ml_match = re.search(
                NUMBER_PATTERN + r"\s*(?:ml|milliliter|milliliters)\b",
                segment,
            )
            if ml_match:
                ml = _number(ml_match.group("number"))
                return self._per_100_item(segment, "whole milk", ml, "ml", [])
            glass_match = re.search(
                NUMBER_PATTERN + r"\s*(?:glass|glasses)\b",
                segment,
            )
            if not glass_match:
                return None
            glasses = _number(glass_match.group("number"))
            ml = glasses * default_milk_serving_ml
            assumption = (
                f"One glass of milk is treated as " f"{default_milk_serving_ml} ml."
            )
            item = self._per_100_item(
                segment,
                "whole milk",
                ml,
                "ml",
                [assumption],
            )
            item.quantity_value = glasses
            item.quantity_unit = "glass"
            item.portion_description = f"{ml} ml total"
            return item

        item_name = None
        if "roti" in segment:
            item_name = "medium roti"
        elif "banana" in segment:
            item_name = "medium banana"
        elif "egg" in segment:
            item_name = "boiled egg"
        if item_name is None:
            return None

        match = re.search(NUMBER_PATTERN, segment)
        if not match:
            return None
        count = _number(match.group("number"))
        reference = self._per_item[item_name]
        assumptions: list[str] = []
        if "medium" not in segment and item_name != "boiled egg":
            assumptions.append(
                f"{item_name.title()} uses the bundled medium-serving reference."
            )
        return EstimatedNutritionItem(
            original_item_text=segment,
            normalized_name=item_name,
            quantity_value=count,
            quantity_unit="item",
            portion_description=f"{count} × reference serving",
            estimated_grams=_rounded(reference["grams"] * count, "0.001"),
            calories=_rounded(reference["calories"] * count, "0.01"),
            protein_grams=_rounded(reference["protein"] * count, "0.001"),
            carbohydrate_grams=_rounded(reference["carbohydrate"] * count, "0.001"),
            fat_grams=_rounded(reference["fat"] * count, "0.001"),
            visible_assumptions=assumptions,
            confidence=Decimal("0.75"),
        )

    def _per_100_item(
        self,
        original: str,
        normalized_name: str,
        quantity: Decimal,
        unit: str,
        assumptions: list[str],
    ) -> EstimatedNutritionItem:
        if quantity <= 0 or quantity > Decimal("100000"):
            raise ValueError("Food quantity is outside the supported range.")
        reference = self._per_100[normalized_name]
        factor = quantity / Decimal("100")
        return EstimatedNutritionItem(
            original_item_text=original,
            normalized_name=normalized_name,
            quantity_value=quantity,
            quantity_unit=unit,
            portion_description=f"{quantity} {unit}",
            estimated_grams=(None if normalized_name == "whole milk" else quantity),
            calories=_rounded(reference["calories"] * factor, "0.01"),
            protein_grams=_rounded(reference["protein"] * factor, "0.001"),
            carbohydrate_grams=_rounded(reference["carbohydrate"] * factor, "0.001"),
            fat_grams=_rounded(reference["fat"] * factor, "0.001"),
            visible_assumptions=assumptions,
            confidence=Decimal("0.8"),
        )
