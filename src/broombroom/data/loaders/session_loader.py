"""Race-weekend loader.

Composes the jolpica, fastf1, and openf1 adapters into a single
:class:`~broombroom.data.models.weekend.RaceWeekendData` aggregate so that
analysis / UI code has exactly one call site to reach for weekend data.

Coverage rules enforced here mirror the adapter-level guards:

* **jolpica** (1950+): always required — an event + race + quali fetch must
  succeed or the loader raises :class:`DataNotAvailableError`.
* **fastf1** (2018+): fetched only when ``year >= 2018``. Failures are
  logged and degrade the result (``race_session=None``) rather than abort
  the whole load — jolpica data alone is still useful.
* **openf1** (2023+): fetched only when ``year >= 2023``. Failures degrade
  individual fields (empty stints / weather / race_control).

Driver number harmonisation:

openf1 identifies drivers by ``driver_number`` (an int), while the rest of
the stack uses the three-letter ``driver_code`` (e.g. ``VER``). The loader
builds a ``driver_number → driver_code`` lookup from the fastf1 race
results DataFrame and uses it to wrap openf1 stint rows in
:class:`~broombroom.data.models.stint.Stint`. Stints with a driver that
cannot be mapped are dropped with a warning rather than raising — incomplete
telemetry data is the normal case.
"""

from __future__ import annotations

import pandas as pd

from broombroom.data.adapters.fastf1_adapter import FastF1Adapter
from broombroom.data.adapters.jolpica_adapter import JolpicaAdapter
from broombroom.data.adapters.openf1_adapter import OpenF1Adapter
from broombroom.data.models.event import RaceEvent, SessionType
from broombroom.data.models.results import QualiResult
from broombroom.data.models.session import SessionData
from broombroom.data.models.stint import Compound, Stint
from broombroom.data.models.telemetry import RaceControlMessage
from broombroom.data.models.weekend import RaceWeekendData
from broombroom.errors import DataNotAvailableError
from broombroom.logging import get_logger

log = get_logger(__name__)

_FASTF1_MIN_YEAR = 2018
_OPENF1_MIN_YEAR = 2023


def load_race_weekend(
    year: int,
    round_number: int,
    *,
    jolpica: JolpicaAdapter,
    fastf1_adapter: FastF1Adapter | None = None,
    openf1: OpenF1Adapter | None = None,
) -> RaceWeekendData:
    """Load every data source we have for a single race weekend.

    Args:
        year: Season year.
        round_number: Round number within the season.
        jolpica: Jolpica adapter (required). Source of the authoritative
            event metadata, race results, and qualifying results.
        fastf1_adapter: fastf1 adapter. Used when ``year >= 2018``. Pass
            ``None`` to skip fastf1 entirely (useful in tests or on
            environments that cannot run fastf1).
        openf1: openf1 adapter. Used when ``year >= 2023``. Pass ``None``
            to skip openf1 entirely.

    Raises:
        DataNotAvailableError: If jolpica has no event metadata for the
            requested round (e.g. future round or invalid season).
    """
    event = _load_event(year, round_number, jolpica)
    race_results = jolpica.get_race_results(year, round_number)
    quali_results = _safe_quali(jolpica, year, round_number)

    race_session = _maybe_load_fastf1_race(year, round_number, fastf1_adapter)
    stints, race_control, openf1_weather = _maybe_load_openf1(
        year=year,
        round_number=round_number,
        event=event,
        race_session=race_session,
        openf1=openf1,
    )

    return RaceWeekendData(
        event=event,
        race_results=race_results,
        quali_results=quali_results,
        race_session=race_session,
        stints=stints,
        race_control=race_control,
        openf1_weather=openf1_weather,
    )


# ── jolpica helpers ────────────────────────────────────────────────────────────


def _load_event(year: int, round_number: int, jolpica: JolpicaAdapter) -> RaceEvent:
    schedule = jolpica.get_season_schedule(year)
    for event in schedule:
        if event.round_number == round_number:
            return event
    raise DataNotAvailableError(f"No event found for {year} round {round_number}")


def _safe_quali(jolpica: JolpicaAdapter, year: int, round_number: int) -> list[QualiResult]:
    try:
        return jolpica.get_qualifying_results(year, round_number)
    except DataNotAvailableError as exc:
        log.info("quali_unavailable", year=year, round=round_number, reason=str(exc))
        return []


# ── fastf1 helpers ─────────────────────────────────────────────────────────────


def _maybe_load_fastf1_race(
    year: int,
    round_number: int,
    fastf1_adapter: FastF1Adapter | None,
) -> SessionData | None:
    if fastf1_adapter is None or year < _FASTF1_MIN_YEAR:
        return None
    try:
        return fastf1_adapter.get_session(year, round_number, SessionType.RACE)
    except DataNotAvailableError as exc:
        log.warning(
            "fastf1_race_session_unavailable",
            year=year,
            round=round_number,
            reason=str(exc),
        )
        return None


# ── openf1 helpers ─────────────────────────────────────────────────────────────


