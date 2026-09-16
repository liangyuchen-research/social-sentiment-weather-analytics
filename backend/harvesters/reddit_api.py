"""Reddit harvester via Arctic Shift API.

No bulk archive or Reddit API key is required. The harvester calls the public
Arctic Shift REST endpoints and paginates across each year window.

Endpoints used:
    GET https://arctic-shift.photon-reddit.com/api/posts/search
    GET https://arctic-shift.photon-reddit.com/api/comments/search

Output: data/raw/reddit_<city>_<year>.jsonl   (matches BlueSky/Mastodon schema)
Harvesting stops at a single total cap per (city, year).
"""

# COMP90024 Team 2

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import requests
from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from backend.harvesters.config import (CITIES, CITY_NAMES, CITY_SUBREDDITS, DATA_RAW,
                    HARVEST_YEARS)

ARCTIC_BASE = "https://arctic-shift.photon-reddit.com/api"
HEADERS = {"User-Agent": "CCC-Cities-Harvester/0.1 (educational)"}
DEFAULT_SLEEP_SEC = 0.05
REQ_TIMEOUT = 30
MAX_RETRY = 3


def _request(session: requests.Session, url: str, params: dict) -> requests.Response:
    last_err = None
    for attempt in range(MAX_RETRY):
        try:
            r = session.get(url, params=params, timeout=REQ_TIMEOUT)
        except requests.exceptions.RequestException as e:
            last_err = e
            time.sleep(2 ** attempt)
            continue

        if r.status_code == 200:
            return r
        if r.status_code == 429:
            wait = 3
            try:
                wait = max(0, int(r.headers.get("Retry-After", "3")))
            except (TypeError, ValueError):
                pass
            time.sleep(wait)
            continue
        if 500 <= r.status_code < 600:
            time.sleep(2 ** attempt)
            continue
        raise RuntimeError(f"Arctic Shift HTTP {r.status_code}: {r.text[:200]}")

    raise RuntimeError(f"Arctic Shift unreachable after {MAX_RETRY} retries: {last_err}")


def _fetch_page(session: requests.Session, kind: str, subreddit: str,
                after: int, before: int) -> list[dict]:
    """One paginated GET. `kind` = 'posts' or 'comments'."""
    url = f"{ARCTIC_BASE}/{kind}/search"
    params = {
        "subreddit": subreddit,
        "after": after,
        "before": before,
    }
    r = _request(session, url, params)
    payload = r.json()
    return payload.get("data", payload) if isinstance(payload, dict) else (payload or [])


def _paginate(session: requests.Session, kind: str, subreddit: str, after: int,
              before: int, sleep_sec: float = DEFAULT_SLEEP_SEC) -> Iterable[dict]:
    """Yield items until we exhaust the [after, before] year window."""
    cursor_before = before
    while cursor_before > after:
        batch = _fetch_page(session, kind, subreddit, after, cursor_before)
        if not batch:
            return

        yielded = 0
        oldest_ts = None
        for item in batch:
            created = item.get("created_utc")
            if created is None:
                continue
            created = int(created)
            if created < after or created > cursor_before:
                continue
            yield item
            yielded += 1
            oldest_ts = created if oldest_ts is None else min(oldest_ts, created)

        if yielded == 0 or oldest_ts is None or oldest_ts <= after:
            return

        next_before = oldest_ts - 1
        if next_before >= cursor_before:
            return

        cursor_before = next_before
        if sleep_sec > 0:
            time.sleep(sleep_sec)


