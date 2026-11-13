"""Сквозные проверки хендлеров на фейковом Telegram: без сети и без токена."""

import asyncio
from datetime import date, datetime
from types import SimpleNamespace

import pytest
from telegram.error import ChatMigrated, Forbidden

import bot
import phrases

GROUP = -1001
OTHER = -1002  # другая конфа, где тоже оказался бот
IDS = {"dima": 11, "artem": 22, "nikita": 33}
STRANGER = 999
REAL_TODAY = bot.today


class FakeBot:
    id = 777

    def __init__(self):
        self.sent = []
        self.kicked_from = set()  # чаты, откуда бота выгнали
        self.migrated = {}  # старый id группы → id супергруппы

    async def send_message(self, chat_id, text, reply_markup=None):
        if chat_id in self.kicked_from:
            raise Forbidden("Forbidden: bot was kicked from the supergroup chat")
        if chat_id in self.migrated:
            raise ChatMigrated(self.migrated[chat_id])
        self.sent.append(SimpleNamespace(chat_id=chat_id, text=text, markup=reply_markup))

    async def get_chat_member(self, chat_id, user_id):
        assert user_id == self.id
        if chat_id in self.kicked_from:
            raise Forbidden("Forbidden: bot was kicked from the supergroup chat")
        if chat_id in self.migrated:
            raise ChatMigrated(self.migrated[chat_id])
        return SimpleNamespace(status="member")


class FakeMessage:
    def __init__(self, chat_id=GROUP):
        self.chat_id = chat_id
        self.reply_markup = None
        self.replies = []

    async def reply_text(self, text, reply_markup=None):
        self.replies.append(SimpleNamespace(text=text, markup=reply_markup))


class FakeQuery:
    def __init__(self, data, person, markup=None, chat_id=GROUP):
        self.data = data
        self.from_user = SimpleNamespace(id=IDS.get(person, STRANGER))
        self.message = FakeMessage(chat_id)
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


def command(handler, person, ctx, chat_id=GROUP):
    msg = FakeMessage(chat_id)
    update = SimpleNamespace(
        effective_message=msg,
        effective_user=SimpleNamespace(id=IDS.get(person, STRANGER)),
        effective_chat=SimpleNamespace(id=chat_id, type="supergroup"),
    )
    asyncio.run(handler(update, ctx))
    return msg.replies


def group_update(chat_id, person, migrate_to=None, migrate_from=None):
    """Апдейт из группы, как его видит watch_chat перед остальными хендлерами."""
    return SimpleNamespace(
        effective_chat=SimpleNamespace(id=chat_id, type="supergroup"),
        effective_user=SimpleNamespace(id=IDS.get(person, STRANGER)),
        effective_message=SimpleNamespace(migrate_to_chat_id=migrate_to, migrate_from_chat_id=migrate_from),
    )


def watch(update, ctx):
    asyncio.run(bot.watch_chat(update, ctx))


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


def set_clock(monkeypatch, day, hour, month=11):
    """Настоящие часы: какое сегодня число, бот решает сам."""
    monkeypatch.setattr(bot, "today", REAL_TODAY)
    monkeypatch.setattr(bot, "now", lambda: datetime(2026, month, day, hour, tzinfo=bot.TZ))


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
    assert "Никита" in q.answers[0]  # чья очередь на самом деле
    assert bot.store.open_tasks()[0].done_on is None

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
    assert q.answers[0] in phrases.SELF_CONFIRM
    assert bot.store.balance("nikita") == 200

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


# --- день до 6 утра ---


def test_trash_taken_out_at_3am_counts_for_the_previous_day(ctx, monkeypatch):
    # Срок 5.11, бесплатно до конца 6.11. В 3 ночи 7.11 это ещё 6.11 — без штрафа.
    set_clock(monkeypatch, 7, 3)
    assert bot.today() == date(2026, 11, 6)
    asyncio.run(bot.send_reminders(ctx.bot, evening=False))
    button = ctx.bot.sent[0].markup.inline_keyboard[0][0].callback_data
    press(bot.on_done, FakeQuery(button, "nikita"), ctx)
    assert "Никита</b> вынес мусор." in ctx.bot.sent[-1].text
    assert "опоздание" not in ctx.bot.sent[-1].text
    assert bot.store.balance("nikita") == 0
    assert "до 10.11" in ctx.bot.sent[-1].text  # следующий срок считается от 6.11


def test_new_day_and_its_fine_start_at_6am(ctx, monkeypatch):
    set_clock(monkeypatch, 7, 5)
    bot.refresh()
    assert bot.store.balance("nikita") == 0
    set_clock(monkeypatch, 7, 6)
    bot.refresh()
    assert bot.store.balance("nikita") == 100


# --- общий чат ---


def test_bot_moves_to_the_group_where_we_write_when_old_chat_is_gone(ctx):
    # Общий чат — OTHER, оттуда бота кикнули, а пишут ему из GROUP
    bot.store.set_chat_id(OTHER)
    ctx.bot.kicked_from.add(OTHER)
    watch(group_update(GROUP, "artem"), ctx)
    assert bot.store.get_chat_id() == GROUP
    assert ctx.bot.sent[-1].chat_id == GROUP
    assert "теперь напоминания пишу сюда" in ctx.bot.sent[-1].text

    assert asyncio.run(bot.send_reminders(ctx.bot, evening=False)) == 1
    assert ctx.bot.sent[-1].chat_id == GROUP


