"""Run the real local pipeline on small synthetic records without network access."""
from pathlib import Path
import json
import os
import subprocess
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]


def main():
    with TemporaryDirectory(prefix='sentiment-weather-demo-') as directory:
        data = Path(directory)
        raw = data / 'raw'
        raw.mkdir()
        (data / 'cleaned').mkdir()
        for city in ('sydney', 'melbourne', 'brisbane'):
            records = [
                {'platform': 'reddit', 'city': city, 'id': f'{city}-positive',
                 'author': 'sample-positive', 'text': 'A wonderful sunny afternoon and a lovely walk outside.',
                 'created_at': '2026-01-01T01:00:00Z', 'score': 3},
                {'platform': 'reddit', 'city': city, 'id': f'{city}-negative',
                 'author': 'sample-negative', 'text': 'Awful rain and a frustrating journey through the cold storm.',
                 'created_at': '2026-01-02T01:00:00Z', 'score': 2},
            ]
            (raw / f'reddit_{city}_2026.jsonl').write_text(
                ''.join(json.dumps(record) + '\n' for record in records), encoding='utf-8')
            (raw / f'weather_{city}_2026.csv').write_text(
                f'time,city,tavg,tmin,tmax,prcp\n2026-01-01,{city},24,18,29,0\n'
                f'2026-01-02,{city},16,12,19,9\n', encoding='utf-8')
        env = dict(os.environ, SOCIAL_WEATHER_DATA_DIR=str(data), PYTHONUTF8='1')
        commands = [
            ['backend/cleaning/clean_pipeline.py', '--all-langs'],
            ['database/bulk_upload.py', '--all', '--dry-run'],
        ]
        for entry, *args in commands:
            subprocess.run([sys.executable, str(ROOT / entry), *args], env=env,
                           cwd=directory, check=True)
        counts = {city: len((data / 'cleaned' / f'{city}.jsonl').read_text(encoding='utf-8').splitlines())
                  for city in ('sydney', 'melbourne', 'brisbane')}
        assert all(count == 2 for count in counts.values()), counts
        print('Demo passed: six synthetic posts were scored, weather-matched, and prepared for indexing.')


if __name__ == '__main__':
    main()
