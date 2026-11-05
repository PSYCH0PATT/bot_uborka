"""Крон: вечерние напоминания."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from web import CronHandler  # noqa: E402


class handler(CronHandler):
    kind = "evening"
