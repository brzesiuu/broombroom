"""Unit tests for the fastf1 adapter — fastf1 module is fully mocked."""

from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest
from pytest_mock import MockerFixture

from broombroom.data.adapters import fastf1_adapter as adapter_mod
from broombroom.data.adapters.fastf1_adapter import FastF1Adapter
from broombroom.data.models.event import SessionType
from broombroom.data.models.session import SessionData, SessionMeta
from broombroom.errors import DataNotAvailableError

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_fastf1(mocker: MockerFixture) -> MagicMock:
    """Replace the fastf1 module reference inside the adapter with a MagicMock."""
    return mocker.patch.object(adapter_mod, "fastf1")


def _make_adapter(tmp_path: Path) -> FastF1Adapter:
    return FastF1Adapter(cache_dir=tmp_path / "fastf1_cache")


def _sample_schedule_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "RoundNumber": 1,
                "EventName": "Bahrain Grand Prix",
                "Country": "Bahrain",
                "Location": "Sakhir",
                "EventDate": pd.Timestamp("2024-03-02"),
                "EventFormat": "conventional",
                "Session1": "Practice 1",
                "Session2": "Practice 2",
                "Session3": "Practice 3",
                "Session4": "Qualifying",
                "Session5": "Race",
            },
            {
                "RoundNumber": 5,
                "EventName": "Miami Grand Prix",
                "Country": "USA",
                "Location": "Miami",
                "EventDate": pd.Timestamp("2024-05-05"),
                "EventFormat": "sprint_qualifying",
                "Session1": "Practice 1",
                "Session2": "Sprint Qualifying",
                "Session3": "Sprint",
                "Session4": "Qualifying",
                "Session5": "Race",
            },
        ]
    )


def _make_mock_session(
    *,
    laps: pd.DataFrame | None = None,
    weather: pd.DataFrame | None = None,
    results: pd.DataFrame | None = None,
    name: str = "Race",
    total_laps: int | None = 57,
    event_name: str = "Bahrain Grand Prix",
    country: str = "Bahrain",
    location: str = "Sakhir",
    date: pd.Timestamp | None = None,
) -> MagicMock:
    """Build a MagicMock that quacks like a fastf1 Session."""
    session = MagicMock()
    session.laps = laps
    session.weather_data = weather
    session.results = results
    session.name = name
    session.total_laps = total_laps
    session.date = date or pd.Timestamp("2024-03-02 15:00:00")
    session.event = pd.Series({"EventName": event_name, "Country": country, "Location": location})
    return session


# ── Init / cache ──────────────────────────────────────────────────────────────


class TestInit:
    def test_enables_fastf1_cache(self, mock_fastf1: MagicMock, tmp_path: Path) -> None:
        cache_dir = tmp_path / "fastf1_cache"
        FastF1Adapter(cache_dir=cache_dir)
        mock_fastf1.Cache.enable_cache.assert_called_once_with(str(cache_dir))
        assert cache_dir.exists()


# ── Year guard ────────────────────────────────────────────────────────────────


class TestYearGuard:
    def test_get_event_schedule_rejects_pre_2018(self, mock_fastf1: MagicMock, tmp_path: Path) -> None:
        a = _make_adapter(tmp_path)
        with pytest.raises(DataNotAvailableError, match="2018"):
            a.get_event_schedule(2017)
        mock_fastf1.get_event_schedule.assert_not_called()

    def test_get_session_rejects_pre_2018(self, mock_fastf1: MagicMock, tmp_path: Path) -> None:
        a = _make_adapter(tmp_path)
        with pytest.raises(DataNotAvailableError):
            a.get_session(2015, 1, SessionType.RACE)
        mock_fastf1.get_session.assert_not_called()


# ── get_event_schedule ────────────────────────────────────────────────────────


