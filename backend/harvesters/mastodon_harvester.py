"""Mastodon harvester, city-tagged.

Two modes (auto-picks based on whether MASTODON_ACCESS_TOKEN is available):

    Method A (no auth): /api/v1/timelines/tag/<tag> on public instances.
                        Limited to hashtag matches and can be slow for old years.
    Method B (auth):    /api/v2/search?q=<query> on a single instance.
                        Preferred for broad city-level harvesting.

Each city in config.CITIES has both `tags` (for Method A) and `queries`
(for Method B). Harvesting stops at a single total cap for that
(city, year). Output: data/raw/mastodon_<city>_<year>.jsonl with `city`
field set on every record.
"""

# COMP90024 Team 2

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import date
from pathlib import Path

import requests
from dotenv import load_dotenv
from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from backend.harvesters.config import (CITIES, CITY_NAMES, DATA_RAW, HARVEST_YEARS,
                    MASTODON_INSTANCES)

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

TIMEOUT = 20
HTML_TAG = re.compile(r"<[^>]+>")
DEFAULT_HEADERS = {"User-Agent": "CCC-Cities-Harvester/0.1"}
PAGE_SLEEP_SEC = 0.1
RATE_LIMIT_RETRY = 3
TAG_FALLBACK_MIN_YEAR = 2022


def strip_html(s: str) -> str:
    return HTML_TAG.sub("", s or "").strip()


def _composite_id(instance: str, status_id: str | None) -> str | None:
    if not status_id:
        return None
    return f"{instance}::{status_id}"


def status_to_dict(s: dict, instance: str, city: str, source_kind: str,
                   kind: str | None = None, root_status_id: str | None = None) -> dict:
    acct = s.get("account", {}) or {}
    parent_status_id = _composite_id(instance, s.get("in_reply_to_id"))
    if kind is None:
        kind = "reply" if parent_status_id else "status"
    return {
        "platform": "mastodon",
        "city": city,
        "instance": instance,
        "source": source_kind,
        "kind": kind,
        "id": _composite_id(instance, s.get("id")),
        "author": acct.get("acct"),
        "author_display": acct.get("display_name"),
        "text": strip_html(s.get("content", "")),
        "lang": s.get("language"),
        "reblogs_count": s.get("reblogs_count", 0),
        "favourites_count": s.get("favourites_count", 0),
        "replies_count": s.get("replies_count", 0),
        "created_at": s.get("created_at"),
        "url": s.get("url"),
        "tags": [t.get("name") for t in s.get("tags", [])],
        "parent_status_id": parent_status_id,
        "root_status_id": _composite_id(instance, root_status_id) or _composite_id(instance, s.get("id")),
    }


def _iter_search_terms(cfg: dict) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()

    # On Mastodon hashtags usually index better than plain city phrases.
    for term in [f"#{tag}" for tag in cfg.get("tags", [])] + list(cfg.get("queries", [])):
        key = term.casefold()
        if key in seen:
            continue
        seen.add(key)
        terms.append(term)
    return terms


def _unique_instances(primary: str) -> list[str]:
    ordered = [primary] + [inst for inst in MASTODON_INSTANCES if inst != primary]
    out: list[str] = []
    seen: set[str] = set()
    for inst in ordered:
        if inst in seen:
            continue
        seen.add(inst)
        out.append(inst)
    return out


def _request(session: requests.Session, url: str, **kwargs) -> requests.Response | None:
    for attempt in range(RATE_LIMIT_RETRY):
        try:
            r = session.get(url, timeout=TIMEOUT, **kwargs)
        except requests.exceptions.RequestException as e:
            if attempt == RATE_LIMIT_RETRY - 1:
                print(f"  [!] request failed: {e}")
                return None
            time.sleep(min(2 ** attempt, 5))
            continue

        if r.status_code == 429:
            retry_after = r.headers.get("Retry-After")
            try:
                wait = int(retry_after) if retry_after else 5 * (attempt + 1)
            except ValueError:
                wait = 5 * (attempt + 1)
            print(f"  [!] rate limited; waiting {wait}s")
            time.sleep(wait)
            continue

        return r

    return None


