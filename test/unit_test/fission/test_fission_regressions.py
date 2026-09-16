"""Offline regressions for packaging, validation, and incremental processing."""

from datetime import datetime, timezone
import importlib.util
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

import pytest


@pytest.mark.parametrize("name", ["api_query", "clean_posts", "harvest_reddit", "harvest_social", "harvest_weather"])
def test_elasticsearch_defaults_to_verified_tls(name, load_fission_module, monkeypatch):
    module = load_fission_module(name)
    values = {"ES_HOST": "https://example.invalid:9200", "ES_PASSWORD": "test-password",
              "ES_CA_CERTS": "/secrets/default/es-creds/ca.crt"}
    monkeypatch.setattr(module, "_setting", lambda key, default=None: values.get(key, default))
    client = module._es()
    assert client.kwargs["verify_certs"] is True
    assert client.kwargs["ca_certs"] == values["ES_CA_CERTS"]


@pytest.mark.parametrize("name", ["api_query", "clean_posts", "harvest_reddit", "harvest_social", "harvest_weather"])
def test_blank_required_settings_fail_explicitly(name, load_fission_module, monkeypatch):
    module = load_fission_module(name)
    monkeypatch.setenv("ES_PASSWORD", " ")
    def missing_file(*args, **kwargs):
        raise FileNotFoundError
    monkeypatch.setattr("builtins.open", missing_file)
    with pytest.raises(RuntimeError, match="ES_PASSWORD"):
        module._setting("ES_PASSWORD")


@pytest.mark.parametrize(("name", "query"), [
    ("api_query", "mode=posts&size=-1"), ("api_query", "mode=posts&size=wrong"),
    ("api_query", "from=2026-02-30"), ("api_query", "from=2026-05-01&to=2026-04-01"),
    ("clean_posts", "batch=0"), ("clean_posts", "batch=wrong"),
    ("harvest_social", "hours=-2"), ("harvest_social", "hours=nan"),
    ("harvest_social", "max_records=0"), ("harvest_social", "mode=unknown"),
    ("harvest_social", "mastodon_mode=unknown"),
    ("harvest_weather", "days=0"), ("harvest_weather", "mode=unknown"),
    ("harvest_weather", "mode=range&from=2026-05-01&to=2026-04-01"),
    ("harvest_reddit", "hours=0"), ("harvest_reddit", "mode=unknown"),
    ("harvest_reddit", "max_records=-1"), ("harvest_reddit", "mode=year&year=invalid"),
])
def test_invalid_inputs_rejected_before_connections(name, query, load_fission_module, flask_app, monkeypatch):
    module = load_fission_module(name)
    def no_connection():
        pytest.fail("Invalid arguments must not initialize an Elasticsearch connection")
    monkeypatch.setattr(module, "_es", no_connection)
    with flask_app.test_request_context("/?" + query):
        response, status = module.main()
    assert status == 400
    assert response.get_json()["error"]


def test_summary_empty_index_and_exact_totals(load_fission_module):
    module = load_fission_module("api_query")
    calls = []
    def search(**kwargs):
        calls.append(kwargs)
        return {"hits": {"total": {"value": 0}}, "aggregations": {
            "by_city": {"buckets": []}, "by_platform": {"buckets": []},
            "by_label": {"buckets": []}, "min_date": {"value": None}, "max_date": {"value": None}}}
    result = module._mode_summary(SimpleNamespace(search=search), {})
    assert result["date_range"] == [None, None]
    assert result["total"] == 0
    assert calls[0]["track_total_hits"] is True


def test_cleaner_progresses_past_existing_prefix_and_releases_scroll(load_fission_module, monkeypatch):
    module = load_fission_module("clean_posts")
    closed, batches, actions = [], [], []
    def scan(*args, **kwargs):
        try:
            for i in range(601):
                yield {"_id": str(i), "_source": {"platform": "reddit", "id": str(i),
                    "text": "Pleasant weather in Sydney today", "created_at": "2024-01-01T20:00:00Z"}}
        finally:
            closed.append(True)
    def mget(index, ids, source=False):
        batches.append(ids)
        return {"docs": [{"_id": i, "found": int(i) < 600} for i in ids]}
    fake_es = SimpleNamespace(mget=mget, get=lambda **kwargs: {"_source": {"date": "2024-01-02"}})
    monkeypatch.setattr(module, "scan", scan)
    monkeypatch.setattr(module, "_detect_lang", lambda text: "en")
    monkeypatch.setattr(module.helpers, "bulk", lambda es, rows, **kwargs: (actions.extend(rows) or len(rows), []))
    vader = SimpleNamespace(polarity_scores=lambda text: {"compound": .6})
    result = module._clean_city(fake_es, "sydney", 1, vader)
    assert result["processed"] == 1
    assert result["scanned"] == 601
    assert result["skipped_existing"] == 600
    assert [len(batch) for batch in batches] == [500, 101]
    assert closed == [True]
    assert actions[0]["_source"]["date_local"] == "2024-01-02"


