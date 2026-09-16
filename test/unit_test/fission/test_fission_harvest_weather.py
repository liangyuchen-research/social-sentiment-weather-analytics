# COMP90024 Team 2

import pytest


@pytest.fixture
def harvest_weather(load_fission_module):
    return load_fission_module("harvest_weather")


def test_harvest_weather_main_rejects_bad_city(harvest_weather, flask_app):
    with flask_app.test_request_context("/?city=perth"):
        response, status = harvest_weather.main()

    assert status == 400
    assert "unknown cities" in response.get_json()["error"]


def test_harvest_weather_main_fetches_and_indexes_rows(harvest_weather, flask_app, monkeypatch):
    rows_by_city = {
        "sydney": [{"city": "sydney", "date": "2024-01-01"}],
        "brisbane": [{"city": "brisbane", "date": "2024-01-01"}],
    }
    monkeypatch.setattr(harvest_weather, "_es", lambda: object())
    monkeypatch.setattr(harvest_weather, "_fetch_city", lambda city, start, end: rows_by_city[city])
    monkeypatch.setattr(harvest_weather, "_bulk_index", lambda es, rows: (len(rows), 0))

    with flask_app.test_request_context("/?cities=sydney,brisbane&mode=range&from=2024-01-01&to=2024-01-02"):
        response, status = harvest_weather.main()

    body = response.get_json()
    assert status == 200
    assert body["mode"] == "range"
    assert body["cities"] == ["sydney", "brisbane"]
    assert body["per_city"] == {"sydney": 1, "brisbane": 1}
    assert body["fetched_total"] == 2
    assert body["indexed_total"] == 2


def test_harvest_weather_bulk_index_builds_weather_actions(harvest_weather, monkeypatch):
    captured = {}

    def fake_bulk(es, actions, **kwargs):
        captured["actions"] = actions
        captured["kwargs"] = kwargs
        return 1, []

    monkeypatch.setattr(harvest_weather.helpers, "bulk", fake_bulk)
    rows = [
        {"city": "sydney", "date": "2024-01-01", "tavg": 22.0},
        {"city": "", "date": "2024-01-02", "tavg": 23.0},
    ]

    success, errors = harvest_weather._bulk_index(object(), rows)

    assert (success, errors) == (1, 0)
    assert captured["actions"] == [
        {
            "_op_type": "index",
            "_index": "weather_daily",
            "_id": "sydney:2024-01-01",
            "_source": {"city": "sydney", "date": "2024-01-01", "tavg": 22.0},
        }
    ]
    assert captured["kwargs"]["raise_on_error"] is False
