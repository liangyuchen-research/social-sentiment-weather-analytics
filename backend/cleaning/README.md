# Cleaning and weather matching

The pipeline reads social JSONL files and weather CSV files from `data/raw/`, normalizes text, removes duplicate records, filters English-language posts, scores sentiment with VADER, and joins daily weather by city and local date.

```bash
python backend/cleaning/clean_pipeline.py
python backend/cleaning/clean_pipeline.py --all-langs
python backend/cleaning/clean_pipeline.py --no-sentiment
```

Run from the repository root with dependencies from `requirements.txt`. Set `SOCIAL_WEATHER_DATA_DIR` before starting the process to use another data root.

Outputs:

- `data/cleaned/<city>.jsonl`: analytical records for each city.
- `data/cleaned/all_posts.parquet`: combined posts with available weather fields.
- `data/cleaned/weather_daily.parquet`: combined daily observations, when supplied.

Deduplication uses platform/source identity and a platform/city/author/text key. UTC timestamps retain their `Z` suffix. Local date and hour fields represent city-local wall-clock time and do not claim to be UTC. Missing weather values are written as JSON `null`.

Sentiment scoring is enabled by default and requires `vaderSentiment`. Use `--no-sentiment` explicitly to omit it. With no weather input, the pipeline produces posts without weather fields. An empty social input stops with an explanatory message.

The VADER scores describe text sentiment. They are not direct measurements of population mood or clinical mental health.
