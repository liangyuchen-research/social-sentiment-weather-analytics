"""Cleaning pipeline — Sydney / Melbourne / Brisbane edition.

Reads:
    data/raw/bluesky_<city>_<year>.jsonl    (atproto SDK)
    data/raw/mastodon_<city>_<year>.jsonl   (api/v2/search)
    data/raw/reddit_<city>_<year>.jsonl     (Arctic Shift API)
    data/raw/weather_<city>_<year>.csv      (meteostat)

Steps:
    1. Load posts from BlueSky + Mastodon + Reddit, keep `city` field
    2. Normalise text (URLs, mentions, whitespace) and dedupe
    3. langdetect (default keep English)
    4. Convert created_at -> UTC + city-local timezone
    5. Add VADER sentiment score + label
    6. Per city: join with that city's daily weather (on date_local)
    7. Write one JSONL per city to data/cleaned/<city>.jsonl
       Also writes:  data/cleaned/all_posts.parquet  (combined, for analysis)
                     data/cleaned/weather_daily.parquet (combined weather)

Usage:
    python backend/cleaning/clean_pipeline.py
    python backend/cleaning/clean_pipeline.py --all-langs
    python backend/cleaning/clean_pipeline.py --no-sentiment

University of Melbourne, Cluster and Cloud Computing
"""

# COMP90024 Team 2

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import pandas as pd
from tqdm import tqdm

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from backend.harvesters.config import CITIES, CITY_NAMES, DATA_CLEAN, DATA_RAW

URL_RE     = re.compile(r"https?://\S+|www\.\S+")
MENTION_RE = re.compile(r"@[\w\.\-]+")
MULTI_WS   = re.compile(r"\s+")

COMMON_COLS = [
    "platform", "city", "id", "author", "text_raw",
    "created_utc", "engagement", "url",
]


# ---------------------------------------------------------------------------
# Loaders — each platform's harvest output -> common schema
# ---------------------------------------------------------------------------
def read_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue


def load_bluesky() -> pd.DataFrame:
    rows = []
    for p in sorted(DATA_RAW.glob("bluesky_*_*.jsonl")):
        for r in read_jsonl(p):
            rows.append({
                "platform":    "bluesky",
                "city":        r.get("city"),
                "id":          r.get("id"),
                "author":      r.get("author_handle"),
                "text_raw":    r.get("text", ""),
                "created_utc": r.get("created_at"),
                "engagement": (r.get("like_count")  or 0)
                            + (r.get("repost_count") or 0)
                            + (r.get("reply_count")  or 0),
                "url":         r.get("url"),
            })
    return pd.DataFrame(rows, columns=COMMON_COLS)


def load_mastodon() -> pd.DataFrame:
    rows = []
    for p in sorted(DATA_RAW.glob("mastodon_*_*.jsonl")):
        for r in read_jsonl(p):
            rows.append({
                "platform":    "mastodon",
                "city":        r.get("city"),
                "id":          r.get("id"),
                "author":      r.get("author"),
                "text_raw":    r.get("text", ""),
                "created_utc": r.get("created_at"),
                "engagement": (r.get("favourites_count") or 0)
                            + (r.get("reblogs_count")    or 0)
                            + (r.get("replies_count")    or 0),
                "url":         r.get("url"),
            })
    return pd.DataFrame(rows, columns=COMMON_COLS)


def load_reddit() -> pd.DataFrame:
    """Reddit JSONL produced by harvesters/reddit_api.py (Arctic Shift)."""
    rows = []
    for p in sorted(DATA_RAW.glob("reddit_*_*.jsonl")):
        for r in read_jsonl(p):
            rows.append({
                "platform":    "reddit",
                "city":        r.get("city"),
                "id":          r.get("id"),
                "author":      r.get("author"),
                "text_raw":    r.get("text", ""),
                "created_utc": r.get("created_at"),
                "engagement": (r.get("score") or 0) + (r.get("num_comments") or 0),
                "url":         r.get("url"),
            })
    return pd.DataFrame(rows, columns=COMMON_COLS)


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------
def normalize_text(s: str) -> str:
    if not isinstance(s, str):
        return ""
    s = URL_RE.sub(" ", s)
    s = MENTION_RE.sub(" ", s)
    s = MULTI_WS.sub(" ", s).strip()
    return s


def detect_lang(s: str) -> str:
    if not s or len(s) < 10:
        return "unknown"
    try:
        from langdetect import detect, DetectorFactory
        DetectorFactory.seed = 42
        return detect(s)
    except Exception:
        return "unknown"


