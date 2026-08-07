import hashlib
import hmac
import json
import logging
import asyncio
import re
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import Optional, List
from urllib.parse import parse_qsl, urlencode

from fastapi import (
    FastAPI,
    HTTPException,
    Request,
    Response,
    Query,
    BackgroundTasks,
    Depends,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict

from auth import (
    AuthResponse,
    TelegramMiniAppAuthRequest,
    TokenData,
    authenticate_request,
    create_session,
    persist_application_session,
    revoke_application_session,
    validate_telegram_init_data,
)
from config import settings
from models import (
    TelegramUpdate,
    LinkedInPost,
    PostUpdateRequest,
    DashboardEntry,
    CalendarDay,
    WeeklyDashboard,
    PostStatus,
)
from memory import get_memory_manager
from bot import get_bot_handler, TelegramClient
from scheduler import get_scheduler
from utils import setup_logging, get_week_boundaries
from api.public_v2 import router as public_v2_router
from abuse_controls import BetaAccessRequired, InviteService
from domain.errors import DomainError
from domain.services import DomainServices
from telegram_cleanup import queue_telegram_message
from observability import operational_snapshot, runtime_metrics

setup_logging()
logger = logging.getLogger(__name__)

if settings.sentry_dsn:
    import sentry_sdk

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.app_env,
        send_default_pii=False,
        traces_sample_rate=0.05,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting PR-Agent Public Edition")
    legacy_scheduler = None
    inline_staging_loop = None
    inline_staging_task = None
    keep_alive_loop = None
    keep_alive_task = None
    app.state.inline_staging_loop = None
    app.state.telegram_delivery_status = "disabled"
    app.state.keep_alive_status = "disabled"
    try:
        memory = get_memory_manager()
        logger.info("Memory manager initialized")

        if settings.public_v2_enabled:
            if (
                settings.inline_staging_worker_enabled
                and settings.telegram_integration_enabled
            ):
                from inline_staging_worker import build_inline_staging_loop

                inline_staging_loop = build_inline_staging_loop()
                app.state.inline_staging_loop = inline_staging_loop
                inline_staging_task = asyncio.create_task(
                    inline_staging_loop.run_forever(),
                    name="inline-staging-delivery",
                )
                logger.warning(
                    "Public-v2 free staging uses best-effort inline delivery"
                )
                app.state.telegram_delivery_status = "running"
            elif settings.inline_staging_worker_enabled:
                app.state.telegram_delivery_status = "awaiting_telegram"
                logger.info(
                    "Telegram integration is disabled; pending delivery records "
                    "remain unclaimed until activation"
                )
            else:
                logger.info(
                    "Public-v2 uses the standalone durable worker; "
                    "legacy in-process schedules are disabled"
                )
        else:
            legacy_scheduler = get_scheduler()
            legacy_scheduler.start()
            logger.info("Legacy scheduler started")

        if settings.public_v2_enabled and settings.telegram_integration_enabled:
            # Best effort: a failure here must never stop the API from serving.
            try:
                from bot import get_bot_handler

                await get_bot_handler().telegram.set_my_commands()
                logger.info("Telegram command menu published")
            except Exception:
                logger.warning("Could not publish the Telegram command menu")

        if settings.keep_alive_enabled:
            from keep_alive import KeepAliveUnavailable, build_keep_alive_loop

            try:
                keep_alive_loop = build_keep_alive_loop()
            except KeepAliveUnavailable as exc:
                app.state.keep_alive_status = "misconfigured"
                logger.warning("Keep-alive self-ping unavailable: %s", exc)
            else:
                keep_alive_task = asyncio.create_task(
                    keep_alive_loop.run_forever(),
                    name="keep-alive-self-ping",
                )
                app.state.keep_alive_status = "running"

        logger.info(
            f"Bot token configured: {'Yes' if settings.telegram_bot_token else 'No'}"
        )
        logger.info(
            f"Groq API key configured: {'Yes' if settings.groq_api_key else 'No'}"
        )
        logger.info(f"Whisper model: {settings.whisper_model}")
        logger.info(f"Timezone: {settings.timezone}")

    except Exception:
        logger.exception("Application startup failed")
        raise

    logger.info("PR-Agent Public Edition started successfully")

    try:
        yield
    finally:
        logger.info("Shutting down PR-Agent Public Edition")

        if legacy_scheduler is not None:
            legacy_scheduler.shutdown()

        if inline_staging_loop is not None and inline_staging_task is not None:
            await inline_staging_loop.stop()
            await inline_staging_task
            app.state.inline_staging_loop = None

        if keep_alive_loop is not None and keep_alive_task is not None:
            await keep_alive_loop.stop()
            await keep_alive_task
            app.state.keep_alive_status = "stopped"

        logger.info("Shutdown complete")


def request_inline_staging_sweep() -> None:
    loop = getattr(app.state, "inline_staging_loop", None)
    if loop is not None:
        loop.request_sweep()


app = FastAPI(
    title="PR-Agent Public Edition",
    description="Invite-only multi-user Telegram tracking assistant",
    version="2.0.0-security-preview",
    lifespan=lifespan,
    docs_url=None if settings.app_env == "production" else "/docs",
    redoc_url=None if settings.app_env == "production" else "/redoc",
)

from rate_limiter import setup_rate_limiting, limiter, RATE_LIMITS

setup_rate_limiting(app)

app.include_router(public_v2_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["Content-Type", "Authorization", "X-CSRF-Token"],
    expose_headers=["X-Request-ID"],
)

PUBLIC_API_PATHS = {
    "/api/health",
    "/api/auth/telegram",
}

REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{8,128}$")


@app.middleware("http")
async def request_context(request: Request, call_next):
    supplied = request.headers.get("X-Request-ID", "")
    request_id = (
        supplied if REQUEST_ID_PATTERN.fullmatch(supplied) else uuid.uuid4().hex
    )
    request.state.request_id = request_id
    started = time.perf_counter()
    response = await call_next(request)
    latency_ms = round((time.perf_counter() - started) * 1000, 2)
    response.headers["X-Request-ID"] = request_id
    logger.info(
        "http_request",
        extra={
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "latency_ms": latency_ms,
        },
    )
    runtime_metrics.increment(f"http_status_{response.status_code}")
    return response


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), geolocation=(), microphone=()"
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    if settings.session_cookie_secure:
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )
    return response


