"""Run frontend notebook cells against synthetic responses without network calls."""

from __future__ import annotations

import argparse
import copy
from datetime import datetime
import json
import math
import os
from pathlib import Path
import sys
from unittest.mock import patch
from zoneinfo import ZoneInfo

os.environ.setdefault('MPLBACKEND', 'Agg')

import matplotlib.pyplot as plt
import pandas as pd


def fixture(params, scenario):
    """Mirror api_query's public JSON contract with entirely invented records."""
    city = params.get('city', 'melbourne')
    mode = params.get('mode', 'summary')
    today = datetime.now(ZoneInfo('Australia/Melbourne')).date()
    if mode == 'health':
        return {'status': 'ok', 'es_version': 'synthetic', 'cluster': 'synthetic-check'}
    if mode == 'summary':
        return {'total': 0 if scenario == 'empty' else 2700,
            'by_city': {} if scenario == 'empty' else {'sydney': 900, 'melbourne': 900, 'brisbane': 900},
            'by_platform': {'reddit': 1200, 'bluesky': 900, 'mastodon': 600},
            'by_sentiment': {'positive': 1300, 'neutral': 500, 'negative': 900},
            'date_range': ['2022-01-01', today.isoformat()]}
    if mode == 'daily':
        if 'from' in params:
            dates = pd.date_range(params['from'], params.get('to', today.isoformat()))
        else:
            dates = pd.date_range('2022-01-01', today.isoformat(), freq='14D')
        rows = []
        for i, date in enumerate(dates):
            rows.append({'date': date.strftime('%Y-%m-%d'), 'count': 20+i%9,
                'sentiment_mean': 0.1+0.15*math.sin(i*0.7),
                'tmax_mean': 12+i%28, 'tmin_mean': 8+i%12,
                'prcp_mean': [0,0,0.5,2.0,12.0][i%5]})
        if scenario == 'weather_pending' and params.get('from') == today.isoformat():
            for row in rows:
                row['tmax_mean'] = row['prcp_mean'] = None
        return {'days': rows}
    if mode == 'temp_buckets':
        names = ['cold (<18)','mild (18-24)','warm (24-30)','hot (30-35)','extreme (>=35)']
        return {'buckets': [{'bucket': label, 'count': 100+i,
            'sentiment_mean': 0.12-i*0.02, 'negative_count':20,
            'neutral_count':30, 'positive_count':50+i} for i,label in enumerate(names)]}
    if mode == 'posts':
        if scenario == 'no_today_posts' and params.get('from') == today.isoformat():
            return {'total': 0, 'rows': []}
        if scenario == 'missing_event_posts' and city == 'melbourne' and params.get('from') == '2025-12-14':
            return {'total': 0, 'rows': []}
        date = params.get('from', today.isoformat())
        rows = []
        for i in range(min(int(params.get('size', 60)),60)):
            sentiment = 0.6*math.sin(i)
            rows.append({'id': f'synthetic-{city}-{date}-{i}', 'city':city,
                'platform':['reddit','mastodon','bluesky'][i%3], 'date_local':date,
                'created_local':f'{date}T{i%24:02d}:00:00', 'sentiment':sentiment,
                'sentiment_label':'positive' if sentiment>0.05 else 'negative' if sentiment<-.05 else 'neutral',
                'tavg':20+i%8,'tmax':15+i%24,'prcp':[0,0.5,2,12][i%4],
                'text':f'Synthetic discussion of sunshine parks rain cycling community {i%7}.'})
        return {'total':len(rows), 'rows':rows}
    raise AssertionError(f'Unexpected API mode: {mode}')


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scenario', choices=['populated','empty','missing_event_posts','weather_pending','no_today_posts'], default='populated')
    parser.add_argument('--plots-dir', type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    paths = [*sorted(root.glob('frontend/*.ipynb')), root/'test/frontend_api_smoke_test.ipynb']
    if args.scenario in {'weather_pending','no_today_posts'}:
        paths = [root/'frontend/realtime_melbourne_monitor.ipynb']
    if args.scenario == 'missing_event_posts':
        paths = [root/'frontend/exploratory_analysis.ipynb']

    class Response:
        def __init__(self, payload):self.payload = payload
        def raise_for_status(self):pass
        def json(self):return copy.deepcopy(self.payload)

    calls = []
    def request(url, params=None, **kwargs):
        calls.append(dict(params or {}))
        return Response(fixture(params or {},args.scenario))

    for path in paths:
        namespace = {'__name__':'__frontend_check__', 'display':lambda *values:None}
        notebook = json.loads(path.read_text(encoding='utf8'))
        cells = 0
        figures = 0
        def show():
            nonlocal figures
            for number in plt.get_fignums():
                figures += 1
                if args.plots_dir:
                    args.plots_dir.mkdir(parents=True,exist_ok=True)
                    plt.figure(number).savefig(args.plots_dir/f'{path.stem}-{figures:02d}-synthetic.png', bbox_inches='tight')
            plt.close('all')
        with patch('requests.get', side_effect=request), patch.object(plt,'show',side_effect=show):
            try:
                for index, cell in enumerate(notebook['cells']):
                    if cell['cell_type'] != 'code':continue
                    exec(compile(''.join(cell['source']),f'{path.name}:cell-{index}','exec'),namespace)
                    cells += 1
                show()
            except RuntimeError as error:
                if args.scenario != 'empty' or 'cleaned-post index is empty' not in str(error):raise
                print(f'PASS {path.name}: empty corpus rejected with actionable message')
            else:
                if args.scenario=='empty':raise AssertionError('Empty-corpus guard did not execute.')
                print(f'PASS {path.name}: {cells} complete code cells, {figures} figures, scenario={args.scenario}')
    print(f'Intercepted {len(calls)} HTTP requests. No network or Elasticsearch connection was used.')
    print('All records are synthetic. This check makes no research-result claim.')


if __name__=='__main__':main()
