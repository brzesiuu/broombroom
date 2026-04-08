"""Unit tests for the season loader — adapters fully mocked."""

from datetime import date, timedelta
from unittest.mock import MagicMock

import pytest
from pytest_mock import MockerFixture

from broombroom.data.loaders.season_loader import (
    load_constructor_championship,
    load_driver_championship,
    load_season_results,
    load_season_schedule,
)
from broombroom.data.models.event import RaceEvent, SessionType
from broombroom.data.models.results import (
    ConstructorStanding,
    DriverStanding,
    RaceResult,
)
from broombroom.errors import DataNotAvailableError


def _event(round_number: int) -> RaceEvent:
    return RaceEvent(
        season=2024,
        round_number=round_number,
        event_name=f"Round {round_number} GP",
        circuit_key=f"circuit_{round_number}",
        country="Country",
        locality="City",
        date=date(2024, 3, round_number),
        sessions=[SessionType.RACE],
    )


def _race_result(driver_id: str, round_number: int = 1) -> RaceResult:
    return RaceResult(
        season=2024,
        round_number=round_number,
        driver_id=driver_id,
        driver_code=driver_id[:3].upper(),
        constructor_id="constructor",
        grid_position=1,
        finish_position=1,
        status="Finished",
        points=25.0,
        fastest_lap=False,
        fastest_lap_time=timedelta(minutes=1, seconds=30),
        laps_completed=57,
    )


@pytest.fixture
def mock_jolpica(mocker: MockerFixture) -> MagicMock:
    return mocker.MagicMock()


class TestLoadSeasonSchedule:
    def test_returns_season_schedule(self, mock_jolpica: MagicMock) -> None:
        mock_jolpica.get_season_schedule.return_value = [_event(1), _event(2)]

        schedule = load_season_schedule(2024, jolpica=mock_jolpica)

        assert schedule.season == 2024
        assert schedule.rounds == 2
        mock_jolpica.get_season_schedule.assert_called_once_with(2024)


class TestLoadSeasonResults:
    def test_collects_results_per_round(self, mock_jolpica: MagicMock) -> None:
        mock_jolpica.get_season_schedule.return_value = [_event(1), _event(2)]
        mock_jolpica.get_race_results.side_effect = [
            [_race_result("max_verstappen", 1)],
            [_race_result("lando_norris", 2)],
        ]

        results = load_season_results(2024, jolpica=mock_jolpica)

        assert set(results.keys()) == {1, 2}
        assert results[1][0].driver_code == "MAX"
        assert results[2][0].driver_code == "LAN"
        assert mock_jolpica.get_race_results.call_count == 2

    def test_skips_rounds_without_results(self, mock_jolpica: MagicMock) -> None:
        mock_jolpica.get_season_schedule.return_value = [_event(1), _event(2), _event(3)]
        mock_jolpica.get_race_results.side_effect = [
            [_race_result("max_verstappen", 1)],
            DataNotAvailableError("future round"),
            DataNotAvailableError("future round"),
        ]

        results = load_season_results(2024, jolpica=mock_jolpica)

        assert list(results.keys()) == [1]

    def test_empty_season_returns_empty_dict(self, mock_jolpica: MagicMock) -> None:
        mock_jolpica.get_season_schedule.return_value = []

        results = load_season_results(2024, jolpica=mock_jolpica)

        assert results == {}
        mock_jolpica.get_race_results.assert_not_called()


class TestLoadDriverChampionship:
    def test_delegates_to_adapter(self, mock_jolpica: MagicMock) -> None:
        standing = DriverStanding(
            season=2024,
            round_number=5,
            position=1,
            driver_id="max_verstappen",
            driver_code="VER",
            constructor_id="red_bull",
            points=150.0,
            wins=5,
        )
        mock_jolpica.get_driver_standings.return_value = [standing]

        result = load_driver_championship(2024, round_number=5, jolpica=mock_jolpica)

        assert result == [standing]
        mock_jolpica.get_driver_standings.assert_called_once_with(2024, round_number=5)

    def test_no_round_uses_latest(self, mock_jolpica: MagicMock) -> None:
        mock_jolpica.get_driver_standings.return_value = []

        load_driver_championship(2024, jolpica=mock_jolpica)

        mock_jolpica.get_driver_standings.assert_called_once_with(2024, round_number=None)


class TestLoadConstructorChampionship:
    def test_delegates_to_adapter(self, mock_jolpica: MagicMock) -> None:
        standing = ConstructorStanding(
            season=2024,
            round_number=5,
            position=1,
            constructor_id="red_bull",
            constructor_name="Red Bull",
            points=300.0,
            wins=5,
        )
        mock_jolpica.get_constructor_standings.return_value = [standing]

        result = load_constructor_championship(2024, round_number=5, jolpica=mock_jolpica)

        assert result == [standing]
        mock_jolpica.get_constructor_standings.assert_called_once_with(2024, round_number=5)
