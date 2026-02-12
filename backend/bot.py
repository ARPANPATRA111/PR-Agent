import logging
from datetime import datetime
from typing import Optional, Dict

import httpx

from config import settings
from models import (
    TelegramUpdate, TelegramMessage, RawEntry, StructuredEntry,
    EntryCategory, StatusResponse
)
from memory import get_memory_manager
from llm_agent import get_llm_agent
from utils import (
    transcribe_telegram_voice, format_streak, format_duration,
    extract_keywords, get_day_boundaries
)

logger = logging.getLogger(__name__)

class TelegramClient:
    def __init__(self, token: str):
        self.token = token
        self.base_url = f"https://api.telegram.org/bot{token}"
        self._max_retries = 3
        self._base_delay = 1.0
    
    async def _request_with_retry(
        self,
        method: str,
        endpoint: str,
        **kwargs
    ) -> dict:
        import asyncio
        import random
        
        last_error = None
        
        for attempt in range(self._max_retries + 1):
            try:
                async with httpx.AsyncClient() as client:
                    if method.upper() == "GET":
                        response = await client.get(
                            f"{self.base_url}/{endpoint}",
                            timeout=30,
                            **kwargs
                        )
                    else:
                        response = await client.post(
                            f"{self.base_url}/{endpoint}",
                            timeout=30,
                            **kwargs
                        )
                    
                    result = response.json()
                    
                    if not result.get("ok") and result.get("error_code") == 429:
                        retry_after = result.get("parameters", {}).get("retry_after", 5)
                        logger.warning(f"Rate limited by Telegram. Waiting {retry_after}s...")
                        await asyncio.sleep(retry_after)
                        continue
                    
                    return result
                    
            except (httpx.TimeoutException, httpx.NetworkError) as e:
                last_error = e
                
                if attempt < self._max_retries:
                    delay = self._base_delay * (2 ** attempt) + random.random()
                    logger.warning(
                        f"Telegram API request failed (attempt {attempt + 1}): {e}. "
                        f"Retrying in {delay:.1f}s..."
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(f"All retries failed for Telegram API: {e}")
                    raise
        
        raise last_error
    
    async def send_message(self, chat_id: int, text: str,
                          parse_mode: str = "HTML",
                          reply_to_message_id: Optional[int] = None) -> dict:
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode
        }
        
        if reply_to_message_id:
            payload["reply_to_message_id"] = reply_to_message_id
        
        return await self._request_with_retry("POST", "sendMessage", json=payload)
    
    async def send_typing_action(self, chat_id: int) -> None:
        try:
            await self._request_with_retry(
                "POST", "sendChatAction",
                json={"chat_id": chat_id, "action": "typing"}
            )
        except Exception:
            pass
    
    async def set_webhook(self, url: str) -> dict:
        return await self._request_with_retry(
            "POST", "setWebhook",
            json={"url": url, "allowed_updates": ["message"]}
        )
    
    async def delete_webhook(self) -> dict:
        return await self._request_with_retry("POST", "deleteWebhook")
    
    async def get_webhook_info(self) -> dict:
        return await self._request_with_retry("GET", "getWebhookInfo")


