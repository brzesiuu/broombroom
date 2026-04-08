"""fastf1 adapter — telemetry, lap data, weather, and circuit geometry.

Coverage: 2018+. fastf1 itself maintains a disk cache; this adapter does NOT
wrap responses in our ``CacheManager`` (that would double-cache). The cache
directory is enabled once in ``__init__`` via ``fastf1.Cache.enable_cache``,
which fastf1 treats as idempotent.

Eager vs lazy loading:

- ``get_event_schedule`` and ``get_session`` return eagerly-populated
  dataclasses / models: laps, weather and results are loaded up front.
- ``get_lap_telemetry`` is lazy — telemetry traces are large, so a caller
  must ask for them explicitly by (driver, lap number).

Errors from fastf1 are deliberately normalised to ``DataNotAvailableError``
so callers can handle "session does not exist" and "year too old" with the
same exception type.
"""

from datetime import date
from pathlib import Path
from typing import Any

import fastf1
import pandas as pd

from broombroom.config import settings
from broombroom.data.models.circuit import CircuitInfo, Corner
from broombroom.data.models.event import RaceEvent, SessionType
from broombroom.data.models.session import SessionData, SessionMeta
from broombroom.errors import DataNotAvailableError
from broombroom.logging import get_logger

log = get_logger(__name__)

# fastf1 telemetry coverage starts in 2018 — older seasons are not supported.
_MIN_SUPPORTED_YEAR = 2018

# Map our SessionType enum to fastf1's short session identifiers.
_SESSION_TYPE_TO_FASTF1: dict[SessionType, str] = {
    SessionType.PRACTICE_1: "FP1",
    SessionType.PRACTICE_2: "FP2",
    SessionType.PRACTICE_3: "FP3",
    SessionType.QUALIFYING: "Q",
    SessionType.SPRINT_QUALIFYING: "SS",  # sprint shootout / sprint qualifying
    SessionType.SPRINT: "S",
    SessionType.RACE: "R",
}

# Map fastf1 long session names (from the schedule DataFrame columns Session1..5)
# to our SessionType enum.
_FASTF1_SESSION_NAME_TO_TYPE: dict[str, SessionType] = {
    "Practice 1": SessionType.PRACTICE_1,
    "Practice 2": SessionType.PRACTICE_2,
    "Practice 3": SessionType.PRACTICE_3,
    "Qualifying": SessionType.QUALIFYING,
    "Sprint Qualifying": SessionType.SPRINT_QUALIFYING,
    "Sprint Shootout": SessionType.SPRINT_QUALIFYING,
    "Sprint": SessionType.SPRINT,
    "Race": SessionType.RACE,
}


