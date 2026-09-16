# Architecture and data flow

The repository supports local batch processing and Fission functions deployed on Kubernetes.

## Collection

Reddit collection uses the Arctic Shift archive API. The local Bluesky collector uses the atproto client, while the Fission collector calls the Bluesky HTTP APIs directly. Mastodon supports public hashtag timelines or authenticated search. Posts are tagged using city-specific queries for Melbourne, Sydney, and Brisbane. Local weather collection retrieves daily observations from configured WMO stations through Meteostat; the Fission weather function uses Open-Meteo and stores its source explicitly.

Collection coverage depends on each service and the requested date window. The configuration retains the 2016–2026 study period, but this does not imply that every platform supplies data for every year.

## Processing

The local pipeline normalizes text, removes duplicates, filters language, converts timestamps to each city's local date, and computes VADER sentiment. It joins posts to daily weather using city and local date. VADER is a rule-based text sentiment method.

Three Elasticsearch indexes separate raw records, analytical posts, and daily weather: `posts_raw`, `posts_clean`, and `weather_daily`. Bulk upload uses deterministic document identifiers and streams records in bounded batches.

## Services

Five Fission functions implement social collection, Reddit collection, weather collection, incremental cleaning, and analytical queries. The REST query API provides health, summary, post, daily, and temperature-bucket views for the Jupyter notebooks. Routes and timers are under `backend/fission/specs/`.

The original deployment used Melbourne Research Cloud. The published manifests require an authorized Kubernetes environment, available storage classes, and operator-managed credentials. No public live service is maintained by this repository.
