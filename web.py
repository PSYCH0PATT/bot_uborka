"""Запуск на Vercel: вместо постоянного процесса Telegram шлёт апдейты на вебхук, а напоминания дёргает крон."""

import asyncio
import hashlib
import json
import logging
import os
import threading
from contextlib import asynccontextmanager
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlsplit

from telegram import Update

import bot
from db import Store

logging.basicConfig(format="%(levelname)s %(name)s: %(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)

# Если платформа пустит несколько запросов в один процесс, они пойдут по очереди: у бота общий bot.store
_lock = threading.Lock()


def token() -> str:
    return os.environ["BOT_TOKEN"]


def webhook_secret() -> str:
    """Секрет для заголовка X-Telegram-Bot-Api-Secret-Token. Выводится из токена, чтобы не заводить ещё переменную."""
    return hashlib.sha256(f"webhook:{token()}".encode()).hexdigest()


def run(coro):
    with _lock:
        return asyncio.run(coro)


def database_url() -> str:
    url = bot.database_url()
    if os.environ.get("VERCEL") and not url.startswith(("postgres://", "postgresql://")):
        raise RuntimeError("Нет DATABASE_URL: подключи Postgres в проекте Vercel → Storage")
    return url


@asynccontextmanager
async def running_app():
    bot.store = Store(database_url())
    try:
        async with bot.build_app(token(), polling=False) as app:
            yield app
    finally:
        bot.store.close()


async def handle_update(data: dict) -> None:
    async with running_app() as app:
        await app.process_update(Update.de_json(data, app.bot))


async def run_cron(kind: str) -> int:
    """Рассылает напоминания. Второй вызов за тот же день ничего не шлёт — крон бывает доставлен дважды."""
    async with running_app() as app:
        if not bot.store.mark_once(f"cron:{kind}:{bot.today().isoformat()}"):
            return 0
        return await bot.send_reminders(app.bot, evening=kind == "evening")


async def setup(base_url: str) -> dict:
    async with running_app() as app:
        await app.bot.set_webhook(
            f"{base_url}/api/webhook",
            secret_token=webhook_secret(),
            allowed_updates=["message", "callback_query"],
        )
        await bot.set_commands(app)
        info = await app.bot.get_webhook_info()
        return {"url": info.url, "pending": info.pending_update_count, "last_error": info.last_error_message}


def cron_allowed(authorization: str | None) -> bool:
    """Если в Vercel задан CRON_SECRET, крон приходит с ним в заголовке — чужие вызовы отбрасываем."""
    secret = os.environ.get("CRON_SECRET")
    return not secret or authorization == f"Bearer {secret}"


class Router(BaseHTTPRequestHandler):
    """Разводит запросы по адресам. Файлы в api/ — тонкие обёртки над ним."""

    def reply(self, status: int, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def route(self) -> str:
        return urlsplit(self.path).path.rstrip("/")

    def do_POST(self):
        if self.route() != "/api/webhook":
            return self.reply(404, {"error": "not found"})
        if self.headers.get("X-Telegram-Bot-Api-Secret-Token") != webhook_secret():
            return self.reply(401, {"error": "bad secret"})
        data = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
        run(handle_update(data))
        self.reply(200, {"ok": True})

    def do_GET(self):
        route = self.route()
        if route in ("/api/morning", "/api/evening"):
            if not cron_allowed(self.headers.get("Authorization")):
                return self.reply(401, {"error": "bad cron secret"})
            kind = route.rsplit("/", 1)[1]
            return self.reply(200, {"kind": kind, "sent": run(run_cron(kind))})
        if route == "/api/setup":
            host = os.environ.get("VERCEL_PROJECT_PRODUCTION_URL") or self.headers.get("Host")
            return self.reply(200, run(setup(f"https://{host}")))
        self.reply(404, {"error": "not found"})
