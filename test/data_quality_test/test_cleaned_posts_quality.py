# COMP90024 Team 2

import pandas as pd

from backend.cleaning import clean_pipeline


def test_cleaned_posts_keep_only_supported_cities_and_unique_platform_ids(monkeypatch):
    monkeypatch.setattr(clean_pipeline, "detect_lang", lambda text: "en")
    raw = pd.DataFrame(
        [
            {
                "platform": "reddit",
                "city": "sydney",
                "id": "r1",
                "author": "alice",
                "text_raw": "Warm sunny weather in Sydney today",
                "created_utc": "2024-01-01T12:30:00Z",
                "engagement": 5,
                "url": None,
            },
            {
                "platform": "reddit",
                "city": "sydney",
                "id": "r1",
                "author": "alice",
                "text_raw": "Duplicate id should disappear",
                "created_utc": "2024-01-01T12:35:00Z",
                "engagement": 1,
                "url": None,
            },
            {
                "platform": "mastodon",
                "city": "perth",
                "id": "wrong-city",
                "author": "bob",
                "text_raw": "Unsupported city should disappear",
                "created_utc": "2024-01-01T00:00:00Z",
                "engagement": 1,
                "url": None,
            },
            {
                "platform": "bluesky",
                "city": "brisbane",
                "id": "b1",
                "author": "carol",
                "text_raw": "Brisbane storm clouds are building quickly",
                "created_utc": "2024-01-01T03:00:00Z",
                "engagement": 4,
                "url": None,
            },
        ]
    )

    cleaned = clean_pipeline.clean_posts(raw, keep_langs=("en",), with_sentiment=False)

    assert set(cleaned["city"]) <= set(clean_pipeline.CITY_NAMES)
    assert not cleaned.duplicated(subset=["platform", "id"]).any()
    assert cleaned["id"].tolist() == ["r1", "b1"]


def test_cleaned_post_local_time_columns_are_consistent(monkeypatch):
    monkeypatch.setattr(clean_pipeline, "detect_lang", lambda text: "en")
    raw = pd.DataFrame(
        [
            {
                "platform": "reddit",
                "city": "melbourne",
                "id": "m1",
                "author": "alice",
                "text_raw": "Melbourne winter weather update today",
                "created_utc": "2024-06-01T00:15:00Z",
                "engagement": 2,
                "url": None,
            },
            {
                "platform": "reddit",
                "city": "sydney",
                "id": "s1",
                "author": "bob",
                "text_raw": "Sydney summer weather update today",
                "created_utc": "2024-01-01T12:45:00Z",
                "engagement": 3,
                "url": None,
            },
        ]
    )

    cleaned = clean_pipeline.clean_posts(raw, keep_langs=("en",), with_sentiment=False)

    assert (cleaned["date_local"] == cleaned["created_local"].dt.date).all()
    assert (cleaned["hour_local"] == cleaned["created_local"].dt.floor("h")).all()
    assert (cleaned["year"] == cleaned["created_local"].dt.year).all()
    assert cleaned.loc[cleaned["id"] == "m1", "created_local"].iloc[0] == pd.Timestamp("2024-06-01 10:15:00")
    assert cleaned.loc[cleaned["id"] == "s1", "created_local"].iloc[0] == pd.Timestamp("2024-01-01 23:45:00")


def test_cleaned_posts_have_required_fields_and_non_negative_engagement(monkeypatch):
    monkeypatch.setattr(clean_pipeline, "detect_lang", lambda text: "en")
    raw = pd.DataFrame(
        [
            {
                "platform": "mastodon",
                "city": "sydney",
                "id": "m1",
                "author": "alice",
                "text_raw": "Sydney weather has a clear sky today",
                "created_utc": "2024-01-01T00:00:00Z",
                "engagement": 0,
                "url": "https://mastodon.example/@alice/1",
            },
            {
                "platform": "bluesky",
                "city": "melbourne",
                "id": "b1",
                "author": "bob",
                "text_raw": "Melbourne has windy weather today",
                "created_utc": "2024-01-01T00:00:00Z",
                "engagement": 7,
                "url": "https://bsky.app/profile/bob/post/1",
            },
        ]
    )

    cleaned = clean_pipeline.clean_posts(raw, keep_langs=("en",), with_sentiment=False)

    required = {
        "platform",
        "city",
        "id",
        "author",
        "text_raw",
        "text",
        "created_utc",
        "created_local",
        "date_local",
        "hour_local",
        "year",
        "lang",
        "engagement",
    }
    assert required <= set(cleaned.columns)
    assert cleaned[list(required)].notna().all().all()
    assert (cleaned["engagement"] >= 0).all()
    assert cleaned["text"].str.len().ge(5).all()
