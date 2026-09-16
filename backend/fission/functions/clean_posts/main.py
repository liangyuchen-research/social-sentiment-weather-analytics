"""Fission function: read posts_raw, clean + sentiment + weather join,
write to posts_clean.

HTTP trigger:
    POST /ingest/clean-posts?city=sydney&batch=2000

Pulls up to `batch` unprocessed records (where ES doesn't yet have them
in posts_clean), runs the same cleaning steps as cleaning/clean_pipeline.py,
and bulk-indexes them to posts_clean.

This is the ELT step in the cloud pipeline:
    posts_raw  --[clean_posts]-->  posts_clean

Team: COMP90024 Team 2
"""

# COMP90024 Team 2

import os
import re
import sys
from datetime import datetime, timezone
from itertools import islice

sys.path.insert(0, os.path.dirname(__file__))

from elasticsearch import Elasticsearch, helpers
from elasticsearch.helpers import scan
from flask import jsonify, request

URL_RE     = re.compile(r"https?://\S+|www\.\S+")
MENTION_RE = re.compile(r"@[\w\.\-]+")
MULTI_WS   = re.compile(r"\s+")

CITY_TZ = {
    "sydney":    "Australia/Sydney",
    "melbourne": "Australia/Melbourne",
    "brisbane":  "Australia/Brisbane",
}


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
        request_timeout=120,
    )


def _normalize_text(s):
    if not isinstance(s, str):
        return ""
    s = URL_RE.sub(" ", s)
    s = MENTION_RE.sub(" ", s)
    s = MULTI_WS.sub(" ", s).strip()
    return s


def _detect_lang(s):
    if not s or len(s) < 10:
        return "unknown"
    try:
        from langdetect import detect, DetectorFactory
        DetectorFactory.seed = 42
        return detect(s)
    except Exception:
        return "unknown"


def _sentiment(s, vader):
    return vader.polarity_scores(s or "")["compound"]


def _label(score):
    if score >= 0.05:  return "positive"
    if score <= -0.05: return "negative"
    return "neutral"


def _weather_for(es, city, date_str):
    """Look up daily weather for city + ISO date. Cached per call."""
    doc_id = f"{city}:{date_str}"
    try:
        res = es.get(index="weather_daily", id=doc_id)
        return res.get("_source", {})
    except Exception as exc:
        if getattr(exc, "status_code", None) != 404:
            raise
        res = es.search(index="weather_daily", size=1, query={
            "bool": {"must": [
                {"term": {"city": city}},
                {"term": {"date": date_str}},
            ]}
        }, _source=["city", "station", "bom_station_id", "date",
                    "tavg", "tmin", "tmax", "prcp", "snow", "wdir",
                    "wspd", "wpgt", "pres", "tsun"])
        hits = res["hits"]["hits"]
        return hits[0]["_source"] if hits else {}


def _existing_clean_ids(es, ids):
    if not ids:
        return set()
    try:
        res = es.mget(index="posts_clean", ids=ids, source=False)
    except Exception as exc:
        if getattr(exc, "status_code", None) == 404:
            return set()
        raise
    return {doc["_id"] for doc in res.get("docs", []) if doc.get("found")}


