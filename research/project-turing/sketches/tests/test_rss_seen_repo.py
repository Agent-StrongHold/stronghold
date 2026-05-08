"""Tests for turing/rss_seen_repo.py — O(1) RSS dedup."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from turing.repo import Repo
from turing.rss_seen_repo import RssSeenRepo
from turing.self_identity import bootstrap_self_id


@pytest.fixture
def rss_repo(repo: Repo) -> RssSeenRepo:
    return RssSeenRepo(repo.conn)


def test_mark_and_is_seen(rss_repo: RssSeenRepo, self_id: str) -> None:
    rss_repo.mark_seen(self_id, "https://feed.example/rss", "guid-1")
    assert rss_repo.is_seen(self_id, "https://feed.example/rss", "guid-1") is True


def test_not_seen_returns_false(rss_repo: RssSeenRepo, self_id: str) -> None:
    assert rss_repo.is_seen(self_id, "https://feed.example/rss", "guid-x") is False


def test_mark_idempotent(rss_repo: RssSeenRepo, self_id: str) -> None:
    feed = "https://feed.example/rss"
    rss_repo.mark_seen(self_id, feed, "guid-1")
    rss_repo.mark_seen(self_id, feed, "guid-1")  # should not raise
    assert rss_repo.count(self_id, feed) == 1


def test_count(rss_repo: RssSeenRepo, self_id: str) -> None:
    feed = "https://feed.example/rss"
    for i in range(5):
        rss_repo.mark_seen(self_id, feed, f"item-{i}")
    assert rss_repo.count(self_id, feed) == 5


def test_count_isolated_by_feed(rss_repo: RssSeenRepo, self_id: str) -> None:
    rss_repo.mark_seen(self_id, "https://a.example/rss", "item-1")
    rss_repo.mark_seen(self_id, "https://b.example/rss", "item-1")
    assert rss_repo.count(self_id, "https://a.example/rss") == 1
    assert rss_repo.count(self_id, "https://b.example/rss") == 1


def test_count_isolated_by_self_id(repo: Repo) -> None:
    conn = repo.conn
    id_a = bootstrap_self_id(conn)
    conn.execute(
        "UPDATE self_identity SET archived_at = 'now' WHERE self_id = ?", (id_a,)
    )
    id_b = bootstrap_self_id(conn)
    rss = RssSeenRepo(conn)
    feed = "https://feed.example/rss"
    rss.mark_seen(id_a, feed, "shared-item")
    assert rss.is_seen(id_a, feed, "shared-item") is True
    assert rss.is_seen(id_b, feed, "shared-item") is False


def test_hydrate_seen_ids(rss_repo: RssSeenRepo, self_id: str) -> None:
    feed = "https://feed.example/rss"
    rss_repo.mark_seen(self_id, feed, "a")
    rss_repo.mark_seen(self_id, feed, "b")
    ids = rss_repo.hydrate_seen_ids(self_id, feed)
    assert ids == {"a", "b"}


def test_hydrate_empty_feed(rss_repo: RssSeenRepo, self_id: str) -> None:
    ids = rss_repo.hydrate_seen_ids(self_id, "https://never-seen.example/rss")
    assert ids == set()


def test_backfill_from_observations(rss_repo: RssSeenRepo, self_id: str) -> None:
    feed = "https://feed.example/rss"
    obs = [
        {"item_id": "old-1", "created_at": "2026-01-01T00:00:00+00:00"},
        {"item_id": "old-2"},
        {"item_id": None},  # should be skipped
        {},                 # should be skipped
    ]
    inserted = rss_repo.backfill_from_observations(self_id, feed, obs)
    assert inserted == 2
    assert rss_repo.is_seen(self_id, feed, "old-1")
    assert rss_repo.is_seen(self_id, feed, "old-2")


def test_backfill_idempotent(rss_repo: RssSeenRepo, self_id: str) -> None:
    feed = "https://feed.example/rss"
    obs = [{"item_id": "x"}]
    rss_repo.backfill_from_observations(self_id, feed, obs)
    second = rss_repo.backfill_from_observations(self_id, feed, obs)
    assert second == 0  # already present