def clean_posts(df: pd.DataFrame, keep_langs=("en",), with_sentiment=True) -> pd.DataFrame:
    print(f"[clean] raw posts: {len(df):,}")

    df = df.dropna(subset=["text_raw", "city", "id"]).copy()
    df["text"] = df["text_raw"].map(normalize_text)
    df = df[df["text"].str.len() >= 5]
    df = df[df["author"].fillna("[deleted]") != "[deleted]"]
    df = df[df["city"].isin(CITY_NAMES)]
    print(f"[clean] after text/author/city: {len(df):,}")

    df = df.drop_duplicates(subset=["platform", "id"])
    df["_dupkey"] = df["platform"] + "::" + df["city"] + "::" + df["author"].fillna("") + "::" + df["text"].str.lower().str[:120]
    df = df.drop_duplicates(subset=["_dupkey"]).drop(columns="_dupkey")
    print(f"[clean] after dedup: {len(df):,}")

    df["created_utc"] = pd.to_datetime(df["created_utc"], utc=True,
                                       format="ISO8601", errors="coerce")
    df = df.dropna(subset=["created_utc"])

    # Local time per-city (Sydney/Mel observe DST, Brisbane doesn't).
    # Note: a single column can't hold mixed timezones, so we store local time
    # as a tz-naive datetime (the wall-clock time in that city's timezone).
    def _to_local_naive(row):
        tz = CITIES[row["city"]]["tz"]
        return row["created_utc"].tz_convert(tz).tz_localize(None)
    df["created_local"] = (pd.to_datetime(df.apply(_to_local_naive, axis=1))
                           if not df.empty else pd.Series(dtype="datetime64[ns]"))
    df["date_local"]    = df["created_local"].dt.date
    df["hour_local"]    = df["created_local"].dt.floor("h")
    df["year"]          = df["created_local"].dt.year

    tqdm.pandas(desc="lang detect")
    df["lang"] = df["text"].progress_map(detect_lang)
    if keep_langs:
        df = df[df["lang"].isin(keep_langs)]
        print(f"[clean] after lang filter {keep_langs}: {len(df):,}")

    if with_sentiment:
        try:
            from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
            v = SentimentIntensityAnalyzer()
            tqdm.pandas(desc="VADER")
            df["sentiment"] = df["text"].progress_map(
                lambda t: v.polarity_scores(t)["compound"])
            df["sentiment_label"] = pd.cut(
                df["sentiment"], bins=[-1.01, -0.05, 0.05, 1.01],
                labels=["negative", "neutral", "positive"]).astype(str)
        except ImportError as exc:
            raise RuntimeError("Install vaderSentiment or pass --no-sentiment") from exc

    return df.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Weather
# ---------------------------------------------------------------------------
def load_weather_for(city: str) -> pd.DataFrame:
    frames = []
    for p in sorted(DATA_RAW.glob(f"weather_{city}_*.csv")):
        w = pd.read_csv(p)
        date_col = "time" if "time" in w.columns else "date"
        if date_col not in w.columns:
            continue
        w["date_local"] = pd.to_datetime(w[date_col]).dt.date
        if "city" not in w.columns:
            w["city"] = city
        frames.append(w)
    if not frames:
        return pd.DataFrame()
    w = pd.concat(frames, ignore_index=True).drop_duplicates(["city", "date_local"])
    keep = [c for c in ("city", "date_local", "tavg", "tmin", "tmax", "prcp",
                        "snow", "wdir", "wspd", "wpgt", "pres", "tsun") if c in w.columns]
    return w[keep]


def load_all_weather() -> pd.DataFrame:
    return pd.concat([load_weather_for(c) for c in CITY_NAMES],
                     ignore_index=True)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main(all_langs: bool, with_sentiment: bool):
    print("=== Loading social posts ===")
    raw = pd.concat([load_bluesky(), load_mastodon(), load_reddit()],
                    ignore_index=True)
    if raw.empty:
        sys.exit("[!] No social data found. Run harvesters first.")

    df = clean_posts(raw,
                     keep_langs=() if all_langs else ("en",),
                     with_sentiment=with_sentiment)

    print("\n=== Loading weather ===")
    weather = load_all_weather()
    if weather.empty:
        print("[!] No weather data — posts will be written without weather columns.")

    # Combined parquet (for cross-city analysis in notebooks)
    if not weather.empty:
        joined = df.merge(weather, on=["city", "date_local"], how="left")
    else:
        joined = df.copy()
    joined.to_parquet(DATA_CLEAN / "all_posts.parquet", index=False)
    print(f"[clean] all_posts.parquet  rows={len(joined):,}")

    if not weather.empty:
        weather.to_parquet(DATA_CLEAN / "weather_daily.parquet", index=False)
        print(f"[clean] weather_daily.parquet  rows={len(weather):,}")

    # Per-city JSONL output
    print("\n=== Writing per-city JSONL ===")
    for city in CITY_NAMES:
        sub = joined[joined["city"] == city].copy()
        out = DATA_CLEAN / f"{city}.jsonl"

        # Convert datetimes/dates to ISO strings so JSON serialises cleanly
        if "created_utc" in sub.columns:
            sub["created_utc"] = pd.to_datetime(sub["created_utc"], utc=True).dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        for col in ("created_local", "hour_local"):
            if col in sub.columns:
                sub[col] = pd.to_datetime(sub[col], errors="coerce").dt.strftime("%Y-%m-%dT%H:%M:%S")
        if "date_local" in sub.columns:
            sub["date_local"] = pd.to_datetime(sub["date_local"]).dt.strftime("%Y-%m-%d")

        # NaN -> None for valid JSON
        sub = sub.astype(object).where(pd.notna(sub), None)

        with out.open("w", encoding="utf-8") as f:
            for rec in sub.to_dict(orient="records"):
                f.write(json.dumps(rec, ensure_ascii=False, default=str, allow_nan=False) + "\n")
        print(f"  {city:10s}  {len(sub):>6,d} rows  -> {out}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--all-langs", action="store_true",
                    help="keep all languages (default: English only)")
    ap.add_argument("--no-sentiment", action="store_true",
                    help="skip VADER sentiment scoring")
    args = ap.parse_args()
    main(all_langs=args.all_langs, with_sentiment=not args.no_sentiment)