def _maybe_load_openf1(
    year: int,
    round_number: int,
    event: RaceEvent,
    race_session: SessionData | None,
    openf1: OpenF1Adapter | None,
) -> tuple[list[Stint], list[RaceControlMessage], pd.DataFrame]:
    """Return ``(stints, race_control, weather)`` from openf1, or empty defaults."""
    if openf1 is None or year < _OPENF1_MIN_YEAR:
        return [], [], pd.DataFrame()

    session_key = _resolve_openf1_race_session_key(openf1, year, event)
    if session_key is None:
        log.warning(
            "openf1_session_key_unresolved",
            year=year,
            round=round_number,
            event_name=event.event_name,
        )
        return [], [], pd.DataFrame()

    driver_map = _build_driver_number_map(race_session)
    stints = _load_stints(openf1, session_key, driver_map, year, round_number)
    race_control = _safe_race_control(openf1, session_key, year, round_number)
    weather = _safe_openf1_weather(openf1, session_key, year, round_number)
    return stints, race_control, weather


def _resolve_openf1_race_session_key(
    openf1: OpenF1Adapter,
    year: int,
    event: RaceEvent,
) -> int | None:
    """Find the openf1 ``session_key`` for the race of an event.

    openf1 does not expose a ``round_number`` field, so we match by event
    date: filter ``get_sessions(year, session_name="Race")`` down to the
    session whose ``date_start`` day equals ``event.date``.
    """
    try:
        sessions = openf1.get_sessions(year, session_name="Race")
    except DataNotAvailableError as exc:
        log.info("openf1_sessions_unavailable", year=year, reason=str(exc))
        return None

    if sessions.empty or "date_start" not in sessions.columns:
        return None

    dates = pd.to_datetime(sessions["date_start"], errors="coerce", utc=True).dt.date
    match = sessions[dates == event.date]
    if match.empty:
        return None

    try:
        return int(match.iloc[0]["session_key"])
    except (KeyError, TypeError, ValueError):
        return None


def _build_driver_number_map(race_session: SessionData | None) -> dict[str, str]:
    """Return a ``driver_number → driver_code`` map from a fastf1 results table.

    fastf1's ``results`` DataFrame carries ``DriverNumber`` and
    ``Abbreviation`` columns. Both are stringified so lookups are robust
    against ``int``-vs-``str`` mismatches from openf1's JSON payloads.
    """
    if race_session is None or race_session.results.empty:
        return {}

    results = race_session.results
    number_col = _first_existing(results, ("DriverNumber", "driver_number"))
    code_col = _first_existing(results, ("Abbreviation", "abbreviation", "driver_code"))
    if number_col is None or code_col is None:
        return {}

    mapping: dict[str, str] = {}
    for _, row in results.iterrows():
        number = row.get(number_col)
        code = row.get(code_col)
        if number is None or code is None:
            continue
        mapping[str(number)] = str(code).upper()
    return mapping


def _first_existing(df: pd.DataFrame, candidates: tuple[str, ...]) -> str | None:
    for name in candidates:
        if name in df.columns:
            return name
    return None


def _load_stints(
    openf1: OpenF1Adapter,
    session_key: int,
    driver_map: dict[str, str],
    year: int,
    round_number: int,
) -> list[Stint]:
    try:
        frame = openf1.get_stints(session_key)
    except DataNotAvailableError as exc:
        log.warning(
            "openf1_stints_unavailable",
            year=year,
            round=round_number,
            session_key=session_key,
            reason=str(exc),
        )
        return []

    if frame.empty:
        return []

    stints: list[Stint] = []
    dropped = 0
    for _, row in frame.iterrows():
        number = row.get("driver_number")
        if number is None or (isinstance(number, float) and pd.isna(number)):
            dropped += 1
            continue
        code = driver_map.get(str(int(number)) if isinstance(number, float) else str(number))
        if code is None:
            dropped += 1
            continue
        try:
            stints.append(
                Stint(
                    driver_code=code,
                    stint_number=int(row["stint_number"]),
                    compound=Compound.from_fastf1(row.get("compound")),
                    start_lap=int(row["lap_start"]),
                    end_lap=int(row["lap_end"]),
                    tyre_age_at_start=int(row.get("tyre_age_at_start") or 0),
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            dropped += 1
            log.debug("stint_row_skipped", reason=str(exc))

    if dropped:
        log.warning(
            "stint_rows_dropped",
            year=year,
            round=round_number,
            dropped=dropped,
            kept=len(stints),
        )
    return stints


def _safe_race_control(
    openf1: OpenF1Adapter,
    session_key: int,
    year: int,
    round_number: int,
) -> list[RaceControlMessage]:
    try:
        return openf1.get_race_control(session_key)
    except DataNotAvailableError as exc:
        log.warning(
            "openf1_race_control_unavailable",
            year=year,
            round=round_number,
            session_key=session_key,
            reason=str(exc),
        )
        return []


def _safe_openf1_weather(
    openf1: OpenF1Adapter,
    session_key: int,
    year: int,
    round_number: int,
) -> pd.DataFrame:
    try:
        return openf1.get_weather(session_key)
    except DataNotAvailableError as exc:
        log.warning(
            "openf1_weather_unavailable",
            year=year,
            round=round_number,
            session_key=session_key,
            reason=str(exc),
        )
        return pd.DataFrame()


__all__ = ["load_race_weekend"]
