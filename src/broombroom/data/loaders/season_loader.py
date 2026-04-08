"""Season-level loaders.

Thin wrappers over :class:`~broombroom.data.adapters.jolpica_adapter.JolpicaAdapter`.
These exist so analysis / UI code never touches an adapter directly — a
loader is the single call site a caller should reach for season-wide data
like the championship tables.

Each function accepts the adapter as an explicit argument (dependency
injection) rather than constructing it internally, which keeps the loaders
trivial to unit-test with mocks and removes hidden global state.
"""

from broombroom.data.adapters.jolpica_adapter import JolpicaAdapter
from broombroom.data.models.event import SeasonSchedule
from broombroom.data.models.results import (
    ConstructorStanding,
    DriverStanding,
    RaceResult,
)
from broombroom.logging import get_logger

log = get_logger(__name__)


def load_season_schedule(year: int, *, jolpica: JolpicaAdapter) -> SeasonSchedule:
    """Return the full race calendar for a season."""
    events = jolpica.get_season_schedule(year)
    log.debug("season_schedule_loaded", year=year, rounds=len(events))
    return SeasonSchedule(season=year, events=events)


def load_season_results(year: int, *, jolpica: JolpicaAdapter) -> dict[int, list[RaceResult]]:
    """Return classified race results for every completed round of a season.

    The return value maps ``round_number → list[RaceResult]``. Rounds for
    which jolpica has no results yet (future rounds of an in-progress
    season) are silently omitted — callers can detect gaps by comparing
    against :func:`load_season_schedule`.
    """
    schedule = jolpica.get_season_schedule(year)
    results: dict[int, list[RaceResult]] = {}
    for event in schedule:
        try:
            results[event.round_number] = jolpica.get_race_results(year, event.round_number)
        except Exception as exc:  # noqa: BLE001 — any failure means "not ready"
            log.info(
                "season_results_round_skipped",
                year=year,
                round=event.round_number,
                reason=str(exc),
            )
    log.debug("season_results_loaded", year=year, rounds=len(results))
    return results


def load_driver_championship(
    year: int,
    round_number: int | None = None,
    *,
    jolpica: JolpicaAdapter,
) -> list[DriverStanding]:
    """Return the driver championship table.

    Args:
        year: Season year.
        round_number: Standing after this round. ``None`` returns the
            latest available standings (end-of-season for completed years,
            current table for the live season).
    """
    standings = jolpica.get_driver_standings(year, round_number=round_number)
    log.debug(
        "driver_championship_loaded",
        year=year,
        round=round_number,
        drivers=len(standings),
    )
    return standings


def load_constructor_championship(
    year: int,
    round_number: int | None = None,
    *,
    jolpica: JolpicaAdapter,
) -> list[ConstructorStanding]:
    """Return the constructor championship table."""
    standings = jolpica.get_constructor_standings(year, round_number=round_number)
    log.debug(
        "constructor_championship_loaded",
        year=year,
        round=round_number,
        constructors=len(standings),
    )
    return standings