class FastF1Adapter:
    """Typed adapter around the fastf1 library.

    Args:
        cache_dir: Directory for the fastf1 disk cache. Defaults to
            ``settings.fastf1_cache_dir``. Created if it does not exist.
        min_year: Earliest supported season. Defaults to 2018 — raising
            ``DataNotAvailableError`` for older years matches fastf1 coverage.
    """

    def __init__(
        self,
        cache_dir: Path | None = None,
        min_year: int = _MIN_SUPPORTED_YEAR,
    ) -> None:
        cache = cache_dir or settings.fastf1_cache_dir
        cache.mkdir(parents=True, exist_ok=True)
        # enable_cache is idempotent — safe to call on every adapter instance.
        fastf1.Cache.enable_cache(str(cache))
        self._min_year = min_year
        log.debug("fastf1_adapter_init", cache_dir=str(cache), min_year=min_year)

    # ── Schedule ───────────────────────────────────────────────────────────────

    def get_event_schedule(self, year: int) -> list[RaceEvent]:
        """Return the race events for ``year`` as ``RaceEvent`` models.

        Testing events are excluded.
        """
        self._guard_year(year)
        try:
            schedule = fastf1.get_event_schedule(year, include_testing=False)
        except Exception as exc:  # noqa: BLE001 — fastf1 raises many error types
            raise DataNotAvailableError(f"fastf1 could not load schedule for {year}: {exc}") from exc

        return [self._row_to_race_event(row, year) for _, row in schedule.iterrows()]

    # ── Session ────────────────────────────────────────────────────────────────

    def get_session(
        self,
        year: int,
        round_number: int,
        session_type: SessionType,
    ) -> SessionData:
        """Load a session and eagerly populate laps, weather, and results.

        Telemetry is deliberately NOT loaded — call :meth:`get_lap_telemetry`
        for specific (driver, lap) traces.
        """
        self._guard_year(year)
        session = self._load_session(
            year=year,
            round_number=round_number,
            session_type=session_type,
            with_telemetry=False,
        )

        meta = self._build_session_meta(
            session=session,
            year=year,
            round_number=round_number,
            session_type=session_type,
        )
        return SessionData(
            meta=meta,
            laps=_safe_frame(getattr(session, "laps", None)),
            weather=_safe_frame(getattr(session, "weather_data", None)),
            results=_safe_frame(getattr(session, "results", None)),
        )

    # ── Circuit info ───────────────────────────────────────────────────────────

    def get_circuit_info(self, year: int, round_number: int) -> CircuitInfo:
        """Return circuit geometry (corners, rotation) for a race weekend.

        fastf1 ties circuit info to a loaded session — we use the race session
        with only metadata loaded (no laps / telemetry / weather).

        Note: ``lap_length_km`` is left as ``None`` — fastf1 does not expose
        it as a scalar, and deriving it from telemetry belongs in the analysis
        layer rather than the adapter.
        """
        self._guard_year(year)
        session = self._load_session(
            year=year,
            round_number=round_number,
            session_type=SessionType.RACE,
            with_laps=False,
            with_weather=False,
        )

        try:
            ci = session.get_circuit_info()
        except Exception as exc:  # noqa: BLE001 — fastf1 raises many error types
            raise DataNotAvailableError(
                f"fastf1 could not load circuit info for {year} round {round_number}: {exc}"
            ) from exc

        corners = _parse_corners(getattr(ci, "corners", None))
        event = getattr(session, "event", None)
        return CircuitInfo(
            circuit_key=_circuit_key_from_event(event),
            name=_event_field(event, "EventName", default=""),
            country=_event_field(event, "Country", default=""),
            locality=_event_field(event, "Location", default=""),
            corners=corners,
            rotation=float(getattr(ci, "rotation", 0.0) or 0.0),
        )

    # ── Telemetry (lazy) ───────────────────────────────────────────────────────

    def get_lap_telemetry(
        self,
        session_data: SessionData,
        driver: str,
        lap_number: int,
    ) -> pd.DataFrame:
        """Return the telemetry DataFrame for a single lap.

        Re-loads the session with telemetry enabled. fastf1's own disk cache
        makes the second load cheap when the same session was fetched earlier
        via :meth:`get_session`.
        """
        meta = session_data.meta
        self._guard_year(meta.season)

        session = self._load_session(
            year=meta.season,
            round_number=meta.round_number,
            session_type=meta.session_type,
            with_telemetry=True,
            with_weather=False,
        )
        try:
            driver_laps = session.laps.pick_drivers(driver)
            lap_rows = driver_laps[driver_laps["LapNumber"] == lap_number]
            if lap_rows.empty:
                raise DataNotAvailableError(
                    f"No lap {lap_number} for driver {driver!r} in "
                    f"{meta.season} R{meta.round_number} {meta.session_type.value}"
                )
            return lap_rows.iloc[0].get_telemetry()
        except DataNotAvailableError:
            raise
        except Exception as exc:  # noqa: BLE001 — fastf1 raises many error types
            raise DataNotAvailableError(
                f"fastf1 could not load telemetry for {driver!r} "
                f"lap {lap_number} ({meta.season} R{meta.round_number}): {exc}"
            ) from exc

    # ── Internals ──────────────────────────────────────────────────────────────

    def _guard_year(self, year: int) -> None:
        if year < self._min_year:
            raise DataNotAvailableError(f"fastf1 only supports year >= {self._min_year}, got {year}")

    def _load_session(
        self,
        year: int,
        round_number: int,
        session_type: SessionType,
        with_laps: bool = True,
        with_telemetry: bool = False,
        with_weather: bool = True,
    ) -> Any:
        """Call fastf1.get_session + session.load, normalising errors."""
        fastf1_id = _SESSION_TYPE_TO_FASTF1[session_type]
        try:
            session = fastf1.get_session(year, round_number, fastf1_id)
            session.load(
                laps=with_laps,
                telemetry=with_telemetry,
                weather=with_weather,
                messages=False,
            )
        except Exception as exc:  # noqa: BLE001 — fastf1 raises many error types
            raise DataNotAvailableError(
                f"fastf1 could not load {session_type.value} for {year} round {round_number}: {exc}"
            ) from exc
        return session

    @staticmethod
    def _build_session_meta(
        session: Any,
        year: int,
        round_number: int,
        session_type: SessionType,
    ) -> SessionMeta:
        event = getattr(session, "event", None)
        raw_total_laps = getattr(session, "total_laps", None)
        total_laps: int | None
        try:
            total_laps = int(raw_total_laps) if raw_total_laps else None
        except (TypeError, ValueError):
            total_laps = None

        raw_date = getattr(session, "date", None)
        session_date = raw_date.to_pydatetime() if isinstance(raw_date, pd.Timestamp) else raw_date

        return SessionMeta(
            season=year,
            round_number=round_number,
            event_name=_event_field(event, "EventName", default=""),
            circuit_key=_circuit_key_from_event(event),
            session_type=session_type,
            session_name=str(getattr(session, "name", "") or ""),
            session_date=session_date,
            total_laps=total_laps,
        )

    @staticmethod
    def _row_to_race_event(row: pd.Series, year: int) -> RaceEvent:
        event_format = str(row.get("EventFormat", "") or "")
        has_sprint = event_format.startswith("sprint")

        sessions: list[SessionType] = []
        for i in range(1, 6):
            raw = row.get(f"Session{i}")
            if raw is None or (isinstance(raw, float) and pd.isna(raw)) or not str(raw):
                continue
            mapped = _FASTF1_SESSION_NAME_TO_TYPE.get(str(raw))
            if mapped is not None:
                sessions.append(mapped)

        date_value = _coerce_date(row["EventDate"])

        return RaceEvent(
            season=year,
            round_number=int(row["RoundNumber"]),
            event_name=str(row.get("EventName", "") or ""),
            circuit_key=_slug(str(row.get("Location", "") or "")),
            country=str(row.get("Country", "") or ""),
            locality=str(row.get("Location", "") or ""),
            date=date_value,
            sprint=has_sprint,
            sessions=sessions,
        )


