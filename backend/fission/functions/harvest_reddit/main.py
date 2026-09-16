"""Fission function: harvest Reddit via Arctic Shift API and bulk-index to ES.

HTTP trigger:
    POST /ingest/harvest-reddit?city=sydney&year=2025&max_records=500

Response: JSON {"city": ..., "year": ..., "indexed": N}

Env vars (from K8s Secret `es-creds`):
    ES_HOST, ES_USER, ES_PASSWORD

Team: COMP90024 Team 2
"""

# COMP90024 Team 2

import os
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))

import requests
from elasticsearch import Elasticsearch, helpers
from flask import current_app, jsonify, request

ARCTIC_BASE = "https://arctic-shift.photon-reddit.com/api"
HEADERS     = {"User-Agent": "CCC-Fission-Reddit/0.1"}

CITY_SUBREDDITS = {
    "sydney":    ["sydney"],
    "melbourne": ["melbourne"],
    "brisbane":  ["brisbane"],
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
        request_timeout=60,
    )


def _fetch_page(kind, sub, after, before, limit=100):
    url = f"{ARCTIC_BASE}/{kind}/search"
    params = {"subreddit": sub, "after": after, "before": before, "limit": limit, "sort": "asc"}
    r = requests.get(url, params=params, headers=HEADERS, timeout=30)
    r.raise_for_status()
    payload = r.json()
    return payload.get("data", payload) if isinstance(payload, dict) else (payload or [])


def _to_unified(item, city, kind):
    is_comment = kind == "comments"
    text = item.get("body") if is_comment else \
           ((item.get("title") or "") + "\n" + (item.get("selftext") or "")).strip()
    permalink = item.get("permalink") or ""
    if permalink and not permalink.startswith("http"):
        permalink = f"https://reddit.com{permalink}"
    created = item.get("created_utc")
    if isinstance(created, (int, float)):
        created_iso = datetime.fromtimestamp(int(created), tz=timezone.utc).isoformat()
    else:
        created_iso = created
    return {
        "platform":     "reddit",
        "city":         city,
        "kind":         "comment" if is_comment else "post",
        "id":           item.get("id"),
        "subreddit":    item.get("subreddit"),
        "author":       item.get("author") or "[deleted]",
        "text":         text,
        "score":        item.get("score") or 0,
        "num_comments": item.get("num_comments") or 0,
        "created_at":   created_iso,
        "url":          permalink,
        "harvested_at": datetime.now(tz=timezone.utc).isoformat(),
    }


def main():
    """Fission entry point. Returns Flask Response.

    Two modes:
      ?mode=year&year=2025          — backfill an entire year (manual / one-shot)
      ?mode=incremental&hours=1     — harvest last N hours (default for timer triggers)

    For timer-triggered runs we don't pass any query params, so it falls into
    `incremental` mode and harvests the last hour. ES de-dupes via `_id`.
    """
    args = request.args
    city = args.get("city")               # None means "all 3 cities"
    mode = args.get("mode", "incremental")
    try:
        max_records = int(args.get("max_records", "500"))
        if max_records < 1:
            raise ValueError("max_records must be a positive integer")
        if mode not in {"year", "incremental"}:
            raise ValueError("mode must be year or incremental")
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    include_comments = args.get("include_comments", "false").lower() == "true"

    cities = [city] if city else list(CITY_SUBREDDITS.keys())
    bad = [c for c in cities if c not in CITY_SUBREDDITS]
    if bad:
        return jsonify({"error": f"unknown cities {bad}",
                        "choices": list(CITY_SUBREDDITS)}), 400

    try:
        if mode == "year":
            year = int(args.get("year", datetime.now(tz=timezone.utc).year))
            after  = int(datetime(year, 1, 1, tzinfo=timezone.utc).timestamp())
            before = int(datetime(year, 12, 31, 23, 59, 59, tzinfo=timezone.utc).timestamp())
        else:  # incremental — last N hours
            hours = int(args.get("hours", "1"))
            if hours < 1:
                raise ValueError("hours must be a positive integer")
            now = datetime.now(tz=timezone.utc)
            before = int(now.timestamp())
            after  = before - hours * 3600
    except (ValueError, OverflowError) as exc:
        return jsonify({"error": str(exc)}), 400

    es = _es()
    actions = []
    seen = set()
    kinds = ["posts", "comments"] if include_comments else ["posts"]
    per_city_count = {}

    for c in cities:
        fetched = 0
        for sub in CITY_SUBREDDITS[c]:
            for kind in kinds:
                cursor = after
                while fetched < max_records:
                    try:
                        batch = _fetch_page(kind, sub, cursor, before)
                    except Exception as e:
                        current_app.logger.warning(f"[harvest_reddit] r/{sub}/{kind}: {e}")
                        break
                    if not batch:
                        break
                    for item in batch:
                        rec = _to_unified(item, c, kind)
                        if not rec["id"] or rec["id"] in seen:
                            continue
                        seen.add(rec["id"])
                        actions.append({
                            "_op_type": "index",
                            "_index":   "posts_raw",
                            "_id":      f"reddit:{rec['id']}",
                            "_source":  rec,
                        })
                        fetched += 1
                        if fetched >= max_records:
                            break
                    last_ts = batch[-1].get("created_utc")
                    if last_ts is None or int(last_ts) >= before:
                        break
                    next_cursor = int(last_ts) + 1
                    if next_cursor <= cursor:
                        break
                    cursor = next_cursor
                    time.sleep(0.4)
                if fetched >= max_records:
                    break
            if fetched >= max_records:
                break
        per_city_count[c] = fetched

    if not actions:
        return jsonify({"mode": mode, "cities": cities,
                        "window": [after, before],
                        "indexed": 0,
                        "message": "no records fetched"}), 200

    success, errors = helpers.bulk(es, actions, raise_on_error=False,
                                    ca_certs=_setting("ES_CA_CERTS", "") or None,
        request_timeout=120)
    err_n = len(errors) if isinstance(errors, list) else errors

    return jsonify({
        "mode": mode, "cities": cities,
        "window_unix": [after, before],
        "per_city": per_city_count,
        "indexed_total": success,
        "errors": err_n,
        "include_comments": include_comments,
    }), 200
