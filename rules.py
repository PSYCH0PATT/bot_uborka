"""Правила квартиры: кто, что и когда. Чистые функции, без Telegram и базы."""

import calendar
from dataclasses import dataclass
from datetime import date, datetime, timedelta

FINE_PER_DAY = 100
CURRENCY = "Kč"
DAY_STARTS_AT = 6  # час: до 6 утра ещё идёт вчерашний день

PEOPLE = ("dima", "artem", "nikita")
NAMES = {"dima": "Дима", "artem": "Артём", "nikita": "Никита"}

GROCERIES = (
    "Мусорные пакеты",
    "Туалетная бумага",
    "Моющее средство",
    "Мыло для ванны",
    "Сахар",
    "Соль",
    "Масло растительное",
    "Масло сливочное",
    "Губки",
    "Тряпки",
)


@dataclass(frozen=True)
class Chore:
    key: str
    emoji: str
    task: str  # «вынести мусор»
    done: str  # «вынес мусор»
    do: str  # «вынеси мусор»
    order: tuple[str, ...]
    first_due: date
    grace_days: int
    every_days: int | None = None  # следующий срок = день выполнения + every_days
    monthly_day: int | None = None  # следующий срок = это число следующего месяца


TRASH = Chore(
    key="trash",
    emoji="🗑",
    task="вынести мусор",
    done="вынес мусор",
    do="вынеси мусор",
    order=("nikita", "artem", "dima"),
    first_due=date(2026, 11, 5),
    grace_days=1,
    every_days=4,
)

RUGS = Chore(
    key="rugs",
    emoji="🧺",
    task="постирать коврики",
    done="постирал коврики",
    do="постирай коврики",
    order=("artem", "dima", "nikita"),
    first_due=date(2026, 11, 29),
    grace_days=2,
    monthly_day=29,
)

CHORES = {c.key: c for c in (TRASH, RUGS)}


def flat_date(moment: datetime) -> date:
    """Какое сегодня число по правилам квартиры: ночь до DAY_STARTS_AT ещё считается вчерашним днём."""
    return (moment - timedelta(hours=DAY_STARTS_AT)).date()


def next_in_order(order: tuple[str, ...], current: str) -> str:
    return order[(order.index(current) + 1) % len(order)]


def fined_dates(chore: Chore, due: date, until: date) -> list[date]:
    """Дни, за которые положен штраф, если задача не сделана до `until` включительно."""
    first = due + timedelta(days=chore.grace_days + 1)
    return [first + timedelta(days=i) for i in range((until - first).days + 1)]


def fine(chore: Chore, due: date, on: date) -> int:
    return len(fined_dates(chore, due, on)) * FINE_PER_DAY


def month_after(d: date, day: int) -> date:
    year, month = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
    return date(year, month, min(day, calendar.monthrange(year, month)[1]))


def next_due(chore: Chore, prev_due: date, done_on: date | None) -> date:
    if chore.every_days:
        return done_on + timedelta(days=chore.every_days)
    return month_after(prev_due, chore.monthly_day)


def next_buyer(purchases: list[tuple[str, datetime]]) -> str:
    """Следующим покупает тот, кто брал эту позицию реже всех, при равенстве — кто дольше не брал."""
    counts = {p: 0 for p in PEOPLE}
    last = {p: float("-inf") for p in PEOPLE}
    for person, when in purchases:
        counts[person] += 1
        last[person] = max(last[person], when.timestamp())
    return min(PEOPLE, key=lambda p: (counts[p], last[p], PEOPLE.index(p)))


def days(n: int) -> str:
    if n % 10 == 1 and n % 100 != 11:
        word = "день"
    elif 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        word = "дня"
    else:
        word = "дней"
    return f"{n} {word}"


def due_label(chore: Chore, due: date, today: date) -> str:
    ahead = (due - today).days
    if ahead > 1:
        return f"до {due:%d.%m}, через {days(ahead)}"
    if ahead == 1:
        return f"до {due:%d.%m}, это завтра"
    if ahead == 0:
        return "сегодня"
    late = -ahead
    free_left = chore.grace_days - late
    if free_left == 0:
        return f"просрочено на {days(late)}, сегодня последний день без штрафа"
    if free_left == 1:
        return f"просрочено на {days(late)}, завтра последний день без штрафа"
    if free_left > 1:
        return f"просрочено на {days(late)}, без штрафа ещё {days(free_left)}"
    return f"просрочено на {days(late)}, штраф {fine(chore, due, today)} {CURRENCY}"
