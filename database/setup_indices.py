"""Create ElasticSearch indices from mappings/*.json.

Usage:
    python database/setup_indices.py                  # create only if missing
    python database/setup_indices.py --recreate       # delete + recreate (DESTROYS DATA)
    python database/setup_indices.py --only posts_clean

Indices created:
    posts_raw      — straight from harvesters, before cleaning
    posts_clean    — after cleaning + sentiment + weather join
    weather_daily  — BOM / meteostat daily observations

University of Melbourne, Cluster and Cloud Computing
"""

# COMP90024 Team 2

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from database.es_client import get_es

MAPPINGS_DIR = Path(__file__).resolve().parent / "mappings"


def list_mappings() -> dict[str, dict]:
    out = {}
    for p in sorted(MAPPINGS_DIR.glob("*.json")):
        out[p.stem] = json.loads(p.read_text(encoding="utf-8"))
    return out


def create_index(es, name: str, body: dict, recreate: bool = False) -> str:
    exists = es.indices.exists(index=name)
    if exists and recreate:
        print(f"  [delete] {name}")
        es.indices.delete(index=name)
        exists = False
    if exists:
        return "already exists, skipped (use --recreate to reset)"
    es.indices.create(index=name, **body)
    return f"created  shards={body.get('settings', {}).get('number_of_shards', '?')}"


def main(only: str | None, recreate: bool):
    es = get_es()
    info = es.info()
    print(f"ElasticSearch {info['version']['number']}  cluster={info['cluster_name']}")

    mappings = list_mappings()
    if only:
        if only not in mappings:
            sys.exit(f"No mapping for index '{only}'. Available: {list(mappings)}")
        mappings = {only: mappings[only]}

    failures = []
    for idx, body in mappings.items():
        try:
            status = create_index(es, idx, body, recreate=recreate)
            print(f"  [{idx:14s}]  {status}")
        except Exception as e:
            print(f"  [{idx:14s}]  ERROR: {e}")
            failures.append(idx)
    if failures:
        raise RuntimeError("Failed to create indices: " + ", ".join(failures))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="only operate on this single index name")
    ap.add_argument("--recreate", action="store_true",
                    help="DROP existing indices and recreate (DESTROYS DATA)")
    args = ap.parse_args()
    main(args.only, args.recreate)
