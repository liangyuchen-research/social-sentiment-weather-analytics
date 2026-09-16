# Fission backend

Five Python functions implement ingestion, transformation, and the REST interface used by the analysis notebooks. The deployment preserves the original project structure and schedules.

| Function | HTTP route | Role |
| --- | --- | --- |
| `api-query` | `GET /api/query` | Read cleaned posts, counts, and aggregate sentiment/weather statistics. |
| `clean-posts` | `POST /ingest/clean-posts` | Normalize English text, score sentiment with VADER, and join daily weather by city and local date. |
| `harvest-social` | `POST /ingest/harvest-social` | Collect Reddit, Bluesky, and Mastodon records into `posts_raw`. |
| `harvest-reddit` | `POST /ingest/harvest-reddit` | Earlier standalone Reddit ingestion endpoint, retained alongside the combined harvester. |
| `harvest-weather` | `POST /ingest/harvest-weather` | Retrieve daily Open-Meteo weather and upsert `weather_daily`. |

The notebooks use only `api-query`. Ingestion and cleaning have separate HTTP routes and independent timers, rather than a guaranteed sequence of dependent invocations. The query function reads `posts_clean`, which already contains the joined weather values.

## Requirements

- An authorized Kubernetes cluster with Fission installed, plus its matching CLI.
- Elasticsearch accessible from the function pods, with the mappings in [`database/`](../../database/README.md) initialized before ingestion.
- Python and pip on the build machine. The archive builder can run on Windows or Linux.
- Credentials for each source API you enable. No credentials are included.

The environment name `python39x` is retained from the original project. Its spec now pins the public **official Fission Python 3.9 runtime and builder** by registry digest. The original teaching-staff image is no longer required. These are legacy Python 3.9 images, preserved for deployment compatibility; upgrading the runtime should be accompanied by deployment testing.

