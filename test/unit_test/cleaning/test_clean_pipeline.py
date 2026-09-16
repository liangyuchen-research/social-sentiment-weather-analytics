# COMP90024 Team 2

import json
import sys
from types import SimpleNamespace

import pandas as pd

from backend.cleaning import clean_pipeline


def test_read_jsonl_skips_blank_and_invalid_lines(tmp_path):
    source = tmp_path / "posts.jsonl"
    source.write_text(
        "\n"
        '{"id": "ok-1", "text": "hello"}\n'
        "{not json}\n"
        '{"id": "ok-2", "text": "world"}\n',
        encoding="utf-8",
    )

    assert list(clean_pipeline.read_jsonl(source)) == [
        {"id": "ok-1", "text": "hello"},
        {"id": "ok-2", "text": "world"},
    ]


def test_normalize_text_removes_urls_mentions_and_extra_whitespace():
    text = "  Rain in @Sydney today! https://example.com/a  \n\tBring   umbrella. "

    assert clean_pipeline.normalize_text(text) == "Rain in today! Bring umbrella."
    assert clean_pipeline.normalize_text(None) == ""


def test_clean_posts_filters_deduplicates_and_adds_local_time(monkeypatch):
    monkeypatch.setattr(clean_pipeline, "detect_lang", lambda text: "en")
    raw = pd.DataFrame(
        [
            {
                "platform": "reddit",
                "city": "sydney",
                "id": "keep",
                "author": "alice",
                "text_raw": "Warm sunny weather in Sydney today",
                "created_utc": "2024-01-01T12:30:00Z",
                "engagement": 5,
                "url": "https://reddit.com/r/sydney",
            },
            {
                "platform": "reddit",
                "city": "sydney",
                "id": "duplicate-id",
                "author": "alice",
                "text_raw": "Warm sunny weather in Sydney today",
                "created_utc": "2024-01-01T12:35:00Z",
                "engagement": 1,
                "url": None,
            },
            {
                "platform": "mastodon",
                "city": "brisbane",
                "id": "deleted",
                "author": "[deleted]",
                "text_raw": "Storm clouds over Brisbane",
                "created_utc": "2024-01-01T02:00:00Z",
                "engagement": 2,
                "url": None,
            },
            {
                "platform": "bluesky",
                "city": "perth",
                "id": "wrong-city",
                "author": "bob",
                "text_raw": "Wrong city should be filtered",
                "created_utc": "2024-01-01T02:00:00Z",
                "engagement": 2,
                "url": None,
            },
            {
                "platform": "bluesky",
                "city": "melbourne",
                "id": "too-short",
                "author": "carol",
                "text_raw": "hey",
                "created_utc": "2024-01-01T02:00:00Z",
                "engagement": 2,
                "url": None,
            },
        ]
    )

    cleaned = clean_pipeline.clean_posts(raw, keep_langs=("en",), with_sentiment=False)

    assert cleaned["id"].tolist() == ["keep"]
    row = cleaned.iloc[0]
    assert row["text"] == "Warm sunny weather in Sydney today"
    assert str(row["created_utc"]) == "2024-01-01 12:30:00+00:00"
    assert row["created_local"] == pd.Timestamp("2024-01-01 23:30:00")
    assert row["date_local"].isoformat() == "2024-01-01"
    assert row["year"] == 2024
    assert row["lang"] == "en"


def test_clean_posts_can_keep_all_languages(monkeypatch):
    monkeypatch.setattr(clean_pipeline, "detect_lang", lambda text: "fr")
    raw = pd.DataFrame(
        [
            {
                "platform": "mastodon",
                "city": "melbourne",
                "id": "bonjour",
                "author": "alice",
                "text_raw": "Bonjour Melbourne avec beaucoup de pluie",
                "created_utc": "2024-06-01T00:00:00Z",
                "engagement": 1,
                "url": None,
            }
        ]
    )

    cleaned = clean_pipeline.clean_posts(raw, keep_langs=(), with_sentiment=False)

    assert cleaned["id"].tolist() == ["bonjour"]
    assert cleaned.loc[0, "lang"] == "fr"


