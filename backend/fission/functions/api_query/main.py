"""Fission function: single read-only API for the frontend notebook.

The notebook hits this one endpoint and asks for whatever it needs by query
string. Returns clean JSON — the notebook never talks to ES directly.

Endpoints (all GET):

    GET /api/query?mode=posts&city=sydney&size=100
        List up to `size` cleaned posts for a city, newest first.
        Optional filters: from=YYYY-MM-DD, to=YYYY-MM-DD, platform=reddit|bluesky|mastodon

    GET /api/query?mode=daily&city=sydney
        Daily aggregation: per-day post count, mean sentiment, mean tmax, mean prcp.
        Useful for time-series plots in the notebook.

    GET /api/query?mode=temp_buckets&city=sydney
        Sentiment by temperature bucket (cold/mild/warm/hot/extreme).
        Useful for boxplot / bar chart.

    GET /api/query?mode=summary
        Top-line summary across all cities: total posts, platforms,
        date range, sentiment distribution.

    GET /api/query?mode=health
        Connection check: returns the ES version and cluster name. No data.

Team: COMP90024 Team 2
"""

# COMP90024 Team 2

import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(__file__))

from elasticsearch import Elasticsearch
from flask import jsonify, request


def _setting(name, default=None):
    value = os.environ.get(name)
    if value and value.strip():
        return value.strip()
    for path in (
        f"/secrets/default/es-creds/{name}",
        f"/secrets/es-creds/{name}",
        f"/secrets/{name}",
    ):
        try:
            with open(path, "r", encoding="utf-8") as handle:
                value = handle.read().strip()
                if value:
                    return value
        except FileNotFoundError:
            pass
    if default is not None:
        return default
    raise RuntimeError(f"Missing required configuration: {name}")


def _es():
    return Elasticsearch(
        [_setting("ES_HOST")],
        basic_auth=(_setting("ES_USER", "elastic"),
                    _setting("ES_PASSWORD")),
        verify_certs=_setting("ES_VERIFY_CERTS", "true").lower() == "true",
        ca_certs=_setting("ES_CA_CERTS", "") or None,
        request_timeout=60,
    )


# ---------------------------------------------------------------------------
def _filters(city, frm, to, platform):
    must = []
    if city:     must.append({"term": {"city": city}})
    if platform: must.append({"term": {"platform": platform}})
    if frm or to:
        rng = {}
        if frm: rng["gte"] = frm
        if to:  rng["lte"] = to
        must.append({"range": {"date_local": rng}})
    return {"bool": {"must": must}} if must else {"match_all": {}}


def _mode_posts(es, args):
    size = min(int(args.get("size", 100)), 1000)
    if size < 1:
        raise ValueError("size must be a positive integer")
    q = _filters(args.get("city"), args.get("from"), args.get("to"),
                 args.get("platform"))
    res = es.search(
        index="posts_clean", size=size, query=q,
        sort=[{"created_utc": "desc"}],
        track_total_hits=True,
        _source_excludes=["text_raw"],
    )
    hits = [h["_source"] for h in res["hits"]["hits"]]
    return {"total": res["hits"]["total"]["value"], "rows": hits}


def _mode_daily(es, args):
    q = _filters(args.get("city"), args.get("from"), args.get("to"),
                 args.get("platform"))
    res = es.search(index="posts_clean", size=0, query=q, aggs={
        "by_day": {
            "date_histogram": {"field": "date_local", "calendar_interval": "day"},
            "aggs": {
                "sentiment": {"avg": {"field": "sentiment"}},
                "tmax":      {"avg": {"field": "tmax"}},
                "tmin":      {"avg": {"field": "tmin"}},
                "prcp":      {"avg": {"field": "prcp"}},
            },
        }
    })
    buckets = [{
        "date":  b["key_as_string"][:10],
        "count": b["doc_count"],
        "sentiment_mean": b["sentiment"]["value"],
        "tmax_mean":      b["tmax"]["value"],
        "tmin_mean":      b["tmin"]["value"],
        "prcp_mean":      b["prcp"]["value"],
    } for b in res["aggregations"]["by_day"]["buckets"]]
    return {"days": buckets}


