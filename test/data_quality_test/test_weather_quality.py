# COMP90024 Team 2

import pandas as pd

from backend.cleaning import clean_pipeline
from database import bulk_upload


def test_weather_loader_produces_unique_city_date_rows(tmp_path, monkeypatch):
    monkeypatch.setattr(clean_pipeline, "DATA_RAW", tmp_path)
    (tmp_path / "weather_sydney_2024.csv").write_text(
        "time,tavg,prcp\n"
        "2024-01-01,22.5,0.0\n"
        "2024-01-01,23.5,1.0\n"
        "2024-01-02,24.0,0.2\n",
        encoding="utf-8",
    )

    weather = clean_pipeline.load_weather_for("sydney")

    assert not weather.duplicated(subset=["city", "date_local"]).any()
    assert weather["date_local"].tolist() == [
        pd.Timestamp("2024-01-01").date(),
        pd.Timestamp("2024-01-02").date(),
    ]
    assert weather["city"].tolist() == ["sydney", "sydney"]


def test_weather_bulk_actions_have_stable_ids_and_valid_dates(tmp_path, monkeypatch):
    monkeypatch.setattr(bulk_upload, "RAW", tmp_path)
    (tmp_path / "weather_brisbane_2024.csv").write_text(
        "date,city,tavg,tmin,tmax,prcp\n"
        "2024-01-01,brisbane,27.0,22.0,31.0,0.0\n"
        "bad-date,brisbane,28.0,23.0,32.0,1.0\n",
        encoding="utf-8",
    )

    actions = list(bulk_upload.gen_weather_daily())

    assert len(actions) == 1
    action = actions[0]
    assert action["_id"] == "brisbane:2024-01-01"
    assert action["_source"]["city"] == "brisbane"
    assert action["_source"]["date"] == "2024-01-01"
    assert action["_source"]["year"] == 2024
    assert action["_source"]["tmin"] <= action["_source"]["tavg"] <= action["_source"]["tmax"]
    assert action["_source"]["prcp"] >= 0
