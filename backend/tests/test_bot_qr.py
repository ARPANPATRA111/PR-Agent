from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "generate_bot_qr.py"
SPEC = spec_from_file_location("generate_bot_qr", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
bot_qr = module_from_spec(SPEC)
SPEC.loader.exec_module(bot_qr)


def test_accepts_bot_deep_link():
    value = "https://t.me/MyPRAgentBot?start=github"
    assert bot_qr.validate_bot_url(value) == value


@pytest.mark.parametrize(
    "value",
    [
        "http://t.me/MyPRAgentBot",
        "https://example.com/MyPRAgentBot",
        "https://t.me/not-a-telegram-bot-user",
        "https://t.me/MyPRAgentBot?token=secret",
        f"https://t.me/MyPRAgentBot?start={'x' * 65}",
    ],
)
def test_rejects_unsafe_or_invalid_links(value):
    with pytest.raises(ValueError):
        bot_qr.validate_bot_url(value)
