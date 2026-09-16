"""Regression checks for fresh checkouts and local export correctness."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pandas as pd
import pytest

from backend.cleaning import clean_pipeline
from database import bulk_upload

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize('entry', [
    'backend/harvesters/reddit_api.py',
    'backend/harvesters/bluesky_harvester.py',
    'backend/harvesters/mastodon_harvester.py',
    'backend/harvesters/bom_weather.py',
    'backend/cleaning/clean_pipeline.py',
    'database/setup_indices.py',
    'database/bulk_upload.py',
])
def test_command_help_from_another_directory(entry, tmp_path):
    env = dict(os.environ, SOCIAL_WEATHER_DATA_DIR=str(tmp_path / 'data'), PYTHONUTF8='1')
    result = subprocess.run([sys.executable, str(ROOT / entry), '--help'], cwd=tmp_path,
                            env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert 'usage:' in result.stdout.lower()


def test_all_filtered_posts_keep_datetime_schema():
    raw = pd.DataFrame([{'platform': 'reddit', 'city': 'sydney', 'id': 'x',
                         'author': '[deleted]', 'text_raw': 'Removed author example',
                         'created_utc': '2026-01-01T00:00:00Z', 'engagement': 0,
                         'url': None}])
    cleaned = clean_pipeline.clean_posts(raw, keep_langs=(), with_sentiment=False)
    assert cleaned.empty
    assert {'created_local', 'date_local', 'hour_local', 'year'} <= set(cleaned)


def test_export_uses_strict_json_and_preserves_local_clock(tmp_path, monkeypatch):
    raw, clean = tmp_path / 'raw', tmp_path / 'cleaned'
    raw.mkdir()
    clean.mkdir()
    monkeypatch.setattr(clean_pipeline, 'DATA_RAW', raw)
    monkeypatch.setattr(clean_pipeline, 'DATA_CLEAN', clean)
    monkeypatch.setattr(clean_pipeline, 'detect_lang', lambda text: 'en')
    posts = [{'city': 'sydney', 'id': 'r1', 'author': 'sample',
              'text': 'A pleasant sunny afternoon by the harbour',
              'created_at': '2026-01-01T00:15:00Z'}]
    (raw / 'reddit_sydney_2026.jsonl').write_text(json.dumps(posts[0]) + '\n', encoding='utf-8')
    (raw / 'weather_sydney_2026.csv').write_text('time,tavg,prcp\n2026-01-01,25,\n', encoding='utf-8')
    clean_pipeline.main(all_langs=False, with_sentiment=True)
    text = (clean / 'sydney.jsonl').read_text(encoding='utf-8')
    row = json.loads(text, parse_constant=lambda value: pytest.fail(f'Invalid JSON constant: {value}'))
    assert row['prcp'] is None
    assert row['created_utc'] == '2026-01-01T00:15:00Z'
    assert row['created_local'] == '2026-01-01T11:15:00'
    assert row['hour_local'] == '2026-01-01T11:00:00'
    assert isinstance(row['sentiment'], float)


def test_raw_upload_includes_reddit(tmp_path, monkeypatch):
    monkeypatch.setattr(bulk_upload, 'RAW', tmp_path)
    (tmp_path / 'reddit_sydney_2026.jsonl').write_text(
        json.dumps({'platform': 'reddit', 'id': 'r1', 'text': 'Synthetic sample'}) + '\n', encoding='utf-8')
    actions = list(bulk_upload.gen_posts_raw())
    assert len(actions) == 1
    assert actions[0]['_id'] == 'reddit:r1'
