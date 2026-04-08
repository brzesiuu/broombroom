"""Unit tests for the race-weekend loader — adapters fully mocked.

Coverage matrix:

* pre-2018 year → jolpica only (fastf1 and openf1 are skipped even if
  non-``None`` adapters are passed).
* 2018–2022 → jolpica + fastf1 (openf1 skipped).
* 2023+ → all three sources, with driver_number → driver_code harmonisation
  driven by the fastf1 results table.
* openf1 session_key resolution matches sessions by ``date_start``.
* Partial-data paths: missing quali, fastf1 failures, openf1 failures,
  unmappable driver numbers are all degraded rather than raised.
"""

from datetime import date, datetime, timedelta
from unittest.mock import MagicMock

import pandas as pd
import pytest
from pytest_mock import MockerFixture

from broombroom.data.loaders.session_loader import load_race_weekend
from broombroom.data.models.event import RaceEvent, SessionType
from broombroom.data.models.results import QualiResult, RaceResult
from broombroom.data.models.session import SessionData, SessionMeta
from broombroom.data.models.stint import Compound
from broombroom.data.models.telemetry import RaceControlMessage
from broombroom.errors import DataNotAvailableError

# ── Fixtures ──────────────────────────────────────────────────────────────────


def _event(year: int, round_number: int = 1, race_date: date | None = None) -> RaceEvent:
    return RaceEvent(
        season=year,
        round_number=round_number,
        event_name="Bahrain Grand Prix",
        circuit_key="bahrain",
        country="Bahrain",
        locality="Sakhir",
        date=race_date or date(year, 3, 2),
        sessions=[SessionType.RACE],
    )


def _race_result(year: int, round_number: int = 1, driver_id: str = "max_verstappen") -> RaceResult:
    return RaceResult(
        season=year,
        round_number=round_number,
        driver_id=driver_id,
        driver_code=driver_id[:3].upper(),
        constructor_id="red_bull",
        grid_position=1,
        finish_position=1,
        status="Finished",
        points=25.0,
        laps_completed=57,
    )


def _quali_result(year: int, round_number: int = 1) -> QualiResult:
    return QualiResult(
        season=year,
        round_number=round_number,
        driver_id="max_verstappen",
        driver_code="VER",
        constructor_id="red_bull",
        position=1,
        q1_time=timedelta(minutes=1, seconds=30),
        q2_time=timedelta(minutes=1, seconds=29),
        q3_time=timedelta(minutes=1, seconds=28),
    )


def _fastf1_results_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"DriverNumber": "1", "Abbreviation": "VER"},
            {"DriverNumber": "4", "Abbreviation": "NOR"},
            {"DriverNumber": "16", "Abbreviation": "LEC"},
        ]
    )


def _session_data(year: int, round_number: int = 1, results: pd.DataFrame | None = None) -> SessionData:
    meta = SessionMeta(
        season=year,
        round_number=round_number,
        event_name="Bahrain Grand Prix",
        circuit_key="bahrain",
        session_type=SessionType.RACE,
        session_name="Race",
        session_date=datetime(year, 3, 2, 15, 0, 0),
        total_laps=57,
    )
    return SessionData(
        meta=meta,
        laps=pd.DataFrame(),
        weather=pd.DataFrame(),
        results=results if results is not None else _fastf1_results_df(),
    )


def _openf1_sessions_df(year: int, race_date: date) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "session_key": 9500,
                "year": year,
                "session_name": "Race",
                "date_start": f"{race_date.isoformat()}T15:00:00+00:00",
            },
            {
                "session_key": 9499,
                "year": year,
                "session_name": "Race",
                "date_start": "2099-01-01T15:00:00+00:00",
            },
        ]
    )


def _openf1_stints_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "driver_number": 1,
                "stint_number": 1,
                "compound": "SOFT",
                "lap_start": 1,
                "lap_end": 20,
                "tyre_age_at_start": 0,
            },
            {
                "driver_number": 1,
                "stint_number": 2,
                "compound": "HARD",
                "lap_start": 21,
                "lap_end": 57,
                "tyre_age_at_start": 0,
            },
            {
                "driver_number": 99,  # unknown driver — must be dropped
                "stint_number": 1,
                "compound": "MEDIUM",
                "lap_start": 1,
                "lap_end": 30,
                "tyre_age_at_start": 0,
            },
        ]
    )


