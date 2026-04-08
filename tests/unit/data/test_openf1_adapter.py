"""Unit tests for the openf1 adapter — all HTTP mocked, no network."""

from pathlib import Path

import pytest
from pytest_httpx import HTTPXMock

from broombroom.data.adapters.openf1_adapter import OpenF1Adapter
from broombroom.errors import APIError, DataNotAvailableError

BASE_URL = "https://api.openf1.org/v1"


def _make_adapter(tmp_path: Path) -> OpenF1Adapter:
    return OpenF1Adapter(
        base_url=BASE_URL,
        cache_dir=tmp_path / "cache",
        rate_per_second=100,  # no throttling in tests
    )


# ── Year guard ────────────────────────────────────────────────────────────────


class TestYearGuard:
    def test_get_sessions_rejects_pre_2023(self, tmp_path: Path) -> None:
        a = _make_adapter(tmp_path)
        with pytest.raises(DataNotAvailableError, match="2023"):
            a.get_sessions(2022)


# ── get_sessions ──────────────────────────────────────────────────────────────


class TestGetSessions:
    _SESSIONS_PAYLOAD = [
        {
            "session_key": 9158,
            "meeting_key": 1219,
            "year": 2023,
            "session_name": "Race",
            "session_type": "Race",
            "date_start": "2023-11-05T17:00:00+00:00",
            "date_end": "2023-11-05T19:00:00+00:00",
            "location": "São Paulo",
            "country_name": "Brazil",
            "country_code": "BRA",
            "circuit_short_name": "Interlagos",
        },
        {
            "session_key": 9157,
            "meeting_key": 1219,
            "year": 2023,
            "session_name": "Qualifying",
            "session_type": "Qualifying",
            "date_start": "2023-11-03T18:00:00+00:00",
            "date_end": "2023-11-03T19:00:00+00:00",
            "location": "São Paulo",
            "country_name": "Brazil",
            "country_code": "BRA",
            "circuit_short_name": "Interlagos",
        },
    ]

    def test_parses_sessions(self, httpx_mock: HTTPXMock, tmp_path: Path) -> None:
        httpx_mock.add_response(
            url=f"{BASE_URL}/sessions?year=2023",
            json=self._SESSIONS_PAYLOAD,
        )
        a = _make_adapter(tmp_path)
        df = a.get_sessions(2023)
        assert len(df) == 2
        assert set(df.columns) >= {"session_key", "session_name", "circuit_short_name"}
        assert df.iloc[0]["session_key"] == 9158
        assert df.iloc[1]["session_name"] == "Qualifying"

    def test_filters_forwarded_as_params(self, httpx_mock: HTTPXMock, tmp_path: Path) -> None:
        httpx_mock.add_response(
            url=f"{BASE_URL}/sessions?year=2024&session_name=Race&country_code=BRA",
            json=self._SESSIONS_PAYLOAD[:1],
        )
        a = _make_adapter(tmp_path)
        df = a.get_sessions(2024, session_name="Race", country_code="BRA")
        assert len(df) == 1

    def test_caches_between_calls(self, httpx_mock: HTTPXMock, tmp_path: Path) -> None:
        httpx_mock.add_response(
            url=f"{BASE_URL}/sessions?year=2023",
            json=self._SESSIONS_PAYLOAD,
        )
        a = _make_adapter(tmp_path)
        first = a.get_sessions(2023)
        second = a.get_sessions(2023)  # must hit cache — only one HTTP response registered
        assert len(first) == len(second) == 2

    def test_empty_result_returns_empty_dataframe(self, httpx_mock: HTTPXMock, tmp_path: Path) -> None:
        httpx_mock.add_response(url=f"{BASE_URL}/sessions?year=2023", json=[])
        a = _make_adapter(tmp_path)
        df = a.get_sessions(2023)
        assert df.empty


# ── get_laps ──────────────────────────────────────────────────────────────────


class TestGetLaps:
    def test_parses_laps(self, httpx_mock: HTTPXMock, tmp_path: Path) -> None:
        httpx_mock.add_response(
            url=f"{BASE_URL}/laps?session_key=9158",
            json=[
                {
                    "driver_number": 1,
                    "lap_number": 1,
                    "lap_duration": 93.456,
                    "duration_sector_1": 28.0,
                    "duration_sector_2": 38.5,
                    "duration_sector_3": 26.9,
                    "st_speed": 323,
                    "is_pit_out_lap": False,
                },
                {
                    "driver_number": 1,
                    "lap_number": 2,
                    "lap_duration": 92.987,
                    "duration_sector_1": 27.8,
                    "duration_sector_2": 38.4,
                    "duration_sector_3": 26.8,
                    "st_speed": 325,
                    "is_pit_out_lap": False,
                },
            ],
        )
        a = _make_adapter(tmp_path)
        df = a.get_laps(9158)
        assert len(df) == 2
        assert "lap_duration" in df.columns
        assert df.iloc[0]["driver_number"] == 1


# ── get_car_data ──────────────────────────────────────────────────────────────


class TestGetCarData:
    def test_no_driver_filter(self, httpx_mock: HTTPXMock, tmp_path: Path) -> None:
        httpx_mock.add_response(
            url=f"{BASE_URL}/car_data?session_key=9158",
            json=[
                {
                    "date": "2023-11-05T17:30:00.000",
                    "driver_number": 1,
                    "rpm": 11500,
                    "speed": 310,
                    "n_gear": 7,
                    "throttle": 100,
                    "brake": 0,
                    "drs": 12,
                }
            ],
        )
        a = _make_adapter(tmp_path)
        df = a.get_car_data(9158)
        assert len(df) == 1
        assert df.iloc[0]["speed"] == 310

    def test_driver_filter_forwarded(self, httpx_mock: HTTPXMock, tmp_path: Path) -> None:
        httpx_mock.add_response(
            url=f"{BASE_URL}/car_data?session_key=9158&driver_number=44",
            json=[],
        )
        a = _make_adapter(tmp_path)
        df = a.get_car_data(9158, driver_number=44)
        assert df.empty


