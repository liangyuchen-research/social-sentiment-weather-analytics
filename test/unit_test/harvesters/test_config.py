# COMP90024 Team 2

from pathlib import Path

from backend.harvesters import config


def test_city_names_match_city_config_order():
    assert config.CITY_NAMES == list(config.CITIES)
    assert config.CITY_NAMES == ["sydney", "melbourne", "brisbane"]


def test_each_city_has_required_harvester_settings():
    for city, settings in config.CITIES.items():
        assert settings["queries"], f"{city} should have search queries"
        assert settings["tags"], f"{city} should have Mastodon tags"
        assert settings["meteostat_station"].isdigit()
        assert settings["bom_station_id"].isdigit()
        assert settings["tz"].startswith("Australia/")


def test_data_paths_match_shared_repository_data_directory():
    backend_root = Path(config.__file__).resolve().parents[2]

    assert config.DATA_RAW == backend_root / "data" / "raw"
    assert config.DATA_CLEAN == backend_root / "data" / "cleaned"
    assert config.DATA_RAW.exists()
    assert config.DATA_CLEAN.exists()


def test_reddit_subreddits_are_defined_for_every_city():
    assert set(config.CITY_SUBREDDITS) == set(config.CITY_NAMES)
    for subreddits in config.CITY_SUBREDDITS.values():
        assert subreddits
        assert all(isinstance(subreddit, str) for subreddit in subreddits)
