# COMP90024 Team 2

import pytest


@pytest.fixture
def api_query(load_fission_module):
    return load_fission_module("api_query")


class FakeSearchES:
    def __init__(self):
        self.calls = []

    def search(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs.get("size") == 0 and "aggs" in kwargs:
            return {
                "hits": {"total": {"value": 2}},
                "aggregations": {
                    "by_city": {"buckets": [{"key": "sydney", "doc_count": 2}]},
                    "by_platform": {"buckets": [{"key": "reddit", "doc_count": 2}]},
                    "by_label": {"buckets": [{"key": "positive", "doc_count": 1}]},
                    "min_date": {"value_as_string": "2024-01-01T00:00:00.000Z"},
                    "max_date": {"value_as_string": "2024-01-02T00:00:00.000Z"},
                },
            }
        return {
            "hits": {
                "total": {"value": 1},
                "hits": [{"_source": {"id": "p1", "city": "sydney", "text": "Clean post"}}],
            }
        }

    def info(self):
        return {"version": {"number": "8.0.0"}, "cluster_name": "test"}


def test_api_query_main_rejects_unknown_mode(api_query, flask_app):
    with flask_app.test_request_context("/?mode=missing"):
        response, status = api_query.main()

    assert status == 400
    assert response.get_json()["error"] == "unknown mode 'missing'"
    assert "summary" in response.get_json()["modes"]


@pytest.mark.parametrize(
    ("path", "expected_mode", "expected_key"),
    [
        pytest.param("/?mode=health", "health", "es_version", id="health"),
        pytest.param("/?mode=posts&city=sydney&platform=reddit&size=10", "posts", "rows", id="posts"),
        pytest.param("/?mode=summary", "summary", "by_city", id="summary"),
    ],
)
def test_api_query_main_dispatches_modes(api_query, flask_app, monkeypatch, path, expected_mode, expected_key):
    fake_es = FakeSearchES()
    monkeypatch.setattr(api_query, "_es", lambda: fake_es)

    with flask_app.test_request_context(path):
        response, status = api_query.main()

    body = response.get_json()
    assert status == 200
    assert body["mode"] == expected_mode
    assert expected_key in body