def _clean_city(es, city, batch, vader, require_weather=True):
    query = {"bool": {"must": [{"term": {"city": city}}]}}

    # Scan in bounded chunks. A fixed prefix would strand new records after
    # that prefix has already been cleaned by earlier invocations.
    raw_docs = scan(es, index="posts_raw", query={"query": query}, size=500)
    scanned = 0

    # Cache weather per (city, date)
    weather_cache = {}
    actions = []
    skipped_lang = 0
    skipped_existing = 0
    skipped_missing_weather = 0

    import zoneinfo
    tz = zoneinfo.ZoneInfo(CITY_TZ[city])

    def pending_hits():
        nonlocal scanned, skipped_existing
        while True:
            chunk = list(islice(raw_docs, 500))
            if not chunk:
                return
            existing_ids = _existing_clean_ids(es, [hit["_id"] for hit in chunk])
            for hit in chunk:
                scanned += 1
                if hit["_id"] in existing_ids:
                    skipped_existing += 1
                else:
                    yield hit

    pending = pending_hits()
    try:
        for hit in pending:
            src = hit["_source"]
            text_raw = ((src.get("title") or "") + "\n" + (src.get("text") or "")).strip() \
                       if src.get("kind") == "post" and "title" in src else \
                       src.get("text", "")
            text = _normalize_text(text_raw)
            if len(text) < 5:
                continue
            lang = _detect_lang(text)
            if lang != "en":
                skipped_lang += 1
                continue

            # Time handling
            try:
                dt_utc = datetime.fromisoformat(src["created_at"].replace("Z", "+00:00"))
                if dt_utc.tzinfo is None:
                    dt_utc = dt_utc.replace(tzinfo=timezone.utc)
            except Exception:
                continue
            dt_local = dt_utc.astimezone(tz)
            date_str = dt_local.strftime("%Y-%m-%d")

            # Weather lookup (cached)
            if date_str not in weather_cache:
                weather_cache[date_str] = _weather_for(es, city, date_str)
            w = weather_cache[date_str]
            if require_weather and not w:
                skipped_missing_weather += 1
                continue

            sent = _sentiment(text, vader)
            rec = {
                "platform":   src.get("platform"),
                "city":       city,
                "id":         src.get("id"),
                "author":     src.get("author"),
                "text_raw":   text_raw,
                "text":       text,
                "created_utc":   dt_utc.isoformat(),
                "created_local": dt_local.replace(tzinfo=None).isoformat(),
                "date_local": date_str,
                "year":       dt_local.year,
                "lang":       lang,
                "engagement": (src.get("score") or 0) + (src.get("num_comments") or 0)
                              if src.get("platform") == "reddit" else
                              (src.get("like_count") or 0) + (src.get("favourites_count") or 0),
                "sentiment":       sent,
                "sentiment_label": _label(sent),
                "weather_joined": bool(w),
                "weather_date": w.get("date") or date_str if w else None,
                "weather_station": w.get("station"),
                "bom_station_id": w.get("bom_station_id"),
                "tavg": w.get("tavg"), "tmin": w.get("tmin"), "tmax": w.get("tmax"),
                "prcp": w.get("prcp"), "snow": w.get("snow"), "wdir": w.get("wdir"),
                "wspd": w.get("wspd"), "wpgt": w.get("wpgt"),
                "pres": w.get("pres"), "tsun": w.get("tsun"),
                "url":  src.get("url"),
                "cleaned_at": datetime.now(tz=timezone.utc).isoformat(),
            }
            actions.append({
                "_op_type": "index",
                "_index":   "posts_clean",
                "_id":      hit["_id"],
                "_source":  rec,
            })
            if len(actions) >= batch:
                break
    finally:
        pending.close()
        close = getattr(raw_docs, "close", None)
        if close:
            close()

    if not actions:
        return {
            "processed": 0,
            "scanned": scanned,
            "skipped_existing": skipped_existing,
            "skipped_non_english": skipped_lang,
            "skipped_missing_weather": skipped_missing_weather,
            "weather_cache_size": len(weather_cache),
        }

    success, errors = helpers.bulk(es, actions, raise_on_error=False)
    err_n = len(errors) if isinstance(errors, list) else errors

    return {
        "processed": success,
        "scanned": scanned,
        "errors":    err_n,
        "skipped_existing": skipped_existing,
        "skipped_non_english": skipped_lang,
        "skipped_missing_weather": skipped_missing_weather,
        "weather_cache_size":  len(weather_cache),
    }


def _requested_cities(args):
    raw = args.get("cities") or args.get("city")
    if not raw or raw.lower() == "all":
        return list(CITY_TZ)
    cities = [c.strip().lower() for c in raw.split(",") if c.strip()]
    bad = [c for c in cities if c not in CITY_TZ]
    if bad:
        raise ValueError(f"unknown cities {bad}; choices={list(CITY_TZ)}")
    return cities


def main():
    args = request.args
    require_weather = args.get("require_weather", "true").lower() not in {"0", "false", "no"}

    try:
        batch = int(args.get("batch", "2000"))
        if batch < 1:
            raise ValueError("batch must be a positive integer")
        cities = _requested_cities(args)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    es = _es()
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
    vader = SentimentIntensityAnalyzer()

    results = {}
    for city in cities:
        results[city] = _clean_city(es, city, batch, vader,
                                    require_weather=require_weather)

    return jsonify({
        "cities": cities,
        "batch_per_city": batch,
        "require_weather": require_weather,
        "processed_total": sum(v.get("processed", 0) for v in results.values()),
        "results": results,
    }), 200
