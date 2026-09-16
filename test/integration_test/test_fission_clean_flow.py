# COMP90024 Team 2

from datetime import datetime, timezone


class FakeRawToCleanES:
    def __init__(self, raw_hits, weather):
        self.raw_hits = raw_hits
        self.weather = weather

    def mget(self, index, ids, source=False):
        return {"docs": [{"_id": doc_id, "found": False} for doc_id in ids]}

    def get(self, index, id):
        return {"_source": self.weather[id]}


class FakeVader:
    def polarity_scores(self, text):
        return {"compound": 0.7}


def test_fission_social_raw_record_can_be_cleaned_and_weather_joined(load_fission_module, monkeypatch):
    harvest_social = load_fission_module("harvest_social")
    clean_posts = load_fission_module("clean_posts")
    created_ts = int(datetime(2024, 1, 1, 12, 30, tzinfo=timezone.utc).timestamp())
    raw_record = harvest_social._reddit_to_raw(
        {
            "id": "r1",
            "subreddit": "sydney",
            "author": "alice",
            "body": "Wonderful weather in Sydney today",
            "score": 4,
            "created_utc": created_ts,
            "link_id": "t3_parent",
        },
        city="sydney",
        kind="comments",
    )
    raw_hits = [{"_id": "reddit:r1", "_source": raw_record}]
    weather = {
        "sydney:2024-01-01": {
            "date": "2024-01-01",
            "station": "open-meteo-sydney",
            "bom_station_id": "066062",
            "tavg": 22.0,
            "tmin": 18.0,
            "tmax": 26.0,
            "prcp": 0.0,
        }
    }
    fake_es = FakeRawToCleanES(raw_hits, weather)
    captured = {}
    monkeypatch.setattr(clean_posts, "scan", lambda *args, **kwargs: iter(raw_hits))
    monkeypatch.setattr(clean_posts, "_detect_lang", lambda text: "en")

    def fake_bulk(es, actions, **kwargs):
        captured["actions"] = actions
        return len(actions), []

    monkeypatch.setattr(clean_posts.helpers, "bulk", fake_bulk)

    result = clean_posts._clean_city(fake_es, "sydney", batch=10, vader=FakeVader(), require_weather=True)

    assert result["processed"] == 1
    assert result["skipped_missing_weather"] == 0
    action = captured["actions"][0]
    assert action["_id"] == "reddit:r1"
    assert action["_index"] == "posts_clean"
    assert action["_source"]["text"] == "Wonderful weather in Sydney today"
    assert action["_source"]["date_local"] == "2024-01-01"
    assert action["_source"]["weather_joined"] is True
    assert action["_source"]["weather_station"] == "open-meteo-sydney"
    assert action["_source"]["sentiment_label"] == "positive"
