"""Bulk upload local data files into ElasticSearch.

Targets:

    posts_raw      reads  data/raw/{bluesky,mastodon,reddit}_<city>_<year>.jsonl
                   _id    "<platform>:<id>"

    posts_clean    reads  data/cleaned/{sydney,melbourne,brisbane}.jsonl
                   _id    "<platform>:<id>"

    weather_daily  reads  data/raw/weather_<city>_<year>.csv
                   _id    "<city>:<yyyy-mm-dd>"

Usage:
    python database/bulk_upload.py --target posts_clean
    python database/bulk_upload.py --all
    python database/bulk_upload.py --target posts_clean --dry-run

University of Melbourne, Cluster and Cloud Computing
"""

# COMP90024 Team 2

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd
from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from database.es_client import get_es
from backend.harvesters.config import CITY_NAMES, DATA_RAW as RAW, DATA_CLEAN as CLEAN


def _stamp() -> str:
    return datetime.now(tz=timezone.utc).isoformat()


# ---------------------------------------------------------------------------
def gen_posts_raw() -> Iterable[dict]:
    files = (sorted(RAW.glob("bluesky_*_*.jsonl"))
             + sorted(RAW.glob("mastodon_*_*.jsonl"))
             + sorted(RAW.glob("reddit_*_*.jsonl")))
    if not files:
        print("[posts_raw] no jsonl files in data/raw/  (skip)")
        return

    stamp = _stamp()
    for fp in files:
        for line in fp.open("r", encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            platform = rec.get("platform") or "unknown"
            rid = rec.get("id")
            if not rid:
                continue
            rec.setdefault("harvested_at", stamp)
            yield {
                "_op_type": "index",
                "_index":   "posts_raw",
                "_id":      f"{platform}:{rid}",
                "_source":  rec,
            }


# ---------------------------------------------------------------------------
def gen_posts_clean() -> Iterable[dict]:
    """Reads the per-city JSONL files produced by clean_pipeline.py."""
    files = sorted([CLEAN / f"{c}.jsonl" for c in CITY_NAMES
                    if (CLEAN / f"{c}.jsonl").exists()])
    if not files:
        print("[posts_clean] no city jsonl files in data/cleaned/  "
              "(run cleaning pipeline first)")
        return

    KEEP = {"platform", "city", "id", "author", "text_raw", "text",
            "created_utc", "created_local", "date_local", "hour_local",
            "year", "lang", "engagement",
            "sentiment", "sentiment_label",
            "tavg", "tmin", "tmax", "prcp", "snow",
            "wdir", "wspd", "wpgt", "pres", "tsun", "url"}

    for fp in files:
        for line in fp.open("r", encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            # whitelist for strict mapping
            rec = {k: v for k, v in rec.items() if k in KEEP}
            platform = rec.get("platform") or "unknown"
            rid = rec.get("id")
            if not rid:
                continue
            yield {
                "_op_type": "index",
                "_index":   "posts_clean",
                "_id":      f"{platform}:{rid}",
                "_source":  rec,
            }


# ---------------------------------------------------------------------------
def gen_weather_daily() -> Iterable[dict]:
    files = sorted(RAW.glob("weather_*_*.csv"))
    if not files:
        print("[weather_daily] no weather_*_*.csv in data/raw/  (skip)")
        return

    for fp in files:
        df = pd.read_csv(fp)
        date_col = "time" if "time" in df.columns else "date"
        if date_col not in df.columns:
            print(f"  [{fp.name}] no date column, skipping")
            continue
        parsed_dates = pd.to_datetime(df[date_col], errors="coerce")
        df = df.loc[parsed_dates.notna()].copy()
        parsed_dates = parsed_dates.loc[df.index]
        df["date"] = parsed_dates.dt.strftime("%Y-%m-%d")
        df["year"] = parsed_dates.dt.year
        if date_col != "date":
            df = df.drop(columns=[date_col])

        for rec in df.to_dict(orient="records"):
            rec = {k: (None if pd.isna(v) else v) for k, v in rec.items()}
            city = rec.get("city") or "unknown"
            yield {
                "_op_type": "index",
                "_index":   "weather_daily",
                "_id":      f"{city}:{rec['date']}",
                "_source":  rec,
            }


# ---------------------------------------------------------------------------
TARGETS = {
    "posts_raw":     gen_posts_raw,
    "posts_clean":   gen_posts_clean,
    "weather_daily": gen_weather_daily,
}


def upload(target: str, batch: int, dry_run: bool):
    gen = TARGETS[target]()

    if dry_run:
        n = 0
        for action in gen:
            n += 1
            if n <= 2:
                print(json.dumps(action, default=str)[:300])
        print(f"\n[{target}] dry-run: {n:,} actions would be sent.")
        return

    from elasticsearch import helpers
    es = get_es()

    if batch < 1:
        raise ValueError("batch must be positive")
    actions = tqdm(gen, desc=f"upload {target}", unit="docs")
    print(f"[{target}] sending documents in batches of {batch}...")
    success, errors = helpers.bulk(
        es, actions, chunk_size=batch, raise_on_error=False, request_timeout=120,
    )
    err_n = len(errors) if isinstance(errors, list) else errors
    print(f"[{target}] success={success:,}  errors={err_n}")
    if isinstance(errors, list) and errors:
        print("First error:", json.dumps(errors[0], default=str)[:500])
    if err_n:
        raise RuntimeError(f"Elasticsearch rejected {err_n} documents")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", choices=list(TARGETS))
    ap.add_argument("--all",    action="store_true")
    ap.add_argument("--batch",  type=int, default=500)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not args.target and not args.all:
        ap.error("specify --target <name>  or  --all")

    targets = list(TARGETS) if args.all else [args.target]
    for t in targets:
        upload(t, args.batch, args.dry_run)


if __name__ == "__main__":
    main()
