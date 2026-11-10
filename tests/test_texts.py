from datetime import timedelta

import pytest

import rules
import texts
from rules import RUGS, TRASH


@pytest.mark.parametrize("chore", [TRASH, RUGS])
@pytest.mark.parametrize("evening", [False, True])
def test_every_template_renders_with_name_and_fine(monkeypatch, chore, evening):
    for late in range(0, 10):
        today = chore.first_due + timedelta(days=late)
        for pick in range(3):
            monkeypatch.setattr(texts.random, "choice", lambda seq: seq[min(pick, len(seq) - 1)])
            text = texts.reminder(chore, "Никита", chore.first_due, today, evening)
            assert "Никита" in text
            fine = rules.fine(chore, chore.first_due, today)
            if fine:
                assert f"{fine} {rules.CURRENCY}" in text


def test_grace_text_says_how_long_it_is_free(monkeypatch):
    monkeypatch.setattr(texts.random, "choice", lambda seq: seq[0])
    assert "сегодня последний бесплатный день" in texts.reminder(TRASH, "Никита", TRASH.first_due, TRASH.first_due + timedelta(days=1))
    assert "завтра последний бесплатный день" in texts.reminder(RUGS, "Артём", RUGS.first_due, RUGS.first_due + timedelta(days=1))


def test_done_text_mentions_fine_only_when_late():
    assert texts.done(TRASH, "Никита", 0) == "✅ Никита вынес мусор. Красавчик."
    assert "300 Kč" in texts.done(TRASH, "Никита", 300)


def test_evening_reminder_says_the_day_lasts_until_6am(monkeypatch):
    for pick in range(len(texts.TODAY_EVENING)):
        monkeypatch.setattr(texts.random, "choice", lambda seq: seq[pick])
        assert "до 6 утра" in texts.reminder(TRASH, "Никита", TRASH.first_due, TRASH.first_due, evening=True)
