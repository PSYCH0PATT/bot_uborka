"""Один раз после деплоя: прописывает вебхук и команды бота. Логика и маршруты — в web.py."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from web import Router  # noqa: E402


class handler(Router):
    pass