# ── get_stints ────────────────────────────────────────────────────────────────


class TestGetStints:
    def test_parses_stints(self, httpx_mock: HTTPXMock, tmp_path: Path) -> None:
        httpx_mock.add_response(
            url=f"{BASE_URL}/stints?session_key=9158",
            json=[
                {
                    "session_key": 9158,
                    "meeting_key": 1219,
                    "driver_number": 1,
                    "stint_number": 1,
                    "compound": "SOFT",
                    "lap_start": 1,
                    "lap_end": 20,
                    "tyre_age_at_start": 0,
                },
                {
                    "session_key": 9158,
                    "meeting_key": 1219,
                    "driver_number": 1,
                    "stint_number": 2,
                    "compound": "HARD",
                    "lap_start": 21,
                    "lap_end": 57,
                    "tyre_age_at_start": 0,
                },
            ],
        )
        a = _make_adapter(tmp_path)
        df = a.get_stints(9158)
        assert len(df) == 2
        assert df.iloc[1]["compound"] == "HARD"
        assert df.iloc[1]["lap_end"] == 57


# ── get_intervals & get_weather ───────────────────────────────────────────────


class TestGetIntervalsAndWeather:
    def test_intervals(self, httpx_mock: HTTPXMock, tmp_path: Path) -> None:
        httpx_mock.add_response(
            url=f"{BASE_URL}/intervals?session_key=9158",
            json=[
                {
                    "date": "2023-11-05T17:45:00.000",
                    "driver_number": 1,
                    "gap_to_leader": 0.0,
                    "interval": 0.0,
                }
            ],
        )
        a = _make_adapter(tmp_path)
        df = a.get_intervals(9158)
        assert df.iloc[0]["gap_to_leader"] == 0.0

    def test_weather(self, httpx_mock: HTTPXMock, tmp_path: Path) -> None:
        httpx_mock.add_response(
            url=f"{BASE_URL}/weather?session_key=9158",
            json=[
                {
                    "date": "2023-11-05T17:00:00.000",
                    "air_temperature": 28.5,
                    "track_temperature": 42.0,
                    "humidity": 55.0,
                    "pressure": 1010.0,
                    "rainfall": 0,
                    "wind_direction": 180,
                    "wind_speed": 2.5,
                }
            ],
        )
        a = _make_adapter(tmp_path)
        df = a.get_weather(9158)
        assert df.iloc[0]["track_temperature"] == 42.0


# ── get_race_control ──────────────────────────────────────────────────────────


class TestGetRaceControl:
    def test_parses_to_pydantic_models(self, httpx_mock: HTTPXMock, tmp_path: Path) -> None:
        httpx_mock.add_response(
            url=f"{BASE_URL}/race_control?session_key=9158",
            json=[
                {
                    "session_key": 9158,
                    "meeting_key": 1219,
                    "driver_number": None,
                    "date": "2023-11-05T17:00:00+00:00",
                    "category": "Flag",
                    "flag": "GREEN",
                    "lap_number": None,
                    "message": "GREEN LIGHT - PIT EXIT OPEN",
                    "scope": "Track",
                    "sector": None,
                },
                {
                    "session_key": 9158,
                    "meeting_key": 1219,
                    "driver_number": 1,
                    "date": "2023-11-05T17:32:10+00:00",
                    "category": "Other",
                    "flag": None,
                    "lap_number": 15,
                    "message": "CAR 1 (VER) TIME 1:13.456 DELETED - TRACK LIMITS AT TURN 4",
                    "scope": "Driver",
                    "sector": 2,
                },
            ],
        )
        a = _make_adapter(tmp_path)
        messages = a.get_race_control(9158)
        assert len(messages) == 2
        assert messages[0].flag == "GREEN"
        assert messages[0].driver_number is None
        assert messages[0].scope == "Track"
        assert messages[1].driver_number == "1"
        assert messages[1].lap_number == 15
        assert messages[1].sector == 2
        assert messages[1].timestamp is not None

    def test_second_call_uses_cache(self, httpx_mock: HTTPXMock, tmp_path: Path) -> None:
        httpx_mock.add_response(
            url=f"{BASE_URL}/race_control?session_key=9158",
            json=[
                {
                    "session_key": 9158,
                    "meeting_key": 1219,
                    "driver_number": None,
                    "date": "2023-11-05T17:00:00+00:00",
                    "category": "Flag",
                    "flag": "GREEN",
                    "lap_number": None,
                    "message": "GREEN",
                    "scope": "Track",
                    "sector": None,
                }
            ],
        )
        a = _make_adapter(tmp_path)
        first = a.get_race_control(9158)
        second = a.get_race_control(9158)
        assert len(first) == len(second) == 1
        assert first[0].flag == second[0].flag


# ── Error shape ───────────────────────────────────────────────────────────────


class TestErrorShape:
    def test_non_list_response_raises_api_error(self, httpx_mock: HTTPXMock, tmp_path: Path) -> None:
        httpx_mock.add_response(
            url=f"{BASE_URL}/laps?session_key=9158",
            json={"unexpected": "shape"},
        )
        a = _make_adapter(tmp_path)
        with pytest.raises(APIError, match="expected JSON array"):
            a.get_laps(9158)
