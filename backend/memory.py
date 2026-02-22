import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple, Generator
from contextlib import contextmanager

from sqlalchemy import create_engine, Column, Integer, String, Text, DateTime, Float, Boolean, ForeignKey, JSON, text, Index
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship, Session
from sqlalchemy.pool import StaticPool

from config import settings
from models import (
    RawEntry, StructuredEntry, DailySummary, WeeklySummary,
    LinkedInPost, User, EntryCategory, PostTone, PostStatus,
    Goal, GoalStatus, ReportFeedback
)

logger = logging.getLogger(__name__)

Base = declarative_base()


class UserDB(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    telegram_id = Column(Integer, unique=True, nullable=False, index=True)
    username = Column(String(255), nullable=True)
    first_name = Column(String(255), nullable=False)
    last_name = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_active = Column(DateTime, default=datetime.utcnow)
    streak = Column(Integer, default=0)
    total_entries = Column(Integer, default=0)
    preferences = Column(JSON, default=dict)
    
    raw_entries = relationship("RawEntryDB", back_populates="user")
    daily_summaries = relationship("DailySummaryDB", back_populates="user")
    weekly_summaries = relationship("WeeklySummaryDB", back_populates="user")
    posts = relationship("LinkedInPostDB", back_populates="user")


class RawEntryDB(Base):
    __tablename__ = "raw_entries"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    telegram_id = Column(Integer, ForeignKey("users.telegram_id"), nullable=False, index=True)
    telegram_message_id = Column(Integer, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    audio_file_id = Column(String(255), nullable=False)
    audio_duration = Column(Integer, nullable=False)
    transcript = Column(Text, nullable=False)
    
    user = relationship("UserDB", back_populates="raw_entries")
    structured_entry = relationship("StructuredEntryDB", back_populates="raw_entry", uselist=False)


class StructuredEntryDB(Base):
    __tablename__ = "structured_entries"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    raw_entry_id = Column(Integer, ForeignKey("raw_entries.id"), nullable=False, unique=True)
    category = Column(String(50), nullable=False, index=True)
    activities = Column(JSON, default=list)
    blockers = Column(JSON, default=list)
    accomplishments = Column(JSON, default=list)
    learnings = Column(JSON, default=list)
    summary = Column(Text, nullable=False)
    keywords = Column(JSON, default=list)
    sentiment = Column(String(50), nullable=True)
    
    raw_entry = relationship("RawEntryDB", back_populates="structured_entry")


class DailySummaryDB(Base):
    __tablename__ = "daily_summaries"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    telegram_id = Column(Integer, ForeignKey("users.telegram_id"), nullable=False, index=True)
    date = Column(DateTime, nullable=False, index=True)
    entries_count = Column(Integer, default=0)
    categories = Column(JSON, default=list)
    achievements = Column(JSON, default=list)
    learnings = Column(JSON, default=list)
    blockers_resolved = Column(JSON, default=list)
    blockers_pending = Column(JSON, default=list)
    reflection = Column(Text, nullable=False)
    themes = Column(JSON, default=list)
    productivity_score = Column(Float, nullable=True)
    
    user = relationship("UserDB", back_populates="daily_summaries")


class WeeklySummaryDB(Base):
    __tablename__ = "weekly_summaries"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    telegram_id = Column(Integer, ForeignKey("users.telegram_id"), nullable=False, index=True)
    week_start = Column(DateTime, nullable=False, index=True)
    week_end = Column(DateTime, nullable=False)
    daily_summary_ids = Column(JSON, default=list)
    total_entries = Column(Integer, default=0)
    main_themes = Column(JSON, default=list)
    accomplishments = Column(JSON, default=list)
    learnings = Column(JSON, default=list)
    trends = Column(JSON, default=dict)
    comparison_with_previous = Column(Text, nullable=True)
    
    user = relationship("UserDB", back_populates="weekly_summaries")
    posts = relationship("LinkedInPostDB", back_populates="weekly_summary")


class LinkedInPostDB(Base):
    __tablename__ = "linkedin_posts"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    telegram_id = Column(Integer, ForeignKey("users.telegram_id"), nullable=False, index=True)
    weekly_summary_id = Column(Integer, ForeignKey("weekly_summaries.id"), nullable=True)
    tone = Column(String(50), nullable=False)
    content = Column(Text, nullable=False)
    status = Column(String(50), default="draft")
    created_at = Column(DateTime, default=datetime.utcnow)
    edited_content = Column(Text, nullable=True)
    published_at = Column(DateTime, nullable=True)
    linkedin_url = Column(String(500), nullable=True)
    week_number = Column(Integer, nullable=True)
    version = Column(Integer, default=1)
    
    user = relationship("UserDB", back_populates="posts")
    weekly_summary = relationship("WeeklySummaryDB", back_populates="posts")


class NudgeLogDB(Base):
    __tablename__ = "nudge_logs"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    telegram_id = Column(Integer, nullable=False, index=True)
    sent_at = Column(DateTime, default=datetime.utcnow)
    nudge_type = Column(String(50), nullable=False)
    message = Column(Text, nullable=True)


class PostedReportDB(Base):
    __tablename__ = "posted_reports"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    telegram_id = Column(Integer, ForeignKey("users.telegram_id"), nullable=False, index=True)
    week_number = Column(Integer, nullable=False, index=True)
    content = Column(Text, nullable=False)
    published_at = Column(DateTime, default=datetime.utcnow)
    linkedin_url = Column(String(500), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    content_cutoff_date = Column(DateTime, nullable=True)
    
    user = relationship("UserDB")


class SearchableEntryDB(Base):
    __tablename__ = "searchable_entries"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    entry_id = Column(Integer, nullable=False, index=True)
    telegram_id = Column(Integer, nullable=False, index=True)
    content = Column(Text, nullable=False)
    keywords = Column(Text, nullable=True)
    metadata_json = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)


class SearchablePostDB(Base):
    __tablename__ = "searchable_posts"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    post_id = Column(Integer, nullable=False, index=True)
    telegram_id = Column(Integer, nullable=False, index=True)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class GoalDB(Base):
    """User goals for tracking progress"""
    __tablename__ = "goals"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    telegram_id = Column(Integer, ForeignKey("users.telegram_id"), nullable=False, index=True)
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    target_date = Column(DateTime, nullable=True)
    status = Column(String(50), default="active")  # active, completed, paused, abandoned
    progress = Column(Integer, default=0)  # 0-100
    sub_tasks = Column(JSON, default=list)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)
    
    user = relationship("UserDB")


class ReportFeedbackDB(Base):
    """Self-reflection feedback on generated reports"""
    __tablename__ = "report_feedback"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    report_type = Column(String(50), nullable=False)  # daily, weekly, linkedin
    report_id = Column(Integer, nullable=False, index=True)
    clarity_score = Column(Integer, nullable=False)  # 1-10
    suggestions = Column(JSON, default=list)
    applied_improvements = Column(JSON, default=list)
    created_at = Column(DateTime, default=datetime.utcnow)


class MemoryManager:
    
    def __init__(self):
        self._ensure_directories()
        self._init_sqlite()
        logger.info("Memory manager initialized successfully")
    
    def _ensure_directories(self):
        data_dir = Path("./data")
        data_dir.mkdir(exist_ok=True)
        
        audio_dir = Path(settings.audio_temp_dir)
        audio_dir.mkdir(parents=True, exist_ok=True)
        
        logs_dir = Path("./data/logs")
        logs_dir.mkdir(parents=True, exist_ok=True)
    
    def _init_sqlite(self):
        db_url = settings.database_url
        self.is_postgres = db_url.startswith("postgresql")
        
        if self.is_postgres:
            self.engine = create_engine(
                db_url,
                pool_pre_ping=True,
                pool_recycle=300,
                echo=settings.debug
            )
        else:
            db_path = db_url.replace("sqlite:///", "")
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
            
            self.engine = create_engine(
                db_url,
                connect_args={
                    "check_same_thread": False,
                    "timeout": 30
                },
                poolclass=StaticPool,
                echo=settings.debug
            )
            
            with self.engine.connect() as conn:
                conn.execute(text("PRAGMA journal_mode=WAL"))
                conn.execute(text("PRAGMA synchronous=NORMAL"))
                conn.commit()
        
        Base.metadata.create_all(bind=self.engine)
        self._run_migrations()
        self.SessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=self.engine
        )
    
    def _run_migrations(self):
        migrations = [
            ("linkedin_posts", "published_at", "TIMESTAMP" if self.is_postgres else "DATETIME"),
            ("linkedin_posts", "linkedin_url", "VARCHAR(500)"),
            ("linkedin_posts", "week_number", "INTEGER"),
            ("linkedin_posts", "version", "INTEGER DEFAULT 1"),
            ("posted_reports", "content_cutoff_date", "TIMESTAMP" if self.is_postgres else "DATETIME"),
        ]
        
        with self.engine.connect() as conn:
            for table, column, col_type in migrations:
                try:
                    if self.is_postgres:
                        result = conn.execute(text(
                            f"SELECT column_name FROM information_schema.columns "
                            f"WHERE table_name = '{table}' AND column_name = '{column}'"
                        ))
                        exists = result.fetchone() is not None
                    else:
                        result = conn.execute(text(f"PRAGMA table_info({table})"))
                        columns = [row[1] for row in result.fetchall()]
                        exists = column in columns
                    
                    if not exists:
                        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"))
                        logger.info(f"Added column {column} to {table}")
                except Exception as e:
                    logger.warning(f"Migration check for {table}.{column}: {e}")
            
            conn.commit()
    
    @contextmanager
    def get_session(self) -> Generator[Session, None, None]:
        session = self.SessionLocal()
        try:
            yield session
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"Database error: {e}")
            raise
        finally:
            session.close()

    def get_or_create_user(self, telegram_id: int, first_name: str, 
                          last_name: Optional[str] = None,
                          username: Optional[str] = None) -> User:
        with self.get_session() as session:
            user_db = session.query(UserDB).filter(
                UserDB.telegram_id == telegram_id
            ).first()
            
            if not user_db:
                user_db = UserDB(
                    telegram_id=telegram_id,
                    first_name=first_name,
                    last_name=last_name,
                    username=username
                )
                session.add(user_db)
                session.flush()
                logger.info(f"Created new user: {telegram_id}")
            else:
                user_db.last_active = datetime.utcnow()
            
            return User.model_validate(user_db)
    
    def update_user_streak(self, telegram_id: int) -> int:
        with self.get_session() as session:
            user = session.query(UserDB).filter(
                UserDB.telegram_id == telegram_id
            ).first()
            
            if not user:
                return 0
            
            today = datetime.utcnow().date()
            
            if user.last_active and user.last_active.date() == today:
                return user.streak
            
            yesterday = today - timedelta(days=1)
            
            if user.last_active and user.last_active.date() == yesterday:
                user.streak += 1
            elif user.last_active and user.last_active.date() < yesterday:
                user.streak = 1
            else:
                user.streak = 1
            
            user.last_active = datetime.utcnow()
            
            return user.streak
    
    def get_user_stats(self, telegram_id: int) -> Dict[str, Any]:
        with self.get_session() as session:
            user = session.query(UserDB).filter(
                UserDB.telegram_id == telegram_id
            ).first()
            
            if not user:
                return {}
            
            week_start = datetime.utcnow() - timedelta(days=7)
            entries_this_week = session.query(RawEntryDB).filter(
                RawEntryDB.telegram_id == telegram_id,
                RawEntryDB.timestamp >= week_start
            ).count()
            
            categories = session.query(
                StructuredEntryDB.category
            ).join(RawEntryDB).filter(
                RawEntryDB.telegram_id == telegram_id
            ).all()
            
            most_common = None
            if categories:
                from collections import Counter
                cat_counts = Counter([c[0] for c in categories])
                most_common = cat_counts.most_common(1)[0][0]
            
            last_entry = session.query(RawEntryDB).filter(
                RawEntryDB.telegram_id == telegram_id
            ).order_by(RawEntryDB.timestamp.desc()).first()
            
            return {
                "telegram_id": telegram_id,
                "streak": user.streak,
                "total_entries": user.total_entries,
                "entries_this_week": entries_this_week,
                "most_common_category": most_common,
                "last_entry": last_entry.timestamp if last_entry else None
            }

    def save_raw_entry(self, entry: RawEntry) -> int:
        with self.get_session() as session:
            entry_db = RawEntryDB(
                telegram_id=entry.telegram_id,
                telegram_message_id=entry.telegram_message_id,
                timestamp=entry.timestamp,
                audio_file_id=entry.audio_file_id,
                audio_duration=entry.audio_duration,
                transcript=entry.transcript
            )
            session.add(entry_db)
            session.flush()
            
            user = session.query(UserDB).filter(
                UserDB.telegram_id == entry.telegram_id
            ).first()
            if user:
                user.total_entries += 1
            
            logger.info(f"Saved raw entry {entry_db.id} for user {entry.telegram_id}")
            return entry_db.id
    
    def get_raw_entries_by_date(self, telegram_id: int, 
                                start_date: datetime,
                                end_date: datetime) -> List[RawEntry]:
        with self.get_session() as session:
            entries = session.query(RawEntryDB).filter(
                RawEntryDB.telegram_id == telegram_id,
                RawEntryDB.timestamp >= start_date,
                RawEntryDB.timestamp <= end_date
            ).order_by(RawEntryDB.timestamp).all()
            
            return [RawEntry.model_validate(e) for e in entries]

    def save_structured_entry(self, entry: StructuredEntry) -> int:
        with self.get_session() as session:
            entry_db = StructuredEntryDB(
                raw_entry_id=entry.raw_entry_id,
                category=entry.category.value,
                activities=entry.activities,
                blockers=entry.blockers,
                accomplishments=entry.accomplishments,
                learnings=entry.learnings,
                summary=entry.summary,
                keywords=entry.keywords,
                sentiment=entry.sentiment
            )
            session.add(entry_db)
            session.flush()
            
            logger.info(f"Saved structured entry {entry_db.id}")
            return entry_db.id
    
    def get_structured_entries_by_date(self, telegram_id: int,
                                       start_date: datetime,
                                       end_date: datetime) -> List[StructuredEntry]:
        try:
            with self.get_session() as session:
                entries = session.query(StructuredEntryDB).join(RawEntryDB).filter(
                    RawEntryDB.telegram_id == telegram_id,
                    RawEntryDB.timestamp >= start_date,
                    RawEntryDB.timestamp <= end_date
                ).order_by(RawEntryDB.timestamp).all()
                
                result = []
                for e in entries:
                    try:
                        entry = StructuredEntry(
                            id=e.id,
                            raw_entry_id=e.raw_entry_id,
                            category=EntryCategory(e.category) if e.category else EntryCategory.OTHER,
                            activities=e.activities or [],
                            blockers=e.blockers or [],
                            accomplishments=e.accomplishments or [],
                            learnings=e.learnings or [],
                            summary=e.summary or '',
                            keywords=e.keywords or [],
                            sentiment=e.sentiment
                        )
                        result.append(entry)
                    except Exception as ex:
                        logger.warning(f"Error converting entry {e.id}: {ex}")
                        continue
                
                return result
        except Exception as ex:
            logger.error(f"Error fetching structured entries: {ex}")
            return []

    def add_to_vector_memory(self, entry_id: int, text: str, 
                            metadata: Dict[str, Any]) -> None:
        with self.get_session() as session:
            try:
                existing = session.query(SearchableEntryDB).filter(
                    SearchableEntryDB.entry_id == entry_id
                ).first()
                if existing:
                    return
                
                keywords = metadata.get('keywords', [])
                keywords_str = ' '.join(keywords) if isinstance(keywords, list) else str(keywords)
                
                searchable = SearchableEntryDB(
                    entry_id=entry_id,
                    telegram_id=metadata.get('telegram_id', 0),
                    content=text,
                    keywords=keywords_str,
                    metadata_json=metadata
                )
                session.add(searchable)
                logger.debug(f"Added entry {entry_id} to search index")
            except Exception as e:
                logger.error(f"Error adding to search index: {e}")
    
    def search_similar_entries(self, query: str, n_results: int = 5,
                               telegram_id: Optional[int] = None) -> List[Dict[str, Any]]:
        with self.get_session() as session:
            try:
                query_filter = SearchableEntryDB.content.ilike(f'%{query}%') | \
                               SearchableEntryDB.keywords.ilike(f'%{query}%')
                
                base_query = session.query(SearchableEntryDB).filter(query_filter)
                
                if telegram_id:
                    base_query = base_query.filter(SearchableEntryDB.telegram_id == telegram_id)
                
                results = base_query.order_by(SearchableEntryDB.created_at.desc()).limit(n_results).all()
                
                return [
                    {
                        "id": str(r.entry_id),
                        "document": r.content,
                        "metadata": r.metadata_json or {},
                        "distance": 0
                    }
                    for r in results
                ]
            except Exception as e:
                logger.error(f"Error searching entries: {e}")
                return []
    
    def get_recent_post_embeddings(self, telegram_id: int, 
                                   n_results: int = 3) -> List[str]:
        with self.get_session() as session:
            try:
                results = session.query(SearchablePostDB).filter(
                    SearchablePostDB.telegram_id == telegram_id
                ).order_by(SearchablePostDB.created_at.desc()).limit(n_results).all()
                
                return [r.content for r in results]
            except Exception as e:
                logger.error(f"Error getting recent post content: {e}")
                return []
    
    def add_post_to_vector_memory(self, post_id: int, content: str,
                                  telegram_id: int) -> None:
        with self.get_session() as session:
            try:
                existing = session.query(SearchablePostDB).filter(
                    SearchablePostDB.post_id == post_id
                ).first()
                if existing:
                    return
                
                searchable = SearchablePostDB(
                    post_id=post_id,
                    telegram_id=telegram_id,
                    content=content
                )
                session.add(searchable)
                logger.debug(f"Added post {post_id} to search index")
            except Exception as e:
                logger.error(f"Error adding post to search index: {e}")
    
    def detect_themes(self, telegram_id: int, 
                     n_clusters: int = 5) -> List[Dict[str, Any]]:
        with self.get_session() as session:
            try:
                results = session.query(SearchableEntryDB).filter(
                    SearchableEntryDB.telegram_id == telegram_id
                ).all()
                
                if not results:
                    return []
                
                from collections import Counter
                
                all_keywords = []
                for r in results:
                    metadata = r.metadata_json or {}
                    keywords = metadata.get('keywords', [])
                    if isinstance(keywords, str) and keywords.strip():
                        try:
                            keywords = json.loads(keywords)
                        except json.JSONDecodeError:
                            keywords = []
                    elif not isinstance(keywords, list):
                        keywords = []
                    all_keywords.extend(keywords)
                
                theme_counts = Counter(all_keywords)
                themes = [
                    {"theme": theme, "count": count}
                    for theme, count in theme_counts.most_common(n_clusters)
                ]
                
                return themes
            except Exception as e:
                logger.error(f"Error detecting themes: {e}")
                return []

    def save_daily_summary(self, summary: DailySummary) -> int:
        with self.get_session() as session:
            summary_db = DailySummaryDB(
                telegram_id=summary.telegram_id,
                date=summary.date,
                entries_count=summary.entries_count,
                categories=summary.categories,
                achievements=summary.achievements,
                learnings=summary.learnings,
                blockers_resolved=summary.blockers_resolved,
                blockers_pending=summary.blockers_pending,
                reflection=summary.reflection,
                themes=summary.themes,
                productivity_score=summary.productivity_score
            )
            session.add(summary_db)
            session.flush()
            
            logger.info(f"Saved daily summary {summary_db.id} for {summary.date.date()}")
            return summary_db.id
    
    def get_daily_summaries(self, telegram_id: int, days: int = 7) -> List[DailySummary]:
        with self.get_session() as session:
            start_date = datetime.utcnow() - timedelta(days=days)
            
            summaries = session.query(DailySummaryDB).filter(
                DailySummaryDB.telegram_id == telegram_id,
                DailySummaryDB.date >= start_date
            ).order_by(DailySummaryDB.date.desc()).all()
            
            return [DailySummary.model_validate(s) for s in summaries]
    
    def save_weekly_summary(self, summary: WeeklySummary) -> int:
        with self.get_session() as session:
            summary_db = WeeklySummaryDB(
                telegram_id=summary.telegram_id,
                week_start=summary.week_start,
                week_end=summary.week_end,
                daily_summary_ids=summary.daily_summaries,
                total_entries=summary.total_entries,
                main_themes=summary.main_themes,
                accomplishments=summary.accomplishments,
                learnings=summary.learnings,
                trends=summary.trends,
                comparison_with_previous=summary.comparison_with_previous
            )
            session.add(summary_db)
            session.flush()
            
            logger.info(f"Saved weekly summary {summary_db.id}")
            return summary_db.id
    
    def get_latest_weekly_summary(self, telegram_id: int) -> Optional[WeeklySummary]:
        with self.get_session() as session:
            summary = session.query(WeeklySummaryDB).filter(
                WeeklySummaryDB.telegram_id == telegram_id
            ).order_by(WeeklySummaryDB.week_end.desc()).first()
            
            if summary:
                return WeeklySummary(
                    id=summary.id,
                    telegram_id=summary.telegram_id,
                    week_start=summary.week_start,
                    week_end=summary.week_end,
                    daily_summaries=summary.daily_summary_ids or [],
                    total_entries=summary.total_entries,
                    main_themes=summary.main_themes or [],
                    accomplishments=summary.accomplishments or [],
                    learnings=summary.learnings or [],
                    trends=summary.trends or {},
                    comparison_with_previous=summary.comparison_with_previous
                )
            return None

    def get_next_version_for_week(self, telegram_id: int, week_number: int) -> int:
        with self.get_session() as session:
            from sqlalchemy import func
            result = session.query(func.max(LinkedInPostDB.version)).filter(
                LinkedInPostDB.telegram_id == telegram_id,
                LinkedInPostDB.week_number == week_number
            ).scalar()
            
            return (result or 0) + 1
    
    def save_linkedin_post(self, post: LinkedInPost) -> int:
        with self.get_session() as session:
            version = post.version
            if post.week_number:
                version = self.get_next_version_for_week(post.telegram_id, post.week_number)
            
            post_db = LinkedInPostDB(
                telegram_id=post.telegram_id,
                weekly_summary_id=post.weekly_summary_id,
                tone=post.tone.value,
                content=post.content,
                status=post.status.value,
                created_at=post.created_at,
                published_at=post.published_at,
                linkedin_url=post.linkedin_url,
                week_number=post.week_number,
                version=version
            )
            session.add(post_db)
            session.flush()
            
            self.add_post_to_vector_memory(
                post_db.id, 
                post.content,
                post.telegram_id
            )
            
            logger.info(f"Saved LinkedIn post {post_db.id} (Week {post.week_number}, Version {version})")
            return post_db.id
    
    def get_drafts_for_week(self, telegram_id: int, week_number: int) -> List[LinkedInPost]:
        with self.get_session() as session:
            posts = session.query(LinkedInPostDB).filter(
                LinkedInPostDB.telegram_id == telegram_id,
                LinkedInPostDB.week_number == week_number
            ).order_by(LinkedInPostDB.version.desc()).all()
            
            return [LinkedInPost.model_validate(p) for p in posts]
    
    def get_posts_for_summary(self, weekly_summary_id: int) -> List[LinkedInPost]:
        with self.get_session() as session:
            posts = session.query(LinkedInPostDB).filter(
                LinkedInPostDB.weekly_summary_id == weekly_summary_id
            ).all()
            
            return [LinkedInPost.model_validate(p) for p in posts]
    
    def update_post(self, post_id: int, content: str, 
                   status: Optional[PostStatus] = None) -> bool:
        with self.get_session() as session:
            post = session.query(LinkedInPostDB).filter(
                LinkedInPostDB.id == post_id
            ).first()
            
            if not post:
                return False
            
            post.edited_content = content
            if status:
                post.status = status.value
            
            return True
    
    def get_recent_posts(self, telegram_id: int, limit: int = 10) -> List[LinkedInPost]:
        with self.get_session() as session:
            posts = session.query(LinkedInPostDB).filter(
                LinkedInPostDB.telegram_id == telegram_id
            ).order_by(LinkedInPostDB.created_at.desc()).limit(limit).all()
            
            return [LinkedInPost.model_validate(p) for p in posts]
    
    def mark_post_as_published(self, post_id: int, linkedin_url: Optional[str] = None,
                                week_number: Optional[int] = None) -> bool:
        with self.get_session() as session:
            post = session.query(LinkedInPostDB).filter(
                LinkedInPostDB.id == post_id
            ).first()
            
            if not post:
                return False
            
            post.status = PostStatus.POSTED.value
            post.published_at = datetime.utcnow()
            if linkedin_url:
                post.linkedin_url = linkedin_url
            if week_number:
                post.week_number = week_number
            
            logger.info(f"Marked post {post_id} as published (Week {week_number})")
            return True
    
    def delete_linkedin_post(self, post_id: int, telegram_id: int) -> bool:
        """Delete a generated LinkedIn post."""
        with self.get_session() as session:
            post = session.query(LinkedInPostDB).filter(
                LinkedInPostDB.id == post_id,
                LinkedInPostDB.telegram_id == telegram_id
            ).first()
            
            if post:
                session.delete(post)
                logger.info(f"Deleted LinkedIn post {post_id}")
                return True
            return False
    
    def get_published_posts(self, telegram_id: int, limit: int = 50) -> List[LinkedInPost]:
        with self.get_session() as session:
            posts = session.query(LinkedInPostDB).filter(
                LinkedInPostDB.telegram_id == telegram_id,
                LinkedInPostDB.status == PostStatus.POSTED.value
            ).order_by(LinkedInPostDB.published_at.desc()).limit(limit).all()
            
            return [LinkedInPost.model_validate(p) for p in posts]
    
    def get_posts_by_week(self, telegram_id: int, week_number: int) -> List[LinkedInPost]:
        with self.get_session() as session:
            posts = session.query(LinkedInPostDB).filter(
                LinkedInPostDB.telegram_id == telegram_id,
                LinkedInPostDB.week_number == week_number
            ).all()
            
            return [LinkedInPost.model_validate(p) for p in posts]
    
    def get_latest_week_number(self, telegram_id: int) -> int:
        with self.get_session() as session:
            from sqlalchemy import func
            result = session.query(func.max(LinkedInPostDB.week_number)).filter(
                LinkedInPostDB.telegram_id == telegram_id,
                LinkedInPostDB.week_number.isnot(None)
            ).scalar()
            
            return result or 0
    
    def get_next_week_number(self, telegram_id: int) -> int:
        """Get next week number based on POSTED reports, not drafts."""
        from config import settings
        latest_posted = self.get_latest_posted_week(telegram_id)
        
        if latest_posted > 0:
            return latest_posted + 1
        else:
            return settings.current_week_number
    
    def get_last_posted_report_date(self, telegram_id: int) -> Optional[datetime]:
        """Get the content cutoff date of the last posted report to determine cutoff for new content."""
        with self.get_session() as session:
            report = session.query(PostedReportDB).filter(
                PostedReportDB.telegram_id == telegram_id
            ).order_by(PostedReportDB.week_number.desc()).first()
            
            if report:
                return report.content_cutoff_date or report.published_at
            return None
    
    def log_nudge(self, telegram_id: int, nudge_type: str, message: str) -> None:
        with self.get_session() as session:
            nudge = NudgeLogDB(
                telegram_id=telegram_id,
                nudge_type=nudge_type,
                message=message
            )
            session.add(nudge)
    
    def get_last_nudge(self, telegram_id: int) -> Optional[datetime]:
        with self.get_session() as session:
            nudge = session.query(NudgeLogDB).filter(
                NudgeLogDB.telegram_id == telegram_id
            ).order_by(NudgeLogDB.sent_at.desc()).first()
            
            return nudge.sent_at if nudge else None
    
    def get_users_needing_nudge(self, hours_threshold: int = 24) -> List[int]:
        with self.get_session() as session:
            threshold = datetime.utcnow() - timedelta(hours=hours_threshold)
            
            users = session.query(UserDB).all()
            
            users_to_nudge = []
            for user in users:
                last_entry = session.query(RawEntryDB).filter(
                    RawEntryDB.telegram_id == user.telegram_id
                ).order_by(RawEntryDB.timestamp.desc()).first()
                
                if last_entry and last_entry.timestamp < threshold:
                    last_nudge = session.query(NudgeLogDB).filter(
                        NudgeLogDB.telegram_id == user.telegram_id,
                        NudgeLogDB.sent_at > threshold
                    ).first()
                    
                    if not last_nudge:
                        users_to_nudge.append(user.telegram_id)
            
            return users_to_nudge

    def get_calendar_data(self, telegram_id: int, 
                         month: int, year: int) -> List[Dict[str, Any]]:
        from calendar import monthrange
        
        with self.get_session() as session:
            start_date = datetime(year, month, 1)
            _, last_day = monthrange(year, month)
            end_date = datetime(year, month, last_day, 23, 59, 59)
            
            entries = session.query(RawEntryDB).filter(
                RawEntryDB.telegram_id == telegram_id,
                RawEntryDB.timestamp >= start_date,
                RawEntryDB.timestamp <= end_date
            ).all()
            
            from collections import defaultdict
            daily_data = defaultdict(lambda: {"count": 0, "categories": set(), "has_blocker": False})
            
            for entry in entries:
                day = entry.timestamp.strftime("%Y-%m-%d")
                daily_data[day]["count"] += 1
                
                if entry.structured_entry:
                    daily_data[day]["categories"].add(entry.structured_entry.category)
                    if entry.structured_entry.blockers:
                        daily_data[day]["has_blocker"] = True
            
            return [
                {
                    "date": day,
                    "entry_count": data["count"],
                    "categories": list(data["categories"]),
                    "has_blocker": data["has_blocker"]
                }
                for day, data in daily_data.items()
            ]

    def save_posted_report(self, telegram_id: int, week_number: int, 
                          content: str, published_at: datetime = None,
                          linkedin_url: str = None,
                          content_cutoff_date: datetime = None) -> int:
        with self.get_session() as session:
            if content_cutoff_date is None:
                from sqlalchemy import func
                latest_entry = session.query(func.max(RawEntryDB.timestamp)).filter(
                    RawEntryDB.telegram_id == telegram_id
                ).scalar()
                content_cutoff_date = latest_entry or datetime.utcnow()
            
            report = PostedReportDB(
                telegram_id=telegram_id,
                week_number=week_number,
                content=content,
                published_at=published_at or datetime.utcnow(),
                linkedin_url=linkedin_url,
                created_at=datetime.utcnow(),
                content_cutoff_date=content_cutoff_date
            )
            session.add(report)
            session.flush()
            
            logger.info(f"Saved posted report for Week {week_number} with cutoff {content_cutoff_date}")
            return report.id
    
    def get_posted_reports(self, telegram_id: int, limit: int = 10, offset: int = 0) -> List[Dict[str, Any]]:
        with self.get_session() as session:
            reports = session.query(PostedReportDB).filter(
                PostedReportDB.telegram_id == telegram_id
            ).order_by(PostedReportDB.week_number.desc()).offset(offset).limit(limit).all()
            
            return [
                {
                    "id": r.id,
                    "week_number": r.week_number,
                    "content": r.content,
                    "published_at": r.published_at,
                    "linkedin_url": r.linkedin_url,
                    "content_cutoff_date": r.content_cutoff_date
                }
                for r in reports
            ]
    
    def count_posted_reports(self, telegram_id: int) -> int:
        with self.get_session() as session:
            return session.query(PostedReportDB).filter(
                PostedReportDB.telegram_id == telegram_id
            ).count()
    
    def get_latest_posted_week(self, telegram_id: int) -> int:
        with self.get_session() as session:
            from sqlalchemy import func
            result = session.query(func.max(PostedReportDB.week_number)).filter(
                PostedReportDB.telegram_id == telegram_id
            ).scalar()
            return result or 0
    
    def delete_posted_report(self, report_id: int, telegram_id: int) -> bool:
        with self.get_session() as session:
            report = session.query(PostedReportDB).filter(
                PostedReportDB.id == report_id,
                PostedReportDB.telegram_id == telegram_id
            ).first()
            
            if report:
                session.delete(report)
                logger.info(f"Deleted posted report {report_id}")
                return True
            return False
    
    def delete_entry(self, entry_id: int, telegram_id: int) -> bool:
        with self.get_session() as session:
            entry = session.query(RawEntryDB).filter(
                RawEntryDB.id == entry_id,
                RawEntryDB.telegram_id == telegram_id
            ).first()
            
            if not entry:
                return False
            
            if entry.structured_entry:
                session.delete(entry.structured_entry)
            
            session.delete(entry)
            
            user = session.query(UserDB).filter(
                UserDB.telegram_id == telegram_id
            ).first()
            if user and user.total_entries > 0:
                user.total_entries -= 1
            
            logger.info(f"Deleted entry {entry_id} for user {telegram_id}")
            return True
    
    def delete_entry_by_message_id(self, telegram_id: int, message_id: int) -> bool:
        with self.get_session() as session:
            entry = session.query(RawEntryDB).filter(
                RawEntryDB.telegram_id == telegram_id,
                RawEntryDB.telegram_message_id == message_id
            ).first()
            
            if not entry:
                return False
            
            if entry.structured_entry:
                session.delete(entry.structured_entry)
            
            session.delete(entry)
            
            user = session.query(UserDB).filter(
                UserDB.telegram_id == telegram_id
            ).first()
            if user and user.total_entries > 0:
                user.total_entries -= 1
            
            logger.info(f"Deleted entry with message_id {message_id}")
            return True
    
    def get_entries(self, telegram_id: int, limit: int = 20) -> List[Dict[str, Any]]:
        """Get recent raw entries for a user."""
        try:
            with self.get_session() as session:
                entries = session.query(RawEntryDB).filter(
                    RawEntryDB.telegram_id == telegram_id
                ).order_by(RawEntryDB.timestamp.desc()).limit(limit).all()
                
                return [
                    {
                        "id": e.id,
                        "telegram_id": e.telegram_id,
                        "raw_text": e.transcript or '',
                        "timestamp": e.timestamp,
                        "created_at": e.timestamp
                    }
                    for e in entries
                ]
        except Exception as ex:
            logger.error(f"Error fetching entries: {ex}")
            return []
    
    def get_recent_entries_for_deletion(self, telegram_id: int, limit: int = 10) -> List[Dict[str, Any]]:
        try:
            with self.get_session() as session:
                entries = session.query(RawEntryDB).filter(
                    RawEntryDB.telegram_id == telegram_id
                ).order_by(RawEntryDB.timestamp.desc()).limit(limit).all()
                
                result = []
                for e in entries:
                    timestamp_str = 'Unknown'
                    if e.timestamp:
                        try:
                            timestamp_str = e.timestamp.strftime('%Y-%m-%d %H:%M')
                        except:
                            timestamp_str = str(e.timestamp)
                    
                    transcript = e.transcript or ''
                    summary = transcript[:100] + "..." if len(transcript) > 100 else transcript
                    
                    category = 'entry'
                    if e.structured_entry:
                        category = e.structured_entry.category or 'entry'
                    
                    result.append({
                        "id": e.id,
                        "message_id": e.telegram_message_id,
                        "timestamp": timestamp_str,
                        "summary": summary,
                        "category": category
                    })
                
                return result
        except Exception as ex:
            logger.error(f"Error fetching entries for deletion: {ex}")
            return []
    
    def clear_generated_posts(self, telegram_id: int) -> int:
        with self.get_session() as session:
            deleted = session.query(LinkedInPostDB).filter(
                LinkedInPostDB.telegram_id == telegram_id
            ).delete()
            logger.info(f"Cleared {deleted} generated posts for user {telegram_id}")
            return deleted
    
    def save_goal(self, goal: Goal) -> int:
        """Save a new goal or update existing one."""
        with self.get_session() as session:
            if goal.id:
                db_goal = session.query(GoalDB).filter(GoalDB.id == goal.id).first()
                if db_goal:
                    db_goal.title = goal.title
                    db_goal.description = goal.description
                    db_goal.target_date = goal.target_date
                    db_goal.status = goal.status.value if isinstance(goal.status, GoalStatus) else goal.status
                    db_goal.progress = goal.progress
                    db_goal.sub_tasks = goal.sub_tasks
                    db_goal.updated_at = datetime.utcnow()
                    return db_goal.id
            
            db_goal = GoalDB(
                telegram_id=goal.telegram_id,
                title=goal.title,
                description=goal.description,
                target_date=goal.target_date,
                status=goal.status.value if isinstance(goal.status, GoalStatus) else goal.status,
                progress=goal.progress,
                sub_tasks=goal.sub_tasks
            )
            session.add(db_goal)
            session.flush()
            logger.info(f"Saved goal '{goal.title}' for user {goal.telegram_id}")
            return db_goal.id
    
    def get_active_goals(self, telegram_id: int) -> List[Goal]:
        """Get all active goals for a user."""
        with self.get_session() as session:
            goals = session.query(GoalDB).filter(
                GoalDB.telegram_id == telegram_id,
                GoalDB.status == "active"
            ).order_by(GoalDB.created_at.desc()).all()
            
            return [
                Goal(
                    id=g.id,
                    telegram_id=g.telegram_id,
                    title=g.title,
                    description=g.description,
                    target_date=g.target_date,
                    status=GoalStatus(g.status),
                    progress=g.progress,
                    sub_tasks=g.sub_tasks or [],
                    created_at=g.created_at,
                    updated_at=g.updated_at
                )
                for g in goals
            ]
    
    def get_all_goals(self, telegram_id: int) -> List[Goal]:
        """Get all goals for a user."""
        with self.get_session() as session:
            goals = session.query(GoalDB).filter(
                GoalDB.telegram_id == telegram_id
            ).order_by(GoalDB.created_at.desc()).all()
            
            return [
                Goal(
                    id=g.id,
                    telegram_id=g.telegram_id,
                    title=g.title,
                    description=g.description,
                    target_date=g.target_date,
                    status=GoalStatus(g.status),
                    progress=g.progress,
                    sub_tasks=g.sub_tasks or [],
                    created_at=g.created_at,
                    updated_at=g.updated_at
                )
                for g in goals
            ]
    
    def update_goal_progress(self, goal_id: int, progress: int, telegram_id: int) -> bool:
        """Update goal progress (0-100)."""
        with self.get_session() as session:
            goal = session.query(GoalDB).filter(
                GoalDB.id == goal_id,
                GoalDB.telegram_id == telegram_id
            ).first()
            
            if goal:
                goal.progress = min(100, max(0, progress))
                goal.updated_at = datetime.utcnow()
                if goal.progress >= 100:
                    goal.status = "completed"
                logger.info(f"Updated goal {goal_id} progress to {progress}%")
                return True
            return False
    
    def update_goal_status(self, goal_id: int, status: str, telegram_id: int) -> bool:
        """Update goal status."""
        with self.get_session() as session:
            goal = session.query(GoalDB).filter(
                GoalDB.id == goal_id,
                GoalDB.telegram_id == telegram_id
            ).first()
            
            if goal:
                goal.status = status
                goal.updated_at = datetime.utcnow()
                logger.info(f"Updated goal {goal_id} status to {status}")
                return True
            return False
    
    def delete_goal(self, goal_id: int, telegram_id: int) -> bool:
        """Delete a goal."""
        with self.get_session() as session:
            goal = session.query(GoalDB).filter(
                GoalDB.id == goal_id,
                GoalDB.telegram_id == telegram_id
            ).first()
            
            if goal:
                session.delete(goal)
                logger.info(f"Deleted goal {goal_id}")
                return True
            return False
    
    def save_report_feedback(self, feedback: ReportFeedback) -> int:
        """Save feedback for a generated report."""
        with self.get_session() as session:
            db_feedback = ReportFeedbackDB(
                report_type=feedback.report_type,
                report_id=feedback.report_id,
                clarity_score=feedback.clarity_score,
                suggestions=feedback.suggestions,
                applied_improvements=feedback.applied_improvements
            )
            session.add(db_feedback)
            session.flush()
            logger.info(f"Saved feedback for {feedback.report_type} report {feedback.report_id}")
            return db_feedback.id
    
    def get_feedback_for_prompt_refinement(self, report_type: str, limit: int = 5) -> List[str]:
        """Get recent feedback suggestions to refine future prompts."""
        with self.get_session() as session:
            feedbacks = session.query(ReportFeedbackDB).filter(
                ReportFeedbackDB.report_type == report_type
            ).order_by(ReportFeedbackDB.created_at.desc()).limit(limit).all()
            
            suggestions = []
            for f in feedbacks:
                if f.suggestions:
                    suggestions.extend(f.suggestions)
            return list(set(suggestions))[:10]  # Dedupe and limit

memory_manager: Optional[MemoryManager] = None


def get_memory_manager() -> MemoryManager:
    global memory_manager
    if memory_manager is None:
        memory_manager = MemoryManager()
    return memory_manager
