from datetime import date, datetime, timedelta

import pytest

NOW = datetime(2026, 11, 3, 12, 0)


def d(day, month=11, year=2026):
    return date(year, month, day)


@pytest.fixture
def store(blank_store):
    blank_store.ensure_tasks(d(3))
    return blank_store


def chain(store, chore):
    return [(t.assignee, t.due, t.done_on) for t in store.tasks(chore)]


def first_open(store, chore):
    return next(t for t in store.open_tasks() if t.chore == chore)


def test_first_tasks_match_the_schedule(store):
    assert [(t.chore, t.assignee, t.due) for t in store.open_tasks()] == [
        ("trash", "nikita", d(5)),
        ("rugs", "artem", d(29)),
    ]


def test_ensure_tasks_is_idempotent(store):
    store.ensure_tasks(d(3))
    store.ensure_tasks(d(4))
    assert len(store.open_tasks()) == 2


def test_trash_rotates_and_counts_from_done_day(store):
    nxt = store.complete(first_open(store, "trash").id, d(6))
    assert (nxt.assignee, nxt.due) == ("artem", d(10))
    nxt = store.complete(nxt.id, d(9))
    assert (nxt.assignee, nxt.due) == ("dima", d(13))
    nxt = store.complete(nxt.id, d(13))
    assert (nxt.assignee, nxt.due) == ("nikita", d(17))


def test_late_trash_accrues_fines_once_per_day(store):
    store.sync_fines(d(8))
    store.sync_fines(d(8))
    assert store.balance("nikita") == 200
    store.complete(first_open(store, "trash").id, d(9))
    assert store.balance("nikita") == 300
    store.sync_fines(d(20))
    assert store.balance("nikita") == 300


def test_complete_charges_fines_even_if_sync_never_ran(store):
    task = first_open(store, "trash")
    store.complete(task.id, d(8))
    assert store.balance("nikita") == 200
    assert store.task_fine(task.id) == 200


def test_completing_twice_does_nothing(store):
    task = first_open(store, "trash")
    store.complete(task.id, d(5))
    assert store.complete(task.id, d(6)) is None
    assert len(store.tasks("trash")) == 2


def test_next_rugs_task_appears_when_due_day_comes(store):
    store.ensure_tasks(d(29))
    assert chain(store, "rugs") == [("artem", d(29), None), ("dima", d(29, 12), None)]


def test_early_rugs_completion_shows_next_person(store):
    nxt = store.complete(first_open(store, "rugs").id, d(28))
    assert (nxt.assignee, nxt.due) == ("dima", d(29, 12))


def test_late_rugs_returns_already_open_next_task(store):
    store.ensure_tasks(d(29, 12))
    nxt = store.complete(first_open(store, "rugs").id, d(30, 12))
    assert (nxt.assignee, nxt.due) == ("dima", d(29, 12))
    assert store.balance("artem") == 2900


def test_rugs_catch_up_after_long_downtime(store):
    store.ensure_tasks(d(1, 3, 2027))
    assert [(a, due) for a, due, _ in chain(store, "rugs")] == [
        ("artem", d(29)),
        ("dima", d(29, 12)),
        ("nikita", d(29, 1, 2027)),
        ("artem", d(28, 2, 2027)),
        ("dima", d(29, 3, 2027)),
    ]


def test_register_people(store):
    assert store.register("dima", 111) == "ok"
    assert store.register("dima", 222) == "taken"
    assert store.register("dima", 111) == "already"
    assert store.person_by_tg(111) == "dima"
    assert store.tg_of("dima") == 111


def test_register_can_fix_a_wrong_choice(store):
    store.register("nikita", 111)
    assert store.register("dima", 111) == "ok"
    assert store.person_by_tg(111) == "dima"
    assert store.tg_of("nikita") is None


def test_chat_id_is_remembered(store):
    assert store.get_chat_id() is None
    store.set_chat_id(-100500)
    assert store.get_chat_id() == -100500


def test_payment_has_to_be_confirmed_by_someone_else(store):
    store.sync_fines(d(8))
    pay = store.request_payment("nikita", NOW)
    assert pay.amount == 200
    assert store.balance("nikita") == 200
    assert store.confirm_payment(pay.id, "nikita", NOW) == "self"
    assert store.confirm_payment(pay.id, "dima", NOW) == "ok"
    assert store.balance("nikita") == 0
    assert store.confirm_payment(pay.id, "artem", NOW) == "done"


def test_rejected_payment_keeps_the_debt(store):
    store.sync_fines(d(8))
    pay = store.request_payment("nikita", NOW)
    assert store.reject_payment(pay.id, "nikita", NOW) == "self"
    assert store.reject_payment(pay.id, "artem", NOW) == "ok"
    assert store.balance("nikita") == 200
    assert store.confirm_payment(pay.id, "dima", NOW) == "done"


def test_no_payment_without_debt(store):
    assert store.request_payment("dima", NOW) is None


def test_repeated_payment_request_reuses_pending_one(store):
    store.sync_fines(d(8))
    first = store.request_payment("nikita", NOW)
    assert store.request_payment("nikita", NOW).id == first.id


def test_fines_after_payment_request_stay_in_debt(store):
    store.sync_fines(d(8))
    pay = store.request_payment("nikita", NOW)
    store.sync_fines(d(9))
    store.confirm_payment(pay.id, "dima", NOW)
    assert store.balance("nikita") == 100


def test_groceries_rotation_and_undo(store):
    assert store.next_buyer("Соль") == "dima"
    store.buy("Соль", "dima", NOW)
    assert store.next_buyer("Соль") == "artem"
    assert store.last_purchase("Соль") == ("dima", NOW)
    assert store.next_buyer("Сахар") == "dima"
    assert store.undo_last_purchase("dima", NOW) == "Соль"
    assert store.next_buyer("Соль") == "dima"
    assert store.undo_last_purchase("dima", NOW) is None


def test_undo_only_works_for_the_last_day(store):
    store.buy("Соль", "dima", NOW)
    assert store.undo_last_purchase("dima", NOW + timedelta(days=2)) is None


def test_mark_once_fires_only_the_first_time(store):
    assert store.mark_once("cron:morning:2026-11-05")
    assert not store.mark_once("cron:morning:2026-11-05")
    assert store.mark_once("cron:evening:2026-11-05")


def test_telegram_ids_bigger_than_32_bits_fit(store):
    big = 7_123_456_789
    assert store.register("artem", big) == "ok"
    assert store.person_by_tg(big) == "artem"
