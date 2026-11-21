"""Правила квартиры: кто, что и когда. Чистые функции, без Telegram и базы."""

import calendar
import html
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

FINE_PER_DAY = 100
CURRENCY = "Kč"
DAY_STARTS_AT = 6  # час: до 6 утра ещё идёт вчерашний день

PEOPLE = ("dima", "artem", "nikita")
NAMES = {"dima": "Дима", "artem": "Артём", "nikita": "Никита"}
# Как имя могут написать в команде
NAME_ALIASES = {"дима": "dima", "дмитрий": "dima", "артём": "artem", "артем": "artem", "никита": "nikita"}

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
    fine_per_day: int = FINE_PER_DAY


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

CUSTOM = "custom"  # разовая задача, которую поставили через /task
TASK_DEFAULT_GRACE = 0
TASK_TITLE_MAX = 100
TASK_GRACE_MAX = 60
TASK_FINE_MAX = 10_000


def custom_chore(title: str, due: date, grace_days: int, fine_per_day: int) -> Chore:
    """Разовая задача в виде Chore, чтобы напоминания и штрафы работали как с мусором.

    Название пишут в инфинитиве («купить стулья»): оно встаёт в {task}. Повелительное наклонение
    из чужого текста не построить, поэтому {do} — «сделай «купить стулья»». Текст экранирован для HTML.
    """
    name = html.escape(title)
    return Chore(
        key=CUSTOM,
        emoji="📌",
        task=name,
        done=f"сделал «{name}»",
        do=f"сделай «{name}»",
        order=(),
        first_due=due,
        grace_days=grace_days,
        fine_per_day=fine_per_day,
    )


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
    return len(fined_dates(chore, due, on)) * chore.fine_per_day


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
    if chore.fine_per_day <= 0:
        return f"просрочено на {days(late)}, штрафа нет — только позор"
    free_left = chore.grace_days - late
    if free_left == 0:
        return f"просрочено на {days(late)}, сегодня последний день без штрафа"
    if free_left == 1:
        return f"просрочено на {days(late)}, завтра последний день без штрафа"
    if free_left > 1:
        return f"просрочено на {days(late)}, без штрафа ещё {days(free_left)}"
    return f"просрочено на {days(late)}, штраф {fine(chore, due, today)} {CURRENCY}"


# --- задачи, которые ставят сами ---


@dataclass(frozen=True)
class TaskRequest:
    assignee: str
    title: str
    due: date
    grace_days: int
    fine_per_day: int


TASK_USAGE = (
    "Как поставить задачу:\n"
    "/task Дима купить стулья до 30.11 штраф 200 льгота 2\n\n"
    "Сначала кому: Дима, Артём, Никита или «я». Потом что сделать. Потом срок: «до 30.11», "
    "«до завтра» или «через 3 дня».\n"
    f"«штраф 200» — сколько {CURRENCY} в день за просрочку, если не указать — {FINE_PER_DAY}. "
    "«штраф 0» — без денег, только позор.\n"
    "«льгота 2» — сколько дней после срока ещё без штрафа, если не указать — 0."
)

_DATE = re.compile(r"\bдо\s+(\d{1,2})\.(\d{1,2})(?:\.(\d{4}|\d{2}))?(?!\d)", re.I)
_WORD_DATE = re.compile(r"\bдо\s+(сегодня|завтра|послезавтра)\b", re.I)
_IN_DAYS = re.compile(r"\bчерез\s+(\d{1,3})\s*(?:дн\w*|день)\b", re.I)
_GRACE = re.compile(r"\b(?:льгот\w*|без\s+штрафа|отсрочк\w*)\s+(\d{1,3})(?:\s*(?:дн\w*|день))?", re.I)
_FINE = re.compile(
    r"\bштраф\w*\s+(\d{1,6})(?:\s*(?:kč|кч|czk|крон\w*))?(?:\s*(?:в|/)\s*день)?", re.I
)
_WORD_DAYS = {"сегодня": 0, "завтра": 1, "послезавтра": 2}


def _deadline(text: str, today: date) -> tuple[date | None, str, str | None]:
    """Срок из текста: (дата, текст без срока, ошибка)."""
    if m := _DATE.search(text):
        day, month, year = int(m[1]), int(m[2]), m[3]
        try:
            if year:
                due = date(int(year) + (2000 if len(year) == 2 else 0), month, day)
            else:
                due = date(today.year, month, day)
                if due < today and (today - due).days > 60:  # «до 05.01» в ноябре — это следующий год
                    due = date(today.year + 1, month, day)
        except ValueError:
            return None, text, f"Нет такой даты: {m[0][3:].strip()}."
        return due, text[: m.start()] + text[m.end() :], None
    if m := _WORD_DATE.search(text):
        return today + timedelta(days=_WORD_DAYS[m[1].lower()]), text[: m.start()] + text[m.end() :], None
    if m := _IN_DAYS.search(text):
        return today + timedelta(days=int(m[1])), text[: m.start()] + text[m.end() :], None
    return None, text, None


def parse_task(text: str, today: date, author: str) -> TaskRequest | str:
    """Разбирает «Дима купить стулья до 30.11 штраф 200 льгота 2». Вернёт задачу или текст ошибки."""
    words = text.split(maxsplit=1)
    if not words:
        return TASK_USAGE
    first = words[0].lower().strip(",:;.—-")
    if first == "я":
        assignee = author
    elif first in NAME_ALIASES:
        assignee = NAME_ALIASES[first]
    else:
        return f"Кому задача? Начни с имени: Дима, Артём, Никита или «я».\n\n{TASK_USAGE}"
    rest = words[1] if len(words) > 1 else ""

    due, rest, error = _deadline(rest, today)
    if error:
        return error
    if due is None:
        return f"Не вижу срок. Напиши «до 30.11», «до завтра» или «через 3 дня».\n\n{TASK_USAGE}"
    if due < today:
        return f"{due:%d.%m} уже прошло. Задачи в прошлое не ставлю."
    if (due - today).days > 366:
        return "Срок больше чем через год. Столько не живут."

    grace = TASK_DEFAULT_GRACE
    if m := _GRACE.search(rest):  # раньше штрафа: «без штрафа 2 дня» иначе прочиталось бы как «штраф 2»
        grace = int(m[1])
        rest = rest[: m.start()] + rest[m.end() :]
    fine_per_day = FINE_PER_DAY
    if m := _FINE.search(rest):
        fine_per_day = int(m[1])
        rest = rest[: m.start()] + rest[m.end() :]
    if grace > TASK_GRACE_MAX:
        return f"Льгота максимум {days(TASK_GRACE_MAX)}."
    if fine_per_day > TASK_FINE_MAX:
        return f"Штраф максимум {TASK_FINE_MAX} {CURRENCY} в день. Совесть имейте."

    title = re.sub(r"\s+", " ", rest).strip(" ,.;:-—")
    if not title:
        return f"А делать-то что?\n\n{TASK_USAGE}"
    if len(title) > TASK_TITLE_MAX:
        return f"Слишком длинно, уложись в {TASK_TITLE_MAX} знаков."
    return TaskRequest(assignee, title, due, grace, fine_per_day)
