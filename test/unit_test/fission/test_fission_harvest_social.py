# COMP90024 Team 2

import pytest


@pytest.fixture
def harvest_social(load_fission_module):
    return load_fission_module("harvest_social")


def test_harvest_social_main_rejects_bad_platform(harvest_social, flask_app):
    with flask_app.test_request_context("/?platform=tiktok"):
        response, status = harvest_social.main()

    assert status == 400
    assert "unknown values" in response.get_json()["error"]


def test_harvest_social_main_dispatches_platforms_and_indexes(harvest_social, flask_app, monkeypatch):
    monkeypatch.setattr(harvest_social, "_es", lambda: object())
    monkeypatch.setattr(harvest_social, "_setting", lambda name, default=None: default)
    monkeypatch.setattr(
        harvest_social,
        "harvest_reddit_city",
        lambda city, start_dt, end_dt, max_records, include_comments: [
            {
                "platform": "reddit",
                "id": "r1",
                "city": city,
                "text": "Sydney post",
                "created_at": "2024-01-01T00:00:00Z",
            }
        ],
    )
    monkeypatch.setattr(harvest_social, "_bulk_index_raw", lambda es, records: (len(records), 0))

    with flask_app.test_request_context(
        "/?platform=reddit&city=sydney&mode=year&year=2024&max_records=5&include_comments=false"
    ):
        response, status = harvest_social.main()

    body = response.get_json()
    assert status == 200
    assert body["mode"] == "year"
    assert body["platforms"] == ["reddit"]
    assert body["cities"] == ["sydney"]
    assert body["per_platform"] == {"reddit": {"sydney": 1}}
    assert body["fetched_total"] == 1
    assert body["indexed_total"] == 1
    assert body["include_comments"] is False


def test_harvest_social_bulk_index_raw_skips_duplicates_and_missing_ids(harvest_social, monkeypatch):
    captured = {}

    def fake_bulk(es, actions, **kwargs):
        captured["actions"] = actions
        captured["kwargs"] = kwargs
        return len(actions), []

    monkeypatch.setattr(harvest_social.helpers, "bulk", fake_bulk)

    success, errors = harvest_social._bulk_index_raw(
        object(),
        [
            {"platform": "reddit", "id": "r1", "text": "one"},
            {"platform": "reddit", "id": "r1", "text": "duplicate"},
            {"platform": "mastodon", "text": "missing id"},
        ],
    )

    assert (success, errors) == (1, 0)
    assert len(captured["actions"]) == 1
    assert captured["actions"][0]["_id"] == "reddit:r1"
    assert captured["actions"][0]["_source"]["harvested_at"]
    assert captured["kwargs"]["raise_on_error"] is False
