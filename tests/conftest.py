"""Shared pytest fixtures for BroomBroom tests."""

import pandas as pd
import pytest

from broombroom.config import Settings


@pytest.fixture(scope="session")
def test_settings() -> Settings:
    """Settings instance pointing at temp directories — no real cache I/O."""
    return Settings(
        fastf1_cache_dir="tests/fixtures/.fastf1_cache",
        app_cache_dir="tests/fixtures/.app_cache",
        model_dir="tests/fixtures/.models",
        mlflow_tracking_uri="tests/fixtures/.mlflow",
        log_format="pretty",
        log_level="WARNING",
    )


@pytest.fixture(scope="session")
def sample_laps() -> pd.DataFrame:
    """Minimal 3-driver, 5-lap DataFrame mimicking fastf1 laps schema."""
    data = {
        "Driver": ["VER", "NOR", "LEC"] * 5,
        "LapNumber": [1, 1, 1, 2, 2, 2, 3, 3, 3, 4, 4, 4, 5, 5, 5],
        "LapTime": pd.to_timedelta(
            [
                "0:01:32.5",
                "0:01:33.1",
                "0:01:33.8",
                "0:01:31.9",
                "0:01:32.4",
                "0:01:33.0",
                "0:01:31.7",
                "0:01:32.1",
                "0:01:32.9",
                "0:01:32.0",
                "0:01:32.6",
                "0:01:33.2",
                "0:01:31.5",
                "0:01:32.0",
                "0:01:32.7",
            ]
        ),
        "Sector1Time": pd.to_timedelta(["0:00:28.1"] * 15),
        "Sector2Time": pd.to_timedelta(["0:00:38.0"] * 15),
        "Sector3Time": pd.to_timedelta(["0:00:25.5"] * 15),
        "Compound": ["SOFT", "MEDIUM", "HARD"] * 5,
        "TyreLife": [1, 1, 1, 2, 2, 2, 3, 3, 3, 4, 4, 4, 5, 5, 5],
        "Stint": [1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1],
        "IsAccurate": [True] * 15,
        "TrackStatus": ["1"] * 15,
        "PitInTime": [pd.NaT] * 15,
        "PitOutTime": [pd.NaT] * 15,
        "Position": [1, 2, 3, 1, 2, 3, 1, 2, 3, 1, 2, 3, 1, 2, 3],
    }
    return pd.DataFrame(data)


@pytest.fixture(scope="session")
def sample_weather() -> pd.DataFrame:
    """Minimal weather DataFrame mimicking fastf1 weather schema."""
    data = {
        "Time": pd.to_timedelta([f"0:{i:02d}:00" for i in range(10)]),
        "AirTemp": [22.5, 22.7, 23.0, 23.2, 23.5, 23.8, 24.0, 24.1, 24.3, 24.5],
        "TrackTemp": [38.0, 38.5, 39.0, 39.5, 40.0, 40.2, 40.5, 40.8, 41.0, 41.2],
        "Humidity": [45.0] * 10,
        "Pressure": [1013.0] * 10,
        "WindDirection": [180] * 10,
        "WindSpeed": [2.5] * 10,
        "Rainfall": [False] * 10,
    }
    return pd.DataFrame(data)
