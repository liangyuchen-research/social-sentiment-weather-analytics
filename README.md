# Kubernetes Pipeline for Linking Social Media Sentiment with Daily Weather Data

A distributed analytics system for collecting social media posts, scoring text sentiment, and matching posts to daily weather in Melbourne, Sydney, and Brisbane. Developed at the University of Melbourne for Cluster and Cloud Computing.

**Stack:** Kubernetes, Fission, Elasticsearch, Python, VADER, and Jupyter. The original deployment ran on Melbourne Research Cloud.

The repository includes the harvesting and cleaning implementations, REST API functions, Elasticsearch mappings, Kubernetes/Fission configuration, analysis notebooks, and automated tests.

## My contribution

A five-person team project. I built the data path end to end: rate-limit-aware harvesters for the Reddit, Bluesky and Mastodon APIs across three Australian cities, the historical backfill that pulled older posts without duplicating stored records, the join between sentiment scores for 1.22M filtered posts and 12.5K daily weather rows in Elasticsearch, and the Fission serverless functions that expose the combined dataset.

## Architecture

```text
Reddit / Bluesky / Mastodon       Daily weather observations
             |                              |
             +----------- Harvesters --------+
                              |
              Normalize, deduplicate, score sentiment
                              |
                    Match by city and local date
                              |
          Elasticsearch: posts_raw / posts_clean / weather_daily
                              |
                     Fission REST query API
                              |
               Exploratory analysis and monitoring notebooks
```

The project report recorded **1,218,705 analytical posts** and **12,453 weather records** on 13 May 2026. These are historical dataset counts, not a throughput benchmark. Raw post collections and credentials are excluded from this public repository.

## Quick start

Use Python 3.12 for the validated local environment. Create and activate a virtual environment, then run:

```bash
python -m pip install -r requirements.txt
python scripts/run_demo.py
python -m pytest test -q
```

The demo runs the actual cleaning, VADER scoring, city/date weather join, and Elasticsearch document preparation on six synthetic posts. It uses a temporary directory and needs no credentials, API access, or cloud cluster. The automated tests use synthetic records and mocked services.

## Run with collected data

Copy `.env.example` to `.env` and supply credentials for the services you use. Run commands from the repository root:

```bash
python backend/harvesters/reddit_api.py --city melbourne --year 2025 --max-records 500
python backend/harvesters/bom_weather.py --city melbourne --year 2025
python backend/cleaning/clean_pipeline.py
python database/bulk_upload.py --target posts_clean --dry-run
```

Data are stored under `data/raw/` and `data/cleaned/`. Set `SOCIAL_WEATHER_DATA_DIR` in the process environment to use another directory. The harvesting commands access external services and write per-city/year files. Keep previous collections in a separate data directory when starting a new run.

For indexing, configure Elasticsearch in `.env`, create the mappings, and upload:

```bash
python database/setup_indices.py
python database/bulk_upload.py --all
```

## Cloud deployment and analysis

[Infrastructure setup](installation/installation.md) covers Kubernetes, Elasticsearch, and Fission. [Function deployment](backend/fission/README.md) documents package builds, secrets, routes, and scheduled ingestion. Deployment requires your own authorized cluster and API credentials.

To use the analysis notebooks:

```bash
python -m pip install -r requirements-notebooks.txt
jupyter lab frontend/
```

The notebooks expect a populated Fission query API. Its default local address is `http://localhost:9090/api/query`, reachable through the documented router port-forward. Set `ANALYTICS_API_URL` before starting the notebook kernel to use another endpoint.

## Repository guide

| Directory | Contents |
| --- | --- |
| [backend/harvesters](backend/harvesters/README.md) | Social API collectors, historical backfill, and weather observations |
| [backend/cleaning](backend/cleaning/README.md) | Text normalization, language filtering, sentiment scoring, and weather joins |
| [backend/fission](backend/fission/README.md) | Five serverless functions, package builder, routes, timers, and deployment specifications |
| [database](database/README.md) | Elasticsearch client, index mappings, and streaming bulk upload |
| [frontend](frontend/) | Exploratory analysis and Melbourne monitoring notebooks |
| [installation](installation/installation.md) | Cluster, storage, Elasticsearch, and Kibana configuration |
| [test](test/) | Unit, integration, data-quality, and API smoke checks |
| [scripts](scripts/) | Offline demonstration and validation helpers |

See [reproduction and validation](docs/reproduction.md), [data interpretation](docs/data-and-limitations.md), and [source provenance](docs/provenance.md). Contributor attribution is recorded in [AUTHORS.md](AUTHORS.md).