def test_cleaner_does_not_hide_elasticsearch_outage(load_fission_module):
    module = load_fission_module("clean_posts")
    def unavailable(**kwargs):
        raise ConnectionError("unavailable")
    es = SimpleNamespace(mget=unavailable, get=unavailable)
    with pytest.raises(ConnectionError):
        module._existing_clean_ids(es, ["x"])
    with pytest.raises(ConnectionError):
        module._weather_for(es, "sydney", "2024-01-01")


def test_naive_source_timestamp_is_utc_and_html_entities_are_decoded(load_fission_module):
    module = load_fission_module("harvest_social")
    assert module._parse_dt("2024-01-01T12:00:00") == datetime(2024, 1, 1, 12, tzinfo=timezone.utc)
    assert module._strip_html("<p>Warm &amp; sunny</p>") == "Warm & sunny"


def test_mastodon_token_not_forwarded_to_other_instances(load_fission_module, monkeypatch):
    module = load_fission_module("harvest_social")
    settings = {"MASTODON_ACCESS_TOKEN": "primary-only-token", "MASTODON_INSTANCE": "https://primary.invalid"}
    monkeypatch.setattr(module, "_setting", lambda name, default=None: settings.get(name, default))
    monkeypatch.setattr(module, "_mastodon_instances", lambda primary: ["https://other.invalid"])
    monkeypatch.setitem(module.CITY_CONFIG, "sydney", {"tags": ["Sydney"], "queries": []})
    monkeypatch.setattr(module, "_mastodon_fetch_tag", lambda *args: [{"id": "https://other.invalid::1",
        "instance": "https://other.invalid", "source": "tag:Sydney", "replies_count": 1}])
    tokens = []
    def replies(session, instance, token, *args):
        tokens.append(token)
        return []
    monkeypatch.setattr(module, "_mastodon_fetch_context_replies", replies)
    now = datetime(2024, 1, 1, tzinfo=timezone.utc)
    assert len(module.harvest_mastodon_city("sydney", now, now, 10, "A", False, True)) == 1
    assert tokens == [""]


def test_repeated_mastodon_cursor_stops(load_fission_module, monkeypatch):
    module = load_fission_module("harvest_social")
    calls = []
    def response(*args, **kwargs):
        calls.append(kwargs["params"])
        return [{"id": "1", "created_at": "2024-01-02T00:00:00Z", "content": "Sunny"}]
    monkeypatch.setattr(module, "_request_json", response)
    monkeypatch.setattr(module.time, "sleep", lambda _: None)
    module._mastodon_fetch_tag(None, "https://example.invalid", "Sydney",
        datetime(2024, 1, 1, tzinfo=timezone.utc), datetime(2024, 1, 3, tzinfo=timezone.utc), 10, "sydney")
    assert len(calls) == 2


def test_archive_builder_preserves_previous_output_and_shell_permissions(tmp_path):
    root = Path(__file__).resolve().parents[3]
    spec = importlib.util.spec_from_file_location("archive_builder", root / "backend/fission/build_deploy_archives.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    stage = tmp_path / "stage"
    stage.mkdir()
    (stage / "main.py").write_text("def main(): return 'ok'", encoding="utf-8")
    (stage / "build.sh").write_text("#!/bin/sh\ntrue\n", encoding="utf-8")
    (stage / "bin").mkdir()
    (stage / "bin/normalizer.exe").write_bytes(b"host-specific launcher")
    target = tmp_path / "sample.zip"
    target.write_bytes(b"previous artifact")
    module.zip_stage(stage, target)
    previous = list(tmp_path.glob("sample-previous-*.zip"))
    assert len(previous) == 1 and previous[0].read_bytes() == b"previous artifact"
    with ZipFile(target) as archive:
        assert set(archive.namelist()) == {"main.py", "build.sh"}
        assert archive.getinfo("build.sh").external_attr >> 16 == 0o755


def test_weather_non_finite_values_are_json_null(load_fission_module):
    module = load_fission_module("harvest_weather")
    assert module._clean_value(float("nan")) is None
    assert module._clean_value(float("inf")) is None
    assert module._clean_value(float("-inf")) is None
    assert module._clean_value(0) == 0
