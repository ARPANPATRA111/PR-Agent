"""Authenticated public-v2 CRUD API.

All handlers are synchronous so SQLAlchemy's synchronous sessions run in
FastAPI's worker thread pool rather than blocking the event loop.
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Generator, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from auth import TokenData, get_current_user
from config import settings
from domain.errors import DomainError, RecordNotFound
from domain.schemas import (
    GoalCreate,
    GoalResponse,
    GoalUpdate,
    LedgerCreate,
    LedgerCurrencySummary,
    LedgerResponse,
    LedgerUpdate,
    NoteCreate,
    NoteResponse,
    NoteUpdate,
    NutritionConfirm,
    NutritionDraftCreate,
    NutritionItemUpdate,
    NutritionLogResponse,
    NutritionManualSave,
    NutritionPeriodSummary,
    NutritionPreferenceResponse,
    NutritionPreferenceUpdate,
    ReminderCreate,
    ReminderResponse,
    ReminderUpdate,
    SchedulePreferenceResponse,
    SchedulePreferenceUpdate,
    WorkLogCreate,
    WorkLogResponse,
    WorkLogUpdate,
    AccountDeletionConfirm,
)
from domain.services import DomainServices
from memory import get_memory_manager
from nutrition.providers import get_nutrition_provider
from privacy import PrivacyService

router = APIRouter(prefix="/api/v2", tags=["Public v2"])


@dataclass
class DomainContext:
    service: DomainServices
    owner_id: int


def get_domain_context(
    current_user: TokenData = Depends(get_current_user),
) -> Generator[DomainContext, None, None]:
    if not settings.public_v2_enabled and settings.app_env in {
        "staging",
        "production",
    }:
        raise RecordNotFound("Public v2 is not enabled.")

    memory = get_memory_manager()
    session = memory.SessionLocal()
    try:
        service = DomainServices(session)
        owner = service.ensure_owner(
            telegram_id=current_user.telegram_id,
            username=current_user.username,
        )
        yield DomainContext(service=service, owner_id=owner.id)
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


Context = Depends(get_domain_context)


@router.post(
    "/work-logs",
    response_model=WorkLogResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_work_log(data: WorkLogCreate, context: DomainContext = Context):
    return context.service.create_work_log(context.owner_id, data)


@router.get("/work-logs", response_model=list[WorkLogResponse])
def list_work_logs(
    start_date: date | None = None,
    end_date: date | None = None,
    tag: str | None = Query(default=None, max_length=64),
    category: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=100_000),
    context: DomainContext = Context,
):
    if start_date and end_date and end_date < start_date:
        raise DomainError("end_date cannot be before start_date.")
    return context.service.list_work_logs(
        context.owner_id,
        start_date=start_date,
        end_date=end_date,
        tag=tag,
        category=category,
        limit=limit,
        offset=offset,
    )


@router.get("/work-logs/aggregate")
def aggregate_work_logs(
    start_date: date,
    end_date: date,
    context: DomainContext = Context,
):
    if end_date < start_date:
        raise DomainError("end_date cannot be before start_date.")
    return context.service.aggregate_work_logs(context.owner_id, start_date, end_date)


@router.get("/work-logs/{record_id}", response_model=WorkLogResponse)
def get_work_log(record_id: int, context: DomainContext = Context):
    return context.service.get_work_log(context.owner_id, record_id)


@router.patch("/work-logs/{record_id}", response_model=WorkLogResponse)
def update_work_log(
    record_id: int,
    data: WorkLogUpdate,
    context: DomainContext = Context,
):
    return context.service.update_work_log(context.owner_id, record_id, data)


@router.delete(
    "/work-logs/{record_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_work_log(record_id: int, context: DomainContext = Context):
    context.service.delete_work_log(context.owner_id, record_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/notes",
    response_model=NoteResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_note(data: NoteCreate, context: DomainContext = Context):
    return context.service.create_note(context.owner_id, data)


@router.get("/notes", response_model=list[NoteResponse])
def list_notes(
    search: str | None = Query(default=None, max_length=200),
    tag: str | None = Query(default=None, max_length=64),
    pinned: bool | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=100_000),
    context: DomainContext = Context,
):
    return context.service.list_notes(
        context.owner_id,
        search=search,
        tag=tag,
        pinned=pinned,
        limit=limit,
        offset=offset,
    )


@router.get("/notes/{record_id}", response_model=NoteResponse)
def get_note(record_id: int, context: DomainContext = Context):
    return context.service.get_note(context.owner_id, record_id)


@router.patch("/notes/{record_id}", response_model=NoteResponse)
def update_note(
    record_id: int,
    data: NoteUpdate,
    context: DomainContext = Context,
):
    return context.service.update_note(context.owner_id, record_id, data)


@router.delete("/notes/{record_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_note(record_id: int, context: DomainContext = Context):
    context.service.delete_note(context.owner_id, record_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/ledger",
    response_model=LedgerResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_ledger_entry(
    data: LedgerCreate,
    context: DomainContext = Context,
):
    return context.service.create_ledger_entry(context.owner_id, data)


@router.get("/ledger", response_model=list[LedgerResponse])
def list_ledger_entries(
    start_date: date | None = None,
    end_date: date | None = None,
    category: str | None = Query(default=None, max_length=64),
    direction: Literal["expense", "income"] | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=100_000),
    context: DomainContext = Context,
):
    if start_date and end_date and end_date < start_date:
        raise DomainError("end_date cannot be before start_date.")
    return context.service.list_ledger_entries(
        context.owner_id,
        start_date=start_date,
        end_date=end_date,
        category=category,
        direction=direction,
        limit=limit,
        offset=offset,
    )


@router.get("/ledger/summary", response_model=list[LedgerCurrencySummary])
def summarize_ledger(
    start_date: date | None = None,
    end_date: date | None = None,
    context: DomainContext = Context,
):
    if start_date and end_date and end_date < start_date:
        raise DomainError("end_date cannot be before start_date.")
    return context.service.summarize_ledger(
        context.owner_id,
        start_date=start_date,
        end_date=end_date,
    )


@router.get("/ledger/{record_id}", response_model=LedgerResponse)
def get_ledger_entry(record_id: int, context: DomainContext = Context):
    return context.service.get_ledger_entry(context.owner_id, record_id)


@router.patch("/ledger/{record_id}", response_model=LedgerResponse)
def update_ledger_entry(
    record_id: int,
    data: LedgerUpdate,
    context: DomainContext = Context,
):
    return context.service.update_ledger_entry(context.owner_id, record_id, data)


@router.delete("/ledger/{record_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_ledger_entry(record_id: int, context: DomainContext = Context):
    context.service.delete_ledger_entry(context.owner_id, record_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/goals",
    response_model=GoalResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_goal(data: GoalCreate, context: DomainContext = Context):
    return context.service.create_goal(context.owner_id, data)


@router.get("/goals", response_model=list[GoalResponse])
def list_goals(
    goal_status: Literal["active", "paused", "completed"] | None = Query(
        default=None,
        alias="status",
    ),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=100_000),
    context: DomainContext = Context,
):
    return context.service.list_goals(
        context.owner_id,
        status=goal_status,
        limit=limit,
        offset=offset,
    )


@router.get("/goals/{record_id}", response_model=GoalResponse)
def get_goal(record_id: int, context: DomainContext = Context):
    return context.service.get_goal(context.owner_id, record_id)


@router.patch("/goals/{record_id}", response_model=GoalResponse)
def update_goal(
    record_id: int,
    data: GoalUpdate,
    context: DomainContext = Context,
):
    return context.service.update_goal(context.owner_id, record_id, data)


@router.delete("/goals/{record_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_goal(record_id: int, context: DomainContext = Context):
    context.service.delete_goal(context.owner_id, record_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/reminders",
    response_model=ReminderResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_reminder(
    data: ReminderCreate,
    context: DomainContext = Context,
):
    return context.service.create_reminder(context.owner_id, data)


@router.get("/reminders", response_model=list[ReminderResponse])
def list_reminders(
    enabled: bool | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=100_000),
    context: DomainContext = Context,
):
    return context.service.list_reminders(
        context.owner_id,
        enabled=enabled,
        limit=limit,
        offset=offset,
    )


@router.get("/reminders/{record_id}", response_model=ReminderResponse)
def get_reminder(record_id: int, context: DomainContext = Context):
    return context.service.get_reminder(context.owner_id, record_id)


@router.patch("/reminders/{record_id}", response_model=ReminderResponse)
def update_reminder(
    record_id: int,
    data: ReminderUpdate,
    context: DomainContext = Context,
):
    return context.service.update_reminder(context.owner_id, record_id, data)


@router.delete(
    "/reminders/{record_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_reminder(record_id: int, context: DomainContext = Context):
    context.service.delete_reminder(context.owner_id, record_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/schedule-preferences",
    response_model=SchedulePreferenceResponse,
)
def get_schedule_preferences(context: DomainContext = Context):
    return context.service.get_schedule_preferences(context.owner_id)


@router.patch(
    "/schedule-preferences",
    response_model=SchedulePreferenceResponse,
)
def update_schedule_preferences(
    data: SchedulePreferenceUpdate,
    context: DomainContext = Context,
):
    return context.service.update_schedule_preferences(context.owner_id, data)


@router.get("/account/export")
def export_account_data(
    export_format: Literal["json", "csv"] = Query(default="json", alias="format"),
    context: DomainContext = Context,
):
    privacy = PrivacyService(context.service.session)
    payload = privacy.export_owner_data(context.owner_id)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
    if export_format == "csv":
        content = privacy.csv_zip_bytes(payload)
        filename = f"pr-agent-export-{stamp}.zip"
        media_type = "application/zip"
    else:
        content = privacy.json_bytes(payload)
        filename = f"pr-agent-export-{stamp}.json"
        media_type = "application/json"
    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.delete("/account", status_code=status.HTTP_204_NO_CONTENT)
def delete_account(
    data: AccountDeletionConfirm,
    current_user: TokenData = Depends(get_current_user),
    context: DomainContext = Context,
):
    issued_at = current_user.issued_at
    if issued_at is None or datetime.now(timezone.utc) - issued_at > timedelta(
        seconds=settings.account_deletion_recent_auth_seconds
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Recent Telegram authentication is required before " "account deletion."
            ),
        )
    PrivacyService(context.service.session).delete_account(
        context.owner_id,
        current_user.telegram_id,
        audit_secret=settings.effective_session_signing_secret,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/nutrition/preferences",
    response_model=NutritionPreferenceResponse,
)
def get_nutrition_preferences(context: DomainContext = Context):
    return context.service.get_nutrition_preferences(context.owner_id)


@router.patch(
    "/nutrition/preferences",
    response_model=NutritionPreferenceResponse,
)
def update_nutrition_preferences(
    data: NutritionPreferenceUpdate,
    context: DomainContext = Context,
):
    return context.service.update_nutrition_preferences(context.owner_id, data)


@router.get(
    "/nutrition/summary",
    response_model=NutritionPeriodSummary,
)
def summarize_nutrition(
    start_date: date,
    end_date: date,
    context: DomainContext = Context,
):
    return context.service.summarize_nutrition(
        context.owner_id,
        start_date,
        end_date,
    )


@router.post(
    "/nutrition",
    response_model=NutritionLogResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_nutrition_preview(
    data: NutritionDraftCreate,
    context: DomainContext = Context,
):
    provider = get_nutrition_provider(settings.nutrition_provider)
    return context.service.estimate_nutrition_draft(
        context.owner_id,
        data,
        provider,
    )


@router.get("/nutrition", response_model=list[NutritionLogResponse])
def list_nutrition_logs(
    start_date: date | None = None,
    end_date: date | None = None,
    nutrition_status: Literal["draft", "confirmed", "unestimated"] | None = Query(
        default=None,
        alias="status",
    ),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=100_000),
    context: DomainContext = Context,
):
    if start_date and end_date and end_date < start_date:
        raise DomainError("end_date cannot be before start_date.")
    return context.service.list_nutrition_logs(
        context.owner_id,
        start_date=start_date,
        end_date=end_date,
        status=nutrition_status,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/nutrition/{record_id}",
    response_model=NutritionLogResponse,
)
def get_nutrition_log(record_id: int, context: DomainContext = Context):
    return context.service.get_nutrition_log(context.owner_id, record_id)


@router.post(
    "/nutrition/{record_id}/confirm",
    response_model=NutritionLogResponse,
)
def confirm_nutrition_log(
    record_id: int,
    data: NutritionConfirm,
    context: DomainContext = Context,
):
    return context.service.confirm_nutrition_log(
        context.owner_id, record_id, data.version
    )


@router.post(
    "/nutrition/{record_id}/manual",
    response_model=NutritionLogResponse,
)
def save_manual_nutrition(
    record_id: int,
    data: NutritionManualSave,
    context: DomainContext = Context,
):
    return context.service.apply_manual_nutrition(context.owner_id, record_id, data)


@router.post(
    "/nutrition/{record_id}/unestimated",
    response_model=NutritionLogResponse,
)
def save_unestimated_nutrition(
    record_id: int,
    data: NutritionConfirm,
    context: DomainContext = Context,
):
    return context.service.save_unestimated_nutrition_log(
        context.owner_id, record_id, data.version
    )


@router.patch(
    "/nutrition/{record_id}/items/{item_id}",
    response_model=NutritionLogResponse,
)
def update_nutrition_item(
    record_id: int,
    item_id: int,
    data: NutritionItemUpdate,
    context: DomainContext = Context,
):
    return context.service.update_nutrition_item(
        context.owner_id,
        record_id,
        item_id,
        data,
    )


@router.delete(
    "/nutrition/{record_id}/items/{item_id}",
    response_model=NutritionLogResponse,
)
def delete_nutrition_item(
    record_id: int,
    item_id: int,
    context: DomainContext = Context,
):
    return context.service.delete_nutrition_item(
        context.owner_id,
        record_id,
        item_id,
    )


@router.delete(
    "/nutrition/{record_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_nutrition_log(
    record_id: int,
    context: DomainContext = Context,
):
    context.service.delete_nutrition_log(context.owner_id, record_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
