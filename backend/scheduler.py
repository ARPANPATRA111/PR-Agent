import logging
from datetime import datetime, timedelta
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

from config import settings
from memory import get_memory_manager
from llm_agent import get_llm_agent
from bot import TelegramClient
from utils import get_day_boundaries, get_week_boundaries

logger = logging.getLogger(__name__)

class SchedulerManager:
    
    def __init__(self):
        self.scheduler = AsyncIOScheduler()
        self.memory = get_memory_manager()
        self.agent = get_llm_agent()
        self.telegram = TelegramClient(settings.telegram_bot_token)
        self.timezone = pytz.timezone(settings.timezone)
        
        self._setup_jobs()
    
    def _setup_jobs(self):
        self.scheduler.add_job(
            self.run_daily_reflection,
            CronTrigger(
                hour=settings.daily_reflection_hour,
                minute=settings.daily_reflection_minute,
                timezone=self.timezone
            ),
            id="daily_reflection",
            name="Daily Reflection Generator",
            replace_existing=True
        )
        
        self.scheduler.add_job(
            self.run_weekly_summary,
            CronTrigger(
                day_of_week=settings.weekly_summary_day,
                hour=settings.weekly_summary_hour,
                minute=settings.weekly_summary_minute,
                timezone=self.timezone
            ),
            id="weekly_summary",
            name="Weekly Summary Generator",
            replace_existing=True
        )
        
        self.scheduler.add_job(
            self.run_morning_nudge,
            CronTrigger(
                hour=settings.morning_nudge_hour,
                minute=settings.morning_nudge_minute,
                timezone=self.timezone
            ),
            id="morning_nudge",
            name="Morning Nudge",
            replace_existing=True
        )
        
        self.scheduler.add_job(
            self.run_inactivity_check,
            CronTrigger(
                hour="*/4",
                minute=30,
                timezone=self.timezone
            ),
            id="inactivity_check",
            name="Inactivity Check",
            replace_existing=True
        )
        
        self.scheduler.add_job(
            self.run_evening_summary,
            CronTrigger(
                hour=settings.evening_summary_hour,
                minute=settings.evening_summary_minute,
                timezone=self.timezone
            ),
            id="evening_summary",
            name="Evening Daily Summary",
            replace_existing=True
        )
        
        if settings.enable_random_reminder:
            self.scheduler.add_job(
                self.schedule_random_reminder,
                CronTrigger(
                    hour=6,
                    minute=0,
                    timezone=self.timezone
                ),
                id="random_reminder_scheduler",
                name="Random Reminder Scheduler",
                replace_existing=True
            )
        
        logger.info("Scheduled jobs configured")
    
    def start(self):
        if not self.scheduler.running:
            self.scheduler.start()
            logger.info("Scheduler started")
    
    def shutdown(self):
        if self.scheduler.running:
            self.scheduler.shutdown()
            logger.info("Scheduler stopped")
    

    async def run_daily_reflection(self):
        logger.info("Starting daily reflection job")
        
        try:
            users_to_process = self._get_users_with_today_entries()
            
            for user_id in users_to_process:
                try:
                    await self._generate_daily_reflection_for_user(user_id)
                except Exception as e:
                    logger.error(f"Error generating daily reflection for user {user_id}: {e}")
            
            logger.info(f"Daily reflection completed for {len(users_to_process)} users")
            
        except Exception as e:
            logger.error(f"Daily reflection job failed: {e}", exc_info=True)
    
    def _get_users_with_today_entries(self) -> list:
        day_start, day_end = get_day_boundaries()
        
        with self.memory.get_session() as session:
            from memory import RawEntryDB
            
            users = session.query(RawEntryDB.telegram_id).filter(
                RawEntryDB.timestamp >= day_start,
                RawEntryDB.timestamp <= day_end
            ).distinct().all()
            
            return [u[0] for u in users]
    
    async def _generate_daily_reflection_for_user(self, user_id: int):
        day_start, day_end = get_day_boundaries()
        
        entries = self.memory.get_structured_entries_by_date(
            user_id, day_start, day_end
        )
        
        if not entries:
            logger.debug(f"No entries today for user {user_id}")
            return
        
        with self.memory.get_session() as session:
            from memory import UserDB
            user = session.query(UserDB).filter(
                UserDB.telegram_id == user_id
            ).first()
            user_name = user.first_name if user else "there"
        
        summary = self.agent.generate_daily_reflection(
            entries=entries,
            date=datetime.utcnow(),
            user_name=user_name
        )
        summary.telegram_id = user_id
        
        summary_id = self.memory.save_daily_summary(summary)
        
        reflection_message = f"""🌙 <b>Daily Reflection - {summary.date.strftime('%B %d')}</b>

📊 <b>Entries:</b> {summary.entries_count}
🎯 <b>Themes:</b> {', '.join(summary.themes) if summary.themes else 'General work'}

✨ <b>Achievements:</b>
{self._format_list(summary.achievements)}

💡 <b>Learnings:</b>
{self._format_list(summary.learnings)}

📝 <b>Reflection:</b>
{summary.reflection}

<i>Score: {summary.productivity_score or 'N/A'}/10</i>

<i>Great job today! 🌟 See you tomorrow!</i>"""
        
        await self.telegram.send_message(user_id, reflection_message)
        
        logger.info(f"Daily reflection sent to user {user_id}")
    
    def _format_list(self, items: list, max_items: int = 3) -> str:
        if not items:
            return "• None recorded"
        return "\n".join([f"• {item}" for item in items[:max_items]])
    

    async def run_weekly_summary(self):
        logger.info("Starting weekly summary job")
        
        try:
            users_to_process = self._get_users_with_week_entries()
            
            for user_id in users_to_process:
                try:
                    await self._generate_weekly_summary_for_user(user_id)
                except Exception as e:
                    logger.error(f"Error generating weekly summary for user {user_id}: {e}")
            
            logger.info(f"Weekly summary completed for {len(users_to_process)} users")
            
        except Exception as e:
            logger.error(f"Weekly summary job failed: {e}", exc_info=True)
    
    def _get_users_with_week_entries(self) -> list:
        week_start, week_end = get_week_boundaries()
        
        with self.memory.get_session() as session:
            from memory import RawEntryDB
            
            users = session.query(RawEntryDB.telegram_id).filter(
                RawEntryDB.timestamp >= week_start,
                RawEntryDB.timestamp <= week_end
            ).distinct().all()
            
            return [u[0] for u in users]
    
    async def _generate_weekly_summary_for_user(self, user_id: int):
        
        daily_summaries = self.memory.get_daily_summaries(user_id, days=7)
        
        if not daily_summaries:
            logger.debug(f"No daily summaries for user {user_id}")
            return
        
        themes = self.memory.detect_themes(user_id)
        
        previous_weekly = self.memory.get_latest_weekly_summary(user_id)
        
        recent_posts = self.memory.get_recent_post_embeddings(user_id, n_results=3)
        
        recent_published_posts = self.memory.get_published_posts(user_id, limit=5)
        
        weekly_summary = self.agent.generate_weekly_summary(
            daily_summaries=daily_summaries,
            themes=themes,
            previous_week=previous_weekly,
            recent_posts=recent_posts
        )
        weekly_summary.telegram_id = user_id
        
        weekly_id = self.memory.save_weekly_summary(weekly_summary)
        weekly_summary.id = weekly_id
        
        next_week = self.memory.get_next_week_number(user_id)
        
        posts = self.agent.generate_linkedin_posts(
            weekly_summary,
            recent_posts=recent_published_posts,
            week_number=next_week
        )
        
        for post in posts:
            post.telegram_id = user_id
            post.weekly_summary_id = weekly_id
            self.memory.save_linkedin_post(post)
        
        week_start, week_end = get_week_boundaries()
        
        notification = f"""📅 <b>Weekly Summary Ready!</b>

<b>Week:</b> {week_start.strftime('%B %d')} - {week_end.strftime('%B %d')}
<b>Total Entries:</b> {weekly_summary.total_entries}
<b>Main Themes:</b> {', '.join(weekly_summary.main_themes[:3])}

✨ <b>Top Accomplishments:</b>
{self._format_list(weekly_summary.accomplishments)}

📝 <b>LinkedIn Post Drafts:</b>
I've generated {len(posts)} post variants for you!

🔗 <i>View and edit them in the dashboard, or use /generate to see them here.</i>

Great week! 🎉"""
        
        await self.telegram.send_message(user_id, notification)
        
        logger.info(f"Weekly summary sent to user {user_id}")

    async def run_morning_nudge(self):
        logger.info("Starting morning nudge job")
        
        try:
            with self.memory.get_session() as session:
                from memory import UserDB
                
                week_ago = datetime.utcnow() - timedelta(days=7)
                active_users = session.query(UserDB).filter(
                    UserDB.last_active >= week_ago
                ).all()
                
                users_to_nudge = []
                
                for user in active_users:
                    day_start, _ = get_day_boundaries()
                    from memory import RawEntryDB
                    
                    today_entry = session.query(RawEntryDB).filter(
                        RawEntryDB.telegram_id == user.telegram_id,
                        RawEntryDB.timestamp >= day_start
                    ).first()
                    
                    if not today_entry:
                        users_to_nudge.append({
                            "id": user.telegram_id,
                            "name": user.first_name,
                            "streak": user.streak
                        })
            
            for user in users_to_nudge:
                try:
                    await self._send_nudge(
                        user_id=user["id"],
                        nudge_type="morning",
                        user_name=user["name"],
                        streak=user["streak"]
                    )
                except Exception as e:
                    logger.error(f"Error sending morning nudge to {user['id']}: {e}")
            
            logger.info(f"Morning nudge sent to {len(users_to_nudge)} users")
            
        except Exception as e:
            logger.error(f"Morning nudge job failed: {e}", exc_info=True)
    
    async def run_inactivity_check(self):
        logger.info("Starting autonomous inactivity check")
        
        try:
            users_to_nudge = self.memory.get_users_needing_nudge(
                hours_threshold=settings.nudge_threshold_hours
            )
            
            for user_id in users_to_nudge:
                try:
                    user_context = await self._build_user_context(user_id)
                    
                    if not user_context:
                        continue
                    
                    analysis = self.agent.autonomous_analyze(user_context)
                    
                    logger.info(
                        f"Autonomous analysis for user {user_id}: "
                        f"action={analysis['priority_action']}, "
                        f"confidence={analysis['confidence']}"
                    )
                    
                    if analysis['confidence'] >= 0.5:
                        decisions = analysis.get('decisions', {})
                        
                        if decisions.get('should_nudge', False):
                            nudge_type = decisions.get('nudge_type', 'gentle')
                            custom_message = decisions.get('custom_message')
                            
                            await self._send_autonomous_nudge(
                                user_id=user_id,
                                user_name=user_context.get('user_name', 'there'),
                                streak=user_context.get('streak', 0),
                                nudge_type=nudge_type,
                                custom_message=custom_message,
                                reasoning=analysis.get('reasoning', '')
                            )
                        elif decisions.get('should_encourage', False):
                            await self._send_encouragement(
                                user_id=user_id,
                                user_name=user_context.get('user_name', 'there'),
                                streak=user_context.get('streak', 0)
                            )
                    
                except Exception as e:
                    logger.error(f"Error in autonomous nudge for {user_id}: {e}")
            
            logger.info(f"Autonomous inactivity check completed for {len(users_to_nudge)} users")
            
        except Exception as e:
            logger.error(f"Autonomous inactivity check failed: {e}", exc_info=True)
    
    async def _build_user_context(self, user_id: int) -> Optional[dict]:
        try:
            with self.memory.get_session() as session:
                from memory import UserDB, RawEntryDB, StructuredEntryDB
                
                user = session.query(UserDB).filter(
                    UserDB.telegram_id == user_id
                ).first()
                
                if not user:
                    return None
                
                last_entry = session.query(RawEntryDB).filter(
                    RawEntryDB.telegram_id == user_id
                ).order_by(RawEntryDB.timestamp.desc()).first()
                
                if last_entry:
                    hours_since = (datetime.utcnow() - last_entry.timestamp).total_seconds() / 3600
                else:
                    hours_since = 48
                
                day_start, day_end = get_day_boundaries()
                today_count = session.query(RawEntryDB).filter(
                    RawEntryDB.telegram_id == user_id,
                    RawEntryDB.timestamp >= day_start,
                    RawEntryDB.timestamp <= day_end
                ).count()
                
                week_start, week_end = get_week_boundaries()
                week_count = session.query(RawEntryDB).filter(
                    RawEntryDB.telegram_id == user_id,
                    RawEntryDB.timestamp >= week_start,
                    RawEntryDB.timestamp <= week_end
                ).count()
                
                recent_entries = session.query(StructuredEntryDB).join(RawEntryDB).filter(
                    RawEntryDB.telegram_id == user_id
                ).order_by(RawEntryDB.timestamp.desc()).limit(10).all()
                
                themes = list(set([e.category.value for e in recent_entries if e.category]))
                
                now = datetime.now(self.timezone)
                
                return {
                    "telegram_id": user_id,
                    "user_name": user.first_name or "there",
                    "streak": user.streak or 0,
                    "time_since_last_entry": round(hours_since, 1),
                    "entry_count_today": today_count,
                    "entry_count_week": week_count,
                    "has_weekly_summary": False,
                    "recent_themes": themes[:5],
                    "current_hour": now.hour,
                    "day_of_week": now.strftime("%A")
                }
                
        except Exception as e:
            logger.error(f"Error building user context: {e}")
            return None
    
    async def _send_autonomous_nudge(
        self, 
        user_id: int, 
        user_name: str, 
        streak: int,
        nudge_type: str = "gentle",
        custom_message: str = None,
        reasoning: str = ""
    ):
        if custom_message:
            message = f"🤖 {custom_message}"
        else:
            message = self.agent.generate_nudge(
                nudge_type="reminder",
                user_name=user_name,
                streak=streak
            )
        
        try:
            await self.telegram.send_message(
                chat_id=user_id,
                text=message,
                parse_mode="HTML"
            )
            
            self.memory.log_nudge(
                telegram_id=user_id,
                nudge_type=f"autonomous_{nudge_type}",
                message=message[:200]
            )
            
            logger.info(f"Autonomous nudge ({nudge_type}) sent to {user_id}")
            
        except Exception as e:
            logger.error(f"Failed to send autonomous nudge to {user_id}: {e}")
    
    async def _send_encouragement(self, user_id: int, user_name: str, streak: int):
        insight = self.agent.generate_personalized_insight({
            "streak": streak,
            "themes": [],
            "trend": "positive"
        })
        
        message = f"""💪 <b>Hey {user_name}!</b>

{insight}

<i>Keep up the momentum! 🚀</i>"""
        
        try:
            await self.telegram.send_message(
                chat_id=user_id,
                text=message,
                parse_mode="HTML"
            )
            logger.info(f"Encouragement sent to {user_id}")
        except Exception as e:
            logger.error(f"Failed to send encouragement to {user_id}: {e}")
    
    async def run_evening_summary(self):
        logger.info("Starting evening summary job")
        
        try:
            users_to_process = self._get_users_with_today_entries()
            
            for user_id in users_to_process:
                try:
                    await self._generate_evening_summary_for_user(user_id)
                except Exception as e:
                    logger.error(f"Error generating evening summary for user {user_id}: {e}")
            
            logger.info(f"Evening summary completed for {len(users_to_process)} users")
            
        except Exception as e:
            logger.error(f"Evening summary job failed: {e}", exc_info=True)
    
    async def _generate_evening_summary_for_user(self, user_id: int):
        day_start, day_end = get_day_boundaries()
        
        entries = self.memory.get_structured_entries_by_date(
            user_id, day_start, day_end
        )
        
        if not entries:
            logger.debug(f"No entries today for user {user_id}")
            return
        
        total_entries = len(entries)
        activities = []
        accomplishments = []
        
        for entry in entries:
            if entry.activities:
                activities.extend(entry.activities)
            if entry.accomplishments:
                accomplishments.extend(entry.accomplishments)
        
        today = datetime.utcnow()
        summary_message = f"""🌙 <b>Evening Summary - {today.strftime('%B %d')}</b>

📝 <b>Today's Activity:</b> {total_entries} voice log{'s' if total_entries != 1 else ''}

✨ <b>What you did:</b>
{self._format_list(list(set(activities))[:5]) if activities else '• No activities logged'}

🎯 <b>Accomplishments:</b>
{self._format_list(list(set(accomplishments))[:5]) if accomplishments else '• Keep going!'}

💪 Great work today! Rest well and come back stronger tomorrow.

<i>Tip: Send a voice note now if you have anything else to log before bed!</i>"""
        
        await self.telegram.send_message(user_id, summary_message)
        logger.info(f"Evening summary sent to user {user_id}")
    
    async def schedule_random_reminder(self):
        import random
        
        logger.info("Scheduling random daily reminder")
        
        try:
            start_hour = settings.random_reminder_start_hour
            end_hour = settings.random_reminder_end_hour
            
            random_hour = random.randint(start_hour, end_hour)
            random_minute = random.randint(0, 59)
            
            now = datetime.now(self.timezone)
            reminder_time = now.replace(hour=random_hour, minute=random_minute, second=0, microsecond=0)
            
            if reminder_time <= now:
                logger.info(f"Random reminder time {random_hour}:{random_minute:02d} already passed")
                return
            
            self.scheduler.add_job(
                self.run_random_reminder,
                'date',
                run_date=reminder_time,
                id=f"random_reminder_{now.date()}",
                name="Random Daily Reminder",
                replace_existing=True
            )
            
            logger.info(f"Random reminder scheduled for {random_hour}:{random_minute:02d}")
            
        except Exception as e:
            logger.error(f"Failed to schedule random reminder: {e}", exc_info=True)
    
    async def run_random_reminder(self):
        logger.info("Running random daily reminder")
        
        try:
            with self.memory.get_session() as session:
                from memory import UserDB, RawEntryDB
                
                week_ago = datetime.utcnow() - timedelta(days=7)
                active_users = session.query(UserDB).filter(
                    UserDB.last_active >= week_ago
                ).all()
                
                users_to_remind = []
                day_start, _ = get_day_boundaries()
                
                for user in active_users:
                    today_entry = session.query(RawEntryDB).filter(
                        RawEntryDB.telegram_id == user.telegram_id,
                        RawEntryDB.timestamp >= day_start
                    ).first()
                    
                    if not today_entry:
                        users_to_remind.append({
                            'id': user.telegram_id,
                            'name': user.first_name
                        })
            
            for user in users_to_remind:
                try:
                    message = self._generate_random_reminder_message(user['name'])
                    await self.telegram.send_message(user['id'], message)
                    self.memory.log_nudge(user['id'], "random_reminder", message)
                except Exception as e:
                    logger.error(f"Error sending random reminder to {user['id']}: {e}")
            
            logger.info(f"Random reminder sent to {len(users_to_remind)} users")
            
        except Exception as e:
            logger.error(f"Random reminder job failed: {e}", exc_info=True)
    
    def _generate_random_reminder_message(self, user_name: str = "there") -> str:
        import random
        
        messages = [
            f"Hey {user_name}! 👋 Quick reminder to log your progress today. What have you been working on?",
            f"🎯 Don't forget to log your progress, {user_name}! Even small updates count.",
            f"📝 Time for a quick voice note, {user_name}? Share what you've accomplished today!",
            f"Hey {user_name}! 🚀 A quick voice log keeps your momentum going. What's up?",
            f"⏰ Friendly reminder, {user_name}! Your future self will thank you for logging today's work.",
            f"🌟 {user_name}, got a minute? Send a quick voice update about your progress!",
            f"💭 {user_name}, how's your day going? Drop a quick voice note to track your work!",
        ]
        
        return random.choice(messages)
    
    async def _send_nudge(self, user_id: int, nudge_type: str,
                         user_name: str = "there",
                         streak: int = 0,
                         last_entry_hours: int = 24):
        
        message = self.agent.generate_nudge(
            nudge_type=nudge_type,
            user_name=user_name,
            streak=streak,
            last_entry_hours=last_entry_hours
        )
        
        await self.telegram.send_message(user_id, message)
        
        self.memory.log_nudge(user_id, nudge_type, message)
        
        logger.debug(f"Sent {nudge_type} nudge to user {user_id}")

_scheduler_manager: Optional[SchedulerManager] = None


def get_scheduler() -> SchedulerManager:
    global _scheduler_manager
    if _scheduler_manager is None:
        _scheduler_manager = SchedulerManager()
    return _scheduler_manager