# ── Module helpers ─────────────────────────────────────────────────────────────


def _coerce_date(value: Any) -> date:
    """Convert a pandas/numpy/datetime-ish value to a plain ``datetime.date``.

    Centralised so the one ``type: ignore`` we need for pandas' broad
    ``Series.__getitem__`` stubs lives in a single place.
    """
    if isinstance(value, pd.Timestamp):
        return value.date()
    if isinstance(value, date):
        return value
    return pd.Timestamp(value).date()  # type: ignore[arg-type]


def _safe_frame(df: pd.DataFrame | None) -> pd.DataFrame:
    """Return ``df`` with a fresh range index, or an empty DataFrame if None."""
    if df is None:
        return pd.DataFrame()
    return df.reset_index(drop=True)


def _parse_corners(corners_df: pd.DataFrame | None) -> list[Corner]:
    if corners_df is None or corners_df.empty:
        return []
    parsed: list[Corner] = []
    for _, row in corners_df.iterrows():
        parsed.append(
            Corner(
                number=int(row["Number"]),
                letter=str(row.get("Letter", "") or ""),
                angle=float(row.get("Angle", 0.0) or 0.0),
                distance=float(row.get("Distance", 0.0) or 0.0),
            )
        )
    return parsed


def _event_field(event: Any, key: str, default: str = "") -> str:
    if event is None:
        return default
    try:
        value = event.get(key, default) if hasattr(event, "get") else getattr(event, key, default)
    except (KeyError, AttributeError):
        return default
    return str(value) if value is not None else default


def _circuit_key_from_event(event: Any) -> str:
    """Derive a stable circuit_key from a fastf1 Event.

    fastf1 does not expose a canonical circuit id — we slugify the Location
    (city) field. The loaders layer (PR 1.5) is responsible for harmonising
    this with jolpica's circuitId.
    """
    location = _event_field(event, "Location", default="")
    return _slug(location)


def _slug(value: str) -> str:
    return value.strip().lower().replace(" ", "_")