def test_clean_posts_drops_invalid_timestamps_and_uses_city_timezones(monkeypatch):
    monkeypatch.setattr(clean_pipeline, "detect_lang", lambda text: "en")
    raw = pd.DataFrame(
        [
            {
                "platform": "reddit",
                "city": "sydney",
                "id": "syd-summer",
                "author": "alice",
                "text_raw": "Sydney summer weather report",
                "created_utc": "2024-01-01T12:30:00Z",
                "engagement": 5,
                "url": None,
            },
            {
                "platform": "reddit",
                "city": "brisbane",
                "id": "bne-no-dst",
                "author": "bob",
                "text_raw": "Brisbane summer weather report",
                "created_utc": "2024-01-01T12:30:00Z",
                "engagement": 4,
                "url": None,
            },
            {
                "platform": "mastodon",
                "city": "melbourne",
                "id": "mel-winter",
                "author": "carol",
                "text_raw": "Melbourne winter weather report",
                "created_utc": "2024-06-01T00:00:00Z",
                "engagement": 3,
                "url": None,
            },
            {
                "platform": "bluesky",
                "city": "sydney",
                "id": "bad-time",
                "author": "dave",
                "text_raw": "This row has an invalid timestamp",
                "created_utc": "not-a-date",
                "engagement": 1,
                "url": None,
            },
        ]
    )

    cleaned = clean_pipeline.clean_posts(raw, keep_langs=("en",), with_sentiment=False)

    assert cleaned["id"].tolist() == ["syd-summer", "bne-no-dst", "mel-winter"]
    local_times = dict(zip(cleaned["id"], cleaned["created_local"]))
    assert local_times["syd-summer"] == pd.Timestamp("2024-01-01 23:30:00")
    assert local_times["bne-no-dst"] == pd.Timestamp("2024-01-01 22:30:00")
    assert local_times["mel-winter"] == pd.Timestamp("2024-06-01 10:00:00")


def test_clean_posts_adds_sentiment_scores_and_labels(monkeypatch):
    monkeypatch.setattr(clean_pipeline, "detect_lang", lambda text: "en")

    class FakeSentimentAnalyzer:
        def polarity_scores(self, text):
            if "terrible" in text:
                return {"compound": -0.6}
            if "wonderful" in text:
                return {"compound": 0.8}
            return {"compound": 0.0}

    fake_vader = SimpleNamespace(SentimentIntensityAnalyzer=FakeSentimentAnalyzer)
    monkeypatch.setitem(sys.modules, "vaderSentiment", SimpleNamespace())
    monkeypatch.setitem(sys.modules, "vaderSentiment.vaderSentiment", fake_vader)
    raw = pd.DataFrame(
        [
            {
                "platform": "reddit",
                "city": "sydney",
                "id": "negative",
                "author": "alice",
                "text_raw": "This weather is terrible today",
                "created_utc": "2024-01-01T00:00:00Z",
                "engagement": 1,
                "url": None,
            },
            {
                "platform": "reddit",
                "city": "melbourne",
                "id": "neutral",
                "author": "bob",
                "text_raw": "The weather exists today",
                "created_utc": "2024-01-01T00:00:00Z",
                "engagement": 1,
                "url": None,
            },
            {
                "platform": "reddit",
                "city": "brisbane",
                "id": "positive",
                "author": "carol",
                "text_raw": "This weather is wonderful today",
                "created_utc": "2024-01-01T00:00:00Z",
                "engagement": 1,
                "url": None,
            },
        ]
    )

    cleaned = clean_pipeline.clean_posts(raw, keep_langs=("en",), with_sentiment=True)

    assert cleaned["sentiment"].tolist() == [-0.6, 0.0, 0.8]
    assert cleaned["sentiment_label"].tolist() == ["negative", "neutral", "positive"]


def test_load_weather_for_reads_csvs_and_keeps_expected_columns(tmp_path, monkeypatch):
    weather_2024 = tmp_path / "weather_sydney_2024.csv"
    weather_2024.write_text(
        "time,tavg,tmin,tmax,prcp,unused\n"
        "2024-01-01,21.5,18.0,24.2,0.0,ignored\n",
        encoding="utf-8",
    )
    weather_2025 = tmp_path / "weather_sydney_2025.csv"
    weather_2025.write_text(
        "date,city,tavg,wspd\n"
        "2025-01-01,sydney,23.0,12.0\n",
        encoding="utf-8",
    )
    (tmp_path / "weather_sydney_bad.csv").write_text("not_a_date,tavg\nx,20\n", encoding="utf-8")
    monkeypatch.setattr(clean_pipeline, "DATA_RAW", tmp_path)

    weather = clean_pipeline.load_weather_for("sydney")

    assert weather["city"].tolist() == ["sydney", "sydney"]
    assert weather["date_local"].tolist() == [
        pd.Timestamp("2024-01-01").date(),
        pd.Timestamp("2025-01-01").date(),
    ]
    assert weather["tavg"].tolist() == [21.5, 23.0]
    assert weather["tmin"].iloc[0] == 18.0
    assert pd.isna(weather["tmin"].iloc[1])
    assert weather["tmax"].iloc[0] == 24.2
    assert pd.isna(weather["tmax"].iloc[1])
    assert weather["prcp"].iloc[0] == 0.0
    assert pd.isna(weather["prcp"].iloc[1])
    assert pd.isna(weather["wspd"].iloc[0])
    assert weather["wspd"].iloc[1] == 12.0


