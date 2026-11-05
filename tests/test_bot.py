"""Сквозные проверки хендлеров на фейковом Telegram: без сети и без токена."""

import asyncio
from datetime import date, datetime
from types import SimpleNamespace

import pytest

import bot
GROUP = -1001
IDS = {"dima": 11, "artem": 22, "nikita": 33}


class FakeBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, reply_markup=None):
        self.sent.append(SimpleNamespace(chat_id=chat_id, text=text, markup=reply_markup))


class FakeMessage:
    def __init__(self, chat_id=GROUP):
        self.chat_id = chat_id
        self.reply_markup = None
        self.replies = []

    async def reply_text(self, text, reply_markup=None):
        self.replies.append(SimpleNamespace(text=text, markup=reply_markup))


class FakeQuery:
    def __init__(self, data, person, markup=None):
        self.data = data
        self.from_user = SimpleNamespace(id=IDS[person])
        self.message = FakeMessage()
        self.message.reply_markup = markup
        self.answers = []
        self.edits = []

    async def answer(self, text=None, show_alert=False):
        self.answers.append(text)

    async def edit_message_text(self, text, reply_markup=None):
        self.edits.append(text)

    async def edit_message_reply_markup(self, markup):
        self.message.reply_markup = markup


def press(handler, query, ctx):
    asyncio.run(handler(SimpleNamespace(callback_query=query), ctx))


def command(handler, person, ctx):
    msg = FakeMessage()
    update = SimpleNamespace(
        effective_message=msg,
        effective_user=SimpleNamespace(id=IDS[person]),
        effective_chat=SimpleNamespace(id=GROUP, type="group"),
    )
    asyncio.run(handler(update, ctx))
    return msg.replies


@pytest.fixture
def ctx(monkeypatch, blank_store):
    store = blank_store
    store.set_chat_id(GROUP)
    for person, tg_id in IDS.items():
        store.register(person, tg_id)
    monkeypatch.setattr(bot, "store", store, raising=False)
    set_day(monkeypatch, 5)
    return SimpleNamespace(bot=FakeBot())


def set_day(monkeypatch, day, month=11):
    monkeypatch.setattr(bot, "today", lambda: date(2026, month, day))
    monkeypatch.setattr(bot, "now", lambda: datetime(2026, month, day, 12, tzinfo=bot.TZ))


def test_app_builds_with_morning_and_evening_jobs():
    app = bot.build_app("123:TEST")
    assert sorted(job.name for job in app.job_queue.jobs()) == ["evening", "morning"]


def test_reminder_pings_assignee_and_only_they_can_mark_done(ctx):
    sent = asyncio.run(bot.send_reminders(ctx.bot, evening=False))
    assert sent == 1
    reminder = ctx.bot.sent[0]
    assert reminder.chat_id == GROUP
    assert f"tg://user?id={IDS['nikita']}" in reminder.text
    button = reminder.markup.inline_keyboard[0][0]

    q = FakeQuery(button.callback_data, "artem", reminder.markup)
    press(bot.on_done, q, ctx)
    assert "Не твоя очередь" in q.answers[0]

    q = FakeQuery(button.callback_data, "nikita", reminder.markup)
    press(bot.on_done, q, ctx)
    assert q.message.reply_markup is None
    announce = ctx.bot.sent[-1].text
    assert "Никита</b> вынес мусор" in announce
    assert f"tg://user?id={IDS['artem']}" in announce
    assert "до 09.11" in announce


def test_late_trash_is_fined_and_paid_with_neighbour_confirmation(ctx, monkeypatch):
    set_day(monkeypatch, 8)
    asyncio.run(bot.send_reminders(ctx.bot, evening=False))
    assert "200 Kč" in ctx.bot.sent[0].text

    replies = command(bot.cmd_paid, "nikita", ctx)
    assert "200 Kč" in replies[0].text
    ok_button = replies[0].markup.inline_keyboard[0][0].callback_data

    q = FakeQuery(ok_button, "nikita")
    press(bot.on_pay, q, ctx)
    assert "хитрожопый" in q.answers[0]

    q = FakeQuery(ok_button, "dima")
    press(bot.on_pay, q, ctx)
    assert "закрыл 200 Kč" in q.edits[0]
    assert bot.store.balance("nikita") == 0


def test_nothing_due_before_first_trash_day(ctx, monkeypatch):
    set_day(monkeypatch, 3)
    assert asyncio.run(bot.send_reminders(ctx.bot, evening=False)) == 0
    status = command(bot.cmd_status, "dima", ctx)[0].text
    assert "Вынести мусор: <b>Никита</b>, до 05.11, через 2 дня" in status
    assert "Постирать коврики: <b>Артём</b>, до 29.11" in status


def test_shop_records_buyer_and_shows_next(ctx):
    q = FakeQuery("buy:5", "dima")
    press(bot.on_buy, q, ctx)
    assert "Соль — <b>Артём</b> (последний раз Дима, 05.11)" in q.edits[0]

    q = FakeQuery("unbuy", "dima")
    press(bot.on_unbuy, q, ctx)
    assert "Соль — <b>Дима</b> (ещё никто не покупал)" in q.edits[0]


def test_unknown_user_is_asked_to_register(ctx, monkeypatch):
    q = FakeQuery("buy:0", "dima")
    q.from_user = SimpleNamespace(id=999)
    press(bot.on_buy, q, ctx)
    assert "/start" in q.answers[0]


def test_webhook_app_builds_without_polling():
    assert bot.build_app("123:TEST", polling=False).updater is None
