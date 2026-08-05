from datetime import date, datetime, timezone
from decimal import Decimal
import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from domain.errors import RecordNotFound
from domain.schemas import (
    EstimatedNutritionItem,
    NutritionDraftCreate,
    NutritionEstimate,
    NutritionItemUpdate,
    NutritionManualSave,
    NutritionPreferenceUpdate,
)
from domain.services import DomainServices
from nutrition.providers import (
    GroqNutritionProvider,
    NutritionEstimationProvider,
    NutritionProviderUnavailable,
    ReferenceNutritionProvider,
    validate_provider_payload,
)
from public_models import NutritionItem, NutritionLog, PublicBase


@pytest.fixture()
def nutrition_services():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, connection_record):
        del connection_record
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    PublicBase.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    service = DomainServices(session)
    owner_a = service.ensure_owner(telegram_id=1001, first_name="A")
    owner_b = service.ensure_owner(telegram_id=2002, first_name="B")
    session.commit()
    try:
        yield service, owner_a.id, owner_b.id
    finally:
        session.close()
        engine.dispose()


@pytest.mark.parametrize(
    ("text", "name", "quantity"),
    [
        ("50 g paneer", "paneer", Decimal("50")),
        ("4 medium rotis", "medium roti", Decimal("4")),
        ("4 bananas", "medium banana", Decimal("4")),
        ("one glass of milk", "whole milk", Decimal("1")),
    ],
)
def test_reference_provider_supported_foods(text, name, quantity):
    estimate = ReferenceNutritionProvider().estimate(
        text,
        default_milk_serving_ml=Decimal("250"),
        measurement_system="metric",
    )
    assert estimate.clarification_required is False
    assert len(estimate.items) == 1
    assert estimate.items[0].normalized_name == name
    assert estimate.items[0].quantity_value == quantity
    assert estimate.items[0].calories > 0
    assert estimate.items[0].protein_grams > 0


def test_mixed_meal_has_visible_assumptions_and_item_totals():
    estimate = ReferenceNutritionProvider().estimate(
        "50 g paneer, 4 medium rotis, 4 bananas and one glass of milk",
        default_milk_serving_ml=Decimal("250"),
        measurement_system="metric",
    )
    assert len(estimate.items) == 4
    assert any("250" in value for value in estimate.visible_assumptions)
    assert sum(item.calories for item in estimate.items) > 1000
    assert sum(item.protein_grams for item in estimate.items) > 30


@pytest.mark.parametrize(
    "text",
    [
        "Had some paneer and roti",
        "paneer",
        "milk",
        "something unknown",
    ],
)
def test_ambiguous_or_missing_portion_requires_clarification(text):
    estimate = ReferenceNutritionProvider().estimate(
        text,
        default_milk_serving_ml=Decimal("250"),
        measurement_system="metric",
    )
    assert estimate.clarification_required is True
    assert "quantity" in estimate.clarification_question.lower()


def test_decimal_and_invalid_quantities():
    decimal_estimate = ReferenceNutritionProvider().estimate(
        "50.5 g paneer",
        default_milk_serving_ml=Decimal("250"),
        measurement_system="metric",
    )
    assert decimal_estimate.items[0].quantity_value == Decimal("50.5")
    with pytest.raises((ValidationError, ValueError)):
        ReferenceNutritionProvider().estimate(
            "-5 g paneer",
            default_milk_serving_ml=Decimal("250"),
            measurement_system="metric",
        )
    with pytest.raises((ValidationError, ValueError)):
        ReferenceNutritionProvider().estimate(
            "100001 g paneer",
            default_milk_serving_ml=Decimal("250"),
            measurement_system="metric",
        )


def test_preview_confirm_edit_delete_and_daily_totals(nutrition_services):
    service, owner_a, owner_b = nutrition_services
    draft = service.estimate_nutrition_draft(
        owner_a,
        NutritionDraftCreate(
            original_text="50 g paneer and one glass of milk",
            meal_name="lunch",
            logged_at_local=datetime(2026, 7, 31, 23, 30),
            timezone="Asia/Kolkata",
            idempotency_key="nutrition-key-1",
        ),
        ReferenceNutritionProvider(),
    )
    duplicate = service.estimate_nutrition_draft(
        owner_a,
        NutritionDraftCreate(
            original_text="50 g paneer and one glass of milk",
            meal_name="lunch",
            timezone="Asia/Kolkata",
            idempotency_key="nutrition-key-1",
        ),
        ReferenceNutritionProvider(),
    )
    assert duplicate.id == draft.id
    assert draft.status == "draft"
    assert draft.user_local_date == date(2026, 7, 31)
    assert draft.total_calories == sum(item.calories for item in draft.items)
    assert draft.total_protein_grams == sum(item.protein_grams for item in draft.items)

    with pytest.raises(RecordNotFound):
        service.get_nutrition_log(owner_b, draft.id)

    confirmed = service.confirm_nutrition_log(owner_a, draft.id, draft.version)
    assert confirmed.status == "confirmed"
    first_item = confirmed.items[0]
    old_total = confirmed.total_protein_grams
    edited = service.update_nutrition_item(
        owner_a,
        confirmed.id,
        first_item.id,
        NutritionItemUpdate(
            version=first_item.version,
            protein_grams=first_item.protein_grams + Decimal("1"),
        ),
    )
    assert edited.total_protein_grams == old_total + Decimal("1")
    assert edited.user_modified is True

    summary = service.summarize_nutrition(owner_a, date(2026, 7, 31), date(2026, 7, 31))
    assert summary["confirmed_meals"] == 1
    assert summary["total_protein_grams"] == edited.total_protein_grams

    second_item = edited.items[1]
    before_delete = edited.total_calories
    after_item_delete = service.delete_nutrition_item(
        owner_a, edited.id, second_item.id
    )
    assert after_item_delete.total_calories < before_delete
    assert (
        service.summarize_nutrition(owner_a, date(2026, 7, 31), date(2026, 7, 31))[
            "total_calories"
        ]
        == after_item_delete.total_calories
    )

    service.delete_nutrition_log(owner_a, edited.id)
    assert service.list_nutrition_logs(owner_a) == []