def _to_unified(item: dict, city: str, kind: str) -> dict:
    is_comment = kind == "comments"
    if is_comment:
        text = item.get("body") or ""
    else:
        text = ((item.get("title") or "") + "\n" + (item.get("selftext") or "")).strip()

    permalink = item.get("permalink") or ""
    if permalink and not permalink.startswith("http"):
        permalink = f"https://reddit.com{permalink}"

    created = item.get("created_utc")
    if isinstance(created, (int, float)):
        created_iso = datetime.fromtimestamp(int(created), tz=timezone.utc).isoformat()
    elif isinstance(created, str):
        created_iso = created
    else:
        created_iso = None

    return {
        "platform": "reddit",
        "city": city,
        "kind": "comment" if is_comment else "post",
        "id": item.get("id"),
        "subreddit": item.get("subreddit"),
        "author": item.get("author") or "[deleted]",
        "text": text,
        "score": item.get("score") or 0,
        "num_comments": item.get("num_comments") or 0,
        "created_at": created_iso,
        "url": permalink,
        "parent_post_id": (item.get("link_id") or "").replace("t3_", "") or None,
    }


def harvest(city: str, year: int, include_comments: bool = True,
            max_records: int | None = None,
            sleep_sec: float = DEFAULT_SLEEP_SEC) -> int:
    if city not in CITIES:
        sys.exit(f"Unknown city '{city}'. Choices: {CITY_NAMES}")
    subreddits = CITY_SUBREDDITS.get(city, [city])

    after = int(datetime(year, 1, 1, 0, 0, 0, tzinfo=timezone.utc).timestamp())
    before = int(datetime(year, 12, 31, 23, 59, 59, tzinfo=timezone.utc).timestamp())

    out_path = DATA_RAW / f"reddit_{city}_{year}.jsonl"
    print(f"[reddit] city={city}  year={year}  subreddits={subreddits}")
    print(f"         comments={include_comments}  cap={max_records}  sleep={sleep_sec}  -> {out_path}")

    seen: set[str] = set()
    written = 0
    kinds = ["posts", "comments"] if include_comments else ["posts"]

    session = requests.Session()
    session.headers.update(HEADERS)

    try:
        with out_path.open("w", encoding="utf-8") as f:
            for sub in subreddits:
                for kind in kinds:
                    if max_records is not None and written >= max_records:
                        break

                    pbar = tqdm(desc=f"  r/{sub}/{kind}", leave=False)
                    try:
                        for item in _paginate(session, kind, sub, after, before, sleep_sec=sleep_sec):
                            rec = _to_unified(item, city, kind)
                            rid = rec["id"]
                            if not rid or rid in seen:
                                continue
                            seen.add(rid)
                            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                            written += 1
                            pbar.update(1)
                            if max_records is not None and written >= max_records:
                                break
                    except Exception as e:
                        print(f"  [!] r/{sub}/{kind} aborted: {e}")
                    pbar.close()

                    if max_records is not None and written >= max_records:
                        break
                if max_records is not None and written >= max_records:
                    break
    finally:
        session.close()

    print(f"[reddit] {city}/{year}: wrote {written} records")
    return written


def main():
    ap = argparse.ArgumentParser()
    g_city = ap.add_mutually_exclusive_group(required=True)
    g_city.add_argument("--city", choices=CITY_NAMES)
    g_city.add_argument("--all-cities", action="store_true")

    g_year = ap.add_mutually_exclusive_group(required=True)
    g_year.add_argument("--year", type=int, choices=HARVEST_YEARS)
    g_year.add_argument("--all-years", action="store_true")

    ap.add_argument("--include-comments", action=argparse.BooleanOptionalAction, default=True,
                    help="also harvest comments")
    ap.add_argument("--max-records", type=int, default=None,
                    help="cap per (city, year) for testing")
    ap.add_argument("--sleep-sec", type=float, default=DEFAULT_SLEEP_SEC,
                    help="pause between page requests")
    args = ap.parse_args()

    cities = CITY_NAMES if args.all_cities else [args.city]
    years = HARVEST_YEARS if args.all_years else [args.year]

    for c in cities:
        for y in years:
            harvest(c, y,
                    include_comments=args.include_comments,
                    max_records=args.max_records,
                    sleep_sec=args.sleep_sec)


if __name__ == "__main__":
    main()