def fetch_tag(session: requests.Session, instance: str, tag: str,
              start_iso: str, end_iso: str, cap: int | None, city: str) -> list[dict]:
    url = f"{instance}/api/v1/timelines/tag/{tag}"
    params = {}
    out: list[dict] = []
    seen_ids: set[str] = set()
    seen_cursors: set[str] = set()
    pbar = tqdm(desc=f"A:{instance.split('//')[1][:18]}/#{tag[:18]}", leave=False)
    while cap is None or len(out) < cap:
        r = _request(session, url, params=params)
        if r is None:
            break
        if r.status_code != 200:
            if r.status_code != 404:
                print(f"  [!] {instance}#{tag} HTTP {r.status_code}")
            break

        batch = r.json()
        if not batch:
            break

        oldest = batch[-1]["created_at"]
        for s in batch:
            if s["id"] in seen_ids:
                continue
            seen_ids.add(s["id"])
            if start_iso <= s["created_at"] <= end_iso:
                out.append(status_to_dict(s, instance, city, f"tag:{tag}"))
                pbar.update(1)
                if cap is not None and len(out) >= cap:
                    break

        if oldest < start_iso:
            break

        next_cursor = batch[-1]["id"]
        if next_cursor in seen_cursors:
            break
        seen_cursors.add(next_cursor)
        params = {"max_id": next_cursor}
        time.sleep(PAGE_SLEEP_SEC)

    pbar.close()
    return out


def fetch_search(session: requests.Session, instance: str, token: str, query: str,
                 start_iso: str, end_iso: str, cap: int | None, city: str) -> list[dict]:
    url = f"{instance}/api/v2/search"
    headers = {"Authorization": f"Bearer {token}"}
    params = {"q": query, "type": "statuses", "resolve": "false"}
    out: list[dict] = []
    seen_ids: set[str] = set()
    seen_cursors: set[str] = set()
    pbar = tqdm(desc=f"B:search({query[:25]})", leave=False)
    while cap is None or len(out) < cap:
        r = _request(session, url, params=params, headers=headers)
        if r is None:
            break
        if r.status_code == 401:
            print("  [!] 401 Unauthorized - bad MASTODON_ACCESS_TOKEN?")
            break
        if r.status_code != 200:
            print(f"  [!] search {query!r} HTTP {r.status_code}")
            break

        statuses = (r.json() or {}).get("statuses", [])
        if not statuses:
            break

        oldest = statuses[-1]["created_at"]
        for s in statuses:
            if s["id"] in seen_ids:
                continue
            seen_ids.add(s["id"])
            if start_iso <= s["created_at"] <= end_iso:
                out.append(status_to_dict(s, instance, city, f"search:{query}"))
                pbar.update(1)
                if cap is not None and len(out) >= cap:
                    break

        if oldest < start_iso:
            break

        next_cursor = statuses[-1]["id"]
        if next_cursor in seen_cursors:
            break
        seen_cursors.add(next_cursor)
        params = {**params, "max_id": next_cursor}
        time.sleep(PAGE_SLEEP_SEC)

    pbar.close()
    return out


def fetch_context_replies(session: requests.Session, instance: str, token: str | None,
                          status_id: str, city: str, source_kind: str,
                          start_iso: str, end_iso: str) -> list[dict]:
    url = f"{instance}/api/v1/statuses/{status_id}/context"
    headers = {"Authorization": f"Bearer {token}"} if token else None
    r = _request(session, url, headers=headers)
    if r is None or r.status_code != 200:
        return []
    payload = r.json() or {}
    descendants = payload.get("descendants", []) or []
    out = []
    for reply in descendants:
        created_at = reply.get("created_at")
        if created_at and start_iso <= created_at <= end_iso:
            out.append(
                status_to_dict(
                    reply, instance, city, f"context:{source_kind}",
                    kind="reply", root_status_id=status_id
                )
            )
    return out


