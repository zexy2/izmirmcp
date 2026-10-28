from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.storage.quota import QuotaError, QuotaStore

NOW = datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc)


def _store(tmp_path: Path) -> QuotaStore:
    return QuotaStore(tmp_path / "quota.sqlite3")


def test_allows_up_to_the_daily_limit(tmp_path: Path):
    store = _store(tmp_path)
    decisions = [store.consume("1.2.3.4", limit=3, now=NOW) for _ in range(3)]
    assert all(decision.allowed for decision in decisions)
    assert [decision.remaining for decision in decisions] == [2, 1, 0]


def test_blocks_past_the_limit_with_retry_after(tmp_path: Path):
    store = _store(tmp_path)
    for _ in range(2):
        store.consume("1.2.3.4", limit=2, now=NOW)
    blocked = store.consume("1.2.3.4", limit=2, now=NOW)
    assert blocked.allowed is False
    assert blocked.used == 2
    assert blocked.remaining == 0
    assert blocked.retry_after_seconds > 0


def test_survives_a_restart(tmp_path: Path):
    """A new process (fresh store object) must still see the used quota."""
    first = _store(tmp_path)
    first.consume("1.2.3.4", limit=2, now=NOW)
    first.consume("1.2.3.4", limit=2, now=NOW)

    second = _store(tmp_path)
    assert second.usage("1.2.3.4", now=NOW) == 2
    assert second.consume("1.2.3.4", limit=2, now=NOW).allowed is False


def test_subjects_are_isolated(tmp_path: Path):
    store = _store(tmp_path)
    store.consume("a", limit=1, now=NOW)
    assert store.consume("a", limit=1, now=NOW).allowed is False
    assert store.consume("b", limit=1, now=NOW).allowed is True


def test_new_day_resets_the_counter(tmp_path: Path):
    store = _store(tmp_path)
    store.consume("a", limit=1, now=NOW)
    tomorrow = datetime(2026, 10, 29, 0, 5, tzinfo=timezone.utc)
    assert store.consume("a", limit=1, now=tomorrow).allowed is True


def test_zero_limit_means_unlimited_and_stores_nothing(tmp_path: Path):
    store = _store(tmp_path)
    decision = store.consume("a", limit=0, now=NOW)
    assert decision.allowed is True
    assert store.usage("a", now=NOW) == 0


def test_prune_drops_old_days_only(tmp_path: Path):
    store = _store(tmp_path)
    store.consume("a", limit=5, now=datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc))
    store.consume("a", limit=5, now=NOW)
    removed = store.prune(keep_days=7, now=NOW)
    assert removed == 1
    assert store.usage("a", now=NOW) == 1


def test_empty_subject_is_rejected(tmp_path: Path):
    with pytest.raises(QuotaError):
        _store(tmp_path).consume("", limit=5, now=NOW)


def test_corrupt_store_raises_a_domain_error(tmp_path: Path):
    path = tmp_path / "broken.sqlite3"
    path.write_bytes(b"not a database")
    with pytest.raises(QuotaError):
        QuotaStore(path).consume("a", limit=1, now=NOW)
