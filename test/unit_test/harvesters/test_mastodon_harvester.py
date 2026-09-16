# COMP90024 Team 2

from types import SimpleNamespace

from backend.harvesters import mastodon_harvester


def test_mastodon_strip_html_and_status_to_dict():
    status = {
        "id": "123",
        "in_reply_to_id": "99",
        "account": {"acct": "alice", "display_name": "Alice"},
        "content": "<p>Hello <strong>Sydney</strong></p>",
        "language": "en",
        "reblogs_count": 1,
        "favourites_count": 2,
        "replies_count": 3,
        "created_at": "2024-01-01T00:00:00.000Z",
        "url": "https://aus.social/@alice/123",
        "tags": [{"name": "Sydney"}],
    }

    rec = mastodon_harvester.status_to_dict(status, "https://aus.social", "sydney", "search:Sydney")

    assert rec["id"] == "https://aus.social::123"
    assert rec["kind"] == "reply"
    assert rec["text"] == "Hello Sydney"
    assert rec["tags"] == ["Sydney"]
    assert rec["parent_status_id"] == "https://aus.social::99"
    assert rec["root_status_id"] == "https://aus.social::123"


def test_mastodon_status_to_dict_defaults_missing_optional_fields():
    rec = mastodon_harvester.status_to_dict(
        {
            "id": "123",
            "content": "<p>Plain status</p>",
        },
        "https://mastodon.au",
        "melbourne",
        "tag:Melbourne",
    )

    assert rec["id"] == "https://mastodon.au::123"
    assert rec["kind"] == "status"
    assert rec["author"] is None
    assert rec["author_display"] is None
    assert rec["text"] == "Plain status"
    assert rec["reblogs_count"] == 0
    assert rec["favourites_count"] == 0
    assert rec["replies_count"] == 0
    assert rec["tags"] == []
    assert rec["parent_status_id"] is None
    assert rec["root_status_id"] == "https://mastodon.au::123"


def test_mastodon_iter_search_terms_deduplicates_case_insensitively():
    terms = mastodon_harvester._iter_search_terms(
        {
            "tags": ["Sydney", "sydney", "NSW"],
            "queries": ["#Sydney", "Sydney Australia"],
        }
    )

    assert terms == ["#Sydney", "#NSW", "Sydney Australia"]


def test_mastodon_unique_instances_puts_primary_first(monkeypatch):
    monkeypatch.setattr(
        mastodon_harvester,
        "MASTODON_INSTANCES",
        ["https://aus.social", "https://mastodon.au", "https://aus.social"],
    )

    assert mastodon_harvester._unique_instances("https://mastodon.au") == [
        "https://mastodon.au",
        "https://aus.social",
    ]


def test_mastodon_request_returns_none_after_repeated_network_errors(monkeypatch):
    sleeps = []

    def failing_get(*args, **kwargs):
        raise mastodon_harvester.requests.exceptions.Timeout("slow")

    session = SimpleNamespace(get=failing_get)
    monkeypatch.setattr(mastodon_harvester.time, "sleep", lambda seconds: sleeps.append(seconds))

    response = mastodon_harvester._request(session, "https://example.test")

    assert response is None
    assert sleeps == [1, 2]


def test_mastodon_fetch_context_replies_filters_by_date(monkeypatch):
    payload = {
        "descendants": [
            {
                "id": "in-window",
                "in_reply_to_id": "root",
                "account": {"acct": "alice"},
                "content": "<p>Reply in range</p>",
                "created_at": "2024-01-15T00:00:00.000Z",
            },
            {
                "id": "too-old",
                "content": "<p>Old reply</p>",
                "created_at": "2023-12-31T23:59:59.000Z",
            },
        ]
    }
    response = SimpleNamespace(status_code=200, json=lambda: payload)
    monkeypatch.setattr(mastodon_harvester, "_request", lambda *args, **kwargs: response)

    replies = mastodon_harvester.fetch_context_replies(
        session=object(),
        instance="https://aus.social",
        token="token",
        status_id="root",
        city="sydney",
        source_kind="search:Sydney",
        start_iso="2024-01-01T00:00:00.000Z",
        end_iso="2024-12-31T23:59:59.999Z",
    )

    assert len(replies) == 1
    assert replies[0]["id"] == "https://aus.social::in-window"
    assert replies[0]["kind"] == "reply"
    assert replies[0]["root_status_id"] == "https://aus.social::root"