@app.middleware("http")
async def enforce_private_api_identity(request: Request, call_next):
    path = request.url.path.rstrip("/") or "/"
    if (
        settings.public_v2_enabled
        and path.startswith("/api/")
        and not path.startswith("/api/v2/")
        and path
        not in {
            "/api/health",
            "/api/auth/telegram",
            "/api/auth/logout",
        }
    ):
        return JSONResponse(status_code=404, content={"detail": "Not found"})
    if (
        request.method == "OPTIONS"
        or not path.startswith("/api/")
        or path in PUBLIC_API_PATHS
    ):
        return await call_next(request)

    try:
        current_user = authenticate_request(request)
        request.state.current_user = current_user

        memory = get_memory_manager()
        allowed = memory.consume_rate_limit(
            subject_key=f"user:{current_user.user_id}",
            scope="private_api",
            limit=settings.per_user_requests_per_minute,
            window_seconds=60,
        )
        if not allowed:
            return JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded"},
            )

        # Temporary compatibility bridge for legacy route signatures. A
        # caller-supplied Telegram ID is removed and replaced only with the
        # authenticated server-side identity before request validation.
        query_pairs = [
            (key, value)
            for key, value in parse_qsl(
                request.scope.get("query_string", b"").decode("utf-8"),
                keep_blank_values=True,
            )
            if key != "telegram_id"
        ]
        query_pairs.append(("telegram_id", str(current_user.telegram_id)))
        request.scope["query_string"] = urlencode(query_pairs).encode("utf-8")
    except HTTPException as exc:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
        )
    except Exception:
        logger.exception("Private API security middleware failed")
        return JSONResponse(
            status_code=503,
            content={"detail": "Authentication service unavailable"},
        )

    response = await call_next(request)
    if response.status_code < 500:
        request_inline_staging_sweep()
    return response