class TestGetEventSchedule:
    def test_parses_schedule(self, mock_fastf1: MagicMock, tmp_path: Path) -> None:
        mock_fastf1.get_event_schedule.return_value = _sample_schedule_df()
        a = _make_adapter(tmp_path)
        events = a.get_event_schedule(2024)

        assert len(events) == 2
        bahrain = events[0]
        assert bahrain.round_number == 1
        assert bahrain.event_name == "Bahrain Grand Prix"
        assert bahrain.circuit_key == "sakhir"
        assert bahrain.sprint is False
        assert SessionType.RACE in bahrain.sessions
        assert SessionType.PRACTICE_3 in bahrain.sessions

        miami = events[1]
        assert miami.sprint is True
        assert SessionType.SPRINT in miami.sessions
        assert SessionType.SPRINT_QUALIFYING in miami.sessions
        # Sprint weekends do not have FP3.
        assert SessionType.PRACTICE_3 not in miami.sessions

    def test_excludes_testing_events(self, mock_fastf1: MagicMock, tmp_path: Path) -> None:
        mock_fastf1.get_event_schedule.return_value = _sample_schedule_df()
        a = _make_adapter(tmp_path)
        a.get_event_schedule(2024)
        _, kwargs = mock_fastf1.get_event_schedule.call_args
        assert kwargs.get("include_testing") is False

    def test_wraps_fastf1_error(self, mock_fastf1: MagicMock, tmp_path: Path) -> None:
        mock_fastf1.get_event_schedule.side_effect = ValueError("network down")
        a = _make_adapter(tmp_path)
        with pytest.raises(DataNotAvailableError, match="schedule"):
            a.get_event_schedule(2024)


# ── get_session ───────────────────────────────────────────────────────────────


class TestGetSession:
    def test_eagerly_loads_laps_weather_results(
        self,
        mock_fastf1: MagicMock,
        tmp_path: Path,
        sample_laps: pd.DataFrame,
        sample_weather: pd.DataFrame,
    ) -> None:
        results_df = pd.DataFrame({"Abbreviation": ["VER", "NOR"], "Position": [1, 2]})
        session = _make_mock_session(
            laps=sample_laps,
            weather=sample_weather,
            results=results_df,
            event_name="Bahrain Grand Prix",
            location="Sakhir",
        )
        mock_fastf1.get_session.return_value = session

        a = _make_adapter(tmp_path)
        data = a.get_session(2024, 1, SessionType.RACE)

        mock_fastf1.get_session.assert_called_once_with(2024, 1, "R")
        session.load.assert_called_once()
        load_kwargs = session.load.call_args.kwargs
        assert load_kwargs["laps"] is True
        assert load_kwargs["telemetry"] is False
        assert load_kwargs["weather"] is True

        assert isinstance(data, SessionData)
        assert isinstance(data.meta, SessionMeta)
        assert data.meta.circuit_key == "sakhir"
        assert data.meta.event_name == "Bahrain Grand Prix"
        assert data.meta.session_type == SessionType.RACE
        assert data.meta.total_laps == 57
        assert isinstance(data.meta.session_date, datetime)

        # DataFrames should be preserved
        assert len(data.laps) == len(sample_laps)
        assert len(data.weather) == len(sample_weather)
        assert list(data.results.columns) == ["Abbreviation", "Position"]

    def test_handles_none_frames(self, mock_fastf1: MagicMock, tmp_path: Path) -> None:
        session = _make_mock_session(laps=None, weather=None, results=None, total_laps=None)
        mock_fastf1.get_session.return_value = session

        a = _make_adapter(tmp_path)
        data = a.get_session(2024, 1, SessionType.QUALIFYING)

        assert data.laps.empty
        assert data.weather.empty
        assert data.results.empty
        assert data.meta.total_laps is None

    def test_wraps_fastf1_error(self, mock_fastf1: MagicMock, tmp_path: Path) -> None:
        mock_fastf1.get_session.side_effect = ValueError("session not found")
        a = _make_adapter(tmp_path)
        with pytest.raises(DataNotAvailableError, match="2024 round 99"):
            a.get_session(2024, 99, SessionType.RACE)

    def test_session_type_mapping(
        self,
        mock_fastf1: MagicMock,
        tmp_path: Path,
    ) -> None:
        session = _make_mock_session()
        mock_fastf1.get_session.return_value = session

        a = _make_adapter(tmp_path)
        a.get_session(2024, 5, SessionType.SPRINT)

        mock_fastf1.get_session.assert_called_with(2024, 5, "S")


# ── get_circuit_info ──────────────────────────────────────────────────────────


