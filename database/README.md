# Elasticsearch storage

The database utilities create index mappings and upload the local pipeline outputs. Configure the connection with `.env.example` at the repository root.

```bash
python database/es_client.py
python database/setup_indices.py
python database/bulk_upload.py --all --dry-run
python database/bulk_upload.py --all
```

| Index | Input | Document identity |
| --- | --- | --- |
| `posts_raw` | Reddit, Bluesky, and Mastodon JSONL files in `data/raw/` | Platform and source identifier |
| `posts_clean` | Per-city JSONL files in `data/cleaned/` | Platform and source identifier |
| `weather_daily` | Weather CSV files in `data/raw/` | City and date |

The shared `SOCIAL_WEATHER_DATA_DIR` environment setting applies to both cleaning and upload. Bulk upload streams records in batches and raises an error if Elasticsearch rejects documents. Repeated uploads use deterministic identifiers.

`setup_indices.py` creates missing indexes without deleting existing data. The optional `--recreate` flag explicitly deletes and recreates an index; it is not part of the quick start. Use `--only <index>` to target a single mapping.

The analytical mapping is strict. The upload helper keeps only declared fields, and the tests check mapping compatibility. Certificate verification is enabled by default. Use `ES_CA_CERT` for a private CA and `ES_TLS_SERVER_NAME` when a local port-forward must verify the service hostname. See [infrastructure setup](../installation/installation.md).
