import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from typing import Optional, List

from fastapi import FastAPI, HTTPException, Request, Response, Query, BackgroundTasks, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from config import settings
from models import (
    TelegramUpdate, LinkedInPost, PostUpdateRequest,
    DashboardEntry, CalendarDay, WeeklyDashboard, PostStatus
)
from memory import get_memory_manager
from bot import get_bot_handler, TelegramClient
from scheduler import get_scheduler
from utils import setup_logging, get_week_boundaries

setup_logging()
logger = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Weekly Progress Agent...")
    
    try:
        memory = get_memory_manager()
        logger.info("Memory manager initialized")
        
        scheduler = get_scheduler()
        scheduler.start()
        logger.info("Scheduler started")
        
        logger.info(f"Bot token configured: {'Yes' if settings.telegram_bot_token else 'No'}")
        logger.info(f"Groq API key configured: {'Yes' if settings.groq_api_key else 'No'}")
        logger.info(f"Whisper model: {settings.whisper_model}")
        logger.info(f"Timezone: {settings.timezone}")
        
    except Exception as e:
        logger.error(f"Startup error: {e}", exc_info=True)
        raise
    
    logger.info("Weekly Progress Agent started successfully!")
    
    yield
    
    logger.info("Shutting down Weekly Progress Agent...")
    
    scheduler = get_scheduler()
    scheduler.shutdown()
    
    logger.info("Shutdown complete")

app = FastAPI(
    title="Weekly Progress Agent",
    description="AI-powered productivity tracking and LinkedIn post generation",
    version="1.1.0",
    lifespan=lifespan
)

from rate_limiter import setup_rate_limiting, limiter, RATE_LIMITS
setup_rate_limiting(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/", tags=["Health"])
@limiter.limit(RATE_LIMITS["health"])
async def root(request: Request, response: Response):
    return {
        "status": "healthy",
        "service": "Weekly Progress Agent",
        "version": "1.1.0",
        "timestamp": datetime.utcnow().isoformat()
    }


@app.get("/health", tags=["Health"])
@app.get("/api/health", tags=["Health"])
@limiter.limit(RATE_LIMITS["health"])
async def health_check(request: Request, response: Response):
    memory = get_memory_manager()
    scheduler = get_scheduler()
    
    from error_recovery import circuit_breakers
    
    return {
        "status": "healthy",
        "version": "1.1.0",
        "components": {
            "database": "connected",
            "vector_store": "connected",
            "scheduler": "running" if scheduler.scheduler.running else "stopped"
        },
        "circuit_breakers": {
            name: cb.get_status() for name, cb in circuit_breakers.items()
        },
        "timestamp": datetime.utcnow().isoformat()
    }

@app.post("/webhook", tags=["Telegram"])
@limiter.limit(RATE_LIMITS["webhook"])
async def telegram_webhook(request: Request, response: Response, background_tasks: BackgroundTasks):
    try:
        data = await request.json()
        update = TelegramUpdate(**data)
        
        if update.message and update.message.from_user:
            request.state.telegram_user_id = update.message.from_user.id
        
        bot_handler = get_bot_handler()
        background_tasks.add_task(bot_handler.handle_update, update)
        
        return JSONResponse(content={"ok": True})
        
    except Exception as e:
        logger.error(f"Webhook error: {e}", exc_info=True)
        return JSONResponse(content={"ok": True, "error": str(e)})


@app.post("/webhook/set")
async def set_webhook(url: Optional[str] = None):
    webhook_url = url or f"{settings.webhook_url}/webhook"
    
    telegram = TelegramClient(settings.telegram_bot_token)
    result = await telegram.set_webhook(webhook_url)
    
    return {
        "success": result.get("ok", False),
        "webhook_url": webhook_url,
        "result": result
    }


@app.get("/webhook/info")
async def get_webhook_info():
    telegram = TelegramClient(settings.telegram_bot_token)
    result = await telegram.get_webhook_info()
    
    return result


@app.post("/webhook/delete")
async def delete_webhook():
    telegram = TelegramClient(settings.telegram_bot_token)
    result = await telegram.delete_webhook()
    
    return result

class UserSettingsUpdate(BaseModel):
    telegram_id: str
    timezone: str = "UTC"
    default_tone: str = "professional"
    nudge_enabled: bool = True
    nudge_time: str = "09:00"
    daily_reflection_time: str = "00:00"
    weekly_summary_day: str = "0"
    weekly_summary_time: str = "00:00"


@app.get("/api/settings")
async def get_settings(telegram_id: Optional[int] = None):
    if telegram_id:
        memory = get_memory_manager()
        user = memory.get_user(telegram_id)
        
        if user:
            return {
                "telegram_id": str(user.telegram_id),
                "timezone": user.timezone or "UTC",
                "default_tone": "professional",
                "nudge_enabled": True,
                "nudge_time": "09:00",
                "daily_reflection_time": "00:00",
                "weekly_summary_day": "0",
                "weekly_summary_time": "20:00",
            }
    
    return {
        "telegram_id": "",
        "timezone": settings.timezone,
        "default_tone": "professional",
        "nudge_enabled": True,
        "nudge_time": "09:00",
        "daily_reflection_time": "00:00",
        "weekly_summary_day": "0",
        "weekly_summary_time": "20:00",
    }


@app.put("/api/settings")
async def update_settings(update: UserSettingsUpdate):
    if not update.telegram_id:
        raise HTTPException(status_code=400, detail="Telegram ID is required")
    
    try:
        telegram_id = int(update.telegram_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid Telegram ID format")
    
    memory = get_memory_manager()
    user = memory.get_user(telegram_id)
    
    if not user:
        raise HTTPException(
            status_code=404, 
            detail="User not found. Please start the bot with /start first."
        )
    
    memory.update_user_timezone(telegram_id, update.timezone)
    
    return {
        "success": True,
        "message": "Settings updated successfully",
        "telegram_id": str(telegram_id)
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
        "config_week": settings.current_week_number
    }

@app.get("/api/entries")
async def get_entries(
    telegram_id: int,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    category: Optional[str] = None,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=10, le=100)
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
        
        result.append({
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
                "sentiment": structured.sentiment if structured else "neutral"
            }
        })
    
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
        "total_pages": total_pages
    }


