# COMP90024 Team 2

import json

import pandas as pd

from backend.cleaning import clean_pipeline
from database import bulk_upload


def test_raw_files_clean_to_city_jsonl_and_posts_clean_bulk_actions(tmp_path, monkeypatch):
    raw_dir = tmp_path / "raw"
    clean_dir = tmp_path / "cleaned"
    raw_dir.mkdir()
    clean_dir.mkdir()
    monkeypatch.setattr(clean_pipeline, "DATA_RAW", raw_dir)
    monkeypatch.setattr(clean_pipeline, "DATA_CLEAN", clean_dir)
    monkeypatch.setattr(clean_pipeline, "detect_lang", lambda text: "en")
    monkeypatch.setattr(bulk_upload, "CLEAN", clean_dir)
    monkeypatch.setattr(bulk_upload, "CITY_NAMES", clean_pipeline.CITY_NAMES)

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
        "time,tavg,tmin,tmax,prcp\n2024-01-01,22.5,18.0,26.0,0.2\n",
        encoding="utf-8",
    )

    clean_pipeline.main(all_langs=False, with_sentiment=False)
    actions = list(bulk_upload.gen_posts_clean())

    assert (clean_dir / "all_posts.parquet").exists()
    assert (clean_dir / "weather_daily.parquet").exists()
    assert (clean_dir / "sydney.jsonl").exists()
    assert len(actions) == 1
    assert actions[0]["_index"] == "posts_clean"
    assert actions[0]["_id"] == "reddit:r1"
    assert actions[0]["_source"]["city"] == "sydney"
    assert actions[0]["_source"]["text"] == "Warm sunny weather around Sydney harbour"
    assert actions[0]["_source"]["engagement"] == 5
    assert actions[0]["_source"]["date_local"] == "2024-01-01"
    assert actions[0]["_source"]["tavg"] == 22.5
    assert actions[0]["_source"]["prcp"] == 0.2


def test_weather_csvs_generate_weather_daily_bulk_actions(tmp_path, monkeypatch):
    monkeypatch.setattr(bulk_upload, "RAW", tmp_path)
    (tmp_path / "weather_sydney_2024.csv").write_text(
        "time,city,tavg,prcp\n2024-01-01,sydney,22.5,\n",
        encoding="utf-8",
    )
    (tmp_path / "weather_brisbane_2024.csv").write_text(
        "date,city,tavg,prcp\n2024-01-02,brisbane,28.0,0.0\n",
        encoding="utf-8",
    )

    actions = list(bulk_upload.gen_weather_daily())

    assert [action["_id"] for action in actions] == [
        "brisbane:2024-01-02",
        "sydney:2024-01-01",
    ]
    assert actions[0]["_index"] == "weather_daily"
    assert actions[1]["_source"]["prcp"] is None
    assert all(isinstance(action["_source"]["year"], int) for action in actions)


def test_cleaned_parquet_matches_city_jsonl_outputs(tmp_path, monkeypatch):
    raw_dir = tmp_path / "raw"
    clean_dir = tmp_path / "cleaned"
    raw_dir.mkdir()
    clean_dir.mkdir()
    monkeypatch.setattr(clean_pipeline, "DATA_RAW", raw_dir)
    monkeypatch.setattr(clean_pipeline, "DATA_CLEAN", clean_dir)
    monkeypatch.setattr(clean_pipeline, "detect_lang", lambda text: "en")

    (raw_dir / "mastodon_melbourne_2024.jsonl").write_text(
        json.dumps(
            {
                "city": "melbourne",
                "id": "m1",
                "author": "bob",
                "text": "Melbourne weather changed very quickly today",
                "created_at": "2024-06-01T00:00:00Z",
                "favourites_count": 1,
                "reblogs_count": 2,
                "replies_count": 3,
                "url": "https://mastodon.example/@bob/1",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (raw_dir / "weather_melbourne_2024.csv").write_text(
        "time,tavg,tmin,tmax,prcp\n2024-06-01,12.0,9.0,16.0,1.5\n",
        encoding="utf-8",
    )

    clean_pipeline.main(all_langs=False, with_sentiment=False)

    parquet_rows = pd.read_parquet(clean_dir / "all_posts.parquet")
    jsonl_rows = [
        json.loads(line)
        for line in (clean_dir / "melbourne.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len(parquet_rows) == 1
    assert len(jsonl_rows) == 1
    assert parquet_rows.loc[0, "id"] == jsonl_rows[0]["id"] == "m1"
    assert parquet_rows.loc[0, "tavg"] == jsonl_rows[0]["tavg"] == 12.0
