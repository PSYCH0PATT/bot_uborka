"""Телеграм-бот по уборке: очереди, напоминания, штрафы и продукты."""

import logging
import os
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from telegram import Bot, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ChatType, ParseMode
from telegram.error import BadRequest
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, Defaults

import texts
from db import Store, Task
from rules import CHORES, CURRENCY, GROCERIES, NAMES, PEOPLE, due_label


def load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


load_env(Path(__file__).with_name(".env"))

TZ = ZoneInfo(os.environ.get("TZ_NAME", "Europe/Prague"))
MORNING = time.fromisoformat(os.environ.get("MORNING", "10:00")).replace(tzinfo=TZ)
EVENING = time.fromisoformat(os.environ.get("EVENING", "21:00")).replace(tzinfo=TZ)
DONE_BUTTON_DAYS_AHEAD = 7  # в /status кнопка «сделал» есть у задач на ближайшую неделю

HELP = (
    "/status — чья очередь и кто сколько должен\n"
    "/shop — кто следующий покупает продукты\n"
    "/fines — долги по штрафам\n"
    "/paid — «я заплатил штраф», сосед подтверждает\n"
    "/remind — прислать напоминания прямо сейчас"
)

log = logging.getLogger("uborka")
store: Store


def database_url() -> str:
    """Postgres на сервере (Vercel кладёт строку в DATABASE_URL или POSTGRES_URL), локально — файл SQLite."""
    return (
        os.environ.get("DATABASE_URL")
        or os.environ.get("POSTGRES_URL")
        or os.environ.get("DB_PATH")
        or str(Path(__file__).with_name("uborka.db"))
    )


def now() -> datetime:
    return datetime.now(TZ)


def today() -> date:
    return now().date()


def name(person: str) -> str:
    return f"<b>{NAMES[person]}</b>"


def who(person: str) -> str:
    """Имя со ссылкой — Telegram пришлёт человеку уведомление."""
    tg_id = store.tg_of(person)
    return f'<a href="tg://user?id={tg_id}">{NAMES[person]}</a>' if tg_id else name(person)


async def safe_edit(query, text: str, markup: InlineKeyboardMarkup | None) -> None:
    try:
        await query.edit_message_text(text, reply_markup=markup)
    except BadRequest as e:
        if "not modified" not in str(e):
            raise


async def whoami(query) -> str | None:
    person = store.person_by_tg(query.from_user.id)
    if person is None:
        await query.answer("Я тебя не знаю. Напиши /start и нажми на своё имя.", show_alert=True)
    return person


def refresh() -> date:
    t = today()
    store.ensure_tasks(t)
    store.sync_fines(t)
    return t


# --- кто есть кто ---


def register_text() -> str:
    lines = ["Кто есть кто? Нажми на своё имя, чтобы я знал, кого пинать:"]
    for p in PEOPLE:
        lines.append(f"{NAMES[p]} {'✅' if store.tg_of(p) else '— ещё не нажал'}")
    return "\n".join(lines)


def register_keyboard() -> InlineKeyboardMarkup | None:
    free = [p for p in PEOPLE if store.tg_of(p) is None]
    if not free:
        return None
    return InlineKeyboardMarkup([[InlineKeyboardButton(f"Я {NAMES[p]}", callback_data=f"reg:{p}") for p in free]])


async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    if chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
        store.set_chat_id(chat.id)
        intro = "Всё, теперь я тут главный по уборке. Напоминания и наезды буду писать сюда."
    else:
        intro = "Добавь меня в общий чат с соседями и напиши там /start: напоминания идут туда."
    await update.effective_message.reply_text(
        f"{intro}\n\n{register_text()}\n\n{HELP}", reply_markup=register_keyboard()
    )


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(HELP)