@app.get("/api/calendar")
async def get_calendar(
    telegram_id: int,
    month: int = Query(ge=1, le=12),
    year: int = Query(ge=2020, le=2100)
):
    memory = get_memory_manager()
    
    calendar_data = memory.get_calendar_data(telegram_id, month, year)
    
    return {"calendar": calendar_data}


@app.get("/api/summaries")
async def get_summaries(
    telegram_id: int,
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=10, le=50)
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
                "created_at": s.date.isoformat()
            }
            for s in paginated
        ],
        "total": total,
        "page": page,
        "limit": limit,
        "total_pages": max(1, (total + limit - 1) // limit)
    }


@app.get("/api/summaries/daily")
async def get_daily_summaries(
    telegram_id: int,
    days: int = Query(default=7, le=30)
):
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
                "productivity_score": s.productivity_score
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
        "comparison": summary.comparison_with_previous
    }


@app.get("/api/posts")
async def get_posts(
    telegram_id: int,
    limit: int = Query(default=10, le=50)
):
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
                "created_at": p.created_at.isoformat()
            }
            for p in posts
        ]
    }


@app.get("/api/posts/{post_id}")
async def get_post(post_id: int):
    memory = get_memory_manager()
    
    with memory.get_session() as session:
        from memory import LinkedInPostDB
        
        post = session.query(LinkedInPostDB).filter(
            LinkedInPostDB.id == post_id
        ).first()
        
        if not post:
            raise HTTPException(status_code=404, detail="Post not found")
        
        return {
            "id": post.id,
            "tone": post.tone,
            "content": post.edited_content or post.content,
            "original_content": post.content,
            "status": post.status,
            "created_at": post.created_at.isoformat()
        }


@app.put("/api/posts/{post_id}")
async def update_post(post_id: int, update: PostUpdateRequest):
    memory = get_memory_manager()
    
    success = memory.update_post(
        post_id=post_id,
        content=update.content,
        status=update.status
    )
    
    if not success:
        raise HTTPException(status_code=404, detail="Post not found")
    
    return {"success": True, "post_id": post_id}


@app.post("/api/posts/{post_id}/publish")
async def mark_post_published(
    post_id: int,
    linkedin_url: Optional[str] = None,
    week_number: Optional[int] = None
):
    memory = get_memory_manager()
    
    success = memory.mark_post_as_published(
        post_id=post_id,
        linkedin_url=linkedin_url,
        week_number=week_number
    )
    
    if not success:
        raise HTTPException(status_code=404, detail="Post not found")
    
    return {
        "success": True,
        "post_id": post_id,
        "message": "Post marked as published"
    }


@app.get("/api/posts/published")
async def get_published_posts(telegram_id: int, limit: int = Query(default=50, le=100)):
    memory = get_memory_manager()
    
    posts = memory.get_published_posts(telegram_id, limit)
    
    return {
        "posts": [p.model_dump() for p in posts],
        "total": len(posts)
    }


