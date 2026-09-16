"""BOM / WMO daily weather harvester for 3 cities.

For each city in config.CITIES we fetch daily observations from its WMO
station via meteostat.Daily, and write:
    data/raw/weather_<city>_<year>.csv

Stations:
    Sydney    — WMO 94767  (Sydney Observatory Hill)
    Melbourne — WMO 94866  (Melbourne Olympic Park)
    Brisbane  — WMO 94578  (Brisbane Aero)

Usage:
    python backend/harvesters/bom_weather.py --city sydney --year 2025
    python backend/harvesters/bom_weather.py --all-cities --year 2025
    python backend/harvesters/bom_weather.py --all-cities --all-years

University of Melbourne, Cluster and Cloud Computing
"""

# COMP90024 Team 2

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from pathlib import Path

from meteostat import Daily

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from backend.harvesters.config import CITIES, CITY_NAMES, DATA_RAW, WEATHER_YEARS


def fetch_one(city: str, year: int) -> None:
    if city not in CITIES:
        sys.exit(f"Unknown city '{city}'. Choices: {CITY_NAMES}")
    cfg = CITIES[city]
    station = cfg["meteostat_station"]

    start = datetime(year, 1, 1)
    end   = datetime(year, 12, 31) if year < datetime.now().year else datetime.now()

    print(f"[bom] city={city}  year={year}  station={station}  ", end="", flush=True)
    try:
        df = Daily(station, start, end).fetch()
    except Exception as e:
        print(f"ERROR: {e}")
        return

    if df.empty:
        print("no data")
        return

    df = df.reset_index()
    df = df.dropna(axis=1, how="all")
    df["city"]    = city
    df["station"] = station

    out = DATA_RAW / f"weather_{city}_{year}.csv"
    df.to_csv(out, index=False)
    print(f"rows={len(df)}  -> {out.name}")


def main():
    ap = argparse.ArgumentParser()
    g_city = ap.add_mutually_exclusive_group(required=True)
    g_city.add_argument("--city", choices=CITY_NAMES)
    g_city.add_argument("--all-cities", action="store_true")

    g_year = ap.add_mutually_exclusive_group(required=True)
    g_year.add_argument("--year", type=int, choices=WEATHER_YEARS)
    g_year.add_argument("--all-years", action="store_true")

    args = ap.parse_args()

    cities = CITY_NAMES if args.all_cities else [args.city]
    years  = WEATHER_YEARS if args.all_years else [args.year]

    for c in cities:
        for y in years:
            fetch_one(c, y)
            time.sleep(0.5)   # polite to meteostat


if __name__ == "__main__":
    main()
