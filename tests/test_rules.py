from datetime import date, datetime

import rules
from rules import RUGS, TRASH


def d(day, month=11, year=2026):
    return date(year, month, day)


def test_trash_starts_with_nikita_on_nov_5():
    assert TRASH.order == ("nikita", "artem", "dima")
    assert TRASH.first_due == d(5)


def test_rugs_start_with_artem_on_nov_29():
    assert RUGS.order == ("artem", "dima", "nikita")
    assert RUGS.first_due == d(29)


def test_trash_has_one_free_day_then_100_per_day():
    due = d(5)
    assert rules.fine(TRASH, due, d(4)) == 0
    assert rules.fine(TRASH, due, d(5)) == 0
    assert rules.fine(TRASH, due, d(6)) == 0
    assert rules.fine(TRASH, due, d(7)) == 100
    assert rules.fine(TRASH, due, d(9)) == 300


def test_rugs_have_two_free_days():
    due = d(29)
    assert rules.fine(RUGS, due, d(1, 12)) == 0
    assert rules.fine(RUGS, due, d(2, 12)) == 100


def test_fined_dates_lists_every_fined_day():
    assert rules.fined_dates(TRASH, d(5), d(8)) == [d(7), d(8)]
    assert rules.fined_dates(TRASH, d(5), d(6)) == []


def test_next_in_order_wraps_around():
    assert rules.next_in_order(TRASH.order, "nikita") == "artem"
    assert rules.next_in_order(TRASH.order, "dima") == "nikita"


def test_trash_next_due_counts_from_done_day():
    assert rules.next_due(TRASH, prev_due=d(5), done_on=d(7)) == d(11)
    assert rules.next_due(TRASH, prev_due=d(5), done_on=d(4)) == d(8)


def test_rugs_next_due_is_29th_of_next_month():
    assert rules.next_due(RUGS, prev_due=d(29), done_on=d(3, 12)) == d(29, 12)
    assert rules.next_due(RUGS, prev_due=d(29, 12), done_on=None) == d(29, 1, 2027)


def test_rugs_february_clamps_then_returns_to_29th():
    feb = rules.next_due(RUGS, prev_due=d(29, 1, 2027), done_on=None)
    assert feb == d(28, 2, 2027)
    assert rules.next_due(RUGS, prev_due=feb, done_on=None) == d(29, 3, 2027)


def test_next_buyer_with_no_history_uses_fixed_order():
    assert rules.next_buyer([]) == "dima"


def test_next_buyer_is_whoever_bought_least():
    t = datetime(2026, 11, 1, 12)
    assert rules.next_buyer([("dima", t)]) == "artem"
    assert rules.next_buyer([("dima", t), ("artem", t)]) == "nikita"


def test_next_buyer_tie_goes_to_whoever_bought_longest_ago():
    history = [
        ("nikita", datetime(2026, 11, 1)),
        ("dima", datetime(2026, 11, 2)),
        ("artem", datetime(2026, 11, 3)),
    ]
    assert rules.next_buyer(history) == "nikita"


def test_plural_days():
    assert rules.days(1) == "1 день"
    assert rules.days(2) == "2 дня"
    assert rules.days(5) == "5 дней"
    assert rules.days(11) == "11 дней"
    assert rules.days(21) == "21 день"
    assert rules.days(22) == "22 дня"


def test_due_label_before_and_on_due_day():
    assert rules.due_label(TRASH, d(5), d(3)) == "до 05.11, через 2 дня"
    assert rules.due_label(TRASH, d(5), d(4)) == "до 05.11, это завтра"
    assert rules.due_label(TRASH, d(5), d(5)) == "сегодня"


def test_due_label_in_grace_period():
    assert rules.due_label(TRASH, d(5), d(6)) == "просрочено на 1 день, сегодня последний день без штрафа"
    assert rules.due_label(RUGS, d(29), d(30)) == "просрочено на 1 день, завтра последний день без штрафа"


def test_due_label_when_fined():
    assert rules.due_label(TRASH, d(5), d(8)) == "просрочено на 3 дня, штраф 200 Kč"
