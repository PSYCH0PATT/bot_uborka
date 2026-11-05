"""Тексты напоминаний и наездов. Чем дольше просрочка, тем злее."""

import random
from datetime import date

from rules import CURRENCY, FINE_PER_DAY, Chore, days, fine, fined_dates

TODAY_MORNING = [
    "{emoji} {who}, сегодня твоя очередь {task}. Сделаешь — жми кнопку, иначе не считается.",
    "{emoji} {who}, доброе утро. Сегодня тебе {task}. Кнопку не забудь, бот на слово не верит.",
]

TODAY_EVENING = [
    "{emoji} {who}, день кончается, а кнопка так и не нажата. Сегодня тебе {task}, время ещё есть.",
    "{emoji} {who}, напоминаю: сегодня тебе {task}. Сделал — жми кнопку.",
]

GRACE = [
    "⏳ {who}, срок был {due}, ты уже опаздываешь. Пока без штрафа, но {free}. Потом {per_day} {cur} в день.",
    "⏳ {who}, {task} надо было ещё {due}. Халява заканчивается: {free}.",
]

FINED = [
    # 1 день штрафа
    [
        "💸 {who}, поздравляю, ты попал на бабки. Надо было {task} ещё {due}, штраф уже {fine} {cur}. Завтра будет {next_fine} {cur}.",
        "💸 {who}, ты охуел? Просрочка {late}, минус {fine} {cur}, и счётчик крутится.",
    ],
    # 2–3 дня
    [
        "🤬 {who}, это уже неприлично. {late} просрочки, долг {fine} {cur}. Мы всё видим.",
        "🤬 {who}, {fine} {cur} штрафа — это пиво, которое ты мог выпить. Иди уже {do}.",
        "🤬 {who}, сколько можно? Уже {fine} {cur}, завтра будет {next_fine}. Просто встань и {do}.",
    ],
    # 4+ дней
    [
        "🚨 {who}, ты позор этой квартиры. {late} просрочки, {fine} {cur}. Соседи уже ищут новую хату.",
        "🚨 {who}, у меня кончились слова. {fine} {cur}. Просто {do}, блять.",
        "🚨 {who}, рекорд квартиры: {late} просрочки и {fine} {cur} долга. Гордиться нечем.",
    ],
]


def _level(fined_days: int) -> int:
    if fined_days <= 1:
        return 0
    if fined_days <= 3:
        return 1
    return 2


def reminder(chore: Chore, who: str, due: date, today: date, evening: bool = False) -> str:
    late = (today - due).days
    fields = dict(
        emoji=chore.emoji,
        who=who,
        task=chore.task,
        do=chore.do,
        due=f"{due:%d.%m}",
        late=days(late),
        cur=CURRENCY,
        fine=fine(chore, due, today),
        next_fine=fine(chore, due, today) + FINE_PER_DAY,
        per_day=FINE_PER_DAY,
    )
    if late <= 0:
        templates = TODAY_EVENING if evening else TODAY_MORNING
    elif late <= chore.grace_days:
        free_left = chore.grace_days - late
        fields["free"] = {0: "сегодня последний бесплатный день", 1: "завтра последний бесплатный день"}.get(
            free_left, f"бесплатных дней осталось: {free_left}"
        )
        templates = GRACE
    else:
        templates = FINED[_level(len(fined_dates(chore, due, today)))]
    return random.choice(templates).format(**fields)


def done(chore: Chore, who: str, fine_total: int) -> str:
    if fine_total:
        return f"✅ {who} наконец-то {chore.done}. Опоздание обошлось в {fine_total} {CURRENCY}."
    return f"✅ {who} {chore.done}. Красавчик."
