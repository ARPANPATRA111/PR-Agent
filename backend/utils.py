import os
import logging
import tempfile
from pathlib import Path
from typing import Optional, Tuple
from datetime import datetime
import asyncio

import httpx
import whisper

from config import settings

logger = logging.getLogger(__name__)
_whisper_model = None


def get_whisper_model():
    global _whisper_model
    
    if _whisper_model is None:
        logger.info(f"Loading Whisper model: {settings.whisper_model}")
        _whisper_model = whisper.load_model(settings.whisper_model)
        logger.info("Whisper model loaded successfully")
    
    return _whisper_model

async def download_telegram_audio(file_id: str, bot_token: str) -> Tuple[str, bytes]:
    async with httpx.AsyncClient() as client:
        file_info_url = f"https://api.telegram.org/bot{bot_token}/getFile"
        response = await client.get(file_info_url, params={"file_id": file_id})
        response.raise_for_status()
        
        file_info = response.json()
        if not file_info.get("ok"):
            raise ValueError(f"Failed to get file info: {file_info}")
        
        file_path = file_info["result"]["file_path"]
        
        download_url = f"https://api.telegram.org/file/bot{bot_token}/{file_path}"
        audio_response = await client.get(download_url)
        audio_response.raise_for_status()
        
        return file_path, audio_response.content


def save_audio_file(audio_bytes: bytes, file_id: str) -> str:
    temp_dir = Path(settings.audio_temp_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"voice_{timestamp}_{file_id[-8:]}.ogg"
    filepath = temp_dir / filename
    
    with open(filepath, "wb") as f:
        f.write(audio_bytes)
    
    logger.debug(f"Saved audio file: {filepath}")
    return str(filepath)


def convert_ogg_to_wav(ogg_path: str) -> str:
    import subprocess
    
    wav_path = ogg_path.replace(".ogg", ".wav")
    
    try:
        result = subprocess.run(
            [
                "ffmpeg", "-y",
                "-i", ogg_path,
                "-ar", "16000",
                "-ac", "1",
                "-c:a", "pcm_s16le",
                wav_path
            ],
            capture_output=True,
            text=True,
            timeout=60
        )
        
        if result.returncode != 0:
            logger.error(f"FFmpeg error: {result.stderr}")
            raise RuntimeError(f"FFmpeg conversion failed: {result.stderr}")
        
        logger.debug(f"Converted audio: {ogg_path} -> {wav_path}")
        return wav_path
        
    except FileNotFoundError:
        logger.error("FFmpeg not found. Please install FFmpeg.")
        raise RuntimeError("FFmpeg is required for audio conversion. Please install it.")


def cleanup_audio_files(*file_paths: str) -> None:
    for path in file_paths:
        try:
            if path and os.path.exists(path):
                os.remove(path)
                logger.debug(f"Cleaned up: {path}")
        except Exception as e:
            logger.warning(f"Failed to clean up {path}: {e}")

def transcribe_audio(audio_path: str) -> str:
    model = get_whisper_model()
    
    logger.info(f"Transcribing: {audio_path}")
    
    if audio_path.endswith(".ogg"):
        wav_path = convert_ogg_to_wav(audio_path)
        audio_to_transcribe = wav_path
    else:
        wav_path = None
        audio_to_transcribe = audio_path
    
    try:
        language = settings.whisper_language
        
        transcribe_options = {
            "fp16": False,
            "verbose": False
        }
        
        if language and language.lower() != "auto":
            transcribe_options["language"] = language
        
        result = model.transcribe(
            audio_to_transcribe,
            **transcribe_options
        )
        
        transcript = result["text"].strip()
        detected_language = result.get("language", "unknown")
        
        logger.info(
            f"Transcription complete: {len(transcript)} characters, "
            f"detected language: {detected_language}"
        )
        
        return transcript
        
    finally:
        if wav_path:
            cleanup_audio_files(wav_path)


async def transcribe_telegram_voice(file_id: str, bot_token: str) -> str:
    ogg_path = None
    
    try:
        _, audio_bytes = await download_telegram_audio(file_id, bot_token)
        
        ogg_path = save_audio_file(audio_bytes, file_id)
        
        loop = asyncio.get_event_loop()
        transcript = await loop.run_in_executor(
            None,
            transcribe_audio,
            ogg_path
        )
        
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
        "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
        "have", "has", "had", "do", "does", "did", "will", "would", "could",
        "should", "may", "might", "must", "shall", "can", "need", "dare",
        "to", "of", "in", "for", "on", "with", "at", "by", "from", "as",
        "into", "through", "during", "before", "after", "above", "below",
        "between", "under", "again", "further", "then", "once", "here",
        "there", "when", "where", "why", "how", "all", "each", "few", "more",
        "most", "other", "some", "such", "no", "nor", "not", "only", "own",
        "same", "so", "than", "too", "very", "just", "and", "but", "if", "or",
        "because", "until", "while", "this", "that", "these", "those", "i",
        "me", "my", "myself", "we", "our", "ours", "you", "your", "he", "him",
        "she", "her", "it", "its", "they", "them", "what", "which", "who"
    }
    
    words = re.findall(r'\b[a-zA-Z]{3,}\b', text.lower())
    
    filtered = [w for w in words if w not in stopwords]
    counts = Counter(filtered)
    
    return [word for word, _ in counts.most_common(max_keywords)]


def format_duration(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds}s"
    
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

def get_week_boundaries(reference_date: Optional[datetime] = None) -> Tuple[datetime, datetime]:
    if reference_date is None:
        reference_date = datetime.utcnow()
    
    days_since_monday = reference_date.weekday()
    week_start = reference_date - timedelta(days=days_since_monday)
    week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)
    
    week_end = week_start + timedelta(days=6)
    week_end = week_end.replace(hour=23, minute=59, second=59, microsecond=999999)
    
    return week_start, week_end


from datetime import timedelta


def get_day_boundaries(reference_date: Optional[datetime] = None) -> Tuple[datetime, datetime]:
    if reference_date is None:
        reference_date = datetime.utcnow()
    
    day_start = reference_date.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = reference_date.replace(hour=23, minute=59, second=59, microsecond=999999)
    
    return day_start, day_end

def setup_logging():
    log_dir = Path(settings.log_file).parent
    log_dir.mkdir(parents=True, exist_ok=True)
    
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )
    
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    
    file_handler = logging.FileHandler(settings.log_file)
    file_handler.setFormatter(formatter)
    
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, settings.log_level.upper()))
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
