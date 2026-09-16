# Architecture and data flow

This description summarizes the supplied project report. It is not a deployment
guide and does not imply that source manifests are included.

## Collection

Social harvesters gather Reddit, Bluesky and Mastodon posts associated with
Melbourne, Sydney and Brisbane. The reported collection workflow supports
incremental ingestion and historical Reddit backfill, handles platform rate
limits, and records platform and city information for downstream grouping.

A separate harvester obtains daily Bureau of Meteorology observations. Weather
records are normalized into a city/date structure suitable for analytical joins.

## Processing and storage

Elasticsearch separates raw social records from analytical records. The cleaning
workflow normalizes text and dates, filters English-language posts, removes
duplicates, and computes VADER sentiment scores. Analytical posts are enriched
with daily weather values using city and date as the matching fields.

The report describes three principal indexes: `posts_raw`, `posts_clean`, and
`weather_daily`. VADER is a rule-based sentiment tool, not a model fine-tuned
within this project. Its scores measure text sentiment rather than clinical
mental health or the emotional state of every resident in a city.

## Cloud services and access

The reported Kubernetes cluster has one master and three worker nodes on
Melbourne Research Cloud. Fission functions divide the workflow into social
collection, weather collection, cleaning and API queries. Elasticsearch stores
the records and performs aggregation.

The query API serves JSON to Jupyter notebooks. Query parameters described in
the report include analytical mode, city, platform and date range. The report
names summary, post and daily aggregation views. Public endpoint addresses and
authentication details are not published here.

Reported modularity and platform capabilities should not be confused with
measured service-level objectives. The available material does not establish
load-tested throughput, guaranteed availability, or independently validated
autoscaling behavior.
