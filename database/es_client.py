"""ElasticSearch connection helper.

Reads from environment so the same code works:
  - locally (port-forwarded ES on https://localhost:9200)
  - inside a Fission function (in-cluster service DNS)
  - inside a Jupyter notebook frontend

Environment variables (all optional except ES_PASSWORD):
  ES_HOST       default: https://localhost:9200
  ES_USER       default: elastic
  ES_PASSWORD   required
  ES_VERIFY_CERTS  default: true (set ES_CA_CERT for a cluster certificate)
  ES_CA_CERT    optional path to CA cert if you want strict verification

University of Melbourne, Cluster and Cloud Computing
"""

# COMP90024 Team 2

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")


@lru_cache(maxsize=1)
def get_es():
    from elasticsearch import Elasticsearch

    host          = os.environ.get("ES_HOST", "https://localhost:9200")
    user          = os.environ.get("ES_USER", "elastic")
    password      = os.environ.get("ES_PASSWORD")
    verify_certs  = os.environ.get("ES_VERIFY_CERTS", "true").lower() == "true"
    ca_cert       = os.environ.get("ES_CA_CERT") or os.environ.get("ES_CA_CERTS") or None
    if ca_cert:
        ca_path = Path(ca_cert).expanduser()
        if not ca_path.is_absolute():
            ca_path = Path(__file__).resolve().parents[1] / ca_path
        ca_cert = str(ca_path)
    server_name = os.environ.get("ES_TLS_SERVER_NAME") or None

    if not password:
        raise RuntimeError(
            "ES_PASSWORD is not set. Add it to your .env file:\n"
            "  ES_PASSWORD=<the password printed by helm install>")

    return Elasticsearch(
        [host],
        basic_auth=(user, password),
        verify_certs=verify_certs,
        ca_certs=ca_cert,
        ssl_assert_hostname=server_name,
        request_timeout=60,
    )


def ping():
    es = get_es()
    info = es.info()
    print(f"Connected to ES {info['version']['number']}  cluster={info['cluster_name']}")
    return info


if __name__ == "__main__":
    ping()