def _mode_temp_buckets(es, args):
    q = _filters(args.get("city"), args.get("from"), args.get("to"),
                 args.get("platform"))
    res = es.search(index="posts_clean", size=0, query=q, aggs={
        "by_temp": {
            "range": {
                "field": "tmax",
                "ranges": [
                    {"key": "cold (<18)",       "to":   18},
                    {"key": "mild (18-24)",     "from": 18, "to": 24},
                    {"key": "warm (24-30)",     "from": 24, "to": 30},
                    {"key": "hot (30-35)",      "from": 30, "to": 35},
                    {"key": "extreme (>=35)",   "from": 35},
                ],
            },
            "aggs": {
                "sentiment": {"avg": {"field": "sentiment"}},
                "neg": {"filter": {"term": {"sentiment_label": "negative"}}},
                "neu": {"filter": {"term": {"sentiment_label": "neutral"}}},
                "pos": {"filter": {"term": {"sentiment_label": "positive"}}},
            },
        }
    })
    rows = [{
        "bucket":          b["key"],
        "count":           b["doc_count"],
        "sentiment_mean":  b["sentiment"]["value"],
        "negative_count":  b["neg"]["doc_count"],
        "neutral_count":   b["neu"]["doc_count"],
        "positive_count":  b["pos"]["doc_count"],
    } for b in res["aggregations"]["by_temp"]["buckets"]]
    return {"buckets": rows}


def _mode_summary(es, args):
    res = es.search(index="posts_clean", size=0, track_total_hits=True, aggs={
        "by_city":     {"terms": {"field": "city",     "size": 10}},
        "by_platform": {"terms": {"field": "platform", "size": 10}},
        "by_label":    {"terms": {"field": "sentiment_label", "size": 5}},
        "min_date":    {"min": {"field": "date_local"}},
        "max_date":    {"max": {"field": "date_local"}},
    })
    a = res["aggregations"]
    return {
        "total":     res["hits"]["total"]["value"],
        "by_city":     {b["key"]: b["doc_count"] for b in a["by_city"]["buckets"]},
        "by_platform": {b["key"]: b["doc_count"] for b in a["by_platform"]["buckets"]},
        "by_sentiment": {b["key"]: b["doc_count"] for b in a["by_label"]["buckets"]},
        "date_range":  [a["min_date"].get("value_as_string"), a["max_date"].get("value_as_string")],
    }


def _mode_health(es, args):
    info = es.info()
    return {
        "es_version":  info["version"]["number"],
        "cluster":     info["cluster_name"],
        "status":      "ok",
    }


MODES = {
    "posts":         _mode_posts,
    "daily":         _mode_daily,
    "temp_buckets":  _mode_temp_buckets,
    "summary":       _mode_summary,
    "health":        _mode_health,
}


# ---------------------------------------------------------------------------
def main():
    args = request.args
    mode = args.get("mode", "summary")
    if mode not in MODES:
        return jsonify({"error": f"unknown mode '{mode}'",
                        "modes": list(MODES)}), 400
    try:
        for key in ("from", "to"):
            if args.get(key):
                date.fromisoformat(args[key])
        if args.get("from") and args.get("to") and args["from"] > args["to"]:
            raise ValueError("from must not be later than to")
        if mode == "posts" and int(args.get("size", 100)) < 1:
            raise ValueError("size must be a positive integer")
    except ValueError as exc:
        return jsonify({"error": str(exc), "mode": mode}), 400
    try:
        es = _es()
        result = MODES[mode](es, args)
        return jsonify({"mode": mode, **result}), 200
    except Exception as e:
        return jsonify({"error": str(e), "mode": mode}), 500