def _openf1_weather_df() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"date": "2024-03-02T15:00:00+00:00", "air_temperature": 25.0, "track_temperature": 38.0},
        ]
    )


def _race_control_msg() -> RaceControlMessage:
    return RaceControlMessage(category="Flag", message="GREEN", flag="GREEN")


@pytest.fixture
def mock_jolpica(mocker: MockerFixture) -> MagicMock:
    jolpica = mocker.MagicMock()
    jolpica.get_season_schedule.return_value = [_event(2024)]
    jolpica.get_race_results.return_value = [_race_result(2024)]
    jolpica.get_qualifying_results.return_value = [_quali_result(2024)]
    return jolpica


@pytest.fixture
def mock_fastf1(mocker: MockerFixture) -> MagicMock:
    ff1 = mocker.MagicMock()
    ff1.get_session.return_value = _session_data(2024)
    return ff1


@pytest.fixture
def mock_openf1(mocker: MockerFixture) -> MagicMock:
    of1 = mocker.MagicMock()
    of1.get_sessions.return_value = _openf1_sessions_df(2024, date(2024, 3, 2))
    of1.get_stints.return_value = _openf1_stints_df()
    of1.get_race_control.return_value = [_race_control_msg()]
    of1.get_weather.return_value = _openf1_weather_df()
    return of1


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestPre2018:
    """Year < 2018 — jolpica only, fastf1 / openf1 skipped even if provided."""

    def test_returns_jolpica_only(
        self, mock_jolpica: MagicMock, mock_fastf1: MagicMock, mock_openf1: MagicMock
    ) -> None:
        mock_jolpica.get_season_schedule.return_value = [_event(2017, race_date=date(2017, 3, 26))]
        mock_jolpica.get_race_results.return_value = [_race_result(2017)]
        mock_jolpica.get_qualifying_results.return_value = [_quali_result(2017)]

        weekend = load_race_weekend(
            2017,
            1,
            jolpica=mock_jolpica,
            fastf1_adapter=mock_fastf1,
            openf1=mock_openf1,
        )

        assert weekend.event.season == 2017
        assert len(weekend.race_results) == 1
        assert weekend.race_session is None
        assert weekend.stints == []
        assert weekend.race_control == []
        assert weekend.openf1_weather.empty
        mock_fastf1.get_session.assert_not_called()
        mock_openf1.get_sessions.assert_not_called()


class Test2018to2022:
    """fastf1 is called but openf1 is not."""

    def test_loads_fastf1_only(self, mock_jolpica: MagicMock, mock_fastf1: MagicMock, mock_openf1: MagicMock) -> None:
        mock_jolpica.get_season_schedule.return_value = [_event(2022, race_date=date(2022, 3, 20))]
        mock_jolpica.get_race_results.return_value = [_race_result(2022)]
        mock_jolpica.get_qualifying_results.return_value = [_quali_result(2022)]
        mock_fastf1.get_session.return_value = _session_data(2022)

        weekend = load_race_weekend(
            2022,
            1,
            jolpica=mock_jolpica,
            fastf1_adapter=mock_fastf1,
            openf1=mock_openf1,
        )

        assert weekend.has_telemetry_data
        assert weekend.stints == []
        assert weekend.race_control == []
        mock_fastf1.get_session.assert_called_once_with(2022, 1, SessionType.RACE)
        mock_openf1.get_sessions.assert_not_called()


