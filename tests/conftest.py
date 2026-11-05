"""Каждый тест с базой гоняется на SQLite и, если задан TEST_DATABASE_URL, ещё и на Postgres."""

import os

import pytest

from db import Store, _clean_pg_url

TABLES = "fines, payments, purchases, people, settings, tasks"


@pytest.fixture(params=["sqlite", "postgres"])
def blank_store(request):
    if request.param == "sqlite":
        store = Store(":memory:")
    else:
        url = os.environ.get("TEST_DATABASE_URL")
        if not url:
            pytest.skip("нет TEST_DATABASE_URL — Postgres пропущен")
        import psycopg

        with psycopg.connect(_clean_pg_url(url), autocommit=True) as conn:
            conn.execute(f"DROP TABLE IF EXISTS {TABLES} CASCADE")
        store = Store(url)
    yield store
    store.close()
