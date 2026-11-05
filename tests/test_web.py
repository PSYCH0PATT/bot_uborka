"""Проверка входных точек Vercel на настоящем HTTP-сервере, но с фейковым Telegram."""

import json
import re
import threading
import urllib.error
import urllib.request
from datetime import date
from http.server import HTTPServer
from types import SimpleNamespace

import pytest

import web
from db import Store
from index import handler

GROUP = -1001


class FakeBot:
    defaults = None

    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, reply_markup=None):
        self.sent.append(SimpleNamespace(chat_id=chat_id, text=text))


class FakeApp:
    def __init__(self):
        self.bot = FakeBot()
        self.updates = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def process_update(self, update):
        self.updates.append(update)


@pytest.fixture
def env(monkeypatch, tmp_path):
    db_path = str(tmp_path / "bot.db")
    monkeypatch.setenv("BOT_TOKEN", "123:TEST")
    monkeypatch.setenv("DB_PATH", db_path)
    for var in ("DATABASE_URL", "POSTGRES_URL", "CRON_SECRET"):
        monkeypatch.delenv(var, raising=False)
    app = FakeApp()
    monkeypatch.setattr(web.bot, "build_app", lambda token, polling: app)
    monkeypatch.setattr(web.bot, "today", lambda: date(2026, 11, 5))

    store = Store(db_path)
    store.set_chat_id(GROUP)
    store.register("nikita", 33)
    store.close()
    return app


def call(name, method="GET", body=None, headers=None):
    server = HTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            f"http://127.0.0.1:{server.server_port}/api/{name}", data=data, method=method, headers=headers or {}
        )
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read())
    finally:
        server.shutdown()
        server.server_close()


def test_webhook_secret_is_stable_and_allowed_by_telegram(env):
    secret = web.webhook_secret()
    assert secret == web.webhook_secret()
    assert re.fullmatch(r"[A-Za-z0-9_-]{1,256}", secret)


def test_webhook_rejects_requests_without_the_secret(env):
    status, _ = call("webhook", "POST", {"update_id": 1})
    assert status == 401
    assert env.updates == []


def test_webhook_passes_update_to_the_bot(env):
    status, _ = call("webhook", "POST", {"update_id": 7}, {"X-Telegram-Bot-Api-Secret-Token": web.webhook_secret()})
    assert status == 200
    assert [u.update_id for u in env.updates] == [7]


def test_morning_cron_reminds_once_per_day(env):
    assert call("morning") == (200, {"kind": "morning", "sent": 1})
    assert call("morning") == (200, {"kind": "morning", "sent": 0})
    assert len(env.bot.sent) == 1
    assert env.bot.sent[0].chat_id == GROUP
    assert "tg://user?id=33" in env.bot.sent[0].text


def test_evening_cron_is_counted_separately(env):
    call("morning")
    assert call("evening") == (200, {"kind": "evening", "sent": 1})


def test_cron_secret_is_checked_when_set(env, monkeypatch):
    monkeypatch.setenv("CRON_SECRET", "s3cret")
    assert call("morning")[0] == 401
    assert call("morning", headers={"Authorization": "Bearer s3cret"})[0] == 200


def test_unknown_paths_are_404(env):
    assert call("nothing")[0] == 404
    assert call("morning", "POST", {})[0] == 404
