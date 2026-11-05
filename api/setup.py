"""Один раз после деплоя: прописывает вебхук и команды бота."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from web import SetupHandler  # noqa: E402


class handler(SetupHandler):
    pass
