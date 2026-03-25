"""Unit tests for the jolpica adapter — all HTTP mocked, no network."""

from datetime import date
from pathlib import Path

import pytest
from pytest_httpx import HTTPXMock

from broombroom.data.adapters.jolpica_adapter import JolpicaAdapter
from broombroom.errors import DataNotAvailableError

BASE_URL = "https://api.jolpi.ca/ergast"


def _make_adapter(tmp_path: Path) -> JolpicaAdapter:
    return JolpicaAdapter(
        base_url=BASE_URL,
        cache_dir=tmp_path / "cache",
        rate_per_second=100,  # no throttling in tests
    )


# ── Season schedule ────────────────────────────────────────────────────────────


class TestGetSeasonSchedule:
    def test_parses_schedule(self, httpx_mock: HTTPXMock, tmp_path: Path) -> None:
        httpx_mock.add_response(
            url=f"{BASE_URL}/f1/2024.json?limit=100",
            json={
                "MRData": {
                    "RaceTable": {
                        "Races": [
                            {
                                "round": "1",
                                "raceName": "Bahrain Grand Prix",
                                "Circuit": {
                                    "circuitId": "bahrain",
                                    "Location": {"country": "Bahrain", "locality": "Sakhir"},
                                },
                                "date": "2024-03-02",
                            }
                        ]
                    }
                }
            },
        )
        adapter = _make_adapter(tmp_path)
        events = adapter.get_season_schedule(2024)
        assert len(events) == 1
        assert events[0].circuit_key == "bahrain"
        assert events[0].date == date(2024, 3, 2)
        assert events[0].round_number == 1

    def test_returns_from_cache_on_second_call(self, httpx_mock: HTTPXMock, tmp_path: Path) -> None:
        httpx_mock.add_response(
            url=f"{BASE_URL}/f1/2022.json?limit=100",
            json={
                "MRData": {
                    "RaceTable": {
                        "Races": [
                            {
                                "round": "1",
                                "raceName": "Bahrain GP",
                                "Circuit": {
                                    "circuitId": "bahrain",
                                    "Location": {"country": "Bahrain", "locality": "Sakhir"},
                                },
                                "date": "2022-03-20",
                            }
                        ]
                    }
                }
            },
        )
        adapter = _make_adapter(tmp_path)
        first = adapter.get_season_schedule(2022)
        second = adapter.get_season_schedule(2022)  # should hit cache, no second HTTP call
        assert first == second


# ── Race results ───────────────────────────────────────────────────────────────


class TestGetRaceResults:
    _RESULT_PAYLOAD = {
        "MRData": {
            "RaceTable": {
                "Races": [
                    {
                        "Results": [
                            {
                                "position": "1",
                                "Driver": {"driverId": "max_verstappen", "code": "VER"},
                                "Constructor": {"constructorId": "red_bull"},
                                "grid": "1",
                                "laps": "57",
                                "status": "Finished",
                                "points": "25",
                                "FastestLap": {"rank": "1", "Time": {"time": "1:28.123"}},
                            },
                            {
                                "position": None,
                                "Driver": {"driverId": "lando_norris", "code": "NOR"},
                                "Constructor": {"constructorId": "mclaren"},
                                "grid": "3",
                                "laps": "30",
                                "status": "Accident",
                                "points": "0",
                                "FastestLap": {},
                            },
                        ]
                    }
                ]
            }
        }
    }

    def test_parses_results(self, httpx_mock: HTTPXMock, tmp_path: Path) -> None:
        httpx_mock.add_response(
            url=f"{BASE_URL}/f1/2024/5/results.json?limit=25",
            json=self._RESULT_PAYLOAD,
        )
        adapter = _make_adapter(tmp_path)
        results = adapter.get_race_results(2024, 5)
        assert len(results) == 2
        ver = results[0]
        assert ver.driver_code == "VER"
        assert ver.finish_position == 1
        assert ver.points == 25.0
        assert ver.fastest_lap is True
        assert ver.fastest_lap_time is not None

    def test_dnf_parsed(self, httpx_mock: HTTPXMock, tmp_path: Path) -> None:
        httpx_mock.add_response(
            url=f"{BASE_URL}/f1/2024/5/results.json?limit=25",
            json=self._RESULT_PAYLOAD,
        )
        adapter = _make_adapter(tmp_path)
        results = adapter.get_race_results(2024, 5)
        nor = results[1]
        assert nor.finish_position is None
        assert nor.dnf is True

    def test_empty_response_raises(self, httpx_mock: HTTPXMock, tmp_path: Path) -> None:
        httpx_mock.add_response(
            url=f"{BASE_URL}/f1/2024/99/results.json?limit=25",
            json={"MRData": {"RaceTable": {"Races": []}}},
        )
        adapter = _make_adapter(tmp_path)
        with pytest.raises(DataNotAvailableError):
            adapter.get_race_results(2024, 99)


# ── Qualifying results ─────────────────────────────────────────────────────────


class TestGetQualifyingResults:
    def test_parses_quali(self, httpx_mock: HTTPXMock, tmp_path: Path) -> None:
        httpx_mock.add_response(
            url=f"{BASE_URL}/f1/2024/5/qualifying.json?limit=25",
            json={
                "MRData": {
                    "RaceTable": {
                        "Races": [
                            {
                                "QualifyingResults": [
                                    {
                                        "position": "1",
                                        "Driver": {"driverId": "max_verstappen", "code": "VER"},
                                        "Constructor": {"constructorId": "red_bull"},
                                        "Q1": "1:29.000",
                                        "Q2": "1:28.500",
                                        "Q3": "1:27.800",
                                    },
                                    {
                                        "position": "11",
                                        "Driver": {"driverId": "george_russell", "code": "RUS"},
                                        "Constructor": {"constructorId": "mercedes"},
                                        "Q1": "1:29.200",
                                        "Q2": None,
                                        "Q3": None,
                                    },
                                ]
                            }
                        ]
                    }
                }
            },
        )
        adapter = _make_adapter(tmp_path)
        results = adapter.get_qualifying_results(2024, 5)
        assert len(results) == 2
        ver = results[0]
        assert ver.driver_code == "VER"
        assert ver.q3_time is not None
        assert ver.best_time == ver.q3_time

        rus = results[1]
        assert rus.q2_time is None
        assert rus.best_time == rus.q1_time


# ── Driver standings ───────────────────────────────────────────────────────────


class TestGetDriverStandings:
    def test_parses_standings(self, httpx_mock: HTTPXMock, tmp_path: Path) -> None:
        httpx_mock.add_response(
            url=f"{BASE_URL}/f1/2024/driverStandings.json?limit=25",
            json={
                "MRData": {
                    "StandingsTable": {
                        "StandingsLists": [
                            {
                                "round": "22",
                                "DriverStandings": [
                                    {
                                        "position": "1",
                                        "points": "437",
                                        "wins": "9",
                                        "Driver": {"driverId": "max_verstappen", "code": "VER"},
                                        "Constructors": [{"constructorId": "red_bull"}],
                                    }
                                ],
                            }
                        ]
                    }
                }
            },
        )
        adapter = _make_adapter(tmp_path)
        standings = adapter.get_driver_standings(2024)
        assert len(standings) == 1
        assert standings[0].driver_code == "VER"
        assert standings[0].points == 437.0
        assert standings[0].wins == 9
