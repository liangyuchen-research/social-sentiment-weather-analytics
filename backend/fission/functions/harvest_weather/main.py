"""Fission function: harvest daily weather into Elasticsearch weather_daily.

Default timer mode:
    POST /ingest/harvest-weather

This fetches recent daily observations for all 3 cities and upserts documents
using _id = <city>:<YYYY-MM-DD>. Cleaned posts join weather on city + local date.
"""

# COMP90024 Team 2

import math
import os
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(__file__))

import requests
from elasticsearch import Elasticsearch, helpers
from flask import jsonify, request


CITY_CONFIG = {
    "sydney": {
        "latitude": -33.8688,
        "longitude": 151.2093,
        "station": "open-meteo-sydney",
        "bom_station_id": "066062",
        "tz": "Australia/Sydney",
    },
    "melbourne": {
        "latitude": -37.8136,
        "longitude": 144.9631,
        "station": "open-meteo-melbourne",
        "bom_station_id": "086338",
        "tz": "Australia/Melbourne",
    },
    "brisbane": {
        "latitude": -27.4698,
        "longitude": 153.0251,
        "station": "open-meteo-brisbane",
        "bom_station_id": "040842",
        "tz": "Australia/Brisbane",
    },
}

DAILY_FIELDS = [
    "temperature_2m_mean",
    "temperature_2m_min",
    "temperature_2m_max",
    "precipitation_sum",
    "snowfall_sum",
    "wind_direction_10m_dominant",
    "wind_speed_10m_max",
    "wind_gusts_10m_max",
    "sunshine_duration",
]
FALLBACK_DAILY_FIELDS = [
    "temperature_2m_mean",
    "temperature_2m_min",
    "temperature_2m_max",
    "precipitation_sum",
]


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


def _requested_cities(args):
    raw = args.get("cities") or args.get("city")
    if not raw or raw.lower() == "all":
        return list(CITY_CONFIG)
    cities = [c.strip().lower() for c in raw.split(",") if c.strip()]
    bad = [c for c in cities if c not in CITY_CONFIG]
    if bad:
        raise ValueError("unknown cities %s; choices=%s" % (bad, list(CITY_CONFIG)))
    return cities


def _date_window(args):
    today = datetime.now(tz=timezone.utc).date()
    mode = args.get("mode", "recent").lower()
    if mode == "year":
        year = int(args.get("year", today.year))
        start = datetime(year, 1, 1)
        end_date = datetime(year, 12, 31).date()
        end = datetime.combine(min(end_date, today), datetime.min.time())
    elif mode == "range":
        start = datetime.fromisoformat(args["from"])
        end = datetime.fromisoformat(args["to"])
    elif mode == "recent":
        days = int(args.get("days", os.environ.get("WEATHER_LOOKBACK_DAYS", "7")))
        if days < 1:
            raise ValueError("days must be a positive integer")
        start_date = today - timedelta(days=max(days - 1, 0))
        start = datetime.combine(start_date, datetime.min.time())
        end = datetime.combine(today, datetime.min.time())
    else:
        raise ValueError("mode must be recent, range, or year")
    if start.date() > end.date():
        raise ValueError("start date must not be later than end date")
    return mode, start, end


def _clean_value(value):
    if value is None:
        return None
    try:
        if not math.isfinite(value):
            return None
    except TypeError:
        pass
    if hasattr(value, "item"):
        return value.item()
    return value


def _weather_endpoint(start, end):
    today = datetime.now(tz=timezone.utc).date()
    if (today - start.date()).days <= 92 and end.date() >= today - timedelta(days=16):
        return "https://api.open-meteo.com/v1/forecast"
    return "https://archive-api.open-meteo.com/v1/archive"


def _fetch_open_meteo(cfg, start, end, daily_fields):
    params = {
        "latitude": cfg["latitude"],
        "longitude": cfg["longitude"],
        "start_date": start.date().isoformat(),
        "end_date": end.date().isoformat(),
        "daily": ",".join(daily_fields),
        "timezone": cfg["tz"],
    }
    response = requests.get(_weather_endpoint(start, end), params=params, timeout=25)
    response.raise_for_status()
    payload = response.json()
    if payload.get("error"):
        raise RuntimeError(payload.get("reason") or "Open-Meteo API error")
    return payload.get("daily") or {}


def _fetch_city(city, start, end):
    cfg = CITY_CONFIG[city]
    try:
        daily = _fetch_open_meteo(cfg, start, end, DAILY_FIELDS)
    except Exception:
        daily = _fetch_open_meteo(cfg, start, end, FALLBACK_DAILY_FIELDS)

    rows = []
    dates = daily.get("time") or []
    for i, date_str in enumerate(dates):
        if not date_str:
            continue
        day_date = datetime.fromisoformat(date_str).date()
        rec = {
            "city": city,
            "station": cfg["station"],
            "bom_station_id": cfg["bom_station_id"],
            "date": date_str,
            "year": day_date.year,
            "tavg": _clean_value(_daily_value(daily, "temperature_2m_mean", i)),
            "tmin": _clean_value(_daily_value(daily, "temperature_2m_min", i)),
            "tmax": _clean_value(_daily_value(daily, "temperature_2m_max", i)),
            "prcp": _clean_value(_daily_value(daily, "precipitation_sum", i)),
            "snow": _clean_value(_daily_value(daily, "snowfall_sum", i)),
            "wdir": _clean_value(_daily_value(daily, "wind_direction_10m_dominant", i)),
            "wspd": _clean_value(_daily_value(daily, "wind_speed_10m_max", i)),
            "wpgt": _clean_value(_daily_value(daily, "wind_gusts_10m_max", i)),
            "pres": None,
            "tsun": _clean_value(_sunshine_minutes(_daily_value(daily, "sunshine_duration", i))),
            "harvested_at": datetime.now(tz=timezone.utc).isoformat(),
            "source": "open-meteo",
        }
        rows.append(rec)
    return rows


def _daily_value(daily, name, index):
    values = daily.get(name) or []
    if index >= len(values):
        return None
    return values[index]


def _sunshine_minutes(value):
    if value is None:
        return None
    return round(float(value) / 60.0, 2)


def _bulk_index(es, rows):
    actions = []
    for rec in rows:
        city = rec.get("city")
        date_str = rec.get("date")
        if not city or not date_str:
            continue
        actions.append({
            "_op_type": "index",
            "_index": "weather_daily",
            "_id": "%s:%s" % (city, date_str),
            "_source": rec,
        })
    if not actions:
        return 0, 0
    success, errors = helpers.bulk(es, actions, raise_on_error=False, request_timeout=180)
    return success, len(errors) if isinstance(errors, list) else errors


def main():
    args = request.args
    try:
        cities = _requested_cities(args)
        mode, start, end = _date_window(args)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 400

    per_city = {}
    errors = []
    rows = []
    for city in cities:
        try:
            city_rows = _fetch_city(city, start, end)
            per_city[city] = len(city_rows)
            rows.extend(city_rows)
        except Exception as exc:
            per_city[city] = 0
            errors.append({"city": city, "error": str(exc)})

    indexed, bulk_errors = _bulk_index(_es(), rows)
    return jsonify({
        "mode": mode,
        "cities": cities,
        "window": [start.date().isoformat(), end.date().isoformat()],
        "per_city": per_city,
        "fetched_total": len(rows),
        "indexed_total": indexed,
        "bulk_errors": bulk_errors,
        "errors": errors,
    }), 200