def test_serving_edit_requires_consistent_macros():
    with pytest.raises(ValidationError):
        NutritionItemUpdate(
            version=1,
            quantity_value=Decimal("400"),
            quantity_unit="ml",
        )


class UnavailableProvider(NutritionEstimationProvider):
    def estimate(self, description, **kwargs):
        del description, kwargs
        raise NutritionProviderUnavailable("timeout")


class InvalidProvider(NutritionEstimationProvider):
    def estimate(self, description, **kwargs):
        del description, kwargs
        return {"items": [{"calories": 10}]}


class LowConfidenceProvider(NutritionEstimationProvider):
    def estimate(self, description, **kwargs):
        del description, kwargs
        return NutritionEstimate(
            items=[
                EstimatedNutritionItem(
                    original_item_text="mystery",
                    normalized_name="mystery",
                    quantity_value=1,
                    quantity_unit="item",
                    calories=10,
                    protein_grams=1,
                    confidence=Decimal("0.3"),
                )
            ],
            provider_name="test",
            provider_version="1",
            confidence=Decimal("0.3"),
        )


@pytest.mark.parametrize(
    ("provider", "source"),
    [
        (UnavailableProvider(), "provider_unavailable"),
        (InvalidProvider(), "provider_invalid"),
    ],
)
def test_provider_failure_preserves_original_as_draft(
    nutrition_services,
    provider,
    source,
):
    service, owner_a, _ = nutrition_services
    draft = service.estimate_nutrition_draft(
        owner_a,
        NutritionDraftCreate(original_text="100 g paneer"),
        provider,
    )
    assert draft.original_text == "100 g paneer"
    assert draft.status == "draft"
    assert draft.estimation_source == source
    assert draft.clarification_question
    saved = service.save_unestimated_nutrition_log(owner_a, draft.id, draft.version)
    assert saved.status == "unestimated"


def test_low_confidence_requires_user_review(nutrition_services):
    service, owner_a, _ = nutrition_services
    draft = service.estimate_nutrition_draft(
        owner_a,
        NutritionDraftCreate(original_text="mystery food"),
        LowConfidenceProvider(),
    )
    assert draft.status == "draft"
    assert "low confidence" in draft.clarification_question.lower()


def test_manual_values_and_user_defined_targets(nutrition_services):
    service, owner_a, _ = nutrition_services
    preferences = service.get_nutrition_preferences(owner_a)
    updated_preferences = service.update_nutrition_preferences(
        owner_a,
        NutritionPreferenceUpdate(
            version=preferences.version,
            calorie_target=Decimal("2000"),
            protein_target_grams=Decimal("100"),
            default_milk_serving_ml=Decimal("300"),
        ),
    )
    assert updated_preferences.calorie_target == Decimal("2000")
    assert updated_preferences.protein_target_grams == Decimal("100")

    draft = service.create_nutrition_draft(
        owner_a,
        NutritionDraftCreate(original_text="Family recipe"),
    )
    manual = service.apply_manual_nutrition(
        owner_a,
        draft.id,
        NutritionManualSave(
            version=draft.version,
            items=[
                EstimatedNutritionItem(
                    original_item_text="Family recipe",
                    normalized_name="family recipe",
                    quantity_value=1,
                    quantity_unit="serving",
                    calories=Decimal("450"),
                    protein_grams=Decimal("20"),
                    visible_assumptions=["Values entered by user."],
                )
            ],
        ),
    )
    assert manual.status == "confirmed"
    assert manual.estimation_source == "manual"
    assert manual.user_modified is True


def test_invalid_provider_payload_rejects_hidden_or_missing_fields():
    with pytest.raises(Exception):
        validate_provider_payload(
            {
                "items": [],
                "provider_name": "bad",
                "provider_version": "1",
                "hidden_chain_of_thought": "must never be stored",
            }
        )


def test_groq_provider_validates_estimates_with_inferred_serving_assumptions():
    payload = {
        "items": [
            {
                "original_item_text": "aloo paratha",
                "normalized_name": "aloo paratha",
                "quantity_value": 1,
                "quantity_unit": "piece",
                "portion_description": "one medium paratha",
                "estimated_grams": 120,
                "calories": 280,
                "protein_grams": 7,
                "carbohydrate_grams": 42,
                "fat_grams": 10,
                "visible_assumptions": "One medium homemade paratha.",
                "confidence": 0.72,
            }
        ],
        "visible_assumptions": "One medium homemade paratha.",
        "confidence": 0.72,
        "clarification_required": False,
        "clarification_question": None,
    }
    provider = GroqNutritionProvider("test-key", "primary", "fallback")
    provider.client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=lambda **_kwargs: SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(content=json.dumps(payload))
                        )
                    ]
                )
            )
        )
    )

    estimate = provider.estimate(
        "I ate an aloo paratha",
        default_milk_serving_ml=Decimal("250"),
        measurement_system="metric",
    )

    assert estimate.items[0].calories == Decimal("280")
    assert estimate.items[0].protein_grams == Decimal("7")
    assert estimate.visible_assumptions
    assert estimate.provider_name == "groq"