class Test2023Plus:
    """All three sources are used; openf1 data is harmonised via fastf1."""

    def test_loads_all_sources(self, mock_jolpica: MagicMock, mock_fastf1: MagicMock, mock_openf1: MagicMock) -> None:
        weekend = load_race_weekend(
            2024,
            1,
            jolpica=mock_jolpica,
            fastf1_adapter=mock_fastf1,
            openf1=mock_openf1,
        )

        assert weekend.has_telemetry_data
        assert weekend.has_openf1_data
        # Two stints for VER survive harmonisation, unknown #99 is dropped.
        assert len(weekend.stints) == 2
        assert {s.driver_code for s in weekend.stints} == {"VER"}
        assert weekend.stints[0].compound == Compound.SOFT
        assert weekend.stints[1].compound == Compound.HARD
        assert weekend.race_control[0].category == "Flag"
        assert not weekend.openf1_weather.empty
        mock_openf1.get_stints.assert_called_once_with(9500)
        mock_openf1.get_race_control.assert_called_once_with(9500)
        mock_openf1.get_weather.assert_called_once_with(9500)

    def test_session_key_matches_by_date(
        self, mock_jolpica: MagicMock, mock_fastf1: MagicMock, mock_openf1: MagicMock
    ) -> None:
        # Two race rows on different dates — the loader must pick the one
        # that matches event.date.
        mock_openf1.get_sessions.return_value = pd.DataFrame(
            [
                {
                    "session_key": 1111,
                    "session_name": "Race",
                    "date_start": "2024-02-01T15:00:00+00:00",
                },
                {
                    "session_key": 2222,
                    "session_name": "Race",
                    "date_start": "2024-03-02T15:00:00+00:00",
                },
            ]
        )

        load_race_weekend(
            2024,
            1,
            jolpica=mock_jolpica,
            fastf1_adapter=mock_fastf1,
            openf1=mock_openf1,
        )

        mock_openf1.get_stints.assert_called_once_with(2222)

    def test_session_key_unresolved_skips_openf1(
        self, mock_jolpica: MagicMock, mock_fastf1: MagicMock, mock_openf1: MagicMock
    ) -> None:
        mock_openf1.get_sessions.return_value = pd.DataFrame(
            [
                {
                    "session_key": 1111,
                    "session_name": "Race",
                    "date_start": "2099-01-01T15:00:00+00:00",
                }
            ]
        )

        weekend = load_race_weekend(
            2024,
            1,
            jolpica=mock_jolpica,
            fastf1_adapter=mock_fastf1,
            openf1=mock_openf1,
        )

        assert weekend.stints == []
        assert weekend.race_control == []
        mock_openf1.get_stints.assert_not_called()
        mock_openf1.get_race_control.assert_not_called()

    def test_stint_harmonisation_without_fastf1_drops_all(
        self, mock_jolpica: MagicMock, mock_openf1: MagicMock
    ) -> None:
        # No fastf1 adapter → no driver_number → driver_code map → every
        # stint row is dropped even though openf1 returned data.
        weekend = load_race_weekend(
            2024,
            1,
            jolpica=mock_jolpica,
            fastf1_adapter=None,
            openf1=mock_openf1,
        )

        assert weekend.stints == []
        # race_control and weather still load — they don't need the map.
        assert weekend.race_control
        assert not weekend.openf1_weather.empty


class TestPartialDataHandling:
    def test_missing_quali_is_logged_not_raised(self, mock_jolpica: MagicMock, mock_fastf1: MagicMock) -> None:
        mock_jolpica.get_qualifying_results.side_effect = DataNotAvailableError("no quali")

        weekend = load_race_weekend(
            2024,
            1,
            jolpica=mock_jolpica,
            fastf1_adapter=mock_fastf1,
        )

        assert weekend.quali_results == []
        assert weekend.race_results  # race results still populated

    def test_fastf1_failure_degrades_race_session(
        self, mock_jolpica: MagicMock, mock_fastf1: MagicMock, mock_openf1: MagicMock
    ) -> None:
        mock_fastf1.get_session.side_effect = DataNotAvailableError("fastf1 down")

        weekend = load_race_weekend(
            2024,
            1,
            jolpica=mock_jolpica,
            fastf1_adapter=mock_fastf1,
            openf1=mock_openf1,
        )

        assert weekend.race_session is None
        # openf1 stints still drop (no driver map), but weather / race_control survive
        assert weekend.stints == []
        assert weekend.race_control
        assert not weekend.openf1_weather.empty

    def test_openf1_stints_failure_degrades_stints_only(
        self, mock_jolpica: MagicMock, mock_fastf1: MagicMock, mock_openf1: MagicMock
    ) -> None:
        mock_openf1.get_stints.side_effect = DataNotAvailableError("stints gone")

        weekend = load_race_weekend(
            2024,
            1,
            jolpica=mock_jolpica,
            fastf1_adapter=mock_fastf1,
            openf1=mock_openf1,
        )

        assert weekend.stints == []
        assert weekend.race_control
        assert not weekend.openf1_weather.empty

    def test_event_not_in_schedule_raises(self, mock_jolpica: MagicMock) -> None:
        mock_jolpica.get_season_schedule.return_value = [_event(2024, round_number=1)]

        with pytest.raises(DataNotAvailableError):
            load_race_weekend(2024, 99, jolpica=mock_jolpica)
