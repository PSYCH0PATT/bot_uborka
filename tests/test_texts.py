from datetime import timedelta

import pytest

import phrases
import rules
import texts
from rules import RUGS, TRASH


def each_phrase(monkeypatch):
    """Перебирает все варианты: random.choice по очереди отдаёт 0-й, 1-й, … элемент."""
    for i in range(100):
        monkeypatch.setattr(texts.random, "choice", lambda seq, i=i: seq[i % len(seq)])
        yield i


@pytest.mark.parametrize("chore", [TRASH, RUGS])
@pytest.mark.parametrize("evening", [False, True])
def test_every_reminder_renders_with_name_and_fine(monkeypatch, chore, evening):
    for late in range(0, 10):
        today = chore.first_due + timedelta(days=late)
        fine = rules.fine(chore, chore.first_due, today)
        for _ in each_phrase(monkeypatch):
            text = texts.reminder(chore, "Никита", chore.first_due, today, evening)
            assert "Никита" in text
            assert "{" not in text
            if fine:
                assert f"штраф уже {fine} {rules.CURRENCY}, завтра будет {fine + rules.FINE_PER_DAY}" in text


def test_grace_text_says_how_long_it_is_free():
    grace = texts.reminder(TRASH, "Никита", TRASH.first_due, TRASH.first_due + timedelta(days=1))
    assert "Срок был 05.11. Сегодня последний день без штрафа, потом 100 Kč в день." in grace
    grace = texts.reminder(RUGS, "Артём", RUGS.first_due, RUGS.first_due + timedelta(days=1))
    assert "Завтра последний день без штрафа" in grace


def test_anger_grows_with_the_fine(monkeypatch):
    due = TRASH.first_due
    assert texts.reminder(TRASH, "Никита", due, due + timedelta(days=2)).startswith("💸")
    assert texts.reminder(TRASH, "Никита", due, due + timedelta(days=4)).startswith("🤬")
    assert texts.reminder(TRASH, "Никита", due, due + timedelta(days=6)).startswith("🚨")


def test_evening_reminder_says_the_day_lasts_until_6am(monkeypatch):
    for _ in each_phrase(monkeypatch):
        assert "6 утра" in texts.reminder(TRASH, "Никита", TRASH.first_due, TRASH.first_due, evening=True)


def test_done_text_mentions_fine_only_when_late(monkeypatch):
    for _ in each_phrase(monkeypatch):
        assert texts.done(TRASH, "Никита", 0).startswith("✅ Никита вынес мусор. ")
        late = texts.done(RUGS, "Артём", 300)
        assert late.startswith("✅ Артём наконец-то постирал коврики, опоздание обошлось в 300 Kč. ")


def test_payment_texts_keep_the_numbers(monkeypatch):
    for _ in each_phrase(monkeypatch):
        ok = texts.pay_confirmed("Никита", "Дима", 200, 0)
        assert ok.startswith("✅ Никита закрыл 200 Kč, подтвердил Дима. Осталось долга: 0 Kč. ")
        no = texts.pay_rejected("Никита", "Дима", 200)
        assert no.startswith("❌ ") and no.endswith(" Долг 200 Kč на месте.")
        assert "Никита" in no and "Дима" in no
    # пока ждали подтверждения, натикал новый штраф — «долг закрыт» не пишем
    assert texts.pay_confirmed("Никита", "Дима", 200, 100).endswith("пока ты платил, счётчик тикал.")


def test_alerts_fit_telegram_limit(monkeypatch):
    for _ in each_phrase(monkeypatch):
        assert "Артём" in texts.not_your_turn("Артём")
        assert len(texts.not_your_turn("Никита")) <= 200
        assert len(texts.self_confirm()) <= 200


def test_banter_and_short_replies_render(monkeypatch):
    seen = set()
    for _ in each_phrase(monkeypatch):
        seen.add(texts.banter("<b>Дима</b>"))
        assert "{" not in texts.no_debt("<b>Дима</b>") + texts.nothing_due()
    assert len(seen) == len(phrases.BANTER)
