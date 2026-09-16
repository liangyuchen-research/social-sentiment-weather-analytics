"""BlueSky harvester — atproto SDK, city-tagged.

Each city has a list of search queries in config.CITIES. We harvest those
queries until we hit a single total cap for that (city, year), tagging every
record with `city` so downstream cleaning + per-city JSONL output is trivial.

Output: data/raw/bluesky_<city>_<year>.jsonl

Usage:
    python backend/harvesters/bluesky_harvester.py --city sydney --year 2025 --limit 500
    python backend/harvesters/bluesky_harvester.py --all-cities --year 2025
    python backend/harvesters/bluesky_harvester.py --all-cities --all-years

University of Melbourne, Cluster and Cloud Computing
"""

# COMP90024 Team 2

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from backend.harvesters.config import CITIES, CITY_NAMES, DATA_RAW, HARVEST_YEARS

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

THREAD_DEPTH = 6


def get_client():
    from atproto import Client
    handle = os.environ.get("BLUESKY_HANDLE")
    pw     = os.environ.get("BLUESKY_APP_PASSWORD")
    if not handle or not pw:
        sys.exit("Missing BLUESKY_HANDLE / BLUESKY_APP_PASSWORD in .env. "
                 "See backend/harvesters/README.md.")
    c = Client()
    c.login(handle, pw)
    return c


def _maybe_get_uri(obj) -> str | None:
    return getattr(obj, "uri", None) if obj is not None else None


def _extract_reply_uris(record):
    reply = getattr(record, "reply", None)
    if reply is None:
        return None, None
    parent_uri = _maybe_get_uri(getattr(reply, "parent", None))
    root_uri = _maybe_get_uri(getattr(reply, "root", None))
    return parent_uri, root_uri


def post_to_dict(post, city: str, query: str, kind: str | None = None) -> dict:
    record = post.record
    parent_uri, root_uri = _extract_reply_uris(record)
    if kind is None:
        kind = "reply" if parent_uri else "post"
    return {
        "platform":     "bluesky",
        "city":         city,
        "matched_query": query,
        "kind":         kind,
        "id":           post.uri,
        "cid":          post.cid,
        "author_handle": post.author.handle,
        "author_did":    post.author.did,
        "text":         getattr(record, "text", ""),
        "lang":         list(getattr(record, "langs", []) or []),
        "reply_count":  post.reply_count,
        "repost_count": post.repost_count,
        "like_count":   post.like_count,
        "created_at":   getattr(record, "created_at", None),
        "url":          f"https://bsky.app/profile/{post.author.handle}/post/{post.uri.split('/')[-1]}",
        "parent_post_id": parent_uri,
        "root_post_id": root_uri,
    }


def _iter_thread_replies(node):
    stack = list(getattr(node, "replies", None) or [])
    while stack:
        child = stack.pop(0)
        if getattr(child, "py_type", None) != "app.bsky.feed.defs#threadViewPost":
            continue
        yield child
        stack[0:0] = list(getattr(child, "replies", None) or [])


def fetch_replies(client, root_uri: str, city: str, query: str,
                  since_iso: str, until_iso: str) -> list[dict]:
    try:
        res = client.app.bsky.feed.get_post_thread(
            {"uri": root_uri, "depth": THREAD_DEPTH, "parent_height": 0}
        )
    except Exception as e:
        print(f"  [!] thread '{root_uri}': {e}")
        return []

    thread = getattr(res, "thread", None)
    if getattr(thread, "py_type", None) != "app.bsky.feed.defs#threadViewPost":
        return []

    out = []
    for reply_node in _iter_thread_replies(thread):
        post = getattr(reply_node, "post", None)
        if post is None:
            continue
        rec = post_to_dict(post, city, query, kind="reply")
        created_at = rec.get("created_at")
        if created_at and since_iso <= created_at <= until_iso:
            out.append(rec)
    return out


def harvest(city: str, year: int, max_records: int | None,
            include_replies: bool = True):
    if city not in CITIES:
        sys.exit(f"Unknown city '{city}'. Choices: {CITY_NAMES}")
    queries = CITIES[city]["queries"]

    start = date(year, 1, 1)
    end   = date(year, 12, 31)
    since_iso = f"{start.isoformat()}T00:00:00Z"
    until_iso = f"{end.isoformat()}T23:59:59Z"

    client = get_client()
    out_path = DATA_RAW / f"bluesky_{city}_{year}.jsonl"

    print(f"[bluesky] city={city}  year={year}  window={since_iso}..{until_iso}")
    print(f"          queries={len(queries)}  cap={max_records}  -> {out_path}")
    seen = set()
    written = 0

    with out_path.open("w", encoding="utf-8") as f:
        for q in queries:
            if max_records is not None and written >= max_records:
                break
            cursor = None
            seen_cursors: set[str] = set()
            pbar = tqdm(desc=f"  q:{q[:30]}", leave=False)
            while True:
                if max_records is not None and written >= max_records:
                    break
                try:
                    params = {"q": q, "since": since_iso, "until": until_iso}
                    if cursor:
                        params["cursor"] = cursor
                    res = client.app.bsky.feed.search_posts(params)
                except Exception as e:
                    print(f"  [!] search '{q}': {e}")
                    break

                posts = getattr(res, "posts", [])
                if not posts:
                    break

                for p in posts:
                    if max_records is not None and written >= max_records:
                        break
                    if p.uri in seen:
                        continue
                    rec = post_to_dict(p, city, q)
                    seen.add(p.uri)
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    written += 1
                    pbar.update(1)
                    if include_replies and getattr(p, "reply_count", 0):
                        for reply in fetch_replies(client, p.uri, city, q, since_iso, until_iso):
                            if max_records is not None and written >= max_records:
                                break
                            if reply["id"] in seen:
                                continue
                            seen.add(reply["id"])
                            f.write(json.dumps(reply, ensure_ascii=False) + "\n")
                            written += 1
                            pbar.update(1)
                        time.sleep(0.1)

                cursor = getattr(res, "cursor", None)
                if not cursor or cursor in seen_cursors:
                    break
                seen_cursors.add(cursor)
                time.sleep(0.2)
            pbar.close()

    print(f"[bluesky] {city}/{year}: wrote {written} records")


def main():
    ap = argparse.ArgumentParser()
    g_city = ap.add_mutually_exclusive_group(required=True)
    g_city.add_argument("--city", choices=CITY_NAMES)
    g_city.add_argument("--all-cities", action="store_true")

    g_year = ap.add_mutually_exclusive_group(required=True)
    g_year.add_argument("--year", type=int, choices=HARVEST_YEARS)
    g_year.add_argument("--all-years", action="store_true")

    ap.add_argument("--limit", type=int, default=500,
                    help="max posts per (city, year)")
    ap.add_argument("--include-replies", action=argparse.BooleanOptionalAction, default=True,
                    help="also fetch replies under harvested posts")
    args = ap.parse_args()

    cities = CITY_NAMES if args.all_cities else [args.city]
    years  = HARVEST_YEARS if args.all_years else [args.year]

    for c in cities:
        for y in years:
            harvest(c, y, args.limit, include_replies=args.include_replies)


if __name__ == "__main__":
    main()