class ImportPostRequest(BaseModel):
    content: str
    week_number: int
    published_at: Optional[datetime] = None
    linkedin_url: Optional[str] = None


@app.post("/api/posts/import")
async def import_posted_report(
    request: ImportPostRequest,
    telegram_id: int
):
    try:
        memory = get_memory_manager()
        
        report_id = memory.save_posted_report(
            telegram_id=telegram_id,
            week_number=request.week_number,
            content=request.content,
            published_at=request.published_at,
            linkedin_url=request.linkedin_url
        )
        
        return {
            "success": True,
            "report_id": report_id,
            "week_number": request.week_number
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
            
            user = session.query(UserDB).filter(UserDB.telegram_id == telegram_id).first()
            if not user:
                raise HTTPException(status_code=404, detail="User not found")
            
            last_entry = session.query(RawEntryDB).filter(
                RawEntryDB.telegram_id == telegram_id
            ).order_by(RawEntryDB.timestamp.desc()).first()
            
            hours_since = 48
            if last_entry:
                hours_since = (datetime.utcnow() - last_entry.timestamp).total_seconds() / 3600
            
            today_count = session.query(RawEntryDB).filter(
                RawEntryDB.telegram_id == telegram_id,
                RawEntryDB.timestamp >= day_start,
                RawEntryDB.timestamp <= day_end
            ).count()
            
            week_count = session.query(RawEntryDB).filter(
                RawEntryDB.telegram_id == telegram_id,
                RawEntryDB.timestamp >= week_start,
                RawEntryDB.timestamp <= week_end
            ).count()
            
            recent_entries = session.query(StructuredEntryDB).join(RawEntryDB).filter(
                RawEntryDB.telegram_id == telegram_id
            ).order_by(RawEntryDB.timestamp.desc()).limit(10).all()
            
            themes = list(set([e.category.value for e in recent_entries if e.category]))
            
            user_context = {
                "telegram_id": telegram_id,
                "user_name": user.first_name or "User",
                "streak": user.streak or 0,
                "time_since_last_entry": round(hours_since, 1),
                "entry_count_today": today_count,
                "entry_count_week": week_count,
                "has_weekly_summary": False,
                "recent_themes": themes[:5],
                "current_hour": datetime.utcnow().hour,
                "day_of_week": datetime.utcnow().strftime("%A")
            }
        
        analysis = agent.autonomous_analyze(user_context)
        
        return {
            "user_context": user_context,
            "analysis": analysis
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
            
            user = session.query(UserDB).filter(UserDB.telegram_id == telegram_id).first()
            if not user:
                raise HTTPException(status_code=404, detail="User not found")
            
            recent = session.query(StructuredEntryDB).join(RawEntryDB).filter(
                RawEntryDB.telegram_id == telegram_id
            ).order_by(RawEntryDB.timestamp.desc()).limit(7).all()
            
            themes = list(set([e.category.value for e in recent if e.category]))[:5]
            
            user_data = {
                "streak": user.streak or 0,
                "entries_this_week": len(recent),
                "themes": themes,
                "trend": "stable"
            }
        
        insight = agent.generate_personalized_insight(user_data)
        
        return {"insight": insight, "user_stats": user_data}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Insight generation failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/posts/week/{week_number}")
async def get_posts_for_week(
    week_number: int,
    telegram_id: int
):
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
                "is_posted": p.status == PostStatus.POSTED
            }
            for p in posts
        ],
        "week_number": week_number,
        "total_versions": len(posts),
        "has_posted": any(p.status == PostStatus.POSTED for p in posts)
    }