def harvest(city: str, year: int, cap: int | None, mode: str,
            include_tags_after_search: bool = False,
            include_replies: bool = True):
    if city not in CITIES:
        sys.exit(f"Unknown city '{city}'. Choices: {CITY_NAMES}")
    cfg = CITIES[city]

    start = date(year, 1, 1)
    end = date(year, 12, 31)
    start_iso = f"{start.isoformat()}T00:00:00.000Z"
    end_iso = f"{end.isoformat()}T23:59:59.999Z"
    out_path = DATA_RAW / f"mastodon_{city}_{year}.jsonl"
    tmp_path = out_path.with_suffix(".jsonl.tmp")

    token = os.environ.get("MASTODON_ACCESS_TOKEN")
    instance = os.environ.get("MASTODON_INSTANCE", "https://aus.social")

    if mode == "auto":
        mode = "B" if token else "A"
    if mode == "B" and not token:
        sys.exit("Mode B requires MASTODON_ACCESS_TOKEN in .env.")

    print(f"[mastodon] city={city}  year={year}  mode={mode}  cap={cap}  -> {out_path}")

    seen: set[str] = set()
    written = 0

    def remaining_cap() -> int | None:
        if cap is None:
            return None
        return max(cap - written, 0)

    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)

    try:
        with tmp_path.open("w", encoding="utf-8") as f:
            def write_record(rec: dict):
                nonlocal written
                if rec["id"] in seen:
                    return False
                seen.add(rec["id"])
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                written += 1
                return True

            def write_with_replies(rec: dict, status_payload: dict, source_kind: str):
                if cap is not None and written >= cap:
                    return
                added = write_record(rec)
                if not added or not include_replies or cap is not None and written >= cap:
                    return
                if not status_payload.get("replies_count"):
                    return
                for reply in fetch_context_replies(
                    session, rec["instance"], token if rec["instance"].rstrip("/") == instance.rstrip("/") else None,
                    status_payload.get("id"), city, source_kind, start_iso, end_iso
                ):
                    if cap is not None and written >= cap:
                        break
                    write_record(reply)
                time.sleep(PAGE_SLEEP_SEC)

            if mode == "A":
                for inst in _unique_instances(instance):
                    if cap is not None and written >= cap:
                        break
                    for tag in cfg["tags"]:
                        rem = remaining_cap()
                        if rem is not None and rem <= 0:
                            break
                        for status_payload in fetch_tag(session, inst, tag, start_iso, end_iso, rem, city):
                            rec = status_payload
                            write_with_replies(rec, {"id": rec["id"].split("::", 1)[1], "replies_count": rec.get("replies_count", 0)}, f"tag:{tag}")
                            if cap is not None and written >= cap:
                                break
            else:
                print(f"  using instance {instance}")
                search_terms = _iter_search_terms(cfg)
                for query in search_terms:
                    rem = remaining_cap()
                    if rem is not None and rem <= 0:
                        break
                    before = written
                    for status_payload in fetch_search(session, instance, token, query, start_iso, end_iso, rem, city):
                        rec = status_payload
                        write_with_replies(rec, {"id": rec["id"].split("::", 1)[1], "replies_count": rec.get("replies_count", 0)}, f"search:{query}")
                        if cap is not None and written >= cap:
                            break
                    gained = written - before
                    if gained:
                        print(f"  search {query!r}: +{gained}")

                if written == 0 and year >= TAG_FALLBACK_MIN_YEAR:
                    print("  [!] search returned 0 records; falling back to hashtag timelines")
                    for inst in _unique_instances(instance):
                        if cap is not None and written >= cap:
                            break
                        for tag in cfg["tags"]:
                            rem = remaining_cap()
                            if rem is not None and rem <= 0:
                                break
                            for status_payload in fetch_tag(session, inst, tag, start_iso, end_iso, rem, city):
                                rec = status_payload
                                write_with_replies(rec, {"id": rec["id"].split("::", 1)[1], "replies_count": rec.get("replies_count", 0)}, f"tag:{tag}")
                                if cap is not None and written >= cap:
                                    break
                elif written == 0:
                    print(f"  [!] search returned 0 records; skip tag fallback before {TAG_FALLBACK_MIN_YEAR}")
                elif include_tags_after_search and (cap is None or written < cap):
                    for tag in cfg["tags"]:
                        rem = remaining_cap()
                        if rem is not None and rem <= 0:
                            break
                        for status_payload in fetch_tag(session, instance, tag, start_iso, end_iso, rem, city):
                            rec = status_payload
                            write_with_replies(rec, {"id": rec["id"].split("::", 1)[1], "replies_count": rec.get("replies_count", 0)}, f"tag:{tag}")
                            if cap is not None and written >= cap:
                                break
    finally:
        session.close()

    if written > 0:
        tmp_path.replace(out_path)
    else:
        if tmp_path.exists():
            tmp_path.unlink()
        if out_path.exists() and out_path.stat().st_size == 0:
            out_path.unlink()
        print("  [!] no Mastodon records found for this city/year")

    print(f"[mastodon] {city}/{year}: wrote {written} records")


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
    ap.add_argument("--mode", choices=["auto", "A", "B"], default="auto")
    ap.add_argument("--include-tags-after-search", action="store_true",
                    help="when using mode B, also walk tag timelines after search")
    ap.add_argument("--include-replies", action=argparse.BooleanOptionalAction, default=True,
                    help="also fetch reply descendants for harvested statuses")
    args = ap.parse_args()

    cities = CITY_NAMES if args.all_cities else [args.city]
    years = HARVEST_YEARS if args.all_years else [args.year]

    for c in cities:
        for y in years:
            harvest(c, y, args.limit, args.mode,
                    include_tags_after_search=args.include_tags_after_search,
                    include_replies=args.include_replies)


if __name__ == "__main__":
    main()
