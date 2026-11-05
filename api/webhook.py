"""Сюда Telegram присылает сообщения и нажатия кнопок."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from web import WebhookHandler  # noqa: E402


class handler(WebhookHandler):
    pass