def test_load_all_weather_combines_available_city_weather(tmp_path, monkeypatch):
    monkeypatch.setattr(clean_pipeline, "DATA_RAW", tmp_path)
    monkeypatch.setattr(clean_pipeline, "CITY_NAMES", ["sydney", "melbourne"])
    (tmp_path / "weather_sydney_2024.csv").write_text(
        "time,tavg\n2024-01-01,21.5\n",
        encoding="utf-8",
    )

    weather = clean_pipeline.load_all_weather()

    assert weather["city"].tolist() == ["sydney"]
    assert weather["date_local"].tolist() == [pd.Timestamp("2024-01-01").date()]
    assert weather["tavg"].tolist() == [21.5]


def test_platform_loaders_map_raw_records_to_common_schema(tmp_path, monkeypatch):
    monkeypatch.setattr(clean_pipeline, "DATA_RAW", tmp_path)
    (tmp_path / "bluesky_sydney_2024.jsonl").write_text(
        json.dumps(
            {
                "city": "sydney",
                "id": "b1",
                "author_handle": "alice.bsky.social",
                "text": "Blue sky",
                "created_at": "2024-01-01T00:00:00Z",
                "like_count": 2,
                "repost_count": 3,
                "reply_count": 4,
                "url": "https://bsky.app/post/b1",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "mastodon_sydney_2024.jsonl").write_text(
        json.dumps(
            {
                "city": "sydney",
                "id": "m1",
                "author": "alice",
                "text": "Toot",
                "created_at": "2024-01-01T00:00:00Z",
                "favourites_count": 2,
                "reblogs_count": 3,
                "replies_count": 4,
                "url": "https://aus.social/@alice/1",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "reddit_sydney_2024.jsonl").write_text(
        json.dumps(
            {
                "city": "sydney",
                "id": "r1",
                "author": "alice",
                "text": "Reddit",
                "created_at": "2024-01-01T00:00:00Z",
                "score": 2,
                "num_comments": 3,
                "url": "https://reddit.com/r/sydney",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    assert clean_pipeline.load_bluesky().loc[0, "engagement"] == 9
    assert clean_pipeline.load_mastodon().loc[0, "engagement"] == 9
    assert clean_pipeline.load_reddit().loc[0, "engagement"] == 5


def test_main_writes_joined_parquet_and_per_city_jsonl(tmp_path, monkeypatch):
    raw_dir = tmp_path / "raw"
    clean_dir = tmp_path / "cleaned"
    raw_dir.mkdir()
    clean_dir.mkdir()
    monkeypatch.setattr(clean_pipeline, "DATA_RAW", raw_dir)
    monkeypatch.setattr(clean_pipeline, "DATA_CLEAN", clean_dir)
    monkeypatch.setattr(clean_pipeline, "detect_lang", lambda text: "en")
    (raw_dir / "reddit_sydney_2024.jsonl").write_text(
        json.dumps(
            {
                "city": "sydney",
                "id": "r1",
                "author": "alice",
                "text": "Warm sunny weather around Sydney harbour",
                "created_at": "2024-01-01T12:30:00Z",
                "score": 2,
                "num_comments": 3,
                "url": "https://reddit.com/r/sydney",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (raw_dir / "weather_sydney_2024.csv").write_text(
        "time,tavg,prcp\n2024-01-01,22.5,0.2\n",
        encoding="utf-8",
    )

    clean_pipeline.main(all_langs=False, with_sentiment=False)

    assert (clean_dir / "all_posts.parquet").exists()
    assert (clean_dir / "weather_daily.parquet").exists()
    for city in clean_pipeline.CITY_NAMES:
        assert (clean_dir / f"{city}.jsonl").exists()

    rows = [
        json.loads(line)
        for line in (clean_dir / "sydney.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len(rows) == 1
    assert rows[0]["id"] == "r1"
    assert rows[0]["city"] == "sydney"
    assert rows[0]["date_local"] == "2024-01-01"
    assert rows[0]["engagement"] == 5
    assert rows[0]["tavg"] == 22.5
    assert rows[0]["prcp"] == 0.2
