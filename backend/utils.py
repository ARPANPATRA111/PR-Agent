import os
import logging
import json
import tempfile
from pathlib import Path
from typing import Optional, Tuple
from datetime import datetime, timezone
import asyncio

import httpx

from config import settings

logger = logging.getLogger(__name__)

ALLOWED_VOICE_SUFFIXES = {".ogg", ".oga", ".opus", ".mp3", ".m4a", ".wav", ".webm"}
ALLOWED_VOICE_MIME_TYPES = {
    "audio/ogg",
    "audio/opus",
    "audio/mpeg",
    "audio/mp4",
    "audio/x-m4a",
    "audio/wav",
    "audio/webm",
}


def validate_voice_metadata(
    *,
    duration_seconds: int,
    file_size: int | None,
    mime_type: str | None,
) -> None:
    if duration_seconds <= 0 or duration_seconds > settings.max_voice_duration_seconds:
        raise ValueError(
            f"Voice notes must be between 1 and "
            f"{settings.max_voice_duration_seconds} seconds."
        )
    if file_size is not None and file_size > settings.max_voice_file_size:
        raise ValueError("That voice note is larger than the supported limit.")
    if mime_type and mime_type.lower() not in ALLOWED_VOICE_MIME_TYPES:
        raise ValueError("That voice file type is not supported.")


async def download_telegram_audio(file_id: str, bot_token: str) -> Tuple[str, bytes]:
    timeout = httpx.Timeout(settings.voice_download_timeout_seconds)
    last_error: Exception | None = None
    for attempt in range(settings.voice_provider_max_attempts):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.get(
                    f"https://api.telegram.org/bot{bot_token}/getFile",
                    params={"file_id": file_id},
                )
                response.raise_for_status()
                file_info = response.json()
                result = file_info.get("result") if file_info.get("ok") else None
                file_path = (
                    result.get("file_path") if isinstance(result, dict) else None
                )
                if not isinstance(file_path, str):
                    raise RuntimeError("Telegram did not return a voice file.")
                suffix = Path(file_path).suffix.lower()
                if suffix not in ALLOWED_VOICE_SUFFIXES:
                    raise ValueError("That voice file type is not supported.")

                content = bytearray()
                async with client.stream(
                    "GET",
                    f"https://api.telegram.org/file/bot{bot_token}/{file_path}",
                ) as audio_response:
                    audio_response.raise_for_status()
                    declared_size = audio_response.headers.get("content-length")
                    if (
                        declared_size
                        and int(declared_size) > settings.max_voice_file_size
                    ):
                        raise ValueError(
                            "That voice note is larger than the supported limit."
                        )
                    async for chunk in audio_response.aiter_bytes():
                        content.extend(chunk)
                        if len(content) > settings.max_voice_file_size:
                            raise ValueError(
                                "That voice note is larger than the supported limit."
                            )
                return suffix, bytes(content)
        except ValueError:
            raise
        except (httpx.HTTPError, RuntimeError) as exc:
            last_error = exc
            if attempt + 1 < settings.voice_provider_max_attempts:
                await asyncio.sleep(0.25 * (attempt + 1))
    raise RuntimeError("Telegram voice download failed.") from last_error


def save_audio_file(audio_bytes: bytes, suffix: str = ".ogg") -> str:
    if len(audio_bytes) > settings.max_voice_file_size:
        raise ValueError("That voice note is larger than the supported limit.")
    if suffix not in ALLOWED_VOICE_SUFFIXES:
        raise ValueError("That voice file type is not supported.")
    temp_dir = Path(settings.audio_temp_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="wb",
        prefix="voice-",
        suffix=suffix,
        dir=temp_dir,
        delete=False,
    ) as audio_file:
        audio_file.write(audio_bytes)
        return audio_file.name


def cleanup_audio_files(*file_paths: str) -> None:
    for path in file_paths:
        try:
            if path and os.path.exists(path):
                os.remove(path)
        except OSError:
            logger.warning("Temporary voice cleanup failed")


async def transcribe_audio_groq(audio_path: str) -> str:
    """Transcribe one bounded temporary audio file."""
    audio_bytes = await asyncio.to_thread(Path(audio_path).read_bytes)
    if len(audio_bytes) > settings.max_voice_file_size:
        raise ValueError("That voice note is larger than the supported limit.")
    suffix = Path(audio_path).suffix.lower()
    last_error: Exception | None = None
    for attempt in range(settings.voice_provider_max_attempts):
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(settings.transcription_timeout_seconds)
            ) as client:
                response = await asyncio.wait_for(
                    client.post(
                        "https://api.groq.com/openai/v1/audio/transcriptions",
                        headers={"Authorization": f"Bearer {settings.groq_api_key}"},
                        files={
                            "file": (
                                f"voice{suffix}",
                                audio_bytes,
                                "application/octet-stream",
                            ),
                            "model": (None, settings.whisper_model),
                        },
                    ),
                    timeout=settings.transcription_timeout_seconds,
                )
                response.raise_for_status()
                transcript = response.json().get("text", "").strip()
                if not transcript:
                    raise RuntimeError("Transcription returned no text.")
                logger.info(
                    "Voice transcription completed",
                    extra={"transcript_length": len(transcript)},
                )
                return transcript
        except (httpx.HTTPError, asyncio.TimeoutError, RuntimeError) as exc:
            last_error = exc
            if attempt + 1 < settings.voice_provider_max_attempts:
                await asyncio.sleep(0.5 * (attempt + 1))
    raise RuntimeError("Voice transcription failed.") from last_error


