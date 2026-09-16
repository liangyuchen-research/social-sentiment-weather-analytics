# COMP90024 Team 2

import json

from database import bulk_upload
from database import setup_indices


def test_posts_clean_bulk_sources_match_strict_posts_clean_mapping(tmp_path, monkeypatch):
    monkeypatch.setattr(bulk_upload, "CLEAN", tmp_path)
    monkeypatch.setattr(bulk_upload, "CITY_NAMES", ["sydney"])
    (tmp_path / "sydney.jsonl").write_text(
        json.dumps(
            {
                "platform": "reddit",
                "city": "sydney",
                "id": "r1",
                "author": "alice",
                "text_raw": "Raw text",
                "text": "Raw text",
                "created_utc": "2024-01-01T00:00:00Z",
                "created_local": "2024-01-01T11:00:00Z",
                "date_local": "2024-01-01",
                "hour_local": "2024-01-01T11:00:00Z",
                "year": 2024,
                "lang": "en",
                "engagement": 5,
                "sentiment": 0.1,
                "sentiment_label": "positive",
                "tavg": 22.5,
                "unknown_field": "must be dropped before strict mapping",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    action = list(bulk_upload.gen_posts_clean())[0]
    mapping_fields = set(setup_indices.list_mappings()["posts_clean"]["mappings"]["properties"])

    assert set(action["_source"]) <= mapping_fields
    assert "unknown_field" not in action["_source"]


def test_weather_daily_bulk_sources_are_compatible_with_weather_mapping(tmp_path, monkeypatch):
    monkeypatch.setattr(bulk_upload, "RAW", tmp_path)
    (tmp_path / "weather_sydney_2024.csv").write_text(
        "time,city,tavg,tmin,tmax,prcp\n2024-01-01,sydney,22.5,18.0,26.0,0.2\n",
        encoding="utf-8",
    )

    action = list(bulk_upload.gen_weather_daily())[0]
    mapping_fields = set(setup_indices.list_mappings()["weather_daily"]["mappings"]["properties"])

    assert set(action["_source"]) <= mapping_fields
    assert action["_id"] == "sydney:2024-01-01"
