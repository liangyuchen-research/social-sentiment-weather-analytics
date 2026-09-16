"""Fission function: harvest Reddit, BlueSky, and Mastodon into posts_raw.

Default timer mode:
    POST /ingest/harvest-social

This harvests the last two hours for all configured cities and platforms,
including comments/replies by default, then bulk-indexes a shared raw schema
into Elasticsearch. ES de-dupes by _id:
    <platform>:<source_id>
"""

# COMP90024 Team 2

import os
import math
from html import unescape
import re
import sys
import time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(__file__))

import requests
from elasticsearch import Elasticsearch, helpers
from flask import current_app, jsonify, request


CITY_CONFIG = {
    "sydney": {
        "queries": [
            "Sydney Australia", "Sydney NSW", "Sydney CBD", "Sydney weather",
            "Bondi Beach", "Manly Beach", "Parramatta", "Sydney Opera House",
            "Sydney Harbour", "#Sydney", "#SydneyAustralia",
        ],
        "tags": [
            "Sydney", "SydneyAustralia", "SydneyAU", "Bondi",
            "SydneyHarbour", "SydneyCBD", "NSW", "NSWweather",
        ],
        "subreddits": ["sydney"],
    },
    "melbourne": {
        "queries": [
            "Melbourne Australia", "Melbourne VIC", "Melbourne CBD",
            "Melbourne weather", "St Kilda Melbourne", "Brunswick Melbourne",
            "Fitzroy Melbourne", "South Yarra", "Melbourne Park",
            "#Melbourne", "#MelbourneAustralia",
        ],
        "tags": [
            "Melbourne", "MelbourneAustralia", "MelbourneAU",
            "MelbCBD", "Victoria", "VICweather", "MelbourneWeather",
        ],
        "subreddits": ["melbourne"],
    },
    "brisbane": {
        "queries": [
            "Brisbane Australia", "Brisbane QLD", "Brisbane CBD",
            "Brisbane weather", "BrisVegas", "Brisbane River",
            "Fortitude Valley", "South Brisbane", "Queen Street Brisbane",
            "#Brisbane", "#BrisbaneAustralia",
        ],
        "tags": [
            "Brisbane", "BrisbaneAustralia", "BrisbaneAU",
            "BrisVegas", "Queensland", "QLDweather", "BrisbaneRiver",
        ],
        "subreddits": ["brisbane"],
    },
}

PLATFORMS = ("reddit", "bluesky", "mastodon")
MASTODON_INSTANCES = [
    "https://aus.social",
    "https://mastodon.au",
    "https://mastodon.social",
]

ARCTIC_BASE = "https://arctic-shift.photon-reddit.com/api"
HTML_TAG = re.compile(r"<[^>]+>")