@app.post("/api/posts/week/{week_number}/regenerate")
async def regenerate_post_for_week(
    week_number: int,
    telegram_id: int,
    custom_instructions: Optional[str] = None,
    background_tasks: BackgroundTasks = None
):
    from llm_agent import get_llm_agent
    
    memory = get_memory_manager()
    agent = get_llm_agent()
    
    entries = memory.get_entries(telegram_id, days=7)
    
    if not entries:
        raise HTTPException(
            status_code=400,
            detail="No entries found for the past week"
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
        main_themes=list(set(all_activities[:5])) if all_activities else ["General progress"],
        accomplishments=list(set(all_accomplishments[:5])) if all_accomplishments else [],
        learnings=list(set(all_learnings[:5])) if all_learnings else [],
        trends={"activities": all_activities[:10], "blockers": all_blockers[:5]}
    )
    
    posts = agent.generate_linkedin_posts(
        weekly_summary,
        custom_instructions=custom_instructions,
        recent_posts=recent_published,
        week_number=week_number
    )
    
    for post in posts:
        post.telegram_id = telegram_id
        memory.save_linkedin_post(post)
    
    all_versions = memory.get_drafts_for_week(telegram_id, week_number)
    
    return {
        "success": True,
        "message": f"Generated new version for Week {week_number}",
        "new_version": len(all_versions),
        "total_versions": len(all_versions)
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
    custom_instructions: Optional[str] = None
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
                detail="Not enough data. Please send some voice notes first!"
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
                    accomplishments=all_accomplishments[:5] if all_accomplishments else ["Made progress on projects"],
                    learnings=all_learnings[:5] if all_learnings else [],
                    trends={
                        "activities": all_activities[:10],
                        "blockers": all_blockers[:5],
                        "productivity_trend": "stable"
                    },
                    comparison_with_previous=None
                )
                
                weekly_id = memory.save_weekly_summary(weekly_summary)
                weekly_summary.id = weekly_id
                
                recent_published = memory.get_published_posts(telegram_id, limit=5)
                
                next_week = memory.get_next_week_number(telegram_id)
                
                posts = agent.generate_linkedin_posts(
                    weekly_summary,
                    custom_instructions=custom_instructions,
                    recent_posts=recent_published,
                    week_number=next_week
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
            "message": "Post generation started. Check /api/posts in a few moments."
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
                recent_posts=recent_posts
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
                week_number=next_week
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
        "message": "Post generation started. Check /api/posts in a few moments."
    }

@app.get("/api/search")
async def search_entries(
    telegram_id: int,
    query: str,
    limit: int = Query(default=10, le=50)
):
    memory = get_memory_manager()
    
    results = memory.search_similar_entries(
        query=query,
        n_results=limit,
        telegram_id=telegram_id
    )
    
    return {"results": results}

from auth import (
    Token, TokenData, AuthResponse, UserCredentials,
    get_current_user, get_current_user_optional, create_tokens,
    generate_verification_code, verify_telegram_code
)

@app.post("/api/auth/request-code", tags=["Authentication"])
@limiter.limit(RATE_LIMITS["auth"])
async def request_auth_code(request: Request, response: Response, telegram_id: int):
    memory = get_memory_manager()
    
    user = memory.get_user(telegram_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found. Please /start the bot first.")
    
    code = generate_verification_code(telegram_id)
    
    bot_handler = get_bot_handler()
    await bot_handler.telegram.send_message(
        telegram_id,
        f"🔐 Your login code is: <code>{code}</code>\n\n"
        f"This code expires in 5 minutes."
    )
    
    return {"success": True, "message": "Verification code sent to Telegram"}


@app.post("/api/auth/verify", response_model=AuthResponse, tags=["Authentication"])
@limiter.limit(RATE_LIMITS["auth"])
async def verify_auth_code(request: Request, response: Response, credentials: UserCredentials):
    if not credentials.verification_code:
        raise HTTPException(status_code=400, detail="Verification code required")
    
    if not verify_telegram_code(credentials.telegram_id, credentials.verification_code):
        raise HTTPException(status_code=401, detail="Invalid or expired verification code")
    
    memory = get_memory_manager()
    user = memory.get_user(credentials.telegram_id)
    
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    tokens = create_tokens(user.id, user.telegram_id, user.username)
    
    return AuthResponse(
        success=True,
        message="Authentication successful",
        token=tokens,
        user={
            "id": user.id,
            "telegram_id": user.telegram_id,
            "username": user.username,
            "first_name": user.first_name,
        }
    )


@app.get("/api/auth/me", tags=["Authentication"])
async def get_current_user_info(user: TokenData = Depends(get_current_user)):
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


@app.post("/api/admin/nudge", tags=["Admin"])
async def trigger_nudge(user_id: int, nudge_type: str = "reminder"):
    scheduler = get_scheduler()
    
    await scheduler._send_nudge(
        user_id=user_id,
        nudge_type=nudge_type,
        user_name="there"
    )
    
    return {"success": True, "message": f"Nudge sent to {user_id}"}


@app.post("/api/admin/daily-reflection")
async def trigger_daily_reflection():
    scheduler = get_scheduler()
    await scheduler.run_daily_reflection()
    
    return {"success": True, "message": "Daily reflection triggered"}


@app.post("/api/admin/weekly-summary")
async def trigger_weekly_summary():
    scheduler = get_scheduler()
    await scheduler.run_weekly_summary()
    
    return {"success": True, "message": "Weekly summary triggered"}

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    
    from error_recovery import error_stats
    error_stats.record_error("global", exc)
    
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "detail": str(exc) if settings.debug else "An unexpected error occurred"
        }
    )

if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.debug
    )
