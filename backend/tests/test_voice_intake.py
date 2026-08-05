"""Every way a user can send speech should reach the same pipeline."""

from __future__ import annotations

import pytest

from models import TelegramMessage
from utils import (
    VOICE_QUOTA_UNIT_SECONDS,
    daily_voice_unit_limit,
    voice_quota_units,
)


def message_with(**attachment) -> TelegramMessage:
    return TelegramMessage.model_validate(
        {
            "message_id": 1,
            "date": 1_760_000_000,
            "chat": {"id": 9001, "type": "private"},
            "from": {"id": 1001, "first_name": "Alice"},
            **attachment,
        }
    )


AUDIO = {
    "file_id": "file-1",
    "file_unique_id": "unique-1",
    "duration": 12,
    "mime_type": "audio/ogg",
    "file_size": 4096,
}


def test_a_recorded_voice_note_is_used():
    message = message_with(voice=AUDIO)

    spoken = message.spoken_audio

    assert spoken is not None
    assert spoken.file_id == "file-1"
    assert spoken.duration == 12


def test_a_forwarded_audio_file_is_treated_as_speech():
    message = message_with(audio={**AUDIO, "mime_type": "audio/mpeg"})

    spoken = message.spoken_audio

    assert spoken is not None
    assert spoken.file_id == "file-1"
    assert spoken.mime_type == "audio/mpeg"


def test_a_round_video_note_is_treated_as_speech():
    message = message_with(video_note={**AUDIO, "mime_type": None})

    assert message.spoken_audio is not None


def test_an_audio_document_is_treated_as_speech():
    message = message_with(document={**AUDIO, "mime_type": "audio/wav"})

    assert message.spoken_audio is not None


def test_a_non_audio_document_is_ignored():
    message = message_with(document={**AUDIO, "mime_type": "application/pdf"})

    assert message.spoken_audio is None


def test_a_plain_text_message_has_no_audio():
    assert message_with(text="hello").spoken_audio is None


def test_a_recorded_note_wins_over_other_attachments():
    message = message_with(
        voice=AUDIO,
        audio={**AUDIO, "file_id": "other", "file_unique_id": "other"},
    )

    assert message.spoken_audio.file_id == "file-1"


def test_a_caption_is_available_as_text():
    message = message_with(document={**AUDIO, "mime_type": "application/pdf"})
    message = message.model_copy(update={"caption": "log this please"})

    assert message.caption == "log this please"


@pytest.mark.parametrize(
    ("duration", "expected"),
    [
        (0, 1),
        (1, 1),
        (VOICE_QUOTA_UNIT_SECONDS, 1),
        (VOICE_QUOTA_UNIT_SECONDS + 1, 2),
        (60, 4),
        (61, 5),
        (600, 40),
    ],
)
def test_voice_is_billed_in_short_blocks(duration, expected):
    assert voice_quota_units(duration) == expected


def test_a_short_note_no_longer_costs_a_whole_minute(monkeypatch):
    """Thirty five-second notes used to exhaust a thirty-minute allowance."""
    from config import settings

    monkeypatch.setattr(settings, "per_user_daily_voice_minutes", 30)

    short_notes_affordable = daily_voice_unit_limit() // voice_quota_units(5)

    assert short_notes_affordable == 120


def test_the_daily_limit_still_reflects_configured_minutes(monkeypatch):
    from config import settings

    monkeypatch.setattr(settings, "per_user_daily_voice_minutes", 10)

    assert daily_voice_unit_limit() == 40
    assert voice_quota_units(600) == 40