def _setting(name, default=None):
    value = os.environ.get(name)
    if value and value.strip():
        return value.strip()
    for secret_name in ("es-creds", "social-creds"):
        for path in (
            f"/secrets/default/{secret_name}/{name}",
            f"/secrets/{secret_name}/{name}",
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


def _bsky_service():
    return _setting("BLUESKY_SERVICE", "https://bsky.social").rstrip("/")


def _bsky_appview():
    return _setting("BLUESKY_APPVIEW", "https://public.api.bsky.app").rstrip("/")


def _bool_arg(args, name, default=False):
    raw = args.get(name)
    if raw is None:
        return default
    return raw.lower() in {"1", "true", "yes", "y", "on"}


def _split_choices(raw, choices):
    if not raw:
        return list(choices)
    vals = [v.strip().lower() for v in raw.split(",") if v.strip()]
    bad = [v for v in vals if v not in choices]
    if bad:
        raise ValueError("unknown values %s; choices=%s" % (bad, list(choices)))
    return vals


def _utc_now():
    return datetime.now(tz=timezone.utc)


def _iso_z(dt):
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_dt(value):
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _in_window(value, start_dt, end_dt):
    dt = _parse_dt(value)
    return dt is not None and start_dt <= dt <= end_dt


def _window_from_args(args):
    mode = args.get("mode", "incremental").lower()
    now = _utc_now()
    if mode == "year":
        year = int(args.get("year", now.year))
        start_dt = datetime(year, 1, 1, tzinfo=timezone.utc)
        end_dt = datetime(year, 12, 31, 23, 59, 59, tzinfo=timezone.utc)
    elif mode == "incremental":
        # Default 2-hour window so we always overlap with the previous timer
        # run. Stable document IDs make repeated writes idempotent.
        # Override with ?hours=N for ad-hoc backfills (e.g. ?hours=24).
        hours = float(args.get("hours", "2"))
        if not math.isfinite(hours) or hours <= 0:
            raise ValueError("hours must be a positive finite number")
        end_dt = now
        start_dt = end_dt - timedelta(hours=hours)
    else:
        raise ValueError("mode must be incremental or year")
    return mode, start_dt, end_dt


def _strip_html(value):
    return unescape(HTML_TAG.sub(" ", value or "")).strip()


def _request_json(session, method, url, **kwargs):
    last_err = None
    for attempt in range(3):
        try:
            resp = session.request(method, url, timeout=30, **kwargs)
        except requests.exceptions.RequestException as exc:
            last_err = exc
            time.sleep(min(2 ** attempt, 5))
            continue

        if resp.status_code == 429:
            retry_after = resp.headers.get("Retry-After")
            try:
                wait = int(retry_after) if retry_after else 5 * (attempt + 1)
            except ValueError:
                wait = 5 * (attempt + 1)
            last_err = "HTTP 429 (rate limited)"
            time.sleep(max(0, min(wait, 60)))
            continue

        if 500 <= resp.status_code < 600:
            last_err = "HTTP %s" % resp.status_code
            time.sleep(min(2 ** attempt, 5))
            continue

        resp.raise_for_status()
        return resp.json()

    raise RuntimeError("request failed after retries: %s" % last_err)


# ---------------------------------------------------------------------------
# Reddit
def _reddit_fetch_page(session, kind, subreddit, after_ts, before_ts):
    payload = _request_json(
        session,
        "GET",
        "%s/%s/search" % (ARCTIC_BASE, kind),
        params={
            "subreddit": subreddit,
            "after": after_ts,
            "before": before_ts,
            "limit": 100,
        },
    )
    return payload.get("data", payload) if isinstance(payload, dict) else (payload or [])


def _reddit_to_raw(item, city, kind):
    is_comment = kind == "comments"
    text = item.get("body") if is_comment else (
        ((item.get("title") or "") + "\n" + (item.get("selftext") or "")).strip()
    )
    permalink = item.get("permalink") or ""
    if permalink and not permalink.startswith("http"):
        permalink = "https://reddit.com%s" % permalink
    created = item.get("created_utc")
    created_iso = None
    if isinstance(created, (int, float)):
        created_iso = datetime.fromtimestamp(int(created), tz=timezone.utc).isoformat()
    elif isinstance(created, str):
        created_iso = created
    return {
        "platform": "reddit",
        "city": city,
        "kind": "comment" if is_comment else "post",
        "id": item.get("id"),
        "subreddit": item.get("subreddit"),
        "author": item.get("author") or "[deleted]",
        "text": text or "",
        "score": item.get("score") or 0,
        "num_comments": item.get("num_comments") or 0,
        "created_at": created_iso,
        "url": permalink,
        "parent_post_id": (item.get("link_id") or "").replace("t3_", "") or None,
    }


def harvest_reddit_city(city, start_dt, end_dt, max_records, include_comments):
    start_ts = int(start_dt.timestamp())
    end_ts = int(end_dt.timestamp())
    session = requests.Session()
    session.headers.update({"User-Agent": "CCC-Fission-Social/0.1"})
    records = []
    seen = set()
    kinds = ["posts", "comments"] if include_comments else ["posts"]

    try:
        for subreddit in CITY_CONFIG[city]["subreddits"]:
            for kind in kinds:
                cursor_before = end_ts
                while cursor_before > start_ts and len(records) < max_records:
                    batch = _reddit_fetch_page(session, kind, subreddit, start_ts, cursor_before)
                    if not batch:
                        break
                    oldest_ts = None
                    yielded = 0
                    for item in batch:
                        created = item.get("created_utc")
                        if created is None:
                            continue
                        created_ts = int(float(created))
                        if created_ts < start_ts or created_ts > cursor_before:
                            continue
                        oldest_ts = created_ts if oldest_ts is None else min(oldest_ts, created_ts)
                        rec = _reddit_to_raw(item, city, kind)
                        if not rec["id"] or rec["id"] in seen:
                            continue
                        seen.add(rec["id"])
                        records.append(rec)
                        yielded += 1
                        if len(records) >= max_records:
                            break
                    if yielded == 0 or oldest_ts is None or oldest_ts <= start_ts:
                        break
                    cursor_before = oldest_ts - 1
                    time.sleep(0.2)
                if len(records) >= max_records:
                    break
            if len(records) >= max_records:
                break
    finally:
        session.close()
    return records


# ---------------------------------------------------------------------------
# BlueSky
def _bsky_session():
    handle = _setting("BLUESKY_HANDLE", "")
    password = _setting("BLUESKY_APP_PASSWORD", "")
    if not handle or not password:
        raise RuntimeError("missing BLUESKY_HANDLE / BLUESKY_APP_PASSWORD")

    session = requests.Session()
    payload = _request_json(
        session,
        "POST",
        "%s/xrpc/com.atproto.server.createSession" % _bsky_service(),
        json={"identifier": handle, "password": password},
    )
    token = payload.get("accessJwt")
    if not token:
        raise RuntimeError("BlueSky login did not return accessJwt")
    session.headers.update({"Authorization": "Bearer %s" % token})
    return session


def _bsky_reply_uris(record):
    reply = record.get("reply") or {}
    parent = reply.get("parent") or {}
    root = reply.get("root") or {}
    return parent.get("uri"), root.get("uri")


def _bsky_post_to_raw(post, city, query, kind=None):
    record = post.get("record") or {}
    author = post.get("author") or {}
    parent_uri, root_uri = _bsky_reply_uris(record)
    if kind is None:
        kind = "reply" if parent_uri else "post"
    uri = post.get("uri")
    handle = author.get("handle")
    post_key = uri.split("/")[-1] if uri else None
    url = "https://bsky.app/profile/%s/post/%s" % (handle, post_key) if handle and post_key else None
    return {
        "platform": "bluesky",
        "city": city,
        "matched_query": query,
        "kind": kind,
        "id": uri,
        "cid": post.get("cid"),
        "author": handle,
        "author_handle": handle,
        "author_did": author.get("did"),
        "text": record.get("text") or "",
        "lang": record.get("langs") or [],
        "reply_count": post.get("replyCount") or 0,
        "repost_count": post.get("repostCount") or 0,
        "like_count": post.get("likeCount") or 0,
        "created_at": record.get("createdAt") or post.get("indexedAt"),
        "url": url,
        "parent_post_id": parent_uri,
        "root_post_id": root_uri,
    }


def _bsky_walk_replies(node):
    for child in node.get("replies") or []:
        post = child.get("post")
        if post:
            yield post
        for nested in _bsky_walk_replies(child):
            yield nested


def _bsky_fetch_replies(session, root_uri, city, query, start_dt, end_dt):
    payload = _request_json(
        session,
        "GET",
        "%s/xrpc/app.bsky.feed.getPostThread" % _bsky_appview(),
        params={"uri": root_uri, "depth": 6, "parentHeight": 0},
    )
    thread = payload.get("thread") or {}
    out = []
    for post in _bsky_walk_replies(thread):
        rec = _bsky_post_to_raw(post, city, query, kind="reply")
        if _in_window(rec.get("created_at"), start_dt, end_dt):
            out.append(rec)
    return out


def harvest_bluesky_city(city, start_dt, end_dt, max_records, include_replies):
    session = _bsky_session()
    records = []
    seen = set()
    since_iso = _iso_z(start_dt)
    until_iso = _iso_z(end_dt)
    try:
        for query in CITY_CONFIG[city]["queries"]:
            cursor = None
            while len(records) < max_records:
                params = {
                    "q": query,
                    "since": since_iso,
                    "until": until_iso,
                    "sort": "latest",
                    "limit": 100,
                }
                if cursor:
                    params["cursor"] = cursor
                payload = _request_json(
                    session,
                    "GET",
                    "%s/xrpc/app.bsky.feed.searchPosts" % _bsky_appview(),
                    params=params,
                )
                posts = payload.get("posts") or []
                if not posts:
                    break
                for post in posts:
                    rec = _bsky_post_to_raw(post, city, query)
                    if not rec["id"] or rec["id"] in seen:
                        continue
                    if not _in_window(rec.get("created_at"), start_dt, end_dt):
                        continue
                    seen.add(rec["id"])
                    records.append(rec)
                    if include_replies and rec.get("reply_count"):
                        for reply in _bsky_fetch_replies(session, rec["id"], city, query, start_dt, end_dt):
                            if len(records) >= max_records:
                                break
                            if not reply["id"] or reply["id"] in seen:
                                continue
                            seen.add(reply["id"])
                            records.append(reply)
                    if len(records) >= max_records:
                        break
                next_cursor = payload.get("cursor")
                if not next_cursor or next_cursor == cursor:
                    break
                cursor = next_cursor
                if not cursor:
                    break
                time.sleep(0.2)
            if len(records) >= max_records:
                break
    finally:
        session.close()
    return records


# ---------------------------------------------------------------------------
# Mastodon
def _mastodon_composite_id(instance, status_id):
    if not status_id:
        return None
    return "%s::%s" % (instance, status_id)


def _mastodon_status_to_raw(status, instance, city, source, kind=None, root_status_id=None):
    account = status.get("account") or {}
    parent_id = _mastodon_composite_id(instance, status.get("in_reply_to_id"))
    if kind is None:
        kind = "reply" if parent_id else "status"
    return {
        "platform": "mastodon",
        "city": city,
        "instance": instance,
        "source": source,
        "kind": kind,
        "id": _mastodon_composite_id(instance, status.get("id")),
        "author": account.get("acct"),
        "author_display": account.get("display_name"),
        "text": _strip_html(status.get("content", "")),
        "lang": status.get("language"),
        "reblogs_count": status.get("reblogs_count") or 0,
        "favourites_count": status.get("favourites_count") or 0,
        "replies_count": status.get("replies_count") or 0,
        "created_at": status.get("created_at"),
        "url": status.get("url"),
        "tags": [tag.get("name") for tag in status.get("tags", [])],
        "parent_status_id": parent_id,
        "root_status_id": (
            _mastodon_composite_id(instance, root_status_id)
            or _mastodon_composite_id(instance, status.get("id"))
        ),
    }


def _mastodon_terms(city):
    out = []
    seen = set()
    cfg = CITY_CONFIG[city]
    for term in ["#%s" % tag for tag in cfg["tags"]] + list(cfg["queries"]):
        key = term.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(term)
    return out


def _mastodon_instances(primary):
    out = []
    seen = set()
    for inst in [primary] + [i for i in MASTODON_INSTANCES if i != primary]:
        if inst in seen:
            continue
        seen.add(inst)
        out.append(inst)
    return out


def _mastodon_fetch_search(session, instance, token, query, start_dt, end_dt, cap, city):
    headers = {"Authorization": "Bearer %s" % token}
    params = {"q": query, "type": "statuses", "resolve": "false", "limit": 40}
    url = "%s/api/v2/search" % instance
    out = []
    while len(out) < cap:
        try:
            payload = _request_json(session, "GET", url, headers=headers, params=params)
        except requests.exceptions.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else None
            current_app.logger.warning("[harvest_social] mastodon search %s HTTP %s", query, status)
            break
        statuses = payload.get("statuses") or []
        if not statuses:
            break
        oldest_dt = None
        for status in statuses:
            created_dt = _parse_dt(status.get("created_at"))
            if created_dt is None:
                continue
            oldest_dt = created_dt if oldest_dt is None else min(oldest_dt, created_dt)
            if start_dt <= created_dt <= end_dt:
                out.append(_mastodon_status_to_raw(status, instance, city, "search:%s" % query))
                if len(out) >= cap:
                    break
        if oldest_dt is None or oldest_dt < start_dt:
            break
        next_id = statuses[-1].get("id")
        if not next_id or next_id == params.get("max_id"):
            break
        params = dict(params)
        params["max_id"] = next_id
        time.sleep(0.1)
    return out


def _mastodon_fetch_tag(session, instance, tag, start_dt, end_dt, cap, city):
    params = {"limit": 40}
    url = "%s/api/v1/timelines/tag/%s" % (instance, tag)
    out = []
    while len(out) < cap:
        try:
            payload = _request_json(session, "GET", url, params=params)
        except requests.exceptions.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else None
            if status != 404:
                current_app.logger.warning("[harvest_social] mastodon tag %s/%s HTTP %s",
                                           instance, tag, status)
            break
        if not payload:
            break
        oldest_dt = None
        for status in payload:
            created_dt = _parse_dt(status.get("created_at"))
            if created_dt is None:
                continue
            oldest_dt = created_dt if oldest_dt is None else min(oldest_dt, created_dt)
            if start_dt <= created_dt <= end_dt:
                out.append(_mastodon_status_to_raw(status, instance, city, "tag:%s" % tag))
                if len(out) >= cap:
                    break
        if oldest_dt is None or oldest_dt < start_dt:
            break
        next_id = payload[-1].get("id")
        if not next_id or next_id == params.get("max_id"):
            break
        params = {"limit": 40, "max_id": next_id}
        time.sleep(0.1)
    return out


def _mastodon_fetch_context_replies(session, instance, token, status_id, city, source, start_dt, end_dt):
    headers = {"Authorization": "Bearer %s" % token} if token else None
    try:
        payload = _request_json(
            session,
            "GET",
            "%s/api/v1/statuses/%s/context" % (instance, status_id),
            headers=headers,
        )
    except requests.exceptions.HTTPError:
        return []
    out = []
    for reply in payload.get("descendants", []) or []:
        if _in_window(reply.get("created_at"), start_dt, end_dt):
            out.append(_mastodon_status_to_raw(reply, instance, city, "context:%s" % source,
                                               kind="reply", root_status_id=status_id))
    return out


def harvest_mastodon_city(city, start_dt, end_dt, max_records, mode,
                          include_tags_after_search, include_replies):
    token = _setting("MASTODON_ACCESS_TOKEN", "")
    primary = _setting("MASTODON_INSTANCE", "https://aus.social")
    if mode == "auto":
        mode = "B" if token else "A"
    if mode == "B" and not token:
        raise RuntimeError("mastodon mode B requires MASTODON_ACCESS_TOKEN")

    session = requests.Session()
    session.headers.update({"User-Agent": "CCC-Fission-Social/0.1"})
    records = []
    seen = set()

    def add_statuses(statuses):
        for rec in statuses:
            if len(records) >= max_records:
                break
            if not rec["id"] or rec["id"] in seen:
                continue
            seen.add(rec["id"])
            records.append(rec)
            if include_replies and rec.get("replies_count"):
                raw_id = rec["id"].split("::", 1)[1]
                for reply in _mastodon_fetch_context_replies(
                    session, rec["instance"], token if rec["instance"] == primary else "",
                    raw_id, city, rec["source"], start_dt, end_dt
                ):
                    if len(records) >= max_records:
                        break
                    if not reply["id"] or reply["id"] in seen:
                        continue
                    seen.add(reply["id"])
                    records.append(reply)

    try:
        if mode == "B":
            for term in _mastodon_terms(city):
                if len(records) >= max_records:
                    break
                statuses = _mastodon_fetch_search(
                    session, primary, token, term, start_dt, end_dt,
                    max_records - len(records), city,
                )
                add_statuses(statuses)

            if (include_tags_after_search or not records) and len(records) < max_records:
                for tag in CITY_CONFIG[city]["tags"]:
                    if len(records) >= max_records:
                        break
                    statuses = _mastodon_fetch_tag(
                        session, primary, tag, start_dt, end_dt,
                        max_records - len(records), city,
                    )
                    add_statuses(statuses)
        else:
            for instance in _mastodon_instances(primary):
                if len(records) >= max_records:
                    break
                for tag in CITY_CONFIG[city]["tags"]:
                    if len(records) >= max_records:
                        break
                    statuses = _mastodon_fetch_tag(
                        session, instance, tag, start_dt, end_dt,
                        max_records - len(records), city,
                    )
                    add_statuses(statuses)
    finally:
        session.close()

    return records


# ---------------------------------------------------------------------------
def _bulk_index_raw(es, records):
    harvested_at = _utc_now().isoformat()
    actions = []
    seen_ids = set()
    for rec in records:
        platform = rec.get("platform")
        source_id = rec.get("id")
        if not platform or not source_id:
            continue
        doc_id = "%s:%s" % (platform, source_id)
        if doc_id in seen_ids:
            continue
        seen_ids.add(doc_id)
        rec["harvested_at"] = harvested_at
        actions.append({
            "_op_type": "index",
            "_index": "posts_raw",
            "_id": doc_id,
            "_source": rec,
        })
    if not actions:
        return 0, 0
    success, errors = helpers.bulk(es, actions, raise_on_error=False, request_timeout=180)
    return success, len(errors) if isinstance(errors, list) else errors


def main():
    args = request.args
    try:
        platforms = _split_choices(args.get("platforms") or args.get("platform"), PLATFORMS)
        cities = _split_choices(args.get("cities") or args.get("city"), CITY_CONFIG.keys())
        mode, start_dt, end_dt = _window_from_args(args)
        max_records = int(args.get("max_records", _setting("HARVEST_MAX_RECORDS", "100")))
        if max_records < 1:
            raise ValueError("max_records must be a positive integer")
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400

    include_comments = _bool_arg(args, "include_comments", True)
    include_replies = _bool_arg(args, "include_replies", True)
    mastodon_mode = args.get("mastodon_mode", _setting("MASTODON_MODE", "auto"))
    if mastodon_mode not in {"auto", "A", "B"}:
        return jsonify({"error": "mastodon_mode must be auto, A, or B"}), 400
    include_tags_after_search = _bool_arg(args, "include_tags_after_search", False)

    per_platform = {}
    errors = []
    all_records = []

    for platform in platforms:
        per_platform[platform] = {}
        for city in cities:
            try:
                if platform == "reddit":
                    records = harvest_reddit_city(city, start_dt, end_dt, max_records, include_comments)
                elif platform == "bluesky":
                    records = harvest_bluesky_city(city, start_dt, end_dt, max_records, include_replies)
                else:
                    records = harvest_mastodon_city(
                        city, start_dt, end_dt, max_records, mastodon_mode,
                        include_tags_after_search, include_replies,
                    )
                per_platform[platform][city] = len(records)
                all_records.extend(records)
            except Exception as exc:
                current_app.logger.warning("[harvest_social] %s/%s: %s", platform, city, exc)
                per_platform[platform][city] = 0
                errors.append({"platform": platform, "city": city, "error": str(exc)})

    indexed, bulk_errors = _bulk_index_raw(_es(), all_records)
    return jsonify({
        "mode": mode,
        "window_utc": [_iso_z(start_dt), _iso_z(end_dt)],
        "platforms": platforms,
        "cities": cities,
        "max_records_per_platform_city": max_records,
        "include_comments": include_comments,
        "include_replies": include_replies,
        "per_platform": per_platform,
        "fetched_total": len(all_records),
        "indexed_total": indexed,
        "bulk_errors": bulk_errors,
        "errors": errors,
    }), 200
