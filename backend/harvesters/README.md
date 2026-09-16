# Social and weather harvesters

Collectors for Reddit, Bluesky, Mastodon, and daily weather observations in Melbourne, Sydney, and Brisbane. Shared city queries, station identifiers, timezones, and data directories are defined in `config.py`.

Run from the repository root after installing `requirements.txt`:

```bash
python backend/harvesters/reddit_api.py --city melbourne --year 2025 --max-records 500
python backend/harvesters/bluesky_harvester.py --city sydney --year 2025 --limit 500
python backend/harvesters/mastodon_harvester.py --city brisbane --year 2025 --limit 500
python backend/harvesters/bom_weather.py --all-cities --year 2025
```

| Collector | Source and authentication | Output |
| --- | --- | --- |
| `reddit_api.py` | Arctic Shift post/comment archive API, no Reddit API key | `reddit_<city>_<year>.jsonl` |
| `bluesky_harvester.py` | atproto search and reply threads, `BLUESKY_HANDLE` and `BLUESKY_APP_PASSWORD` | `bluesky_<city>_<year>.jsonl` |
| `mastodon_harvester.py` | Public hashtag timelines, or authenticated search with `MASTODON_ACCESS_TOKEN` | `mastodon_<city>_<year>.jsonl` |
| `bom_weather.py` | Meteostat daily observations at configured WMO stations | `weather_<city>_<year>.csv` |

Add credentials to the root `.env` file using [.env.example](../../.env.example). Mastodon tokens are sent only to the configured authenticated instance. Fallback public instances do not receive that token.

Outputs are written under `data/raw/`. Set `SOCIAL_WEATHER_DATA_DIR` in the process environment for an alternate data root. Each command writes a city/year collection, so use a separate data directory when preserving an earlier harvest. The configured 2016–2026 study window does not guarantee historical coverage on every platform.

`--all-cities` and `--all-years` expand the collection scope. Use the single-city limits first. Reddit implements bounded retries for transient failures and HTTP 429 responses; Mastodon also backs off on rate limits. Bluesky collection reports a failed query and proceeds to the next configured query.

Social records retain source identifiers, text, city, timestamps, and engagement fields for downstream processing. Run [the cleaning pipeline](../cleaning/README.md) to convert platform-specific records to the common analytical schema.
