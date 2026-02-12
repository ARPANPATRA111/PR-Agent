import json
import logging
from datetime import datetime
from typing import List, Optional, Dict, Any
from pathlib import Path

from groq import Groq

from config import settings
from models import (
    ClassificationResult, DailySummary, WeeklySummary, LinkedInPost,
    EntryCategory, PostTone, PostStatus, StructuredEntry
)

UNICODE_BOLD_DIGITS = {
    '0': '𝟎', '1': '𝟏', '2': '𝟐', '3': '𝟑', '4': '𝟒',
    '5': '𝟓', '6': '𝟔', '7': '𝟕', '8': '𝟖', '9': '𝟗'
}

def to_unicode_bold_number(num: int) -> str:
    return ''.join(UNICODE_BOLD_DIGITS.get(d, d) for d in str(num))

_historical_examples_db = None

def get_historical_examples_db():
    global _historical_examples_db
    if _historical_examples_db is None:
        try:
            from historical_examples import HistoricalExamplesDB, HistoricalPostParser
            _historical_examples_db = HistoricalExamplesDB()
            if _historical_examples_db.collection.count() == 0:
                parser = HistoricalPostParser()
                parser.parse_file()
                if parser.posts:
                    _historical_examples_db.populate_from_parser(parser)
                    logger.info(f"Populated historical examples DB with {len(parser.posts)} posts")
        except Exception as e:
            logger.warning(f"Could not initialize historical examples: {e}")
            _historical_examples_db = None
    return _historical_examples_db

logger = logging.getLogger(__name__)

class PromptLoader:
    
    def __init__(self, prompts_dir: str = "../prompts"):
        self.prompts_dir = Path(__file__).parent / prompts_dir
        self._cache = {}
    
    def load(self, prompt_name: str) -> str:
        if prompt_name in self._cache:
            return self._cache[prompt_name]
        
        prompt_path = self.prompts_dir / f"{prompt_name}.md"
        
        if not prompt_path.exists():
            logger.warning(f"Prompt file not found: {prompt_path}")
            return ""
        
        with open(prompt_path, "r", encoding="utf-8") as f:
            content = f.read()
        
        self._cache[prompt_name] = content
        return content
    
    def reload(self, prompt_name: Optional[str] = None):
        if prompt_name:
            self._cache.pop(prompt_name, None)
        else:
            self._cache.clear()


