"""Что бот пишет. Сами подъёбы лежат в phrases.py, тут — какой взять и какие факты дописать рядом."""

import random
from datetime import date

import phrases
from rules import CURRENCY, DAY_STARTS_AT, Chore, days, due_label, fine, fined_dates

DAY_END = f"{DAY_STARTS_AT} утра"

# Чем дольше штраф, тем злее: 1 день, 2–3 дня, 4 и больше
FINED = (phrases.FINED_1, phrases.FINED_2, phrases.FINED_3)
FINED_EMOJI = ("💸", "🤬", "🚨")


def pick(options: tuple[str, ...], **fields) -> str:
    return random.choice(options).format(**fields)


def _level(fined_days: int) -> int:
    if fined_days <= 1:
        return 0
    if fined_days <= 3:
        return 1
    return 2


def reminder(chore: Chore, who: str, due: date, today: date, evening: bool = False, *, other: str) -> str:
    """{who} — чья очередь (ссылка с уведомлением), {other} — кто-то из двух других соседей."""
    late = (today - due).days
    fields = dict(
        who=who,
        other=other,
        task=chore.task,
        do=chore.do,
        due=f"{due:%d.%m}",
        late=days(late),
        cur=CURRENCY,
        fine=fine(chore, due, today),
        next_fine=fine(chore, due, today) + chore.fine_per_day,
        day_end=DAY_END,
    )
    if late <= 0 and not evening:
        return f"{chore.emoji} {pick(phrases.TODAY_MORNING, **fields)}"
    if late <= 0:
        template = random.choice(phrases.TODAY_EVENING)
        text = f"{chore.emoji} {template.format(**fields)}"
        if "{day_end}" not in template:
            text += f"\n⏰ Успеешь до {DAY_END} — не опоздание."
        return text
    if chore.fine_per_day <= 0:  # задача из /task без денег: только позор, злость не растёт
        return f"⏳ {pick(phrases.GRACE, **fields)}\nСрок был {fields['due']}, просрочка {fields['late']}. Штрафа нет, только позор."
    if late <= chore.grace_days:
        free_left = chore.grace_days - late
        free = {0: "Сегодня последний день без штрафа", 1: "Завтра последний день без штрафа"}.get(
            free_left, f"Без штрафа ещё {days(free_left)}"
        )
        return (
            f"⏳ {pick(phrases.GRACE, **fields)}\n"
            f"Срок был {fields['due']}. {free}, потом {chore.fine_per_day} {CURRENCY} в день."
        )
    level = _level(len(fined_dates(chore, due, today)))
    return (
        f"{FINED_EMOJI[level]} {pick(FINED[level], **fields)}\n"
        f"Просрочка {fields['late']}, штраф уже {fields['fine']} {CURRENCY}, завтра будет {fields['next_fine']} {CURRENCY}."
    )


def done(chore: Chore, who: str, fine_total: int, *, other: str) -> str:
    if fine_total:
        head = f"✅ {who} наконец-то {chore.done}, опоздание обошлось в {fine_total} {CURRENCY}."
        return f"{head} {pick(phrases.DONE_LATE, who=who, other=other, fine=fine_total, cur=CURRENCY)}"
    return f"✅ {who} {chore.done}. {pick(phrases.DONE_OK, who=who, other=other)}"


def not_your_turn(owner: str) -> str:
    """Всплывашка: жмёт «сделал» на чужой задаче. Обычный текст, без HTML."""
    return pick(phrases.NOT_YOUR_TURN, owner=owner)


def self_confirm() -> str:
    return pick(phrases.SELF_CONFIRM)


def no_debt(who: str) -> str:
    return pick(phrases.NO_DEBT, who=who)


def nothing_due() -> str:
    return pick(phrases.NOTHING_DUE)


def pay_confirmed(payer: str, judge: str, amount: int, left: int) -> str:
    head = f"✅ {payer} закрыл {amount} {CURRENCY}, подтвердил {judge}. Осталось долга: {left} {CURRENCY}."
    if left > 0:  # пока ждали подтверждения, натикал новый штраф — фразы про «долг закрыт» тут врут
        return f"{head} Не расслабляйся, {payer}: пока ты платил, счётчик тикал."
    return f"{head} {pick(phrases.PAY_CONFIRMED, payer=payer, judge=judge)}"


def pay_rejected(payer: str, judge: str, left: int) -> str:
    return f"❌ {pick(phrases.PAY_REJECTED, payer=payer, judge=judge)} Долг {left} {CURRENCY} на месте."


def banter(who: str, other: str) -> str:
    """Подъёб просто так: {who} — кого подъёбываем, {other} — второй из соседей, если фразе нужен."""
    return pick(phrases.BANTER, who=who, other=other)


# --- задачи из /task ---


def cap(text: str) -> str:
    """Первая буква заглавная, остальное как есть (str.capitalize ломает «купить IKEA»)."""
    return text[:1].upper() + text[1:]


def fine_terms(chore: Chore) -> str:
    if chore.fine_per_day <= 0:
        return "Штрафа нет, только позор."
    if chore.grace_days <= 0:
        return f"Опоздание — {chore.fine_per_day} {CURRENCY} в день с первого же дня."
    return f"После срока {days(chore.grace_days)} без штрафа, дальше {chore.fine_per_day} {CURRENCY} в день."


def fine_terms_short(chore: Chore) -> str:
    if chore.fine_per_day <= 0:
        return "без штрафа"
    grace = f" после {days(chore.grace_days)} льготы" if chore.grace_days else ""
    return f"штраф {chore.fine_per_day} {CURRENCY}/день{grace}"


def task_created(chore: Chore, who: str, author: str, due: date, today: date, promise: bool) -> str:
    """{who} — исполнитель (ссылка с уведомлением), author — кто поставил."""
    head = f"📌 {who} пообещал: {chore.task}." if promise else f"📌 Новая задача. {who}, тебе {chore.task}."
    lines = [head, f"Срок: {due_label(chore, due, today)}.", fine_terms(chore)]
    if not promise:
        lines.append(f"Поставил {author}.")
    lines.append("Сделал — жми кнопку. Отменить может только сосед.")
    return "\n".join(lines)


def task_cancelled(chore: Chore, assignee: str, judge: str, fined: int) -> str:
    text = f"🗑 {judge} отменил задачу «{chore.task}». {assignee} выдыхает."
    if fined:
        text += f" Накапавшие {fined} {CURRENCY} остаются."
    return text


def early_done_check(chore: Chore, who: str, due: date, next_who: str, next_due: date) -> str:
    return (
        f"{who}, срок только {due:%d.%m}. Точно уже {chore.done}?\n"
        f"Если да, следующим будет {next_who}, до {next_due:%d.%m}."
    )