async def on_register(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    person = q.data.split(":")[1]
    status = store.register(person, q.from_user.id)
    if status == "taken":
        await q.answer(f"{NAMES[person]} уже занят другим человеком.", show_alert=True)
        return
    if status == "already":
        await q.answer(f"Ты и так {NAMES[person]}.")
        return
    await q.answer(f"Запомнил, ты {NAMES[person]}.")
    await safe_edit(q, register_text(), register_keyboard())


# --- обязанности ---


def done_keyboard(tasks: list[Task], with_names: bool) -> InlineKeyboardMarkup | None:
    rows = []
    for t in tasks:
        chore = CHORES[t.chore]
        label = f"✅ {NAMES[t.assignee]} {chore.done}" if with_names else f"✅ {chore.done.capitalize()}"
        rows.append([InlineKeyboardButton(label, callback_data=f"done:{t.id}")])
    return InlineKeyboardMarkup(rows) if rows else None


def without_button(markup: InlineKeyboardMarkup | None, data: str) -> InlineKeyboardMarkup | None:
    if markup is None:
        return None
    rows = [row for row in markup.inline_keyboard if all(b.callback_data != data for b in row)]
    return InlineKeyboardMarkup(rows) if rows else None


def status_text(t: date) -> str:
    lines = [f"📋 <b>Расклад на {t:%d.%m}</b>", ""]
    for task in store.open_tasks():
        chore = CHORES[task.chore]
        lines.append(f"{chore.emoji} {chore.task.capitalize()}: {name(task.assignee)}, {due_label(chore, task.due, t)}")
    debts = ", ".join(f"{NAMES[p]} {b} {CURRENCY}" for p, b in store.balances().items())
    lines += ["", f"💸 Долги: {debts}"]
    missing = [NAMES[p] for p in PEOPLE if store.tg_of(p) is None]
    if missing:
        lines += ["", f"⚠️ Ещё не представились: {', '.join(missing)}. Напишите /start."]
    return "\n".join(lines)


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    t = refresh()
    soon = [task for task in store.open_tasks() if task.due <= t + timedelta(days=DONE_BUTTON_DAYS_AHEAD)]
    await update.effective_message.reply_text(status_text(t), reply_markup=done_keyboard(soon, with_names=True))


async def on_done(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    person = await whoami(q)
    if person is None:
        return
    task = store.task(int(q.data.split(":")[1]))
    if task is None or task.done_on:
        await q.answer("Это уже отмечено.")
        await q.edit_message_reply_markup(without_button(q.message.reply_markup, q.data))
        return
    if task.assignee != person:
        await q.answer(f"Не твоя очередь, это задача для {NAMES[task.assignee]}.", show_alert=True)
        return

    t = today()
    nxt = store.complete(task.id, t)
    chore = CHORES[task.chore]
    await q.answer("Записал 👍")
    await q.edit_message_reply_markup(without_button(q.message.reply_markup, q.data))

    text = (
        f"{texts.done(chore, name(person), store.task_fine(task.id))}\n\n"
        f"Дальше: {who(nxt.assignee)}, {chore.task} {due_label(chore, nxt.due, t)}."
    )
    group = store.get_chat_id()
    await ctx.bot.send_message(q.message.chat_id, text)
    if group and group != q.message.chat_id:
        await ctx.bot.send_message(group, text)


async def send_reminders(api: Bot, evening: bool) -> int:
    chat_id = store.get_chat_id()
    if chat_id is None:
        log.warning("Нет группового чата: добавьте бота в группу и напишите там /start")
        return 0
    t = refresh()
    due = [task for task in store.open_tasks() if task.due <= t]
    for task in due:
        text = texts.reminder(CHORES[task.chore], who(task.assignee), task.due, t, evening)
        await api.send_message(chat_id, text, reply_markup=done_keyboard([task], with_names=False))
    return len(due)


async def morning(ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await send_reminders(ctx.bot, evening=False)


async def evening(ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await send_reminders(ctx.bot, evening=True)


async def cmd_remind(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if store.get_chat_id() is None:
        await update.effective_message.reply_text("Сначала добавь меня в общий чат и напиши там /start.")
        return
    if await send_reminders(ctx.bot, evening=False) == 0:
        await update.effective_message.reply_text("Сегодня никто ничего не должен. Подозрительно.")


# --- штрафы ---


async def cmd_fines(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    refresh()
    lines = ["💸 <b>Долги по штрафам</b>", ""]
    lines += [f"{NAMES[p]} — {b} {CURRENCY}" for p, b in store.balances().items()]
    lines += ["", "Заплатил — пиши /paid, сосед подтвердит."]
    await update.effective_message.reply_text("\n".join(lines))


async def cmd_paid(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    person = store.person_by_tg(update.effective_user.id)
    if person is None:
        await update.effective_message.reply_text("Я тебя не знаю. Напиши /start и нажми на своё имя.")
        return
    refresh()
    pay = store.request_payment(person, now())
    if pay is None:
        await update.effective_message.reply_text("Ты ничего не должен. Пока что.")
        return
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Подтверждаю", callback_data=f"pay:ok:{pay.id}"),
                InlineKeyboardButton("❌ Враньё", callback_data=f"pay:no:{pay.id}"),
            ]
        ]
    )
    await update.effective_message.reply_text(
        f"💰 {name(person)} говорит, что заплатил {pay.amount} {CURRENCY}. Соседи, подтвердите:",
        reply_markup=keyboard,
    )


async def on_pay(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    person = await whoami(q)
    if person is None:
        return
    _, verdict, payment_id = q.data.split(":")
    pay = store.payment(int(payment_id))
    decide = store.confirm_payment if verdict == "ok" else store.reject_payment
    status = decide(pay.id, person, now()) if pay else "done"
    if status == "self":
        await q.answer("Сам себе не подтвердишь, хитрожопый.", show_alert=True)
        return
    if status == "done":
        await q.answer("Уже решено.")
        await q.edit_message_reply_markup(None)
        return
    await q.answer("Записал.")
    left = store.balance(pay.person)
    if verdict == "ok":
        text = (
            f"✅ {name(pay.person)} закрыл {pay.amount} {CURRENCY}, подтвердил {name(person)}. "
            f"Осталось долга: {left} {CURRENCY}."
        )
    else:
        text = f"❌ {name(person)} говорит, что {name(pay.person)} гонит. Долг {left} {CURRENCY} на месте."
    await safe_edit(q, text, None)


# --- продукты ---


def shop_text() -> str:
    lines = ["🛒 <b>Кто следующий покупает</b>", ""]
    for item in GROCERIES:
        last = store.last_purchase(item)
        tail = f"последний раз {NAMES[last[0]]}, {last[1]:%d.%m}" if last else "ещё никто не покупал"
        lines.append(f"{item} — <b>{NAMES[store.next_buyer(item)]}</b> ({tail})")
    lines += ["", "Купил — жми кнопку, запишу на тебя."]
    return "\n".join(lines)


def shop_keyboard() -> InlineKeyboardMarkup:
    buttons = [InlineKeyboardButton(item, callback_data=f"buy:{i}") for i, item in enumerate(GROCERIES)]
    rows = [buttons[i : i + 2] for i in range(0, len(buttons), 2)]
    rows.append([InlineKeyboardButton("↩️ Отменить мою последнюю покупку", callback_data="unbuy")])
    return InlineKeyboardMarkup(rows)


async def cmd_shop(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text(shop_text(), reply_markup=shop_keyboard())


async def on_buy(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    person = await whoami(q)
    if person is None:
        return
    item = GROCERIES[int(q.data.split(":")[1])]
    store.buy(item, person, now())
    await q.answer(f"Записал: {item} купил {NAMES[person]}.")
    await safe_edit(q, shop_text(), shop_keyboard())


async def on_unbuy(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    person = await whoami(q)
    if person is None:
        return
    item = store.undo_last_purchase(person, now())
    if item is None:
        await q.answer("За последние сутки ты ничего не покупал, отменять нечего.", show_alert=True)
        return
    await q.answer(f"Отменил: {item}.")
    await safe_edit(q, shop_text(), shop_keyboard())


# --- запуск ---


async def on_error(update: object, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    log.error("Ошибка при обработке апдейта", exc_info=ctx.error)


async def set_commands(app: Application) -> None:
    await app.bot.set_my_commands(
        [
            BotCommand("status", "Чья очередь и кто сколько должен"),
            BotCommand("shop", "Кто следующий покупает продукты"),
            BotCommand("fines", "Долги по штрафам"),
            BotCommand("paid", "Я заплатил штраф"),
            BotCommand("remind", "Напомнить прямо сейчас"),
            BotCommand("start", "Привязать чат и представиться"),
        ]
    )


def build_app(token: str, polling: bool = True) -> Application:
    """polling=True — постоянный процесс с планировщиком; False — разовая обработка вебхука или крона."""
    builder = Application.builder().token(token).defaults(Defaults(parse_mode=ParseMode.HTML, tzinfo=TZ))
    if polling:
        builder = builder.post_init(set_commands)
    else:
        builder = builder.updater(None).job_queue(None)
    app = builder.build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("shop", cmd_shop))
    app.add_handler(CommandHandler("fines", cmd_fines))
    app.add_handler(CommandHandler("paid", cmd_paid))
    app.add_handler(CommandHandler("remind", cmd_remind))
    app.add_handler(CallbackQueryHandler(on_register, pattern=r"^reg:"))
    app.add_handler(CallbackQueryHandler(on_done, pattern=r"^done:"))
    app.add_handler(CallbackQueryHandler(on_pay, pattern=r"^pay:"))
    app.add_handler(CallbackQueryHandler(on_buy, pattern=r"^buy:"))
    app.add_handler(CallbackQueryHandler(on_unbuy, pattern=r"^unbuy$"))
    app.add_error_handler(on_error)
    if polling:
        app.job_queue.run_daily(morning, MORNING, name="morning")
        app.job_queue.run_daily(evening, EVENING, name="evening")
    return app


def main() -> None:
    global store
    logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    token = os.environ.get("BOT_TOKEN")
    if not token:
        raise SystemExit("Нет BOT_TOKEN. Создай файл .env рядом с bot.py и впиши туда BOT_TOKEN=<токен от @BotFather>")
    store = Store(database_url())
    refresh()
    build_app(token).run_polling()


if __name__ == "__main__":
    main()