def test_strangers_and_live_chat_keep_the_binding(ctx):
    # Живой общий чат молча не отбирается
    watch(group_update(OTHER, "artem"), ctx)
    assert bot.store.get_chat_id() == GROUP
    # Чужие в другой группе не перехватят даже пропавший чат
    ctx.bot.kicked_from.add(GROUP)
    watch(group_update(OTHER, "stranger"), ctx)
    assert bot.store.get_chat_id() == GROUP
    assert ctx.bot.sent == []


def test_group_turned_into_supergroup_is_followed(ctx):
    watch(group_update(GROUP, "dima", migrate_to=-1009), ctx)
    assert bot.store.get_chat_id() == -1009

    bot.store.set_chat_id(GROUP)
    watch(group_update(-1009, "stranger", migrate_from=GROUP), ctx)
    assert bot.store.get_chat_id() == -1009


def test_reminder_follows_supergroup_migration_on_send(ctx):
    ctx.bot.migrated[GROUP] = -1009
    assert asyncio.run(bot.send_reminders(ctx.bot, evening=False)) == 1
    assert ctx.bot.sent[0].chat_id == -1009
    assert bot.store.get_chat_id() == -1009


def test_reminders_to_a_lost_chat_fail_loudly(ctx):
    ctx.bot.kicked_from.add(GROUP)
    with pytest.raises(Forbidden):
        asyncio.run(bot.send_reminders(ctx.bot, evening=False))


def test_start_in_another_group_asks_before_moving(ctx):
    reply = command(bot.cmd_start, "stranger", ctx, chat_id=OTHER)[0]
    assert bot.store.get_chat_id() == GROUP
    move = reply.markup.inline_keyboard[0][0].callback_data
    assert move == "move"

    q = FakeQuery(move, "stranger", reply.markup, chat_id=OTHER)
    press(bot.on_move, q, ctx)
    assert "/start" in q.answers[0]
    assert bot.store.get_chat_id() == GROUP

    q = FakeQuery(move, "dima", reply.markup, chat_id=OTHER)
    press(bot.on_move, q, ctx)
    assert bot.store.get_chat_id() == OTHER
    assert q.message.reply_markup is None
    assert {m.chat_id for m in ctx.bot.sent} == {GROUP, OTHER}  # старый чат тоже в курсе


def test_start_in_the_home_group_keeps_it(ctx):
    reply = command(bot.cmd_start, "dima", ctx)[0]
    assert bot.store.get_chat_id() == GROUP
    assert "буду писать сюда" in reply.text


def test_done_in_new_group_survives_lost_old_chat(ctx):
    bot.store.set_chat_id(OTHER)
    ctx.bot.kicked_from.add(OTHER)
    bot.refresh()
    task = bot.store.open_tasks()[0]
    press(bot.on_done, FakeQuery(f"done:{task.id}", "nikita"), ctx)
    assert "вынес мусор" in ctx.bot.sent[-1].text
    assert ctx.bot.sent[-1].chat_id == GROUP


def test_remind_from_another_chat_says_where_it_went(ctx):
    replies = command(bot.cmd_remind, "dima", ctx, chat_id=OTHER)
    assert replies[0].text == "Напоминания ушли в общий чат."
    assert ctx.bot.sent[0].chat_id == GROUP


# --- подъёбы просто так ---


def test_banter_is_random_and_not_too_often(ctx, monkeypatch):
    monkeypatch.setattr(bot, "BANTER_CHANCE", 1)
    set_day(monkeypatch, 1)
    assert asyncio.run(bot.cron(ctx.bot, evening=False)) == (0, True)
    assert asyncio.run(bot.cron(ctx.bot, evening=True)) == (0, False)
    set_day(monkeypatch, 2)
    assert asyncio.run(bot.cron(ctx.bot, evening=False)) == (0, False)
    set_day(monkeypatch, 3)
    assert asyncio.run(bot.cron(ctx.bot, evening=False)) == (0, True)
    assert len(ctx.bot.sent) == 2
    assert all(m.chat_id == GROUP for m in ctx.bot.sent)
    pairs = [(bot.name(a), bot.name(b)) for a in bot.PEOPLE for b in bot.PEOPLE if a != b]
    rendered = {line.format(who=a, other=b) for line in phrases.BANTER for a, b in pairs}
    assert all(m.text in rendered for m in ctx.bot.sent)


def test_no_banter_when_dice_say_no_or_reminders_went_out(ctx, monkeypatch):
    monkeypatch.setattr(bot, "BANTER_CHANCE", 0)
    set_day(monkeypatch, 1)
    assert asyncio.run(bot.cron(ctx.bot, evening=False)) == (0, False)
    monkeypatch.setattr(bot, "BANTER_CHANCE", 1)
    set_day(monkeypatch, 5)  # Никите выносить мусор: хватит и напоминания
    assert asyncio.run(bot.cron(ctx.bot, evening=False)) == (1, False)


def test_short_replies_come_from_phrases(ctx, monkeypatch):
    replies = command(bot.cmd_paid, "dima", ctx)
    assert replies[0].text in {line.format(who=bot.name("dima")) for line in phrases.NO_DEBT}
    set_day(monkeypatch, 3)  # до 5.11 никто ничего не должен
    replies = command(bot.cmd_remind, "dima", ctx)
    assert replies[0].text in phrases.NOTHING_DUE
