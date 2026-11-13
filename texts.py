"""Что бот пишет. Сами подъёбы лежат в phrases.py, тут — какой взять и какие факты дописать рядом."""

import random
from datetime import date

import phrases
from rules import CURRENCY, DAY_STARTS_AT, FINE_PER_DAY, Chore, days, fine, fined_dates

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
        next_fine=fine(chore, due, today) + FINE_PER_DAY,
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
    if late <= chore.grace_days:
        free_left = chore.grace_days - late
        free = {0: "Сегодня последний день без штрафа", 1: "Завтра последний день без штрафа"}.get(
            free_left, f"Без штрафа ещё {days(free_left)}"
        )
        return (
            f"⏳ {pick(phrases.GRACE, **fields)}\n"
            f"Срок был {fields['due']}. {free}, потом {FINE_PER_DAY} {CURRENCY} в день."
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