@app.get("/", tags=["Health"])
@limiter.limit(RATE_LIMITS["health"])
async def root(request: Request, response: Response):
    return {
        "status": "healthy",
        "service": "PR-Agent Public Edition",
        "version": "2.0.0",
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.head("/", tags=["Health"])
@app.head("/health", tags=["Health"])
@limiter.limit(RATE_LIMITS["health"])
async def keep_alive_check(request: Request, response: Response):
    """Lightweight liveness endpoint for platform health checks."""
    return Response(status_code=200)


@app.get("/health", tags=["Health"])
@app.get("/api/health", tags=["Health"])
@limiter.limit(RATE_LIMITS["health"])
async def health_check(request: Request, response: Response):
    return {
        "status": "healthy",
        "service": "pr-agent-api",
        "version": "2.0.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/ready", tags=["Health"])
async def readiness_check():
    from sqlalchemy import text

    memory = get_memory_manager()
    session = memory.SessionLocal()
    try:
        session.execute(text("SELECT 1"))
    except Exception:
        runtime_metrics.increment("readiness_failures")
        return JSONResponse(
            status_code=503,
            content={"status": "not_ready", "database": "unavailable"},
        )
    try:
        revision = session.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one_or_none()
    except Exception:
        revision = "unversioned"
    finally:
        session.close()
    return {
        "status": "ready",
        "database": "connected",
        "migration_revision": revision,
        "environment": settings.app_env,
        "debug": settings.debug,
        "components": {
            "telegram": (
                "enabled" if settings.telegram_integration_enabled else "disabled"
            ),
            "telegram_delivery": getattr(
                app.state,
                "telegram_delivery_status",
                "disabled",
            ),
            "ai": "enabled" if settings.ai_agent_enabled else "disabled",
            "nutrition_provider": settings.nutrition_provider,
            "message_cleanup": (
                "enabled" if settings.message_cleanup_enabled else "disabled"
            ),
            "keep_alive": getattr(app.state, "keep_alive_status", "disabled"),
            # Exposed so configuration questions can be answered without the
            # hosting dashboard: whether daily caps apply, and how many
            # provider credentials the rotation actually picked up. Counts and
            # flags only; no credential material.
            "daily_quotas": "enforced" if settings.quotas_enabled else "unlimited",
            "groq_credentials": _configured_groq_credential_count(),
            "privacy_policy": (
                "published"
                if settings.privacy_policy_url.startswith("https://")
                else "unset"
            ),
        },
    }


def _configured_groq_credential_count() -> int:
    try:
        from groq_keys import configured_groq_keys

        return len(configured_groq_keys())
    except Exception:
        return 0


@app.get("/internal/metrics", tags=["Operations"])
def internal_metrics(request: Request):
    configured = settings.internal_monitoring_token
    if not configured:
        raise HTTPException(status_code=404, detail="Not found")
    supplied = request.headers.get("Authorization", "")
    expected = f"Bearer {configured}"
    if not hmac.compare_digest(supplied, expected):
        runtime_metrics.increment("monitoring_auth_rejections")
        raise HTTPException(status_code=401, detail="Unauthorized")
    memory = get_memory_manager()
    with memory.get_session() as session:
        return operational_snapshot(
            session,
            stale_after_seconds=settings.worker_heartbeat_stale_seconds,
        )


@app.post("/webhook", tags=["Telegram"])
@limiter.limit(RATE_LIMITS["webhook"])
async def telegram_webhook(
    request: Request, response: Response, background_tasks: BackgroundTasks
):
    if not settings.telegram_integration_enabled:
        raise HTTPException(
            status_code=503,
            detail="Telegram integration is disabled",
        )
    configured_secret = settings.telegram_webhook_secret
    if not configured_secret:
        raise HTTPException(
            status_code=503,
            detail="Telegram webhook is not configured",
        )

    provided_secret = request.headers.get(
        "X-Telegram-Bot-Api-Secret-Token",
        "",
    )
    if not provided_secret or not hmac.compare_digest(
        provided_secret,
        configured_secret,
    ):
        runtime_metrics.increment("telegram_auth_rejections")
        raise HTTPException(
            status_code=401,
            detail="Invalid Telegram webhook secret",
        )

    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > settings.max_webhook_body_bytes:
                raise HTTPException(status_code=413, detail="Webhook body too large")
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail="Invalid content length",
            ) from exc

    try:
        raw_body = await request.body()
        if len(raw_body) > settings.max_webhook_body_bytes:
            raise HTTPException(status_code=413, detail="Webhook body too large")
        data = json.loads(raw_body)
        update = TelegramUpdate(**data)

        if update.message and update.message.from_user:
            request.state.telegram_user_id = update.message.from_user.id
            subject = f"telegram:{update.message.from_user.id}"
        elif update.callback_query:
            request.state.telegram_user_id = update.callback_query.from_user.id
            subject = f"telegram:{update.callback_query.from_user.id}"
        else:
            subject = "telegram:unknown"

        memory = get_memory_manager()
        if not memory.register_telegram_update(update.update_id):
            runtime_metrics.increment("telegram_duplicate_updates")
            return JSONResponse(content={"ok": True, "duplicate": True})

        if not memory.consume_rate_limit(
            subject_key=subject,
            scope="telegram_webhook",
            limit=settings.per_user_requests_per_minute,
            window_seconds=60,
        ):
            runtime_metrics.increment("telegram_rate_limit_rejections")
            memory.mark_telegram_update(
                update.update_id,
                "failed",
                "rate_limited",
            )
            raise HTTPException(status_code=429, detail="Rate limit exceeded")

        async def process_update() -> None:
            try:
                if (
                    settings.message_cleanup_enabled
                    and update.message
                    and update.message.from_user
                ):

                    def ensure_cleanup_owner() -> None:
                        with memory.get_session() as session:
                            DomainServices(session).ensure_owner(
                                telegram_id=update.message.from_user.id,
                                first_name=update.message.from_user.first_name,
                                last_name=update.message.from_user.last_name,
                                username=update.message.from_user.username,
                            )

                    await asyncio.to_thread(ensure_cleanup_owner)
                await get_bot_handler().handle_update(update)
                if (
                    settings.message_cleanup_enabled
                    and update.message
                    and update.message.from_user
                ):

                    def queue_inbound_cleanup() -> None:
                        now = datetime.now(timezone.utc)
                        with memory.get_session() as session:
                            queue_telegram_message(
                                session,
                                telegram_id=update.message.from_user.id,
                                chat_id=update.message.chat.get("id"),
                                message_id=update.message.message_id,
                                direction="inbound",
                                purpose="processed_input",
                                processed_at=now,
                                delete_after=now
                                + timedelta(
                                    seconds=(settings.message_cleanup_delay_seconds)
                                ),
                            )

                    await asyncio.to_thread(queue_inbound_cleanup)
                memory.mark_telegram_update(update.update_id, "completed")
                request_inline_staging_sweep()
            except Exception as exc:
                memory.mark_telegram_update(
                    update.update_id,
                    "failed",
                    type(exc).__name__,
                )
                logger.exception(
                    "Telegram update processing failed",
                    extra={"update_id": update.update_id},
                )

        background_tasks.add_task(process_update)
        return JSONResponse(content={"ok": True, "duplicate": False})
    except HTTPException:
        raise
    except (json.JSONDecodeError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid Telegram update")
    except Exception as e:
        logger.exception("Webhook request failed")
        raise HTTPException(status_code=500, detail="Webhook processing failed") from e


@app.post(
    "/api/auth/telegram",
    response_model=AuthResponse,
    tags=["Authentication"],
)
def authenticate_telegram_mini_app(
    payload: TelegramMiniAppAuthRequest,
    request: Request,
    response: Response,
):
    if not settings.telegram_integration_enabled:
        raise HTTPException(
            status_code=503,
            detail="Telegram integration is disabled",
        )
    memory = get_memory_manager()
    remote_address = request.client.host if request.client else "unknown"
    subject_hash = hashlib.sha256(remote_address.encode("utf-8")).hexdigest()[:32]
    if not memory.consume_rate_limit(
        subject_key=f"auth_ip:{subject_hash}",
        scope="mini_app_auth",
        limit=10,
        window_seconds=60,
    ):
        raise HTTPException(status_code=429, detail="Rate limit exceeded")

    telegram_user = validate_telegram_init_data(payload.init_data)
    with memory.get_session() as session:
        owner = DomainServices(session).ensure_owner(
            telegram_id=telegram_user["telegram_id"],
            first_name=telegram_user["first_name"],
            last_name=telegram_user["last_name"],
            username=telegram_user["username"],
        )
        invites = InviteService(session)
        invite_claimed = False
        if payload.invite_code:
            invites.claim(owner.id, payload.invite_code)
            invite_claimed = True
        if (
            settings.public_v2_enabled
            and settings.invite_only
            and not invite_claimed
            and not invites.has_access(owner.id)
        ):
            raise BetaAccessRequired()
        owner_id = owner.id
        auth_user = {
            "id": owner.id,
            "telegram_id": owner.telegram_id,
            "username": owner.username,
            "first_name": owner.first_name,
        }

    session_token, csrf_token = create_session(
        user_id=owner_id,
        telegram_id=telegram_user["telegram_id"],
        username=telegram_user["username"],
    )
    with memory.get_session() as session:
        persist_application_session(
            session,
            session_token,
            owner_id=owner_id,
        )
    same_site = "none" if settings.session_cookie_secure else "lax"
    response.set_cookie(
        key=settings.session_cookie_name,
        value=session_token,
        max_age=settings.session_max_age_seconds,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite=same_site,
        path="/",
    )
    response.set_cookie(
        key=settings.csrf_cookie_name,
        value=csrf_token,
        max_age=settings.session_max_age_seconds,
        httponly=False,
        secure=settings.session_cookie_secure,
        samesite=same_site,
        path="/",
    )

    return AuthResponse(
        success=True,
        message="Authentication successful",
        access_token=session_token,
        csrf_token=csrf_token,
        expires_in=settings.session_max_age_seconds,
        user=auth_user,
    )


@app.post("/api/auth/logout", tags=["Authentication"])
async def logout(request: Request, response: Response):
    authorization = request.headers.get("Authorization", "")
    bearer_token = (
        authorization[7:].strip()
        if authorization.lower().startswith("bearer ")
        else None
    )
    token = request.cookies.get(settings.session_cookie_name) or bearer_token
    if token:
        memory = get_memory_manager()
        with memory.get_session() as session:
            revoke_application_session(session, token)
    response.delete_cookie(
        settings.session_cookie_name,
        path="/",
        secure=settings.session_cookie_secure,
    )
    response.delete_cookie(
        settings.csrf_cookie_name,
        path="/",
        secure=settings.session_cookie_secure,
    )
    return {"success": True}


class UserSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timezone: str = "UTC"
    display_name: str = ""
    default_tone: str = "professional"
    nudge_enabled: bool = True
    nudge_time: str = "09:00"
    daily_reflection_time: str = "00:00"
    weekly_summary_day: str = "0"
    weekly_summary_time: str = "00:00"


@app.get("/api/settings")
async def get_settings(request: Request):
    current_user: TokenData = request.state.current_user
    memory = get_memory_manager()
    user = memory.get_user(current_user.telegram_id)

    if user:
        prefs = user.preferences or {}
        display_name = (prefs.get("display_name") or "").strip() or (
            user.first_name or ""
        )
        return {
            "timezone": prefs.get("timezone", settings.timezone),
            "display_name": display_name,
            "default_tone": prefs.get("default_tone", "professional"),
            "nudge_enabled": prefs.get("nudge_enabled", True),
            "nudge_time": prefs.get("nudge_time", "09:00"),
            "daily_reflection_time": prefs.get("daily_reflection_time", "00:00"),
            "weekly_summary_day": str(prefs.get("weekly_summary_day", "0")),
            "weekly_summary_time": prefs.get("weekly_summary_time", "20:00"),
        }

    return {
        "timezone": settings.timezone,
        "display_name": "",
        "default_tone": "professional",
        "nudge_enabled": True,
        "nudge_time": "09:00",
        "daily_reflection_time": "00:00",
        "weekly_summary_day": "0",
        "weekly_summary_time": "20:00",
    }


@app.put("/api/settings")
async def update_settings(update: UserSettingsUpdate, request: Request):
    current_user: TokenData = request.state.current_user
    telegram_id = current_user.telegram_id
    memory = get_memory_manager()
    user = memory.get_user(telegram_id)

    if not user:
        fallback_name = (update.display_name or "").strip() or "User"
        memory.get_or_create_user(telegram_id=telegram_id, first_name=fallback_name)
        user = memory.get_user(telegram_id)

    memory.update_user_timezone(telegram_id, update.timezone)

    # Save nudge and notification settings to preferences
    prefs = (user.preferences or {}) if user else {}
    cleaned_display_name = (update.display_name or "").strip()
    prefs.update(
        {
            "display_name": cleaned_display_name,
            "default_tone": update.default_tone,
            "nudge_enabled": update.nudge_enabled,
            "nudge_time": update.nudge_time,
            "daily_reflection_time": update.daily_reflection_time,
            "weekly_summary_day": update.weekly_summary_day,
            "weekly_summary_time": update.weekly_summary_time,
            "timezone": update.timezone,
        }
    )
    memory.update_user_preferences(telegram_id, prefs)

    return {
        "success": True,
        "message": "Settings updated successfully",
        # Per-user durable schedules replace the unsafe global reschedule call
        # in Phase 6. Persisting preferences is safe; changing shared jobs is not.
        "schedule_applied": False,
    }


@app.get("/api/week-number")
async def get_week_number(telegram_id: int):
    memory = get_memory_manager()

    published_posts = memory.get_published_posts(telegram_id, limit=1)
    latest_posted = published_posts[0].week_number if published_posts else 0

    latest_any = memory.get_latest_week_number(telegram_id)

    next_week = memory.get_next_week_number(telegram_id)

    return {
        "next_week": next_week,
        "latest_posted": latest_posted or 0,
        "latest_any": latest_any or 0,
        "config_week": settings.current_week_number,
    }


@app.get("/api/entries")
async def get_entries(
    telegram_id: int,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    category: Optional[str] = None,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=10, le=100),
):
    memory = get_memory_manager()

    if start_date:
        start = datetime.fromisoformat(start_date)
    else:
        start = datetime.utcnow() - timedelta(days=30)

    if end_date:
        end = datetime.fromisoformat(end_date)
    else:
        end = datetime.utcnow()

    raw_entries = memory.get_raw_entries_by_date(telegram_id, start, end)
    structured_entries = memory.get_structured_entries_by_date(telegram_id, start, end)

    structured_map = {s.raw_entry_id: s for s in structured_entries}

    result = []
    for raw in raw_entries:
        structured = structured_map.get(raw.id)
        if category and structured and structured.category.value != category:
            continue
        if category and not structured:
            continue

        result.append(
            {
                "id": raw.id,
                "date": raw.timestamp.isoformat(),
                "created_at": raw.timestamp.isoformat(),
                "category": structured.category.value if structured else "other",
                "raw_text": raw.transcript,
                "structured_data": {
                    "summary": structured.summary if structured else "",
                    "activities": structured.activities if structured else [],
                    "blockers": structured.blockers if structured else [],
                    "accomplishments": structured.accomplishments if structured else [],
                    "learnings": structured.learnings if structured else [],
                    "keywords": structured.keywords if structured else [],
                    "sentiment": structured.sentiment if structured else "neutral",
                },
            }
        )

    result.sort(key=lambda x: x["date"], reverse=True)

    total = len(result)
    total_pages = (total + limit - 1) // limit
    start_idx = (page - 1) * limit
    end_idx = start_idx + limit
    paginated = result[start_idx:end_idx]

    return {
        "entries": paginated,
        "total": total,
        "page": page,
        "limit": limit,
        "total_pages": total_pages,
    }