class BotHandler:
    def __init__(self):
        self.telegram = TelegramClient(settings.telegram_bot_token)
        self.memory = get_memory_manager()
        self.agent = get_llm_agent()
    
    async def handle_update(self, update: TelegramUpdate) -> None:
        if not update.message:
            logger.debug("Update has no message, skipping")
            return
        
        message = update.message
        chat_id = message.chat.get("id")
        user_id = message.from_user.id if message.from_user else None
        
        if settings.telegram_admin_id and user_id != settings.telegram_admin_id:
            logger.warning(f"Unauthorized access attempt from user {user_id}")
            return
        
        try:
            if message.from_user:
                self.memory.get_or_create_user(
                    telegram_id=message.from_user.id,
                    first_name=message.from_user.first_name,
                    last_name=message.from_user.last_name,
                    username=message.from_user.username
                )
            
            if message.voice:
                await self._handle_voice(message)
            elif message.text:
                if message.text.startswith("/"):
                    await self._handle_command(message)
                else:
                    await self._handle_text(message)
            else:
                await self.telegram.send_message(
                    chat_id,
                    "📢 I work best with voice notes! Send me a voice message about your progress."
                )
                
        except Exception as e:
            logger.error(f"Error handling update: {e}", exc_info=True)
            await self.telegram.send_message(
                chat_id,
                "❌ Sorry, something went wrong. Please try again."
            )
    
    async def _handle_voice(self, message: TelegramMessage) -> None:
        chat_id = message.chat.get("id")
        user_id = message.from_user.id if message.from_user else 0
        
        await self.telegram.send_typing_action(chat_id)
        
        await self.telegram.send_message(
            chat_id,
            "🎙️ Got your voice note! Processing...",
            reply_to_message_id=message.message_id
        )
        
        try:
            logger.info(f"Transcribing voice note from user {user_id}")
            transcript = await transcribe_telegram_voice(
                message.voice.file_id,
                settings.telegram_bot_token
            )
            
            if not transcript or len(transcript.strip()) < 10:
                await self.telegram.send_message(
                    chat_id,
                    "🔇 I couldn't hear anything clear in that recording. Could you try again?"
                )
                return
            
            validation = self.agent.validate_content_relevance(transcript)
            if not validation["is_relevant"] and validation["confidence"] > 0.7:
                logger.warning(f"Content not relevant for user {user_id}: {validation['reason']}")
                await self.telegram.send_message(
                    chat_id,
                    f"⚠️ <b>Content Not Related</b>\n\n"
                    f"This doesn't seem to be about work or learning progress.\n\n"
                    f"📋 <b>Detected:</b> {validation['category'].title()}\n"
                    f"💡 <b>Tip:</b> Share updates about coding, learning, meetings, blockers, or achievements!\n\n"
                    f"<i>If you think this is a mistake, try rephrasing your update.</i>",
                    parse_mode="HTML"
                )
                return
            
            logger.info(f"Classifying transcript: {len(transcript)} chars")
            classification = self.agent.classify_entry(transcript)
            
            raw_entry = RawEntry(
                telegram_id=user_id,
                telegram_message_id=message.message_id,
                timestamp=datetime.utcfromtimestamp(message.date),
                audio_file_id=message.voice.file_id,
                audio_duration=message.voice.duration,
                transcript=transcript
            )
            raw_entry_id = self.memory.save_raw_entry(raw_entry)
            
            structured_entry = StructuredEntry(
                raw_entry_id=raw_entry_id,
                category=classification.category,
                activities=classification.activities,
                blockers=classification.blockers,
                accomplishments=classification.accomplishments,
                learnings=classification.learnings,
                summary=classification.summary,
                keywords=classification.keywords,
                sentiment=classification.sentiment
            )
            self.memory.save_structured_entry(structured_entry)
            
            keywords_str = ",".join(classification.keywords) if classification.keywords else ""
            self.memory.add_to_vector_memory(
                entry_id=raw_entry_id,
                text=transcript,
                metadata={
                    "telegram_id": user_id,
                    "category": classification.category.value,
                    "timestamp": datetime.utcnow().isoformat(),
                    "keywords": keywords_str
                }
            )
            
            streak = self.memory.update_user_streak(user_id)
            
            category_emoji = self._get_category_emoji(classification.category)
            duration_str = format_duration(message.voice.duration)
            streak_str = format_streak(streak)
            
            response = f"""✅ <b>Entry Logged!</b>

{category_emoji} <b>Category:</b> {classification.category.value.title()}

📝 <b>Summary:</b>
{classification.summary}

{self._format_entry_details(classification)}

{streak_str}

<i>Duration: {duration_str}</i>"""
            
            await self.telegram.send_message(chat_id, response)
            
            logger.info(f"Successfully processed voice note for user {user_id}")
            
        except Exception as e:
            logger.error(f"Error processing voice note: {e}", exc_info=True)
            await self.telegram.send_message(
                chat_id,
                "❌ Error processing your voice note. Please try again."
            )
    
    def _get_category_emoji(self, category: EntryCategory) -> str:
        emojis = {
            EntryCategory.CODING: "💻",
            EntryCategory.LEARNING: "📚",
            EntryCategory.DEBUGGING: "🐛",
            EntryCategory.RESEARCH: "🔍",
            EntryCategory.MEETING: "👥",
            EntryCategory.PLANNING: "📋",
            EntryCategory.BLOCKERS: "🚧",
            EntryCategory.ACHIEVEMENT: "🏆",
            EntryCategory.OTHER: "📌"
        }
        return emojis.get(category, "📌")
    
    def _format_entry_details(self, classification) -> str:
        parts = []
        
        if classification.activities:
            parts.append(f"🎯 <b>Activities:</b> {', '.join(classification.activities[:3])}")
        
        if classification.accomplishments:
            parts.append(f"✨ <b>Done:</b> {', '.join(classification.accomplishments[:3])}")
        
        if classification.blockers:
            parts.append(f"⚠️ <b>Blockers:</b> {', '.join(classification.blockers[:2])}")
        
        if classification.learnings:
            parts.append(f"💡 <b>Learned:</b> {', '.join(classification.learnings[:2])}")
        
        return "\n".join(parts) if parts else ""
    
    async def _handle_command(self, message: TelegramMessage) -> None:
        chat_id = message.chat.get("id")
        command = message.text.split()[0].lower()
        
        commands = {
            "/start": self._cmd_start,
            "/help": self._cmd_help,
            "/status": self._cmd_status,
            "/summary": self._cmd_summary,
            "/generate": self._cmd_generate,
            "/stats": self._cmd_status,
            "/delete": self._cmd_delete,
            "/recent": self._cmd_recent,
        }
        
        handler = commands.get(command)
        
        if handler:
            await handler(message)
        else:
            await self.telegram.send_message(
                chat_id,
                "❓ Unknown command. Use /help to see available commands."
            )
    
    async def _cmd_start(self, message: TelegramMessage) -> None:
        chat_id = message.chat.get("id")
        user_name = message.from_user.first_name if message.from_user else "there"
        
        welcome = f"""👋 <b>Welcome to Weekly Progress Agent, {user_name}!</b>

I'm your personal productivity assistant. I help you:

🎙️ <b>Track Progress:</b> Send voice notes about your daily work
📊 <b>Get Insights:</b> Automatic daily reflections and summaries
📝 <b>LinkedIn Posts:</b> Weekly generated posts for your network

<b>How to use:</b>
1. Send me voice notes about what you're working on
2. I'll transcribe, categorize, and remember everything
3. Get daily summaries and weekly LinkedIn post drafts!

<b>Commands:</b>
/status - See your streak and stats
/summary - Get your latest summary
/generate - Generate LinkedIn post drafts
/help - Show all commands

<i>💡 Tip: Voice notes work best! Just talk naturally about your day.</i>

Ready to start? Send me your first voice note! 🚀"""
        
        await self.telegram.send_message(chat_id, welcome)
    
    async def _cmd_help(self, message: TelegramMessage) -> None:
        chat_id = message.chat.get("id")
        
        help_text = """📚 <b>Weekly Progress Agent - Help</b>

<b>🎙️ Voice Notes</b>
Send a voice message about:
• What you worked on
• What you learned
• Blockers or challenges
• Accomplishments

<b>📝 Text Logging</b>
<code>#log Worked on API, fixed 3 bugs</code>
<code>#progress Learned React hooks today</code>

<b>Commands</b>
/status - Your streak and stats
/summary - Today's logged entries
/summary DD-MM-YYYY DD-MM-YYYY - Date range summary
/generate - Generate LinkedIn post
/recent - Show recent entries
/delete [ID] - Delete an entry
/help - This help

<b>Examples</b>
<code>/summary</code> - Today's summary
<code>/summary 01-02-2026 07-02-2026</code> - Week summary

<b>🤖 Features</b>
• Asks clarifying questions if unclear
• Morning reminder if no logs
• Daily reflection at midnight
• Weekly LinkedIn posts on Sunday

<b>Tips</b>
• Be specific about what you did
• Mention technologies and projects
• Regular logging = better posts!"""
        
        await self.telegram.send_message(chat_id, help_text)
    
    async def _cmd_status(self, message: TelegramMessage) -> None:
        chat_id = message.chat.get("id")
        user_id = message.from_user.id if message.from_user else 0
        
        await self.telegram.send_typing_action(chat_id)
        
        try:
            stats = self.memory.get_user_stats(user_id)
            
            if not stats:
                await self.telegram.send_message(
                    chat_id,
                    "📊 No data yet! Send your first voice note to get started."
                )
                return
            
            streak_str = format_streak(stats.get("streak", 0))
            last_entry = stats.get("last_entry")
            
            if last_entry:
                time_ago = datetime.utcnow() - last_entry
                hours_ago = int(time_ago.total_seconds() / 3600)
                if hours_ago < 1:
                    last_entry_str = "Just now"
                elif hours_ago < 24:
                    last_entry_str = f"{hours_ago} hours ago"
                else:
                    days_ago = hours_ago // 24
                    last_entry_str = f"{days_ago} days ago"
            else:
                last_entry_str = "Never"
            
            status = f"""📊 <b>Your Status</b>

{streak_str}

📈 <b>Stats:</b>
• Total entries: {stats.get('total_entries', 0)}
• This week: {stats.get('entries_this_week', 0)}
• Most logged: {stats.get('most_common_category', 'N/A').title()}

⏰ <b>Last entry:</b> {last_entry_str}

<i>Keep logging to build your streak! 💪</i>"""
            
            await self.telegram.send_message(chat_id, status)
            
        except Exception as e:
            logger.error(f"Error getting status: {e}")
            await self.telegram.send_message(
                chat_id,
                "❌ Error fetching status. Please try again."
            )
    
    async def _cmd_summary(self, message: TelegramMessage) -> None:
        chat_id = message.chat.get("id")
        user_id = message.from_user.id if message.from_user else 0
        
        await self.telegram.send_typing_action(chat_id)
        
        try:
            parts = message.text.split()
            
            if len(parts) >= 3:
                try:
                    start_date = datetime.strptime(parts[1], "%d-%m-%Y")
                    end_date = datetime.strptime(parts[2], "%d-%m-%Y")
                    end_date = end_date.replace(hour=23, minute=59, second=59)
                    
                    entries = self.memory.get_structured_entries_by_date(
                        user_id, start_date, end_date
                    )
                    
                    if not entries:
                        await self.telegram.send_message(
                            chat_id,
                            f"📭 No entries found between {parts[1]} and {parts[2]}"
                        )
                        return
                    
                    summary = await self._generate_quick_summary(entries, start_date, end_date)
                    await self.telegram.send_message(chat_id, summary)
                    return
                    
                except ValueError:
                    await self.telegram.send_message(
                        chat_id,
                        "❌ Invalid date format. Use: /summary DD-MM-YYYY DD-MM-YYYY\n\nExample: /summary 02-02-2026 04-02-2026"
                    )
                    return
            
            day_start, day_end = get_day_boundaries()
            entries = self.memory.get_structured_entries_by_date(
                user_id, day_start, day_end
            )
            
            if entries:
                summary = await self._generate_quick_summary(entries, day_start, day_end)
                await self.telegram.send_message(chat_id, summary)
            else:
                await self.telegram.send_message(
                    chat_id,
                    """📅 <b>No entries today yet!</b>

Send a voice note or text with #log to start logging.

<i>Tip: Talk about what you're working on, learning, or struggling with.</i>"""
                )
            
        except Exception as e:
            logger.error(f"Error getting summary: {e}")
            await self.telegram.send_message(
                chat_id,
                "❌ Error generating summary. Please try again."
            )
    
    async def _generate_quick_summary(self, entries: list, start_date: datetime, end_date: datetime) -> str:
        categories = {}
        all_text = []
        
        for e in entries:
            cat = e.category.value if hasattr(e.category, 'value') else str(e.category)
            categories[cat] = categories.get(cat, 0) + 1
            if e.keywords:
                all_text.extend(e.keywords[:2])
            if e.summary:
                all_text.append(e.summary[:100])
        
        is_single_day = start_date.date() == end_date.date()
        date_str = start_date.strftime('%B %d') if is_single_day else f"{start_date.strftime('%b %d')} - {end_date.strftime('%b %d')}"
        
        categories_text = ', '.join([f"{k}: {v}" for k, v in categories.items()]) if categories else "None"
        
        topics_summary = ""
        if all_text:
            unique_topics = list(dict.fromkeys(all_text))[:6]
            topics_summary = f"\n\n🏷️ <b>Topics:</b>\n" + "\n".join([f"• {t}" for t in unique_topics])
        
        return f"""📅 <b>Summary - {date_str}</b>

📊 <b>Total Entries:</b> {len(entries)}
📁 <b>Categories:</b> {categories_text}{topics_summary}

<i>Use /generate to create a LinkedIn post from these entries.</i>"""
    
    def _format_list(self, items: list, max_items: int = 3) -> str:
        if not items:
            return "• None"
        return "\n".join([f"• {item}" for item in items[:max_items]])
    
    async def _cmd_generate(self, message: TelegramMessage) -> None:
        chat_id = message.chat.get("id")
        user_id = message.from_user.id if message.from_user else 0
        
        await self.telegram.send_message(
            chat_id,
            "✍️ Generating LinkedIn post drafts... This may take a moment."
        )
        await self.telegram.send_typing_action(chat_id)
        
        try:
            daily_summaries = self.memory.get_daily_summaries(user_id, days=7)
            
            if not daily_summaries:
                from datetime import timedelta
                start = datetime.utcnow() - timedelta(days=7)
                end = datetime.utcnow()
                entries = self.memory.get_structured_entries_by_date(user_id, start, end)
                
                if not entries or len(entries) < 1:
                    await self.telegram.send_message(
                        chat_id,
                        "📭 Not enough data to generate posts. Please send some voice notes first!"
                    )
                    return
                
                logger.info(f"Creating summary from {len(entries)} entries for user {user_id}")
                
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
                
                from models import WeeklySummary, LinkedInPost, PostStatus, PostTone
                
                unique_themes = list(set(all_themes))[:5]
                
                weekly_summary = WeeklySummary(
                    telegram_id=user_id,
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
                
                weekly_id = self.memory.save_weekly_summary(weekly_summary)
                weekly_summary.id = weekly_id
                
                recent_published = self.memory.get_published_posts(user_id, limit=5)
                
                next_week = self.memory.get_next_week_number(user_id)
                
                posts = self.agent.generate_linkedin_posts(
                    weekly_summary,
                    recent_posts=recent_published,
                    week_number=next_week
                )
            else:
                themes = self.memory.detect_themes(user_id)
                
                previous_weekly = self.memory.get_latest_weekly_summary(user_id)
                
                recent_posts = self.memory.get_recent_post_embeddings(user_id, n_results=3)
                
                weekly_summary = self.agent.generate_weekly_summary(
                    daily_summaries=daily_summaries,
                    themes=themes,
                    previous_week=previous_weekly,
                    recent_posts=recent_posts
                )
                weekly_summary.telegram_id = user_id
                
                weekly_id = self.memory.save_weekly_summary(weekly_summary)
                weekly_summary.id = weekly_id
                
                recent_published = self.memory.get_published_posts(user_id, limit=5)
                
                next_week = self.memory.get_next_week_number(user_id)
                
                posts = self.agent.generate_linkedin_posts(
                    weekly_summary,
                    recent_posts=recent_published,
                    week_number=next_week
                )
            
            for post in posts:
                post.telegram_id = user_id
                post.weekly_summary_id = weekly_summary.id
                self.memory.save_linkedin_post(post)
            
            await self.telegram.send_message(
                chat_id,
                f"✅ Generated {len(posts)} LinkedIn post drafts!\n\n<i>Here they are:</i>"
            )
            
            for post in posts:
                tone_emoji = {"friendly": "😊", "professional": "💼", "technical": "🔧"}
                emoji = tone_emoji.get(post.tone.value, "📝")
                
                post_message = f"""{emoji} <b>{post.tone.value.title()} Version</b>

{post.content}

<i>Reply with edits or use the dashboard to customize.</i>"""
                
                await self.telegram.send_message(chat_id, post_message)
            
            await self.telegram.send_message(
                chat_id,
                "💡 <b>Tip:</b> View and edit these posts in the web dashboard for easier copying!"
            )
            
        except Exception as e:
            logger.error(f"Error generating posts: {e}", exc_info=True)
            await self.telegram.send_message(
                chat_id,
                "❌ Error generating posts. Please try again later."
            )
    
    async def _cmd_delete(self, message: TelegramMessage) -> None:
        chat_id = message.chat.get("id")
        user_id = message.from_user.id if message.from_user else 0
        
        try:
            parts = message.text.split()
            
            if len(parts) > 1:
                try:
                    entry_id = int(parts[1])
                    success = self.memory.delete_entry(entry_id, user_id)
                    
                    if success:
                        await self.telegram.send_message(
                            chat_id,
                            f"✅ Entry #{entry_id} deleted!"
                        )
                    else:
                        await self.telegram.send_message(
                            chat_id,
                            f"❌ Entry #{entry_id} not found."
                        )
                    return
                except ValueError:
                    pass
            
            entries = self.memory.get_recent_entries_for_deletion(user_id, limit=5)
            
            if not entries:
                await self.telegram.send_message(
                    chat_id,
                    "📭 No recent entries found."
                )
                return
            
            entries_text = "\n\n".join([
                f"🔹 <b>ID: {e['id']}</b>\n"
                f"   📅 {e.get('timestamp', 'Unknown')}\n"
                f"   📝 {e.get('summary', '')[:80]}"
                for e in entries
            ])
            
            response = f"""🗑️ <b>Delete Entry</b>

{entries_text}

<b>To delete:</b> <code>/delete [ID]</code>
Example: <code>/delete {entries[0]['id']}</code>"""
            
            await self.telegram.send_message(chat_id, response)
        except Exception as e:
            logger.error(f"Error in /delete: {e}")
            await self.telegram.send_message(
                chat_id,
                "❌ Error. Please try again."
            )
    
    async def _cmd_recent(self, message: TelegramMessage) -> None:
        chat_id = message.chat.get("id")
        user_id = message.from_user.id if message.from_user else 0
        
        try:
            entries = self.memory.get_recent_entries_for_deletion(user_id, limit=10)
            
            if not entries:
                await self.telegram.send_message(
                    chat_id,
                    "📭 No recent entries found."
                )
                return
            
            entries_text = "\n\n".join([
                f"🔹 <b>#{e['id']}</b> | {e.get('category', 'entry').title()}\n"
                f"   📅 {e.get('timestamp', 'Unknown')}\n"
                f"   📝 {e.get('summary', '')[:100]}"
                for e in entries
            ])
            
            response = f"""📋 <b>Recent Entries</b>

{entries_text}

💡 <i>Use /delete [ID] to remove an entry.</i>"""
            
            await self.telegram.send_message(chat_id, response)
        except Exception as e:
            logger.error(f"Error in /recent: {e}")
            await self.telegram.send_message(
                chat_id,
                "❌ Error fetching entries. Please try again."
            )

    TEXT_LOG_PREFIXES = ["#log", "#progress", "/log"]
    
    async def _handle_text(self, message: TelegramMessage) -> None:
        chat_id = message.chat.get("id")
        user_id = message.from_user.id if message.from_user else 0
        text = message.text.strip() if message.text else ""
        
        text_lower = text.lower()
        for prefix in self.TEXT_LOG_PREFIXES:
            if text_lower.startswith(prefix):
                log_content = text[len(prefix):].strip()
                
                if not log_content or len(log_content) < 10:
                    await self.telegram.send_message(
                        chat_id,
                        f"📝 Please include your progress after the prefix.\n\nExample:\n<code>{prefix} Today I worked on the API endpoints and fixed 3 bugs.</code>"
                    )
                    return
                
                await self._process_text_log(message, log_content)
                return
        
        if await self._handle_clarification_response(message):
            return
        
        await self.telegram.send_message(
            chat_id,
            """📝 <b>Text Logging Available!</b>

To log progress via text, use one of these prefixes:

• <code>#log</code> Your progress here
• <code>#progress</code> What you worked on
• <code>/log</code> Your update

<b>Example:</b>
<code>#log Worked on the API today, fixed authentication bug and added rate limiting.</code>

🎙️ <b>Voice notes work too!</b>
Just send a voice message directly.

<i>Use /help to see all commands.</i>"""
        )
    
    async def _process_text_log(self, message: TelegramMessage, log_content: str) -> None:
        chat_id = message.chat.get("id")
        user_id = message.from_user.id if message.from_user else 0
        
        await self.telegram.send_typing_action(chat_id)
        
        await self.telegram.send_message(
            chat_id,
            "📝 Processing your text log...",
            reply_to_message_id=message.message_id
        )
        
        try:
            logger.info(f"Classifying text log: {len(log_content)} chars")
            classification = self.agent.classify_entry(log_content)
            
            clarification = self._check_needs_clarification(log_content, classification)
            if clarification:
                await self._ask_clarification(chat_id, user_id, message.message_id, 
                                              log_content, classification, clarification)
                return
            
            raw_entry = RawEntry(
                telegram_id=user_id,
                telegram_message_id=message.message_id,
                timestamp=datetime.utcfromtimestamp(message.date),
                audio_file_id="text_entry",
                audio_duration=0,
                transcript=log_content
            )
            raw_entry_id = self.memory.save_raw_entry(raw_entry)
            
            structured_entry = StructuredEntry(
                raw_entry_id=raw_entry_id,
                category=classification.category,
                activities=classification.activities,
                blockers=classification.blockers,
                accomplishments=classification.accomplishments,
                learnings=classification.learnings,
                summary=classification.summary,
                keywords=classification.keywords,
                sentiment=classification.sentiment
            )
            self.memory.save_structured_entry(structured_entry)
            
            keywords_str = ",".join(classification.keywords) if classification.keywords else ""
            self.memory.add_to_vector_memory(
                entry_id=raw_entry_id,
                text=log_content,
                metadata={
                    "telegram_id": user_id,
                    "category": classification.category.value,
                    "timestamp": datetime.utcnow().isoformat(),
                    "keywords": keywords_str,
                    "source": "text"
                }
            )
            
            streak = self.memory.update_user_streak(user_id)
            
            category_emoji = self._get_category_emoji(classification.category)
            streak_str = format_streak(streak)
            
            response = f"""✅ <b>Text Entry Logged!</b>

{category_emoji} <b>Category:</b> {classification.category.value.title()}

📝 <b>Summary:</b>
{classification.summary}

{self._format_entry_details(classification)}

{streak_str}

<i>Source: Text message</i>"""
            
            await self.telegram.send_message(chat_id, response)
            logger.info(f"Successfully processed text log for user {user_id}")
            
        except Exception as e:
            logger.error(f"Error processing text log: {e}", exc_info=True)
            await self.telegram.send_message(
                chat_id,
                "❌ Error processing your text log. Please try again."
            )
    
    def _check_needs_clarification(self, content: str, classification) -> Optional[str]:
        vague_indicators = [
            "stuff", "things", "some work", "worked on it",
            "did stuff", "made progress", "worked"
        ]
        
        content_lower = content.lower()
        
        if len(content.split()) < 5:
            return "Could you tell me more about what you worked on? What specific tasks or projects?"
        
        for indicator in vague_indicators:
            if indicator in content_lower and not classification.activities:
                return f"I see you mentioned '{indicator}'. Could you be more specific about what you actually did?"
        
        if any(word in content_lower for word in ["stuck", "problem", "issue", "cant", "can't"]):
            if not classification.blockers:
                return "It sounds like you ran into some issues. What specific problems are you facing?"
        
        if "learned" in content_lower or "learning" in content_lower:
            if not classification.learnings:
                return "What specifically did you learn? Any key takeaways?"
        
        return None
    
    _pending_clarifications: Dict[int, Dict] = {}
    
    async def _ask_clarification(self, chat_id: int, user_id: int, message_id: int,
                                  original_content: str, classification, question: str) -> None:
        self._pending_clarifications[user_id] = {
            "original_content": original_content,
            "classification": classification,
            "message_id": message_id,
            "timestamp": datetime.utcnow()
        }
        
        await self.telegram.send_message(
            chat_id,
            f"❓ <b>Quick question:</b>\n\n{question}\n\n<i>Just reply with more details, or type 'skip' to log as-is.</i>",
            reply_to_message_id=message_id
        )
    
    async def _handle_clarification_response(self, message: TelegramMessage) -> bool:
        user_id = message.from_user.id if message.from_user else 0
        
        if user_id not in self._pending_clarifications:
            return False
        
        pending = self._pending_clarifications[user_id]
        
        if (datetime.utcnow() - pending["timestamp"]).seconds > 600:
            del self._pending_clarifications[user_id]
            return False
        
        chat_id = message.chat.get("id")
        text = message.text.strip() if message.text else ""
        
        if text.lower() in ["skip", "no", "nevermind", "nvm"]:
            del self._pending_clarifications[user_id]
            await self._save_clarified_entry(chat_id, user_id, pending["original_content"], 
                                             pending["classification"])
            return True
        
        enhanced_content = f"{pending['original_content']}\n\nAdditional details: {text}"
        
        try:
            new_classification = self.agent.classify_entry(enhanced_content)
            await self._save_clarified_entry(chat_id, user_id, enhanced_content, new_classification)
        except Exception as e:
            logger.error(f"Error processing clarification: {e}")
            await self._save_clarified_entry(chat_id, user_id, pending["original_content"],
                                             pending["classification"])
        
        del self._pending_clarifications[user_id]
        return True
    
    async def _save_clarified_entry(self, chat_id: int, user_id: int, 
                                     content: str, classification) -> None:
        try:
            raw_entry = RawEntry(
                telegram_id=user_id,
                telegram_message_id=0,
                timestamp=datetime.utcnow(),
                audio_file_id="text_entry_clarified",
                audio_duration=0,
                transcript=content
            )
            raw_entry_id = self.memory.save_raw_entry(raw_entry)
            
            structured_entry = StructuredEntry(
                raw_entry_id=raw_entry_id,
                category=classification.category,
                activities=classification.activities,
                blockers=classification.blockers,
                accomplishments=classification.accomplishments,
                learnings=classification.learnings,
                summary=classification.summary,
                keywords=classification.keywords,
                sentiment=classification.sentiment
            )
            self.memory.save_structured_entry(structured_entry)
            
            keywords_str = ",".join(classification.keywords) if classification.keywords else ""
            self.memory.add_to_vector_memory(
                entry_id=raw_entry_id,
                text=content,
                metadata={
                    "telegram_id": user_id,
                    "category": classification.category.value,
                    "timestamp": datetime.utcnow().isoformat(),
                    "keywords": keywords_str,
                    "source": "text_clarified"
                }
            )
            
            streak = self.memory.update_user_streak(user_id)
            
            category_emoji = self._get_category_emoji(classification.category)
            streak_str = format_streak(streak)
            
            response = f"""✅ <b>Entry Logged!</b>

{category_emoji} <b>Category:</b> {classification.category.value.title()}

📝 <b>Summary:</b>
{classification.summary}

{self._format_entry_details(classification)}

{streak_str}"""
            
            await self.telegram.send_message(chat_id, response)
            
        except Exception as e:
            logger.error(f"Error saving clarified entry: {e}", exc_info=True)
            await self.telegram.send_message(
                chat_id,
                "❌ Error saving your entry. Please try again."
            )

_bot_handler: Optional[BotHandler] = None


def get_bot_handler() -> BotHandler:
    global _bot_handler
    if _bot_handler is None:
        _bot_handler = BotHandler()
    return _bot_handler