class LLMAgent:
    
    def __init__(self):
        self.client = Groq(api_key=settings.groq_api_key)
        self.model = settings.groq_model
        self.temperature = settings.llm_temperature
        self.prompts = PromptLoader()
        
        logger.info(f"LLM Agent initialized with model: {self.model}")
    
    def _call_llm(self, system_prompt: str, user_prompt: str, 
                  temperature: Optional[float] = None,
                  max_tokens: int = 2000,
                  json_mode: bool = False) -> str:
        try:
            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ]
            
            kwargs = {
                "model": self.model,
                "messages": messages,
                "temperature": temperature or self.temperature,
                "max_tokens": max_tokens,
            }
            
            if json_mode:
                kwargs["response_format"] = {"type": "json_object"}
            
            response = self.client.chat.completions.create(**kwargs)
            
            return response.choices[0].message.content.strip()
            
        except Exception as e:
            logger.error(f"LLM call failed: {e}")
            raise

    def classify_entry(self, transcript: str) -> ClassificationResult:
        system_prompt = self.prompts.load("classification") or self._default_classification_prompt()
        
        user_prompt = f"""Analyze the following voice note transcript and extract structured information.

TRANSCRIPT:
{transcript}

Respond with a JSON object containing:
- category: one of [coding, learning, debugging, research, meeting, planning, blockers, achievement, other]
- activities: list of activities mentioned
- blockers: list of blockers or challenges
- accomplishments: list of things completed or achieved
- learnings: list of things learned
- summary: a 1-2 sentence summary
- keywords: list of 3-5 relevant keywords
- sentiment: one of [positive, neutral, negative]
"""
        
        response = self._call_llm(
            system_prompt, 
            user_prompt,
            temperature=0.3,
            json_mode=True
        )
        
        try:
            data = json.loads(response)
            
            category_str = data.get("category", "other").lower()
            try:
                category = EntryCategory(category_str)
            except ValueError:
                category = EntryCategory.OTHER
            
            return ClassificationResult(
                category=category,
                activities=data.get("activities", []),
                blockers=data.get("blockers", []),
                accomplishments=data.get("accomplishments", []),
                learnings=data.get("learnings", []),
                summary=data.get("summary", transcript[:100]),
                keywords=data.get("keywords", []),
                sentiment=data.get("sentiment", "neutral")
            )
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse classification response: {e}")
            return ClassificationResult(
                category=EntryCategory.OTHER,
                summary=transcript[:100],
                activities=[],
                blockers=[],
                accomplishments=[],
                learnings=[],
                keywords=[],
                sentiment="neutral"
            )
    
    def _default_classification_prompt(self) -> str:
        return """You are an expert at analyzing work log entries. Your task is to:
1. Categorize the entry into one of the predefined categories
2. Extract key activities, blockers, accomplishments, and learnings
3. Provide a brief summary
4. Identify relevant keywords
5. Assess the overall sentiment

Be concise and accurate. Focus on actionable information.
Always respond with valid JSON."""
    
    def validate_content_relevance(self, transcript: str) -> Dict[str, Any]:
        transcript = transcript.strip()
        
        if len(transcript) < 15:
            return {
                "is_relevant": False,
                "confidence": 0.99,
                "reason": "Too short to be meaningful",
                "category": "unrelated"
            }
        
        words = transcript.lower().split()
        if len(words) < 4:
            return {
                "is_relevant": False,
                "confidence": 0.95,
                "reason": "Not enough context",
                "category": "unrelated"
            }
        
        nonsense_patterns = [
            "1, 2, 3", "one two three", "testing", "test test", "hello hello",
            "mic check", "check check", "can you hear", "is this working"
        ]
        transcript_lower = transcript.lower()
        for pattern in nonsense_patterns:
            if pattern in transcript_lower:
                return {
                    "is_relevant": False,
                    "confidence": 0.95,
                    "reason": "Looks like a test message",
                    "category": "unrelated"
                }
        
        system_prompt = """You are a STRICT content validator. You REJECT anything that is NOT a clear work update.

ACCEPT ONLY if the message DESCRIBES:
- Specific work done: "I implemented the login feature", "Fixed the database bug"
- Learning with context: "Learned about React hooks while building the form"
- Meeting notes: "Met with the team to discuss the API design"
- Progress updates: "Finished 3 tickets today", "Completed the auth module"
- Technical problems: "Struggling with the deployment pipeline"

REJECT if:
- Random words without clear meaning or context
- Testing the system ("1 2 3", "hello", "testing")
- Incomplete fragments that don't describe actual work
- Just listing technologies without saying what was done
- Personal life unrelated to work

The message must clearly state WHAT was done or learned. Just mentioning tech words is NOT enough.
Return JSON only."""

        user_prompt = f"""Does this describe actual work or learning? Be STRICT.

MESSAGE:
{transcript}

Return JSON:
{{
    "is_relevant": true/false,
    "confidence": 0.0-1.0,
    "reason": "why",
    "category": "coding|learning|meeting|project|blocker|unrelated"
}}"""

        try:
            response = self._call_llm(
                system_prompt,
                user_prompt,
                temperature=0.0,
                max_tokens=150,
                json_mode=True
            )
            
            data = json.loads(response)
            is_relevant = data.get("is_relevant", False)
            confidence = data.get("confidence", 0.5)
            
            if confidence < 0.75:
                is_relevant = False
                data["reason"] = "Low confidence - unclear if this is actual work"
            
            return {
                "is_relevant": is_relevant,
                "confidence": confidence,
                "reason": data.get("reason", ""),
                "category": data.get("category", "unrelated")
            }
            
        except (json.JSONDecodeError, Exception) as e:
            logger.warning(f"Validation failed: {e}")
            return {
                "is_relevant": False,
                "confidence": 0.5,
                "reason": "Validation error",
                "category": "unrelated"
            }


    def generate_daily_reflection(self, entries: List[StructuredEntry],
                                  date: datetime,
                                  user_name: str = "User") -> DailySummary:
        system_prompt = self.prompts.load("reflection") or self._default_reflection_prompt()
        
        entries_text = self._format_entries_for_reflection(entries)
        
        user_prompt = f"""Generate a daily reflection for {user_name} on {date.strftime('%A, %B %d, %Y')}.

TODAY'S ENTRIES:
{entries_text}

Create a thoughtful reflection that:
1. Summarizes what was accomplished
2. Highlights key learnings
3. Notes any blockers (resolved or pending)
4. Identifies themes or patterns
5. Provides encouragement or motivation

Respond with JSON containing:
- achievements: list of accomplishments
- learnings: list of key learnings
- blockers_resolved: list of resolved blockers
- blockers_pending: list of unresolved blockers
- reflection: a paragraph-length reflection (2-3 sentences)
- themes: list of main themes
- productivity_score: number 1-10
"""
        
        response = self._call_llm(
            system_prompt,
            user_prompt,
            temperature=0.7,
            json_mode=True
        )
        
        try:
            data = json.loads(response)
            
            categories = list(set(e.category.value for e in entries))
            
            return DailySummary(
                telegram_id=0,
                date=date,
                entries_count=len(entries),
                categories=categories,
                achievements=data.get("achievements", []),
                learnings=data.get("learnings", []),
                blockers_resolved=data.get("blockers_resolved", []),
                blockers_pending=data.get("blockers_pending", []),
                reflection=data.get("reflection", ""),
                themes=data.get("themes", []),
                productivity_score=data.get("productivity_score")
            )
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse reflection response: {e}")
            return DailySummary(
                telegram_id=0,
                date=date,
                entries_count=len(entries),
                categories=[],
                achievements=[],
                learnings=[],
                blockers_resolved=[],
                blockers_pending=[],
                reflection="Unable to generate reflection.",
                themes=[],
                productivity_score=None
            )
    
    def _format_entries_for_reflection(self, entries: List[StructuredEntry]) -> str:
        if not entries:
            return "No entries recorded today."
        
        parts = []
        for i, entry in enumerate(entries, 1):
            part = f"""Entry {i} ({entry.category.value}):
Summary: {entry.summary}
Activities: {', '.join(entry.activities) if entry.activities else 'None'}
Blockers: {', '.join(entry.blockers) if entry.blockers else 'None'}
Accomplishments: {', '.join(entry.accomplishments) if entry.accomplishments else 'None'}
Learnings: {', '.join(entry.learnings) if entry.learnings else 'None'}
"""
            parts.append(part)
        
        return "\n".join(parts)
    
    def _default_reflection_prompt(self) -> str:
        return """You are a thoughtful personal productivity coach helping someone reflect on their day.
Your reflections should be:
- Encouraging and supportive
- Focused on growth and learning
- Specific about accomplishments
- Constructive about challenges
- Brief but meaningful

Always respond with valid JSON."""
    
    def generate_weekly_summary(self, daily_summaries: List[DailySummary],
                                themes: List[Dict[str, Any]],
                                previous_week: Optional[WeeklySummary] = None,
                                recent_posts: List[str] = None) -> WeeklySummary:
        system_prompt = self.prompts.load("weekly_report") or self._default_weekly_prompt()
        
        summaries_text = self._format_summaries_for_weekly(daily_summaries)
        themes_text = self._format_themes(themes)
        comparison_text = self._format_previous_week(previous_week) if previous_week else "No previous week data."
        avoid_text = self._format_avoid_topics(recent_posts) if recent_posts else ""
        
        user_prompt = f"""Generate a weekly summary and analysis.

DAILY SUMMARIES:
{summaries_text}

DETECTED THEMES:
{themes_text}

PREVIOUS WEEK COMPARISON:
{comparison_text}

{avoid_text}

Create a comprehensive weekly summary including:
1. Main accomplishments across the week
2. Key learnings and insights
3. Recurring themes and patterns
4. Comparison with previous week (if available)
5. Trends in productivity or focus areas

Respond with JSON containing:
- main_themes: list of 3-5 main themes
- accomplishments: list of top accomplishments
- learnings: list of key learnings
- trends: object with trend observations
- comparison_with_previous: brief comparison paragraph (or null)
- total_entries: estimated total entries
"""
        
        response = self._call_llm(
            system_prompt,
            user_prompt,
            temperature=0.7,
            json_mode=True
        )
        
        try:
            data = json.loads(response)
            
            if daily_summaries:
                dates = [s.date for s in daily_summaries]
                week_start = min(dates)
                week_end = max(dates)
            else:
                from utils import get_week_boundaries
                week_start, week_end = get_week_boundaries()
            
            return WeeklySummary(
                telegram_id=0,
                week_start=week_start,
                week_end=week_end,
                daily_summaries=[s.id for s in daily_summaries if s.id],
                total_entries=data.get("total_entries", sum(s.entries_count for s in daily_summaries)),
                main_themes=data.get("main_themes", []),
                accomplishments=data.get("accomplishments", []),
                learnings=data.get("learnings", []),
                trends=data.get("trends", {}),
                comparison_with_previous=data.get("comparison_with_previous")
            )
            
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse weekly summary response: {e}")
            from utils import get_week_boundaries
            week_start, week_end = get_week_boundaries()
            
            return WeeklySummary(
                telegram_id=0,
                week_start=week_start,
                week_end=week_end,
                daily_summaries=[],
                total_entries=0,
                main_themes=[],
                accomplishments=[],
                learnings=[],
                trends={},
                comparison_with_previous=None
            )
    
    def _format_summaries_for_weekly(self, summaries: List[DailySummary]) -> str:
        if not summaries:
            return "No daily summaries available."
        
        parts = []
        for summary in summaries:
            part = f"""{summary.date.strftime('%A, %B %d')}:
- Entries: {summary.entries_count}
- Achievements: {', '.join(summary.achievements[:3]) if summary.achievements else 'None'}
- Learnings: {', '.join(summary.learnings[:2]) if summary.learnings else 'None'}
- Themes: {', '.join(summary.themes) if summary.themes else 'None'}
- Score: {summary.productivity_score or 'N/A'}/10
"""
            parts.append(part)
        
        return "\n".join(parts)
    
    def _format_themes(self, themes: List[Dict[str, Any]]) -> str:
        if not themes:
            return "No themes detected."
        
        return "\n".join([f"- {t['theme']}: {t['count']} occurrences" for t in themes])
    
    def _format_previous_week(self, previous: WeeklySummary) -> str:
        return f"""Last week ({previous.week_start.strftime('%b %d')} - {previous.week_end.strftime('%b %d')}):
- Entries: {previous.total_entries}
- Main themes: {', '.join(previous.main_themes)}
- Top accomplishments: {', '.join(previous.accomplishments[:3])}"""
    
    def _format_avoid_topics(self, recent_posts: List[str]) -> str:
        if not recent_posts:
            return ""
        
        return f"""AVOID REPETITION:
The following topics were recently covered in LinkedIn posts. Try to focus on different aspects:
{chr(10).join(['- ' + p[:100] + '...' for p in recent_posts[:3]])}
"""
    
    def _default_weekly_prompt(self) -> str:
        return """You are an expert at analyzing weekly productivity and creating insightful summaries.
Focus on:
- Patterns and trends over the week
- Growth and progress
- Areas of focus
- Balance between different activities

Always respond with valid JSON."""
    
    def generate_linkedin_posts(self, weekly_summary: WeeklySummary,
                                tones: List[PostTone] = None,
                                custom_instructions: str = None,
                                week_number: int = None,
                                project_links: List[str] = None,
                                recent_posts: List[LinkedInPost] = None) -> List[LinkedInPost]:
        post = self._generate_arpan_style_post(
            weekly_summary, 
            custom_instructions,
            week_number=week_number,
            project_links=project_links,
            recent_posts=recent_posts
        )
        return [post]
    
    def _generate_arpan_style_post(self, summary: WeeklySummary,
                                    custom_instructions: str = None,
                                    week_number: int = None,
                                    project_links: List[str] = None,
                                    recent_posts: List[LinkedInPost] = None) -> LinkedInPost:
        from memory import get_memory_manager
        memory = get_memory_manager()
        
        if week_number is None:
            latest_week = memory.get_latest_posted_week(summary.telegram_id)
            week_number = latest_week + 1 if latest_week > 0 else settings.current_week_number
        
        entries = memory.get_structured_entries_by_date(
            summary.telegram_id, summary.week_start, summary.week_end
        )
        
        entry_details = []
        all_activities = []
        all_accomplishments = []
        all_learnings = []
        
        for entry in entries:
            if entry.summary:
                entry_details.append(entry.summary)
            all_activities.extend(entry.activities or [])
            all_accomplishments.extend(entry.accomplishments or [])
            all_learnings.extend(entry.learnings or [])
        
        all_activities = list(dict.fromkeys(all_activities))[:10]
        all_accomplishments = list(dict.fromkeys(all_accomplishments))[:8]
        all_learnings = list(dict.fromkeys(all_learnings))[:6]
        
        posted_reports = memory.get_posted_reports(summary.telegram_id, limit=5)
        
        style_context = ""
        if posted_reports:
            style_context = "\n\nMY ACTUAL PAST POSTS (this is my writing style - match it exactly):\n"
            for report in posted_reports[:5]:
                style_context += f"\n--- Week {report['week_number']} ---\n{report['content']}\n"
        
        hashtag_year = "2026" if week_number > 52 else "2025"
        week_bold = to_unicode_bold_number(week_number)
        year_digit = to_unicode_bold_number(int(hashtag_year[-1]))
        
        header = f"🌟 𝐖𝐞𝐞𝐤-{week_bold} 𝐏𝐫𝐨𝐠𝐫𝐞𝐬𝐬 𝐑𝐞𝐩𝐨𝐫𝐭 🚀"
        footer = f"✨ Let's 𝐜𝐨𝐝𝐞 👨‍💻, 𝐠𝐫𝐨𝐰 🌱, and 𝐚𝐜𝐡𝐢𝐞𝐯𝐞 🎯 together! #𝐋𝐞𝐭𝐬𝐂𝐨𝐝𝐞𝟐𝟎𝟐{year_digit} 🚀🎉"
        
        specific_work = "\n".join([f"• {detail}" for detail in entry_details[:8]]) if entry_details else "No detailed logs"
        specific_activities = ", ".join(all_activities) if all_activities else "General work"
        specific_accomplishments = "\n".join([f"• {acc}" for acc in all_accomplishments]) if all_accomplishments else "Various tasks completed"
        specific_learnings = ", ".join(all_learnings) if all_learnings else "Technical skills"
        
        system_prompt = """You are writing a personal weekly update post exactly in the user's voice. Study their past posts and match:
- Their casual, direct tone (like talking to friends)
- How they mention real life events (college, hackathons, personal stuff)  
- Short sentences, no corporate fluff
- When they use bullet points vs flowing text
- Their emoji patterns

This is NOT a professional report. It's a personal update about their week.
DO NOT include header or footer - they are added separately.
NEVER use: "excited", "thrilled", "journey", "passionate", "proud", "significant progress", "making strides", "I'm happy to share", "I had the opportunity"."""

        user_prompt = f"""Write my Week-{week_number} personal update (body only).

WHAT I ACTUALLY DID THIS WEEK:
{specific_work}

Activities: {specific_activities}
Accomplishments: {specific_accomplishments}
Learnings: {specific_learnings}
{style_context}
{f"Project link: {project_links[0]}" if project_links else ""}
{f"Notes: {custom_instructions}" if custom_instructions else ""}

Write like my past posts above. Be specific about what I actually worked on.
- Start with how the week felt or a specific event
- Mention what I worked on naturally (not in bullet lists unless I use them in past posts)
- Keep it real and personal
- End with 🔮 𝐋𝐨𝐨𝐤𝐢𝐧𝐠 𝐀𝐡𝐞𝐚𝐝 (1-2 sentences) and 💬 𝐐𝐮𝐨𝐭𝐞 𝐨𝐟 𝐭𝐡𝐞 𝐖𝐞𝐞𝐤
- Include GitHub link naturally if provided"""
        
        response = self._call_llm(
            system_prompt,
            user_prompt,
            temperature=0.7
        )
        
        content = f"{header}\n\n{response.strip()}\n\n{footer}"
        
        return LinkedInPost(
            telegram_id=summary.telegram_id,
            weekly_summary_id=summary.id or 0,
            tone=PostTone.FRIENDLY,
            content=content,
            status=PostStatus.DRAFT,
            created_at=datetime.utcnow(),
            week_number=week_number
        )
    
    def _get_historical_context(self, summary: WeeklySummary) -> str:
        db = get_historical_examples_db()
        if db is None:
            return ""
        
        query_parts = []
        if summary.main_themes:
            query_parts.extend(summary.main_themes[:3])
        if summary.accomplishments:
            query_parts.extend(summary.accomplishments[:2])
        
        if not query_parts:
            return ""
        
        query = " ".join(query_parts)
        
        try:
            similar = db.find_similar_examples(query, n_results=2)
            if similar:
                examples_text = "\nSIMILAR HISTORICAL POSTS FOR REFERENCE:\n"
                for ex in similar:
                    examples_text += f"--- Week {ex['week_number']} ---\n{ex['content'][:300]}...\n\n"
                return examples_text
        except Exception as e:
            logger.warning(f"Could not get historical examples: {e}")
        
        return ""
    
    def _build_recent_posts_context(self, recent_posts: List[LinkedInPost] = None) -> str:
        if not recent_posts:
            return ""
        
        context = "LAST 5 PROGRESS REPORTS (for context and continuity - maintain voice consistency, don't repeat themes):\n"
        for i, post in enumerate(recent_posts[:5], 1):
            week_num = post.week_number if post.week_number else "?"
            content_preview = post.content[:500] if len(post.content) > 500 else post.content
            context += f"\n--- Week {week_num} ---\n{content_preview}\n"
        
        context += "\nIMPORTANT: Use these posts to maintain consistent tone and voice. Avoid repeating the same accomplishments or themes. Reference ongoing projects where relevant.\n"
        return context
    
    def _generate_single_post(self, summary: WeeklySummary, 
                              tone: PostTone,
                              custom_instructions: str = None) -> LinkedInPost:
        return self._generate_arpan_style_post(summary, custom_instructions)
    
    def _default_linkedin_prompt(self) -> str:
        return """You are an expert at crafting engaging LinkedIn posts that showcase professional growth and learning.

Your posts should:
- Be authentic and genuine
- Highlight progress without bragging
- Include specific examples and learnings
- Encourage engagement from the community
- Use appropriate formatting (line breaks, emojis)

Write content that professionals would find valuable and relatable."""
    
    def generate_nudge(self, nudge_type: str, user_name: str = "there",
                      streak: int = 0, last_entry_hours: int = 24) -> str:
        system_prompt = self.prompts.load("nudging") or self._default_nudge_prompt()
        
        context = {
            "morning": f"It's a new day! {user_name} should log their plans.",
            "reminder": f"It's been {last_entry_hours} hours since the last log.",
            "streak": f"Current streak: {streak} days. Encourage continuing."
        }
        
        user_prompt = f"""Generate a brief, friendly nudge message.

TYPE: {nudge_type}
CONTEXT: {context.get(nudge_type, '')}
USER: {user_name}
STREAK: {streak} days

Requirements:
- Keep it under 200 characters
- Be encouraging, not pushy
- Use 1-2 relevant emojis
- Reference the streak if > 0
- Create urgency without pressure

Generate just the nudge message text.
"""
        
        response = self._call_llm(
            system_prompt,
            user_prompt,
            temperature=0.9,
            max_tokens=100
        )
        
        return response.strip()
    
    def _default_nudge_prompt(self) -> str:
        return """You are a supportive accountability partner helping someone maintain their logging habit.

Your nudges should be:
- Brief and friendly
- Encouraging, never nagging
- Varied (don't repeat the same message)
- Acknowledging of their efforts
- Light and playful when appropriate

Use behavioral psychology principles:
- Commitment/consistency (reference their streak)
- Social proof (others are logging too)
- Immediate rewards (the good feeling of logging)"""
    
    def analyze_themes(self, entries_text: List[str]) -> List[str]:
        if not entries_text:
            return []
        
        combined = "\n".join([f"- {text[:200]}" for text in entries_text[:20]])
        
        user_prompt = f"""Analyze these work log entries and identify the main recurring themes.

ENTRIES:
{combined}

Identify 3-5 main themes that appear across these entries.
Respond with JSON: {{"themes": ["theme1", "theme2", ...]}}
"""
        
        response = self._call_llm(
            "You are an expert at identifying patterns and themes in work logs.",
            user_prompt,
            temperature=0.3,
            json_mode=True
        )
        
        try:
            data = json.loads(response)
            return data.get("themes", [])
        except json.JSONDecodeError:
            return []
    
    def autonomous_analyze(self, user_context: Dict[str, Any]) -> Dict[str, Any]:
        system_prompt = """You are an autonomous AI agent for a weekly progress tracking system.
Your role is to THINK, PLAN, REASON, and DECIDE to help users maintain consistent progress logging.

You must analyze the user's activity patterns and make intelligent decisions about:
1. When to send reminders
2. When to generate summaries
3. When to encourage the user
4. When to provide insights
5. What actions would most benefit the user right now

Think step by step, consider multiple options, and provide clear reasoning for your decisions.
Always respond with valid JSON."""

        user_prompt = f"""Analyze this user's situation and provide autonomous recommendations:

USER CONTEXT:
- Telegram ID: {user_context.get('telegram_id', 'Unknown')}
- Last Entry: {user_context.get('time_since_last_entry', 'Unknown')} hours ago
- Current Streak: {user_context.get('streak', 0)} days
- Entries Today: {user_context.get('entry_count_today', 0)}
- Entries This Week: {user_context.get('entry_count_week', 0)}
- Has Weekly Summary: {user_context.get('has_weekly_summary', False)}
- Recent Themes: {', '.join(user_context.get('recent_themes', []))}
- Current Hour: {user_context.get('current_hour', 12)}
- Day of Week: {user_context.get('day_of_week', 'Unknown')}

Respond with your analysis:
{{
    "thinking": "Your analysis of the current situation...",
    "plan": ["action1", "action2", ...],
    "reasoning": "Why these actions make sense...",
    "decisions": {{
        "should_nudge": true/false,
        "should_generate_summary": true/false,
        "should_encourage": true/false,
        "nudge_type": "gentle|moderate|urgent|none",
        "custom_message": "Optional personalized message for the user"
    }},
    "priority_action": "single most important action",
    "confidence": 0.0-1.0
}}"""

        try:
            response = self._call_llm(
                system_prompt,
                user_prompt,
                temperature=0.5,
                max_tokens=1000,
                json_mode=True
            )
            
            data = json.loads(response)
            return {
                "thinking": data.get("thinking", ""),
                "plan": data.get("plan", []),
                "reasoning": data.get("reasoning", ""),
                "decisions": data.get("decisions", {}),
                "priority_action": data.get("priority_action", "monitor"),
                "confidence": data.get("confidence", 0.5)
            }
            
        except (json.JSONDecodeError, Exception) as e:
            logger.warning(f"Autonomous analysis failed: {e}")
            return {
                "thinking": "Unable to complete analysis",
                "plan": [],
                "reasoning": "Analysis failed, defaulting to standard behavior",
                "decisions": {
                    "should_nudge": False,
                    "should_generate_summary": False,
                    "should_encourage": False,
                    "nudge_type": "none"
                },
                "priority_action": "monitor",
                "confidence": 0.0
            }
    
    def generate_personalized_insight(self, user_data: Dict[str, Any]) -> str:
        system_prompt = """You are a thoughtful productivity coach who provides brief, 
actionable insights based on work patterns. Be encouraging but honest.
Keep insights to 2-3 sentences maximum."""

        user_prompt = f"""Based on this user's activity, provide ONE actionable insight:

- Streak: {user_data.get('streak', 0)} days
- This Week: {user_data.get('entries_this_week', 0)} entries
- Main Focus: {', '.join(user_data.get('themes', ['general work']))}
- Productivity Trend: {user_data.get('trend', 'stable')}

Provide a brief, personalized insight (2-3 sentences).
Do NOT use JSON - just write the insight directly."""

        try:
            response = self._call_llm(
                system_prompt,
                user_prompt,
                temperature=0.7,
                max_tokens=150
            )
            return response.strip()
        except Exception as e:
            logger.warning(f"Failed to generate insight: {e}")
            return "Keep up the great work! Regular logging helps track your progress."

_llm_agent: Optional[LLMAgent] = None


def get_llm_agent() -> LLMAgent:
    global _llm_agent
    if _llm_agent is None:
        _llm_agent = LLMAgent()
    return _llm_agent