async def transcribe_telegram_voice(file_id: str, bot_token: str) -> str:
    ogg_path = None

    try:
        suffix, audio_bytes = await download_telegram_audio(file_id, bot_token)
        ogg_path = save_audio_file(audio_bytes, suffix)

        # Use Groq's fast Whisper API instead of local model
        transcript = await transcribe_audio_groq(ogg_path)

        return transcript

    finally:
        if ogg_path:
            cleanup_audio_files(ogg_path)


def truncate_text(text: str, max_length: int = 500) -> str:
    if len(text) <= max_length:
        return text

    truncated = text[:max_length]
    last_space = truncated.rfind(" ")

    if last_space > max_length * 0.8:
        truncated = truncated[:last_space]

    return truncated + "..."


def extract_keywords(text: str, max_keywords: int = 10) -> list:
    import re
    from collections import Counter

    stopwords = {
        "the",
        "a",
        "an",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "could",
        "should",
        "may",
        "might",
        "must",
        "shall",
        "can",
        "need",
        "dare",
        "to",
        "of",
        "in",
        "for",
        "on",
        "with",
        "at",
        "by",
        "from",
        "as",
        "into",
        "through",
        "during",
        "before",
        "after",
        "above",
        "below",
        "between",
        "under",
        "again",
        "further",
        "then",
        "once",
        "here",
        "there",
        "when",
        "where",
        "why",
        "how",
        "all",
        "each",
        "few",
        "more",
        "most",
        "other",
        "some",
        "such",
        "no",
        "nor",
        "not",
        "only",
        "own",
        "same",
        "so",
        "than",
        "too",
        "very",
        "just",
        "and",
        "but",
        "if",
        "or",
        "because",
        "until",
        "while",
        "this",
        "that",
        "these",
        "those",
        "i",
        "me",
        "my",
        "myself",
        "we",
        "our",
        "ours",
        "you",
        "your",
        "he",
        "him",
        "she",
        "her",
        "it",
        "its",
        "they",
        "them",
        "what",
        "which",
        "who",
    }

    words = re.findall(r"\b[a-zA-Z]{3,}\b", text.lower())

    filtered = [w for w in words if w not in stopwords]
    counts = Counter(filtered)

    return [word for word, _ in counts.most_common(max_keywords)]


def format_duration(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds}s"

    if seconds >= 3600:
        hours = seconds // 3600
        remaining_minutes = (seconds % 3600) // 60
        if remaining_minutes == 0:
            return f"{hours}h"
        return f"{hours}h {remaining_minutes}m"

    minutes = seconds // 60
    remaining_seconds = seconds % 60

    if remaining_seconds == 0:
        return f"{minutes}m"

    return f"{minutes}m {remaining_seconds}s"


def format_streak(streak: int) -> str:
    if streak == 0:
        return "Start your streak today! 🌱"
    elif streak < 3:
        return f"🔥 {streak} day streak - keep it up!"
    elif streak < 7:
        return f"🔥🔥 {streak} day streak - you're on fire!"
    elif streak < 14:
        return f"🔥🔥🔥 {streak} day streak - amazing consistency!"
    elif streak < 30:
        return f"⭐ {streak} day streak - you're a star!"
    else:
        return f"🏆 {streak} day streak - legendary consistency!"


def get_week_boundaries(
    reference_date: Optional[datetime] = None,
) -> Tuple[datetime, datetime]:
    if reference_date is None:
        reference_date = datetime.utcnow()

    days_since_monday = reference_date.weekday()
    week_start = reference_date - timedelta(days=days_since_monday)
    week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)

    week_end = week_start + timedelta(days=6)
    week_end = week_end.replace(hour=23, minute=59, second=59, microsecond=999999)

    return week_start, week_end


from datetime import timedelta


def get_day_boundaries(
    reference_date: Optional[datetime] = None,
) -> Tuple[datetime, datetime]:
    if reference_date is None:
        reference_date = datetime.utcnow()

    day_start = reference_date.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = reference_date.replace(hour=23, minute=59, second=59, microsecond=999999)

    return day_start, day_end


def setup_logging():
    log_dir = Path(settings.log_file).parent
    log_dir.mkdir(parents=True, exist_ok=True)

    class SafeJsonFormatter(logging.Formatter):
        allowed_fields = {
            "request_id",
            "method",
            "path",
            "status_code",
            "latency_ms",
            "update_id",
            "job_id",
            "delivery_id",
            "owner_id",
            "error_category",
            "transcript_length",
        }

        def format(self, record):
            payload = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "level": record.levelname,
                "logger": record.name,
                "event": record.getMessage(),
            }
            for field in self.allowed_fields:
                value = getattr(record, field, None)
                if value is not None:
                    payload[field] = value
            if record.exc_info:
                payload["exception_type"] = record.exc_info[0].__name__
            return json.dumps(payload, separators=(",", ":"), default=str)

    formatter = (
        SafeJsonFormatter()
        if settings.json_logs
        else logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    file_handler = logging.FileHandler(settings.log_file)
    file_handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, settings.log_level.upper()))
    if not root_logger.handlers:
        root_logger.addHandler(console_handler)
        root_logger.addHandler(file_handler)

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("chromadb").setLevel(logging.WARNING)
    logging.getLogger("whisper").setLevel(logging.WARNING)


def validate_telegram_token(token: str) -> bool:
    if not token:
        return False

    parts = token.split(":")
    if len(parts) != 2:
        return False

    try:
        int(parts[0])
        return len(parts[1]) > 20
    except ValueError:
        return False


def validate_groq_api_key(key: str) -> bool:
    if not key:
        return False

    return key.startswith("gsk_") and len(key) > 20
