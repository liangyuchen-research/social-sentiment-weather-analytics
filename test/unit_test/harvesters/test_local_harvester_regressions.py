"""Offline regressions for pagination and instance-scoped authentication."""

import json
from types import SimpleNamespace

import pytest

from backend.harvesters import bluesky_harvester as bluesky
from backend.harvesters import mastodon_harvester as mastodon


def mastodon_status(identifier, created_at="2024-06-01T00:00:00.000Z"):
    return {"id": identifier, "created_at": created_at, "content": "Sunny weather"}


def fetch_mastodon(method, cap):
    kwargs = dict(session=object(), instance="https://example.invalid",
                  start_iso="2024-01-01T00:00:00.000Z",
                  end_iso="2024-12-31T23:59:59.999Z", cap=cap, city="sydney")
    if method == "tag":
        return mastodon.fetch_tag(tag="Sydney", **kwargs)
    return mastodon.fetch_search(token="primary-only-token", query="Sydney", **kwargs)


def mock_mastodon_pages(monkeypatch, method, pages):
    calls = []

    def request(*args, **kwargs):
        calls.append(dict(kwargs["params"]))
        assert len(calls) <= len(pages), "Pagination failed to stop after the last expected page"
        page = pages[len(calls) - 1]
        payload = page if method == "tag" else {"statuses": page}
        return SimpleNamespace(status_code=200, json=lambda: payload)

    monkeypatch.setattr(mastodon, "_request", request)
    monkeypatch.setattr(mastodon.time, "sleep", lambda _: None)
    return calls


@pytest.mark.parametrize("method", ["tag", "search"])
@pytest.mark.parametrize("cap", [None, 100])
@pytest.mark.parametrize("in_window", [True, False])
def test_repeated_mastodon_page_stops_without_duplicate_records(monkeypatch, method, cap, in_window):
    timestamp = "2024-06-01T00:00:00.000Z" if in_window else "2025-06-01T00:00:00.000Z"
    page = [mastodon_status("2", timestamp), mastodon_status("1", timestamp)]
    calls = mock_mastodon_pages(monkeypatch, method, [page, page])
    records = fetch_mastodon(method, cap)
    assert len(calls) == 2
    assert len(records) == (2 if in_window else 0)
    assert len({record["id"] for record in records}) == len(records)


@pytest.mark.parametrize("method", ["tag", "search"])
def test_mastodon_cursor_cycle_stops(monkeypatch, method):
    pages = [[mastodon_status("3"), mastodon_status("2")],
             [mastodon_status("2"), mastodon_status("1")],
             [mastodon_status("3"), mastodon_status("2")]]
    calls = mock_mastodon_pages(monkeypatch, method, pages)
    records = fetch_mastodon(method, None)
    assert len(calls) == 3
    assert [record["id"].split("::")[1] for record in records] == ["3", "2", "1"]


@pytest.mark.parametrize("method", ["tag", "search"])
def test_overlapping_mastodon_pages_count_only_unique_statuses_toward_cap(monkeypatch, method):
    pages = [[mastodon_status("3"), mastodon_status("2")],
             [mastodon_status("2"), mastodon_status("1")]]
    mock_mastodon_pages(monkeypatch, method, pages)
    records = fetch_mastodon(method, 3)
    assert [record["id"].split("::")[1] for record in records] == ["3", "2", "1"]


def test_mastodon_search_fallback_keeps_token_on_primary_instance(tmp_path, monkeypatch):
    primary, other = "https://primary.invalid", "https://other.invalid"
    monkeypatch.setenv("MASTODON_ACCESS_TOKEN", "primary-only-token")
    monkeypatch.setenv("MASTODON_INSTANCE", primary + "/")
    monkeypatch.setitem(mastodon.CITIES, "sydney", {"tags": ["Sydney"], "queries": []})
    monkeypatch.setattr(mastodon, "DATA_RAW", tmp_path)
    monkeypatch.setattr(mastodon, "_unique_instances", lambda _: [primary, other])
    monkeypatch.setattr(mastodon, "fetch_search", lambda *args: [])
    monkeypatch.setattr(mastodon.time, "sleep", lambda _: None)

    def fetch_tag(session, instance, tag, *args):
        status = dict(mastodon_status("1"), replies_count=1)
        return [mastodon.status_to_dict(status, instance, "sydney", "tag: Sydney")]

    tokens = []

    def fetch_replies(session, instance, token, status_id, *args):
        tokens.append((instance, token, status_id))
        return []

    monkeypatch.setattr(mastodon, "fetch_tag", fetch_tag)
    monkeypatch.setattr(mastodon, "fetch_context_replies", fetch_replies)
    mastodon.harvest("sydney", 2024, None, "B")
    assert tokens == [(primary, "primary-only-token", "1"), (other, None, "1")]
    records = [json.loads(line) for line in (tmp_path / "mastodon_sydney_2024.jsonl").read_text().splitlines()]
    assert len(records) == 2


def bluesky_post(identifier):
    return SimpleNamespace(
        uri=f"at://did:example:alice/app.bsky.feed.post/{identifier}", cid=identifier,
        author=SimpleNamespace(handle="alice.example.invalid", did="did:example:alice"),
        record=SimpleNamespace(text="Pleasant weather", langs=["en"],
                               created_at="2024-06-01T00:00:00Z", reply=None),
        reply_count=0, repost_count=0, like_count=0,
    )


@pytest.mark.parametrize("cursors", [["A", "A"], ["A", "B", "A"]])
@pytest.mark.parametrize("cap", [None, 100])
def test_bluesky_stops_repeated_cursors_and_resets_tracking_per_query(tmp_path, monkeypatch, cursors, cap):
    calls = {"first": [], "second": []}

    def search(params):
        query = params["q"]
        calls[query].append(params.get("cursor"))
        number = len(calls[query])
        assert number <= len(cursors), "Pagination continued through a cursor cycle"
        return SimpleNamespace(posts=[bluesky_post(query)], cursor=cursors[number - 1])

    client = SimpleNamespace(app=SimpleNamespace(bsky=SimpleNamespace(feed=SimpleNamespace(search_posts=search))))
    monkeypatch.setattr(bluesky, "get_client", lambda: client)
    monkeypatch.setattr(bluesky, "DATA_RAW", tmp_path)
    monkeypatch.setitem(bluesky.CITIES, "sydney", {"queries": ["first", "second"]})
    monkeypatch.setattr(bluesky.time, "sleep", lambda _: None)
    bluesky.harvest("sydney", 2024, cap, include_replies=False)
    assert all(len(query_calls) == len(cursors) for query_calls in calls.values())
    records = [json.loads(line) for line in (tmp_path / "bluesky_sydney_2024.jsonl").read_text().splitlines()]
    assert len(records) == 2
    assert len({record["id"] for record in records}) == 2
