"""Shared config — cities, queries, weather stations, paths.

Project scope:
    Analyse the relationship between social media posts and weather across
    Sydney, Melbourne, and Brisbane.

Each post is tagged with its `city` at harvest time using city-specific
queries / hashtags. Weather data is fetched per-city from the corresponding
WMO station via meteostat.

University of Melbourne, Cluster and Cloud Computing
"""

# COMP90024 Team 2

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# 1. Paths
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_ROOT = Path(os.environ.get("SOCIAL_WEATHER_DATA_DIR", PROJECT_ROOT / "data")).expanduser().resolve()
DATA_RAW = DATA_ROOT / "raw"
DATA_CLEAN = DATA_ROOT / "cleaned"

DATA_RAW.mkdir(parents=True, exist_ok=True)
DATA_CLEAN.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# 2. Time window
#    BlueSky meaningful from ~2024, Mastodon from ~2023.
#    For BOM weather we can go back further (any year).
# ---------------------------------------------------------------------------
HARVEST_YEARS  = list(range(2016, 2027))   # Historical project window
WEATHER_YEARS  = list(range(2016, 2027))   # broader weather baseline


# ---------------------------------------------------------------------------
# 3. Cities
#    Each city has:
#      queries             — keyword phrases for BlueSky search + Mastodon v2/search
#      tags                — hashtags for Mastodon /api/v1/timelines/tag/<tag>
#      meteostat_station   — WMO id for `meteostat.Daily(station, ...)`
#      bom_station_id      — official BOM id (for the report / docs)
#      tz                  — local timezone (for Sydney/Mel DST, Brisbane no DST)
# ---------------------------------------------------------------------------
CITIES = {
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
        "meteostat_station": "94767",   # Sydney Observatory Hill
        "bom_station_id":    "066062",
        "tz": "Australia/Sydney",
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
        "meteostat_station": "94866",   # Melbourne (Olympic Park)
        "bom_station_id":    "086338",
        "tz": "Australia/Melbourne",
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
        "meteostat_station": "94578",   # Brisbane Aero
        "bom_station_id":    "040842",
        "tz": "Australia/Brisbane",
    },
}

CITY_NAMES = list(CITIES.keys())   # ["sydney", "melbourne", "brisbane"]


# ---------------------------------------------------------------------------
# Reddit subreddits per city (used by reddit_api.py via Arctic Shift)
#   Add more subreddits here to broaden coverage.
# ---------------------------------------------------------------------------
CITY_SUBREDDITS = {
    "sydney":    ["sydney"],
    "melbourne": ["melbourne"],
    "brisbane":  ["brisbane"],
}


# ---------------------------------------------------------------------------
# 4. Mastodon instances (used by Method A — public hashtag timelines)
# ---------------------------------------------------------------------------
MASTODON_INSTANCES = [
    "https://aus.social",
    "https://mastodon.au",
    "https://mastodon.social",
]


# ---------------------------------------------------------------------------
# 5. Backwards-compat shim (only kept so legacy notebooks don't crash;
#    new code should NOT use these. Will be removed once all callers updated.)
# ---------------------------------------------------------------------------
METEOSTAT_STATION = CITIES["melbourne"]["meteostat_station"]
BOM_STATION_ID    = CITIES["melbourne"]["bom_station_id"]
