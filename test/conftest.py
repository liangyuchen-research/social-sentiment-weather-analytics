# COMP90024 Team 2

import importlib.util
import sys
from pathlib import Path
import types

from flask import Flask
import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

FISSION_ROOT = PROJECT_ROOT / "backend" / "fission" / "functions"


@pytest.fixture
def fake_elasticsearch_modules(monkeypatch):
    class FakeElasticsearch:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    helpers_module = types.ModuleType("elasticsearch.helpers")
    helpers_module.bulk = lambda *args, **kwargs: (0, [])
    helpers_module.scan = lambda *args, **kwargs: iter(())

    elasticsearch_module = types.ModuleType("elasticsearch")
    elasticsearch_module.Elasticsearch = FakeElasticsearch
    elasticsearch_module.helpers = helpers_module

    monkeypatch.setitem(sys.modules, "elasticsearch", elasticsearch_module)
    monkeypatch.setitem(sys.modules, "elasticsearch.helpers", helpers_module)


@pytest.fixture
def flask_app():
    return Flask(__name__)


@pytest.fixture
def load_fission_module(fake_elasticsearch_modules):
    def _load(name):
        path = FISSION_ROOT / name / "main.py"
        spec = importlib.util.spec_from_file_location(f"fission_{name}_main", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    return _load
