from datetime import datetime
from typing import List, Optional, Dict, Any
from enum import Enum
from pydantic import BaseModel, Field


class EntryCategory(str, Enum):
    CODING = "coding"
    LEARNING = "learning"
    DEBUGGING = "debugging"
    RESEARCH = "research"
    MEETING = "meeting"
    PLANNING = "planning"
    BLOCKERS = "blockers"
    ACHIEVEMENT = "achievement"
    OTHER = "other"


class PostTone(str, Enum):
    FRIENDLY = "friendly"
    PROFESSIONAL = "professional"
    TECHNICAL = "technical"


class PostStatus(str, Enum):
    DRAFT = "draft"
    SELECTED = "selected"
    POSTED = "posted"


class TelegramUser(BaseModel):
    id: int
    first_name: str
    last_name: Optional[str] = None
    username: Optional[str] = None
    language_code: Optional[str] = None


class TelegramVoice(BaseModel):
    file_id: str
    file_unique_id: str
    duration: int
    mime_type: Optional[str] = None
    file_size: Optional[int] = None


class TelegramMessage(BaseModel):
    message_id: int
    date: int
    chat: Dict[str, Any]
    from_user: Optional[TelegramUser] = Field(None, alias="from")
    text: Optional[str] = None
    voice: Optional[TelegramVoice] = None
    
    class Config:
        populate_by_name = True


class TelegramUpdate(BaseModel):
    update_id: int
    message: Optional[TelegramMessage] = None


class RawEntry(BaseModel):
    id: Optional[int] = None
    telegram_id: int
    telegram_message_id: int
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    audio_file_id: str
    audio_duration: int
    transcript: str
    
    class Config:
        from_attributes = True


class StructuredEntry(BaseModel):
    id: Optional[int] = None
    raw_entry_id: int
    category: EntryCategory
    activities: List[str] = []
    blockers: List[str] = []
    accomplishments: List[str] = []
    learnings: List[str] = []
    summary: str
    keywords: List[str] = []
    sentiment: Optional[str] = None
    
    class Config:
        from_attributes = True


class ClassificationResult(BaseModel):
    category: EntryCategory
    activities: List[str] = []
    blockers: List[str] = []
    accomplishments: List[str] = []
    learnings: List[str] = []
    summary: str
    keywords: List[str] = []
    sentiment: str = "neutral"


class DailySummary(BaseModel):
    id: Optional[int] = None
    telegram_id: int
    date: datetime
    entries_count: int
    categories: List[str]
    achievements: List[str]
    learnings: List[str]
    blockers_resolved: List[str]
    blockers_pending: List[str]
    reflection: str
    themes: List[str] = []
    productivity_score: Optional[float] = None
    
    class Config:
        from_attributes = True


class WeeklySummary(BaseModel):
    id: Optional[int] = None
    telegram_id: int
    week_start: datetime
    week_end: datetime
    daily_summaries: List[int]
    total_entries: int
    main_themes: List[str]
    accomplishments: List[str]
    learnings: List[str]
    trends: Dict[str, Any]
    comparison_with_previous: Optional[str] = None
    
    class Config:
        from_attributes = True


class LinkedInPost(BaseModel):
    id: Optional[int] = None
    telegram_id: int
    weekly_summary_id: Optional[int] = None
    tone: PostTone
    content: str
    status: PostStatus = PostStatus.DRAFT
    created_at: datetime = Field(default_factory=datetime.utcnow)
    edited_content: Optional[str] = None
    published_at: Optional[datetime] = None
    linkedin_url: Optional[str] = None
    week_number: Optional[int] = None
    version: int = 1
    
    class Config:
        from_attributes = True


class PostGenerationRequest(BaseModel):
    telegram_id: int
    custom_instructions: Optional[str] = None
    tones: List[PostTone] = [PostTone.FRIENDLY, PostTone.PROFESSIONAL, PostTone.TECHNICAL]


class PostUpdateRequest(BaseModel):
    content: str
    status: Optional[PostStatus] = None


class EntryResponse(BaseModel):
    success: bool
    message: str
    entry_id: int
    category: str
    summary: str
    streak: int


class StatusResponse(BaseModel):
    last_entry: Optional[datetime]
    entries_today: int
    streak: int
    total_entries: int


class SummaryResponse(BaseModel):
    type: str
    summary: str
    date: datetime


class GenerateResponse(BaseModel):
    success: bool
    posts_generated: int
    message: str


class User(BaseModel):
    id: Optional[int] = None
    telegram_id: int
    username: Optional[str] = None
    first_name: str
    last_name: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_active: datetime = Field(default_factory=datetime.utcnow)
    streak: int = 0
    total_entries: int = 0
    preferences: Dict[str, Any] = {}
    
    class Config:
        from_attributes = True


class UserStats(BaseModel):
    telegram_id: int
    streak: int
    total_entries: int
    entries_this_week: int
    most_common_category: Optional[str]
    average_entries_per_day: float
    last_entry: Optional[datetime]


class DashboardEntry(BaseModel):
    id: int
    date: datetime
    category: str
    summary: str
    activities: List[str]
    blockers: List[str]


class CalendarDay(BaseModel):
    date: str
    entry_count: int
    categories: List[str]
    has_blocker: bool


class WeeklyDashboard(BaseModel):
    week_start: str
    week_end: str
    entries: List[DashboardEntry]
    summary: Optional[WeeklySummary]
    posts: List[LinkedInPost]
    stats: Dict[str, Any]


class ThemeCluster(BaseModel):
    theme: str
    keywords: List[str]
    entry_count: int
    sample_entries: List[str]
    trend: str
