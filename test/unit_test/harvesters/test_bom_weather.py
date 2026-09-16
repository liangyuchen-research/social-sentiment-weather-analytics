# COMP90024 Team 2

import importlib
import sys
from types import SimpleNamespace

import pytest


def test_bom_fetch_one_exits_for_unknown_city(monkeypatch):
    monkeypatch.setitem(sys.modules, "meteostat", SimpleNamespace(Daily=object))
    sys.modules.pop("backend.harvesters.bom_weather", None)
    bom_weather = importlib.import_module("backend.harvesters.bom_weather")

    with pytest.raises(SystemExit, match="Unknown city"):
        bom_weather.fetch_one("perth", 2024)
