# COMP90024 Team 2

from types import SimpleNamespace

import pytest

from backend.harvesters import reddit_api


def test_reddit_to_unified_post_combines_title_selftext_and_url():
    rec = reddit_api._to_unified(
        {
            "id": "abc",
            "subreddit": "sydney",
            "author": "alice",
            "title": "Sunny day",
            "selftext": "At the harbour",
            "score": 10,
            "num_comments": 4,
            "created_utc": 1704067200,
            "permalink": "/r/sydney/comments/abc/sunny_day/",
        },
        city="sydney",
        kind="posts",
    )

    assert rec["platform"] == "reddit"
    assert rec["kind"] == "post"
    assert rec["text"] == "Sunny day\nAt the harbour"
    assert rec["created_at"] == "2024-01-01T00:00:00+00:00"
    assert rec["url"] == "https://reddit.com/r/sydney/comments/abc/sunny_day/"
    assert rec["parent_post_id"] is None


def test_reddit_to_unified_comment_uses_body_and_parent_post_id():
    rec = reddit_api._to_unified(
        {
            "id": "comment-1",
            "subreddit": "melbourne",
            "body": "Bring a jacket",
            "author": None,
            "score": None,
            "created_utc": "2024-01-01T00:00:00Z",
            "link_id": "t3_parent",
        },
        city="melbourne",
        kind="comments",
    )

    assert rec["kind"] == "comment"
    assert rec["author"] == "[deleted]"
    assert rec["text"] == "Bring a jacket"
    assert rec["score"] == 0
    assert rec["created_at"] == "2024-01-01T00:00:00Z"
    assert rec["parent_post_id"] == "parent"


def test_reddit_to_unified_handles_missing_optional_fields():
    rec = reddit_api._to_unified(
        {
            "id": "minimal",
            "subreddit": "brisbane",
            "created_utc": None,
        },
        city="brisbane",
        kind="posts",
    )

    assert rec["kind"] == "post"
    assert rec["author"] == "[deleted]"
    assert rec["text"] == ""
    assert rec["score"] == 0
    assert rec["num_comments"] == 0
    assert rec["created_at"] is None
    assert rec["url"] == ""
    assert rec["parent_post_id"] is None


def test_reddit_paginate_moves_cursor_to_oldest_timestamp(monkeypatch):
    calls = []
    batches = [
        [
            {"id": "newer", "created_utc": 30},
            {"id": "older", "created_utc": 20},
            {"id": "missing-created"},
        ],
        [{"id": "oldest", "created_utc": 10}],
    ]

    def fake_fetch_page(session, kind, subreddit, after, before):
        calls.append(before)
        return batches.pop(0)

    monkeypatch.setattr(reddit_api, "_fetch_page", fake_fetch_page)

    items = list(
        reddit_api._paginate(
            session=object(),
            kind="posts",
            subreddit="sydney",
            after=10,
            before=40,
            sleep_sec=0,
        )
    )

    assert [item["id"] for item in items] == ["newer", "older", "oldest"]
    assert calls == [40, 19]


def test_reddit_paginate_stops_on_empty_page(monkeypatch):
    calls = []

    def fake_fetch_page(session, kind, subreddit, after, before):
        calls.append((kind, subreddit, after, before))
        return []

    monkeypatch.setattr(reddit_api, "_fetch_page", fake_fetch_page)

    items = list(
        reddit_api._paginate(
            session=object(),
            kind="comments",
            subreddit="brisbane",
            after=10,
            before=40,
            sleep_sec=0,
        )
    )

    assert items == []
    assert calls == [("comments", "brisbane", 10, 40)]


def test_reddit_request_retries_rate_limits(monkeypatch):
    sleeps = []
    responses = [
        SimpleNamespace(status_code=429, headers={"Retry-After": "7"}, text="rate limited"),
        SimpleNamespace(status_code=200, headers={}, text="ok"),
    ]
    session = SimpleNamespace(get=lambda *args, **kwargs: responses.pop(0))
    monkeypatch.setattr(reddit_api.time, "sleep", lambda seconds: sleeps.append(seconds))

    response = reddit_api._request(session, "https://example.test", {"q": "sydney"})

    assert response.status_code == 200
    assert sleeps == [7]


def test_reddit_request_retries_server_errors(monkeypatch):
    sleeps = []
    responses = [
        SimpleNamespace(status_code=500, headers={}, text="server error"),
        SimpleNamespace(status_code=502, headers={}, text="bad gateway"),
        SimpleNamespace(status_code=200, headers={}, text="ok"),
    ]
    session = SimpleNamespace(get=lambda *args, **kwargs: responses.pop(0))
    monkeypatch.setattr(reddit_api.time, "sleep", lambda seconds: sleeps.append(seconds))

    response = reddit_api._request(session, "https://example.test", {"q": "sydney"})

    assert response.status_code == 200
    assert sleeps == [1, 2]


def test_reddit_request_raises_for_non_retryable_http_error():
    session = SimpleNamespace(
        get=lambda *args, **kwargs: SimpleNamespace(
            status_code=400,
            headers={},
            text="bad request with details",
        )
    )

    with pytest.raises(RuntimeError, match="Arctic Shift HTTP 400"):
        reddit_api._request(session, "https://example.test", {"q": "sydney"})
