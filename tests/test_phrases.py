"""Фразы в phrases.py правят руками, поэтому проверяем формат: подстановки, длину, HTML и повторы."""

import re

import pytest

import phrases

REMIND = {"who", "task", "do", "due", "late", "fine", "next_fine", "cur"}

# имя: (обязательные — из каждой группы хотя бы одна подстановка, допустимые, предел длины)
SPECS = {
    "TODAY_MORNING": ([{"who"}, {"task", "do"}], {"who", "task", "do", "day_end"}, 200),
    "TODAY_EVENING": ([{"who"}, {"task", "do"}], {"who", "task", "do", "day_end"}, 200),
    "GRACE": ([{"who"}], {"who", "task", "do", "due", "late"}, 200),
    "FINED_1": ([{"who"}], REMIND, 200),
    "FINED_2": ([{"who"}], REMIND, 200),
    "FINED_3": ([{"who"}], REMIND, 200),
    "DONE_OK": ([], {"who"}, 140),
    "DONE_LATE": ([], {"who", "fine", "cur"}, 140),
    "PAY_CONFIRMED": ([], {"payer", "judge"}, 140),
    "PAY_REJECTED": ([{"judge"}, {"payer"}], {"judge", "payer"}, 160),
    "NOT_YOUR_TURN": ([{"owner"}], {"owner"}, 150),  # всплывашка Telegram — максимум 200 знаков
    "SELF_CONFIRM": ([], set(), 150),
    "NO_DEBT": ([], {"who"}, 160),
    "NOTHING_DUE": ([], set(), 160),
    "BANTER": ([], {"who"}, 220),
}
SAMPLE = dict(
    who="Никита", task="постирать коврики", do="постирай коврики", day_end="6 утра", due="05.11", late="2 дня",
    fine="200", next_fine="300", cur="Kč", owner="Артём", payer="Никита", judge="Дима",
)
# Напоминания и «сделал» общие для мусора и ковриков: дело называется только через {task}/{do}
CHORE_AGNOSTIC = {"TODAY_MORNING", "TODAY_EVENING", "GRACE", "FINED_1", "FINED_2", "FINED_3", "DONE_OK", "DONE_LATE"}


def test_every_phrase_list_is_checked():
    assert {n for n in dir(phrases) if n.isupper()} == set(SPECS)


@pytest.mark.parametrize("list_name", SPECS)
def test_hundred_distinct_phrases(list_name):
    lines = getattr(phrases, list_name)
    assert len(lines) == 100
    normalized = [re.sub(r"\W+", " ", line.lower()).strip() for line in lines]
    assert len(set(normalized)) == len(lines), "есть повторы"


@pytest.mark.parametrize("list_name", SPECS)
def test_phrases_have_the_right_placeholders_and_render(list_name):
    required, allowed, limit = SPECS[list_name]
    for line in getattr(phrases, list_name):
        used = set(re.findall(r"\{(\w+)\}", line))
        assert used <= allowed, line
        assert all(used & group for group in required), line
        assert not set(line) & set("<>&"), line
        assert len(line) <= limit, line
        rendered = line.format(**SAMPLE)
        assert "{" not in rendered and "}" not in rendered, line
        if list_name in CHORE_AGNOSTIC:
            assert not re.search(r"мусор|коврик|пакет", line, re.I), line