The official runtime provides Flask. Each deployment archive includes its remaining dependencies as pure-Python packages, suitable for the Alpine runtime. The Elasticsearch client is constrained to the 8.x series. Elastic documents compatibility with 9.x servers, subject to breaking changes, in its [client compatibility guide](https://www.elastic.co/docs/reference/elasticsearch/clients/python). No live Elasticsearch or Kubernetes deployment is needed for the offline tests below.

## Build deployment archives

From the repository root, activate the project environment and run:

```bash
python backend/fission/build_deploy_archives.py
```

This builds `api_query.zip`, `clean_posts.zip`, and the three harvester ZIPs inside `backend/fission/`. The specs reference these generated archives, so this step must precede `fission spec apply`. Dependencies are resolved for Python 3.9 using universal wheels. `langdetect` is installed from its pure-Python distribution, with its `six` dependency listed explicitly. Platform-specific Windows or glibc extensions are not included.

Each build receives a separate `.fission_build/` directory. Existing deployment ZIPs are copied into that build directory before replacement. Build outputs and downloaded dependencies are ignored by Git. The per-function `build.sh` files support source-package builds as an alternative, while the supplied package specs use prebuilt deployment archives.

## Configure secrets

Create `es-creds` in the function namespace, `default`. Set the service URL and password for your own cluster. For a private certificate authority, place its certificate in a local `ca.crt` file and include it in the secret:

```bash
kubectl create secret generic es-creds \
  --from-literal=ES_HOST=https://elasticsearch-es-http.elastic.svc.cluster.local:9200 \
  --from-literal=ES_USER=elastic \
  --from-literal=ES_PASSWORD='<ELASTIC_PASSWORD>' \
  --from-literal=ES_VERIFY_CERTS=true \
  --from-literal=ES_CA_CERTS=/secrets/default/es-creds/ca.crt \
  --from-file=ca.crt=./ca.crt
```

The functions read environment variables first, then Fission-mounted secrets. `ES_HOST` and `ES_PASSWORD` are required. Certificate verification defaults to enabled. `ES_CA_CERTS` is the **path inside the function container**, not a workstation path. Omit the CA path and file only when the Elasticsearch certificate already chains to a trusted public CA.

`harvest-social` also references a `social-creds` secret. Create it even when only the unauthenticated Reddit or Mastodon tag endpoints are enabled:

```bash
kubectl create secret generic social-creds \
  --from-literal=HARVEST_MAX_RECORDS=100
```

Add `BLUESKY_HANDLE` and `BLUESKY_APP_PASSWORD` to enable the Bluesky collector. Authenticated Mastodon search uses `MASTODON_ACCESS_TOKEN` and `MASTODON_INSTANCE` for the issuing instance. `MASTODON_MODE` accepts `auto`, `A` (public tag timelines), or `B` (authenticated search). API availability and authentication policies remain subject to the source services.

## Apply and inspect the deployment

First initialize the Elasticsearch mappings using the root setup instructions. Then, from `backend/fission/`:

```bash
fission spec apply --specdir specs/
fission package list
fission function list
fission route list
```

Applying the supplied specs also enables timers: social ingestion every minute, weather ingestion every ten minutes, and cleaning every ten minutes. The social timer retains its original resource name ending in `every-10min`, but its actual cron expression is every minute. Review the schedule before applying it to a new cluster, since invocations can overlap and source APIs impose rate limits.

Stable document IDs make repeat ingestion idempotent. They do not coordinate concurrent runs or guarantee complete source coverage. The cleaner scans raw records in chunks, checks IDs against `posts_clean`, and stops after one output batch per city. It skips previously cleaned records, so changes to their sentiment or weather fields require an explicit reprocessing workflow.

The inherited ID format is `<platform>:<source_id>`, with one city field per document. A post matching several cities is therefore stored once, and Reddit post/comment identifiers are not separately namespaced. Analyses should account for those limitations; changing the ID scheme requires a coordinated migration of raw and cleaned indices.

For local access to the deployed router:

```bash
kubectl port-forward -n fission service/router 9090:80
```

Keep this process running while using the notebook. The supplied routes have no application-level authentication. Keep ingestion endpoints restricted to the intended cluster or local port-forward access.

## Query and ingestion examples

```bash
curl 'http://localhost:9090/api/query?mode=health'
curl 'http://localhost:9090/api/query?mode=summary'
curl 'http://localhost:9090/api/query?mode=posts&city=sydney&size=3'
curl 'http://localhost:9090/api/query?mode=daily&city=melbourne&from=2025-01-01&to=2025-01-31'
curl 'http://localhost:9090/api/query?mode=temp_buckets&city=brisbane'
```

`health` checks the Elasticsearch connection and returns its version and cluster name. `summary` reports exact document totals, distributions, and date bounds across the cleaned index. Empty date bounds are returned as JSON null. The `posts` mode returns at most 1,000 records ordered by creation time. `daily` and `temp_buckets` return aggregate sentiment and weather statistics.

The following requests perform real ingestion or transformation on a deployed instance:

```bash
curl -X POST 'http://localhost:9090/ingest/harvest-social?platforms=reddit&hours=1&max_records=20'
curl -X POST 'http://localhost:9090/ingest/harvest-weather?days=7'
curl -X POST 'http://localhost:9090/ingest/clean-posts?cities=all&batch=2000'
```

Harvesting responses include per-source errors and indexing counts. A successful HTTP response does not imply every external source supplied records. City assignments come from the configured subreddits, search terms, or tags, rather than verified user locations. Reddit archive pagination and source search limits may omit records, so year mode is a bounded backfill rather than a guarantee of exhaustive retrieval.

## Offline verification

From the repository root:

```bash
python -m pytest test/unit_test/fission test/integration_test/test_fission_clean_flow.py -q
```

The tests use Flask request contexts and substitute Elasticsearch and source responses. They cover argument validation, TLS configuration, raw-to-clean weather joins, progress past already processed records, exact query totals, pagination termination, and package layout. They do not contact a live cluster or source API. A production deployment still needs a smoke test against its configured runtime, credentials, certificates, and index mappings.