class TestGetCircuitInfo:
    def test_parses_corners_and_rotation(self, mock_fastf1: MagicMock, tmp_path: Path) -> None:
        corners_df = pd.DataFrame(
            [
                {"Number": 1, "Letter": "", "Angle": 90.0, "Distance": 120.0},
                {"Number": 6, "Letter": "A", "Angle": 45.0, "Distance": 980.0},
            ]
        )
        circuit_info_obj = MagicMock()
        circuit_info_obj.corners = corners_df
        circuit_info_obj.rotation = 12.5

        session = _make_mock_session(event_name="Italian Grand Prix", country="Italy", location="Monza")
        session.get_circuit_info.return_value = circuit_info_obj
        mock_fastf1.get_session.return_value = session

        a = _make_adapter(tmp_path)
        info = a.get_circuit_info(2024, 16)

        # Race session is loaded without laps/weather for circuit info.
        load_kwargs = session.load.call_args.kwargs
        assert load_kwargs["laps"] is False
        assert load_kwargs["weather"] is False
        assert load_kwargs["telemetry"] is False

        assert info.name == "Italian Grand Prix"
        assert info.circuit_key == "monza"
        assert info.country == "Italy"
        assert info.lap_length_km is None
        assert info.rotation == 12.5
        assert len(info.corners) == 2
        assert info.corners[0].number == 1
        assert info.corners[1].letter == "A"

    def test_wraps_circuit_info_error(self, mock_fastf1: MagicMock, tmp_path: Path) -> None:
        session = _make_mock_session()
        session.get_circuit_info.side_effect = KeyError("no circuit info")
        mock_fastf1.get_session.return_value = session

        a = _make_adapter(tmp_path)
        with pytest.raises(DataNotAvailableError, match="circuit info"):
            a.get_circuit_info(2024, 1)


# ── get_lap_telemetry ─────────────────────────────────────────────────────────


class TestGetLapTelemetry:
    def _make_session_with_telemetry(self, telemetry_df: pd.DataFrame, lap_exists: bool = True) -> MagicMock:
        lap_row = MagicMock()
        lap_row.get_telemetry.return_value = telemetry_df

        iloc_mock = MagicMock()
        iloc_mock.__getitem__.return_value = lap_row

        matching_laps = MagicMock()
        matching_laps.empty = not lap_exists
        matching_laps.iloc = iloc_mock

        driver_laps = MagicMock()
        driver_laps.__getitem__.return_value = matching_laps

        laps = MagicMock()
        laps.pick_drivers.return_value = driver_laps

        session = MagicMock()
        session.laps = laps
        return session

    def test_returns_telemetry_dataframe(self, mock_fastf1: MagicMock, tmp_path: Path) -> None:
        telemetry = pd.DataFrame({"Speed": [250, 260, 270], "Throttle": [80, 90, 100]})
        session = self._make_session_with_telemetry(telemetry)
        mock_fastf1.get_session.return_value = session

        a = _make_adapter(tmp_path)
        session_data = SessionData(
            meta=SessionMeta(
                season=2024,
                round_number=1,
                event_name="Bahrain",
                circuit_key="sakhir",
                session_type=SessionType.RACE,
                session_name="Race",
                total_laps=57,
            ),
            laps=pd.DataFrame(),
            weather=pd.DataFrame(),
            results=pd.DataFrame(),
        )
        result = a.get_lap_telemetry(session_data, driver="VER", lap_number=35)

        # Re-loads the session with telemetry=True
        load_kwargs = session.load.call_args.kwargs
        assert load_kwargs["telemetry"] is True
        assert list(result.columns) == ["Speed", "Throttle"]

    def test_missing_lap_raises(self, mock_fastf1: MagicMock, tmp_path: Path) -> None:
        session = self._make_session_with_telemetry(pd.DataFrame(), lap_exists=False)
        mock_fastf1.get_session.return_value = session

        a = _make_adapter(tmp_path)
        session_data = SessionData(
            meta=SessionMeta(
                season=2024,
                round_number=1,
                event_name="Bahrain",
                circuit_key="sakhir",
                session_type=SessionType.RACE,
                session_name="Race",
            ),
            laps=pd.DataFrame(),
            weather=pd.DataFrame(),
            results=pd.DataFrame(),
        )
        with pytest.raises(DataNotAvailableError, match="No lap 99"):
            a.get_lap_telemetry(session_data, driver="VER", lap_number=99)
