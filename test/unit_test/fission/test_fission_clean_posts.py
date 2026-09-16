# COMP90024 Team 2

import pytest


@pytest.fixture
def clean_posts_fn(load_fission_module):
    return load_fission_module("clean_posts")


class FakeCleanES:
    def mget(self, index, ids, source=False):
        return {"docs": [{"_id": "reddit:existing", "found": True}]}

    def get(self, index, id):
        return {
            "_source": {
                "date": id.split(":", 1)[1],
                "station": "open-meteo-sydney",
                "bom_station_id": "066062",
                "tavg": 22.0,
                "tmin": 18.0,
                "tmax": 25.0,
                "prcp": 0.0,
            }
        }


class FakeVader:
    def polarity_scores(self, text):
        return {"compound": 0.6}


def test_clean_posts_clean_city_skips_existing_and_bulk_indexes(clean_posts_fn, monkeypatch):
    raw_hits = [
        {
            "_id": "reddit:existing",
            "_source": {
                "platform": "reddit",
                "city": "sydney",
                "id": "existing",
                "kind": "comment",
                "text": "Already cleaned post",
                "created_at": "2024-01-01T00:00:00Z",
            },
        },
        {
            "_id": "reddit:new",
            "_source": {
                "platform": "reddit",
                "city": "sydney",
                "id": "new",
                "kind": "comment",
                "author": "alice",
                "text": "Wonderful sunny weather in Sydney",
                "created_at": "2024-01-01T00:00:00Z",
                "score": 3,
                "num_comments": 2,
                "url": "https://reddit.com/r/sydney",
            },
        },
    ]
    captured = {}
    monkeypatch.setattr(clean_posts_fn, "scan", lambda *args, **kwargs: iter(raw_hits))
    monkeypatch.setattr(clean_posts_fn, "_detect_lang", lambda text: "en")

    def fake_bulk(es, actions, **kwargs):
        captured["actions"] = actions
        return len(actions), []

    monkeypatch.setattr(clean_posts_fn.helpers, "bulk", fake_bulk)

    result = clean_posts_fn._clean_city(FakeCleanES(), "sydney", 10, FakeVader(), require_weather=True)

    assert result["processed"] == 1
    assert result["scanned"] == 2
    assert result["skipped_existing"] == 1
    assert result["weather_cache_size"] == 1
    action = captured["actions"][0]
    assert action["_index"] == "posts_clean"
    assert action["_id"] == "reddit:new"
    assert action["_source"]["sentiment_label"] == "positive"
    assert action["_source"]["engagement"] == 5
    assert action["_source"]["weather_joined"] is True


def test_clean_posts_main_rejects_bad_city(clean_posts_fn, flask_app):
    with flask_app.test_request_context("/?city=perth"):
        response, status = clean_posts_fn.main()

    assert status == 400
    assert "unknown cities" in response.get_json()["error"]
