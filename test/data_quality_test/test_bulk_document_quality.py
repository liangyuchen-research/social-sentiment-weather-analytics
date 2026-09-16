# COMP90024 Team 2

import json

from database import bulk_upload


def test_posts_clean_bulk_documents_have_stable_ids_and_allowed_cities(tmp_path, monkeypatch):
    monkeypatch.setattr(bulk_upload, "CLEAN", tmp_path)
    monkeypatch.setattr(bulk_upload, "CITY_NAMES", ["sydney", "brisbane"])
    (tmp_path / "sydney.jsonl").write_text(
        json.dumps(
            {
                "platform": "reddit",
                "city": "sydney",
                "id": "r1",
                "author": "alice",
                "text": "Clean Sydney post",
                "date_local": "2024-01-01",
                "engagement": 5,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "brisbane.jsonl").write_text(
        json.dumps(
            {
                "platform": "mastodon",
                "city": "brisbane",
                "id": "m1",
                "author": "bob",
                "text": "Clean Brisbane post",
                "date_local": "2024-01-02",
                "engagement": 2,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    actions = list(bulk_upload.gen_posts_clean())

    assert [action["_id"] for action in actions] == ["mastodon:m1", "reddit:r1"]
    assert {action["_source"]["city"] for action in actions} == {"sydney", "brisbane"}
    assert all(action["_source"]["platform"] in {"reddit", "mastodon", "bluesky"} for action in actions)
    assert all(action["_source"]["engagement"] >= 0 for action in actions)


def test_raw_bulk_documents_skip_missing_ids_and_preserve_harvest_timestamp(tmp_path, monkeypatch):
    monkeypatch.setattr(bulk_upload, "RAW", tmp_path)
    monkeypatch.setattr(bulk_upload, "_stamp", lambda: "2024-01-01T00:00:00+00:00")
    (tmp_path / "bluesky_sydney_2024.jsonl").write_text(
        json.dumps({"platform": "bluesky", "id": "b1", "city": "sydney", "text": "Raw post"})
        + "\n"
        + json.dumps({"platform": "bluesky", "city": "sydney", "text": "Missing id"})
        + "\n",
        encoding="utf-8",
    )

    actions = list(bulk_upload.gen_posts_raw())

    assert len(actions) == 1
    assert actions[0]["_id"] == "bluesky:b1"
    assert actions[0]["_source"]["harvested_at"] == "2024-01-01T00:00:00+00:00"
    assert actions[0]["_source"]["platform"] == "bluesky"
