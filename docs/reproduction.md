# Reproduction and verification

The repository contains the original project implementation, including local
harvesters, cleaning and weather matching, Elasticsearch ingestion, Fission
functions and deployment specifications, and three analytical notebooks.
The source revision and subsequent maintenance are documented in
[provenance](provenance.md).

## Local verification

From the repository root, use Python 3.12 and a virtual environment:

```bash
python -m pip install -r requirements.txt
python scripts/validate_repository.py
python -m pytest test -q
python scripts/run_demo.py
```

The demonstration creates six synthetic posts and daily weather records across
three cities in a temporary directory. It runs the actual cleaning, VADER
sentiment scoring, city/date matching, and Elasticsearch upload preparation.
It does not contact social networks or require an Elasticsearch service.

To check every notebook code cell, install the plotting dependencies and use
the offline notebook runner:

```bash
python -m pip install -r requirements-notebooks.txt
python test/check_frontend_notebooks.py
```

The runner supplies labeled synthetic API responses. These checks verify
notebook execution and response handling, not historical analytical results.

## Collecting and serving data

1. Configure external-service credentials using `.env.example`. See the
   [harvester guide](../backend/harvesters/README.md) for supported commands.
2. Collect social posts and weather data into the shared data directory.
   Process them with the [cleaning pipeline](../backend/cleaning/README.md).
3. Configure Elasticsearch TLS and credentials, create index mappings, and
   upload records using the [database guide](../database/README.md).
4. For scheduled collection and REST endpoints, follow the
   [Fission guide](../backend/fission/README.md) and
   [cluster installation notes](../installation/installation.md).
5. Set `ANALYTICS_API_URL` to the deployed endpoint before running the
   notebooks interactively.

Fission deployment archives target Python 3.9 independently of the local
Python 3.12 environment. Their packaging procedure is described in the Fission
guide. Credentials, cluster configuration and generated archives are ignored
by Git.

## Boundaries

The published checks cover local processing, request validation, mocked service
interactions, package construction and complete notebook execution with
synthetic responses. They do not establish that a live Kubernetes cluster,
external social API credentials or current service quotas are available.

The original corpus and deployed Elasticsearch snapshot are not bundled. The
historical counts in the README come from the project report, not a newly
recreated deployment. Current social-platform access and weather availability
can produce different datasets. See [data and limitations](data-and-limitations.md).

The retained raw-document key is `<platform>:<source_id>`. A post collected for
multiple cities shares one key, and Reddit post/comment IDs do not have separate
type namespaces in the original schema. Analyses should account for these
collection limitations. Migrating an existing dataset requires coordinated
changes to collection, indexing and cleaning rather than relabeling historical
counts.