@app.get("/api/calendar")
async def get_calendar(
    telegram_id: int,
    month: int = Query(ge=1, le=12),
    year: int = Query(ge=2020, le=2100),
):
    memory = get_memory_manager()

    calendar_data = memory.get_calendar_data(telegram_id, month, year)

    return {"calendar": calendar_data}


@app.get("/api/summaries")
async def get_summaries(
    telegram_id: int,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=10, le=50),
):
    memory = get_memory_manager()

    all_summaries = memory.get_daily_summaries(telegram_id, days=limit * page + limit)

    total = len(all_summaries)
    start_idx = (page - 1) * limit
    end_idx = start_idx + limit
    paginated = all_summaries[start_idx:end_idx]

    return {
        "summaries": [
            {
                "id": s.id,
                "date": s.date.isoformat(),
                "content": s.reflection or "",
                "entry_count": s.entries_count,
                "productivity_score": s.productivity_score or 0,
                "themes": s.themes or [],
                "highlights": s.achievements or [],
                "areas_for_improvement": s.learnings or [],
                "created_at": s.date.isoformat(),
            }
            for s in paginated
        ],
        "total": total,
        "page": page,
        "limit": limit,
        "total_pages": max(1, (total + limit - 1) // limit),
    }


@app.get("/api/summaries/daily")
async def get_daily_summaries(telegram_id: int, days: int = Query(default=7, le=30)):
    memory = get_memory_manager()

    summaries = memory.get_daily_summaries(telegram_id, days)

    return {
        "summaries": [
            {
                "id": s.id,
                "date": s.date.isoformat(),
                "entries_count": s.entries_count,
                "categories": s.categories,
                "achievements": s.achievements,
                "learnings": s.learnings,
                "reflection": s.reflection,
                "themes": s.themes,
                "productivity_score": s.productivity_score,
            }
            for s in summaries
        ]
    }


@app.get("/api/summaries/weekly")
async def get_weekly_summary(telegram_id: int):
    memory = get_memory_manager()

    summary = memory.get_latest_weekly_summary(telegram_id)

    if not summary:
        raise HTTPException(status_code=404, detail="No weekly summary found")

    return {
        "id": summary.id,
        "week_start": summary.week_start.isoformat(),
        "week_end": summary.week_end.isoformat(),
        "total_entries": summary.total_entries,
        "main_themes": summary.main_themes,
        "accomplishments": summary.accomplishments,
        "learnings": summary.learnings,
        "trends": summary.trends,
        "comparison": summary.comparison_with_previous,
    }


@app.get("/api/posts")
async def get_posts(telegram_id: int, limit: int = Query(default=10, le=50)):
    memory = get_memory_manager()

    posts = memory.get_recent_posts(telegram_id, limit)

    return {
        "posts": [
            {
                "id": p.id,
                "tone": p.tone.value,
                "content": p.edited_content or p.content,
                "original_content": p.content,
                "status": p.status.value,
                "created_at": p.created_at.isoformat(),
            }
            for p in posts
        ]
    }


@app.get("/api/posts/{post_id}")
async def get_post(post_id: int, request: Request):
    memory = get_memory_manager()
    current_user: TokenData = request.state.current_user
    post = memory.get_post(post_id, current_user.telegram_id)

    if not post:
        raise HTTPException(status_code=404, detail="Post not found")

    return {
        "id": post.id,
        "tone": post.tone.value,
        "content": post.edited_content or post.content,
        "original_content": post.content,
        "status": post.status.value,
        "created_at": post.created_at.isoformat(),
    }


@app.put("/api/posts/{post_id}")
async def update_post(post_id: int, update: PostUpdateRequest, request: Request):
    memory = get_memory_manager()
    current_user: TokenData = request.state.current_user
    success = memory.update_post(
        post_id=post_id,
        telegram_id=current_user.telegram_id,
        content=update.content,
        status=update.status,
    )

    if not success:
        raise HTTPException(status_code=404, detail="Post not found")

    return {"success": True, "post_id": post_id}


@app.delete("/api/posts/{post_id}")
async def delete_post(post_id: int, telegram_id: int):
    memory = get_memory_manager()

    success = memory.delete_linkedin_post(post_id, telegram_id)

    if not success:
        raise HTTPException(status_code=404, detail="Post not found")

    return {"success": True, "message": "Post deleted"}


@app.post("/api/posts/{post_id}/publish")
async def mark_post_published(
    post_id: int,
    request: Request,
    linkedin_url: Optional[str] = None,
    week_number: Optional[int] = None,
):
    memory = get_memory_manager()
    current_user: TokenData = request.state.current_user
    success = memory.mark_post_as_published(
        post_id=post_id,
        telegram_id=current_user.telegram_id,
        linkedin_url=linkedin_url,
        week_number=week_number,
    )

    if not success:
        raise HTTPException(status_code=404, detail="Post not found")

    return {"success": True, "post_id": post_id, "message": "Post marked as published"}


@app.get("/api/posts/published")
async def get_published_posts(telegram_id: int, limit: int = Query(default=50, le=100)):
    memory = get_memory_manager()

    posts = memory.get_published_posts(telegram_id, limit)

    return {"posts": [p.model_dump() for p in posts], "total": len(posts)}


class ImportPostRequest(BaseModel):
    content: str
    week_number: int
    published_at: Optional[datetime] = None
    linkedin_url: Optional[str] = None
    content_cutoff_date: Optional[datetime] = None


@app.post("/api/posts/import")
async def import_posted_report(request: ImportPostRequest, telegram_id: int):
    try:
        memory = get_memory_manager()

        report_id = memory.save_posted_report(
            telegram_id=telegram_id,
            week_number=request.week_number,
            content=request.content,
            published_at=request.published_at,
            linkedin_url=request.linkedin_url,
            content_cutoff_date=request.content_cutoff_date,
        )

        return {
            "success": True,
            "report_id": report_id,
            "week_number": request.week_number,
        }
    except Exception as e:
        logger.error(f"Failed to import posted report: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/posted-reports")
async def get_posted_reports(telegram_id: int, limit: int = 20, offset: int = 0):
    memory = get_memory_manager()
    reports = memory.get_posted_reports(telegram_id, limit, offset)
    total = memory.count_posted_reports(telegram_id)
    return {"reports": reports, "total": total}


@app.delete("/api/posted-reports/{report_id}")
async def delete_posted_report(report_id: int, telegram_id: int):
    memory = get_memory_manager()
    success = memory.delete_posted_report(report_id, telegram_id)

    if not success:
        raise HTTPException(status_code=404, detail="Report not found")

    return {"success": True, "message": "Report deleted"}


@app.delete("/api/entries/{entry_id}")
async def delete_entry(entry_id: int, telegram_id: int):
    memory = get_memory_manager()
    success = memory.delete_entry(entry_id, telegram_id)

    if not success:
        raise HTTPException(status_code=404, detail="Entry not found")

    return {"success": True, "message": "Entry deleted"}


@app.get("/api/entries/recent-for-delete")
async def get_recent_entries_for_delete(telegram_id: int, limit: int = 10):
    memory = get_memory_manager()
    entries = memory.get_recent_entries_for_deletion(telegram_id, limit)
    return {"entries": entries}


@app.get("/api/agent/analyze")
async def autonomous_analyze(telegram_id: int):
    from datetime import timedelta
    from llm_agent import get_llm_agent

    memory = get_memory_manager()
    agent = get_llm_agent()

    try:
        day_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)
        week_start = day_start - timedelta(days=day_start.weekday())
        week_end = week_start + timedelta(days=7)

        with memory.get_session() as session:
            from memory import UserDB, RawEntryDB, StructuredEntryDB

            user = (
                session.query(UserDB).filter(UserDB.telegram_id == telegram_id).first()
            )
            if not user:
                raise HTTPException(status_code=404, detail="User not found")

            last_entry = (
                session.query(RawEntryDB)
                .filter(RawEntryDB.telegram_id == telegram_id)
                .order_by(RawEntryDB.timestamp.desc())
                .first()
            )

            hours_since = 48
            if last_entry:
                hours_since = (
                    datetime.utcnow() - last_entry.timestamp
                ).total_seconds() / 3600

            today_count = (
                session.query(RawEntryDB)
                .filter(
                    RawEntryDB.telegram_id == telegram_id,
                    RawEntryDB.timestamp >= day_start,
                    RawEntryDB.timestamp <= day_end,
                )
                .count()
            )

            week_count = (
                session.query(RawEntryDB)
                .filter(
                    RawEntryDB.telegram_id == telegram_id,
                    RawEntryDB.timestamp >= week_start,
                    RawEntryDB.timestamp <= week_end,
                )
                .count()
            )

            recent_entries = (
                session.query(StructuredEntryDB)
                .join(RawEntryDB)
                .filter(RawEntryDB.telegram_id == telegram_id)
                .order_by(RawEntryDB.timestamp.desc())
                .limit(10)
                .all()
            )

            themes = list(set([e.category.value for e in recent_entries if e.category]))

            user_context = {
                "user_name": user.first_name or "User",
                "streak": user.streak or 0,
                "time_since_last_entry": round(hours_since, 1),
                "entry_count_today": today_count,
                "entry_count_week": week_count,
                "has_weekly_summary": False,
                "recent_themes": themes[:5],
                "current_hour": datetime.utcnow().hour,
                "day_of_week": datetime.utcnow().strftime("%A"),
            }

        analysis = agent.autonomous_analyze(user_context)

        return {
            "user_context": user_context,
            "analysis": {
                "plan": analysis.get("plan", []),
                "decisions": analysis.get("decisions", {}),
                "priority_action": analysis.get("priority_action", "monitor"),
                "confidence": analysis.get("confidence", 0.0),
            },
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Autonomous analysis failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/agent/insight")
async def get_agent_insight(telegram_id: int):
    from llm_agent import get_llm_agent

    memory = get_memory_manager()
    agent = get_llm_agent()

    try:
        with memory.get_session() as session:
            from memory import UserDB, StructuredEntryDB, RawEntryDB

            user = (
                session.query(UserDB).filter(UserDB.telegram_id == telegram_id).first()
            )
            if not user:
                raise HTTPException(status_code=404, detail="User not found")

            recent = (
                session.query(StructuredEntryDB)
                .join(RawEntryDB)
                .filter(RawEntryDB.telegram_id == telegram_id)
                .order_by(RawEntryDB.timestamp.desc())
                .limit(7)
                .all()
            )

            themes = list(set([e.category.value for e in recent if e.category]))[:5]

            user_data = {
                "streak": user.streak or 0,
                "entries_this_week": len(recent),
                "themes": themes,
                "trend": "stable",
            }

        insight = agent.generate_personalized_insight(user_data)

        return {"insight": insight, "user_stats": user_data}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Insight generation failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/posts/week/{week_number}")
async def get_posts_for_week(week_number: int, telegram_id: int):
    memory = get_memory_manager()

    posts = memory.get_drafts_for_week(telegram_id, week_number)

    return {
        "posts": [
            {
                "id": p.id,
                "content": p.edited_content or p.content,
                "status": p.status.value,
                "version": p.version,
                "created_at": p.created_at.isoformat(),
                "published_at": p.published_at.isoformat() if p.published_at else None,
                "week_number": p.week_number,
                "is_posted": p.status == PostStatus.POSTED,
            }
            for p in posts
        ],
        "week_number": week_number,
        "total_versions": len(posts),
        "has_posted": any(p.status == PostStatus.POSTED for p in posts),
    }


@app.post("/api/posts/week/{week_number}/regenerate")
async def regenerate_post_for_week(
    week_number: int,
    telegram_id: int,
    custom_instructions: Optional[str] = None,
    background_tasks: BackgroundTasks = None,
):
    from llm_agent import get_llm_agent

    memory = get_memory_manager()
    agent = get_llm_agent()

    entries = memory.get_entries(telegram_id, days=7)

    if not entries:
        raise HTTPException(
            status_code=400, detail="No entries found for the past week"
        )

    recent_published = memory.get_published_posts(telegram_id, limit=5)

    from datetime import timedelta
    from models import WeeklySummary

    all_activities = []
    all_blockers = []
    all_accomplishments = []
    all_learnings = []

    for entry in entries:
        if entry.activities:
            all_activities.extend(entry.activities)
        if entry.blockers:
            all_blockers.extend(entry.blockers)
        if entry.accomplishments:
            all_accomplishments.extend(entry.accomplishments)
        if entry.learnings:
            all_learnings.extend(entry.learnings)

    weekly_summary = WeeklySummary(
        telegram_id=telegram_id,
        week_start=datetime.utcnow() - timedelta(days=7),
        week_end=datetime.utcnow(),
        total_entries=len(entries),
        main_themes=(
            list(set(all_activities[:5])) if all_activities else ["General progress"]
        ),
        accomplishments=(
            list(set(all_accomplishments[:5])) if all_accomplishments else []
        ),
        learnings=list(set(all_learnings[:5])) if all_learnings else [],
        trends={"activities": all_activities[:10], "blockers": all_blockers[:5]},
    )

    posts = agent.generate_linkedin_posts(
        weekly_summary,
        custom_instructions=custom_instructions,
        recent_posts=recent_published,
        week_number=week_number,
    )

    for post in posts:
        post.telegram_id = telegram_id
        memory.save_linkedin_post(post)

    all_versions = memory.get_drafts_for_week(telegram_id, week_number)

    return {
        "success": True,
        "message": f"Generated new version for Week {week_number}",
        "new_version": len(all_versions),
        "total_versions": len(all_versions),
    }


@app.get("/api/stats")
async def get_stats(telegram_id: int):
    memory = get_memory_manager()

    stats = memory.get_user_stats(telegram_id)

    if not stats:
        raise HTTPException(status_code=404, detail="User not found")

    return stats


@app.get("/api/themes")
async def get_themes(telegram_id: int, n_clusters: int = Query(default=5, le=10)):
    memory = get_memory_manager()

    themes = memory.detect_themes(telegram_id, n_clusters)

    return {"themes": themes}


@app.post("/api/generate")
async def generate_posts(
    telegram_id: int,
    background_tasks: BackgroundTasks,
    custom_instructions: Optional[str] = None,
):
    from llm_agent import get_llm_agent
    from models import WeeklySummary

    memory = get_memory_manager()
    agent = get_llm_agent()

    daily_summaries = memory.get_daily_summaries(telegram_id, days=7)

    if not daily_summaries:
        start = datetime.utcnow() - timedelta(days=7)
        end = datetime.utcnow()
        entries = memory.get_structured_entries_by_date(telegram_id, start, end)

        if not entries or len(entries) < 1:
            raise HTTPException(
                status_code=400,
                detail="Not enough data. Please send some voice notes first!",
            )

        async def generate_from_entries():
            try:
                all_activities = []
                all_learnings = []
                all_accomplishments = []
                all_blockers = []
                all_themes = []

                for entry in entries:
                    if entry.activities:
                        all_activities.extend(entry.activities)
                    if entry.learnings:
                        all_learnings.extend(entry.learnings)
                    if entry.accomplishments:
                        all_accomplishments.extend(entry.accomplishments)
                    if entry.blockers:
                        all_blockers.extend(entry.blockers)
                    all_themes.append(entry.category.value)

                unique_themes = list(set(all_themes))[:5]

                weekly_summary = WeeklySummary(
                    telegram_id=telegram_id,
                    week_start=start,
                    week_end=end,
                    daily_summaries=[],
                    total_entries=len(entries),
                    main_themes=unique_themes if unique_themes else ["development"],
                    accomplishments=(
                        all_accomplishments[:5]
                        if all_accomplishments
                        else ["Made progress on projects"]
                    ),
                    learnings=all_learnings[:5] if all_learnings else [],
                    trends={
                        "activities": all_activities[:10],
                        "blockers": all_blockers[:5],
                        "productivity_trend": "stable",
                    },
                    comparison_with_previous=None,
                )

                weekly_id = memory.save_weekly_summary(weekly_summary)
                weekly_summary.id = weekly_id

                recent_published = memory.get_published_posts(telegram_id, limit=5)

                next_week = memory.get_next_week_number(telegram_id)

                posts = agent.generate_linkedin_posts(
                    weekly_summary,
                    custom_instructions=custom_instructions,
                    recent_posts=recent_published,
                    week_number=next_week,
                )

                for post in posts:
                    post.telegram_id = telegram_id
                    post.weekly_summary_id = weekly_id
                    memory.save_linkedin_post(post)

            except Exception as e:
                logger.error(f"Generation task failed: {e}", exc_info=True)

        background_tasks.add_task(generate_from_entries)

        return {
            "success": True,
            "message": "Post generation started. Check /api/posts in a few moments.",
        }

    async def generate_task():
        try:
            themes = memory.detect_themes(telegram_id)
            previous_weekly = memory.get_latest_weekly_summary(telegram_id)
            recent_posts = memory.get_recent_post_embeddings(telegram_id, n_results=3)

            weekly_summary = agent.generate_weekly_summary(
                daily_summaries=daily_summaries,
                themes=themes,
                previous_week=previous_weekly,
                recent_posts=recent_posts,
            )
            weekly_summary.telegram_id = telegram_id

            weekly_id = memory.save_weekly_summary(weekly_summary)
            weekly_summary.id = weekly_id

            recent_published = memory.get_published_posts(telegram_id, limit=5)

            next_week = memory.get_next_week_number(telegram_id)

            posts = agent.generate_linkedin_posts(
                weekly_summary,
                custom_instructions=custom_instructions,
                recent_posts=recent_published,
                week_number=next_week,
            )

            for post in posts:
                post.telegram_id = telegram_id
                post.weekly_summary_id = weekly_id
                memory.save_linkedin_post(post)

        except Exception as e:
            logger.error(f"Generation task failed: {e}", exc_info=True)

    background_tasks.add_task(generate_task)

    return {
        "success": True,
        "message": "Post generation started. Check /api/posts in a few moments.",
    }


@app.get("/api/search")
async def search_entries(
    telegram_id: int, query: str, limit: int = Query(default=10, le=50)
):
    memory = get_memory_manager()

    results = memory.search_similar_entries(
        query=query, n_results=limit, telegram_id=telegram_id
    )

    return {"results": results}


@app.get("/api/auth/me", tags=["Authentication"])
async def get_current_user_info(request: Request):
    user: TokenData = request.state.current_user
    memory = get_memory_manager()
    db_user = memory.get_user(user.telegram_id)

    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")

    return {
        "id": db_user.id,
        "telegram_id": db_user.telegram_id,
        "username": db_user.username,
        "first_name": db_user.first_name,
        "streak": db_user.streak,
        "total_entries": db_user.total_entries,
    }


@app.exception_handler(DomainError)
async def domain_error_handler(request: Request, exc: DomainError):
    del request
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.public_message},
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(
        "Unhandled application exception",
        extra={"error_category": type(exc).__name__},
    )

    from error_recovery import error_stats

    error_stats.record_error("global", exc)

    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "detail": str(exc) if settings.debug else "An unexpected error occurred",
        },
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=settings.debug)
