"""openf1 API adapter — supplemental F1 telemetry and session data.

openf1 provides high-resolution telemetry, stints, intervals, weather, and
race control messages for F1 sessions. Coverage begins in 2023 — any earlier
year raises :class:`DataNotAvailableError`.

Return shapes:

- Tabular endpoints (``sessions``, ``laps``, ``car_data``, ``stints``,
  ``intervals``, ``weather``) return ``pandas.DataFrame``. The columns
  mirror the openf1 response fields 1:1; harmonisation with jolpica /
  fastf1 identifiers (e.g. ``driver_number`` → ``driver_code``) belongs in
  the loaders layer, not here.
- ``get_race_control`` returns ``list[RaceControlMessage]`` — the data is
  small and structured enough to justify a typed Pydantic model.

Caching policy:

- ``get_sessions`` for a past year: ``TTL_INFINITE`` — past schedules do
  not change.
- ``get_sessions`` for the current / future year: ``TTL_SCHEDULE``.
- Per-session data endpoints: ``TTL_LIVE`` — callers cannot tell from a
  session_key alone whether the session is complete, so a short TTL is
  the safe default. PR 1.5 loaders can invalidate aggressively once a
  session is known to be over.

API base: https://api.openf1.org/v1
Docs: https://openf1.org/
"""

from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from broombroom.config import settings
from broombroom.data.cache.cache_manager import (
    TTL_INFINITE,
    TTL_LIVE,
    TTL_SCHEDULE,
    CacheManager,
)
from broombroom.data.models.telemetry import RaceControlMessage
from broombroom.errors import APIError, DataNotAvailableError
from broombroom.http import RateLimitedSession
from broombroom.logging import get_logger

log = get_logger(__name__)

_SOURCE = "openf1"
_MIN_SUPPORTED_YEAR = 2023


class OpenF1Adapter:
    """Typed client for the openf1 REST API with file-based caching.

    Args:
        base_url: API root URL (defaults to ``settings.openf1_base_url``).
        cache_dir: Directory for the application cache.
        rate_per_second: Max requests per second (defaults to
            ``settings.openf1_rate_limit_per_second``).
        min_year: Earliest supported year (defaults to 2023 — openf1 coverage).
    """

    def __init__(
        self,
        base_url: str | None = None,
        cache_dir: Path | None = None,
        rate_per_second: float | None = None,
        min_year: int = _MIN_SUPPORTED_YEAR,
    ) -> None:
        self._session = RateLimitedSession(
            base_url=base_url or settings.openf1_base_url,
            rate_per_second=rate_per_second or settings.openf1_rate_limit_per_second,
            timeout=settings.http_timeout_seconds,
            max_retries=settings.http_max_retries,
        )
        self._cache = CacheManager(cache_dir or settings.app_cache_dir)
        self._min_year = min_year

    # ── Sessions ───────────────────────────────────────────────────────────────

    def get_sessions(
        self,
        year: int,
        session_name: str | None = None,
        country_code: str | None = None,
    ) -> pd.DataFrame:
        """Return session metadata for a year, optionally filtered.

        Expected columns include ``session_key``, ``meeting_key``, ``year``,
        ``session_name``, ``session_type``, ``date_start``, ``date_end``,
        ``location``, ``country_name``, ``country_code``, ``circuit_short_name``.
        Returns an empty DataFrame if openf1 has no matching sessions.
        """
        self._guard_year(year)
        params: dict[str, str | int] = {"year": year}
        if session_name is not None:
            params["session_name"] = session_name
        if country_code is not None:
            params["country_code"] = country_code

        key = CacheManager.make_key(_SOURCE, "sessions", str(year), session_name or "", country_code or "")
        ttl = TTL_INFINITE if year < date.today().year else TTL_SCHEDULE
        return self._fetch_tabular("sessions", params=params, cache_key=key, ttl=ttl)

    # ── Laps ───────────────────────────────────────────────────────────────────

    def get_laps(self, session_key: int) -> pd.DataFrame:
        """Return per-lap data for a session.

        Expected columns include ``driver_number``, ``lap_number``,
        ``lap_duration``, ``duration_sector_1/2/3``, ``i1_speed``, ``i2_speed``,
        ``st_speed``, ``is_pit_out_lap``, ``date_start``.
        """
        return self._fetch_session_tabular("laps", session_key)

    # ── Car data ───────────────────────────────────────────────────────────────

    def get_car_data(
        self,
        session_key: int,
        driver_number: int | None = None,
    ) -> pd.DataFrame:
        """Return high-frequency car telemetry for a session.

        Expected columns include ``date``, ``driver_number``, ``rpm``,
        ``speed``, ``n_gear``, ``throttle``, ``brake``, ``drs``. Very large
        (thousands of rows per driver per session) — prefer filtering by
        ``driver_number`` unless you actually need everyone.
        """
        params: dict[str, str | int] = {"session_key": session_key}
        cache_parts = ["car_data", str(session_key)]
        if driver_number is not None:
            params["driver_number"] = driver_number
            cache_parts.append(str(driver_number))
        key = CacheManager.make_key(_SOURCE, *cache_parts)
        return self._fetch_tabular("car_data", params=params, cache_key=key, ttl=TTL_LIVE)

    # ── Stints ─────────────────────────────────────────────────────────────────

    def get_stints(self, session_key: int) -> pd.DataFrame:
        """Return tyre stint data for a session.

        Expected columns: ``session_key``, ``meeting_key``, ``driver_number``,
        ``stint_number``, ``compound``, ``lap_start``, ``lap_end``,
        ``tyre_age_at_start``. The loader (PR 1.5) maps ``driver_number`` to
        a driver code and wraps rows in :class:`~broombroom.data.models.stint.Stint`.
        """
        return self._fetch_session_tabular("stints", session_key)

    # ── Intervals ──────────────────────────────────────────────────────────────

    def get_intervals(self, session_key: int) -> pd.DataFrame:
        """Return gap-to-leader and interval-to-ahead data for a race session.

        Expected columns: ``date``, ``driver_number``, ``gap_to_leader``,
        ``interval``. High-frequency — multiple updates per driver per lap.
        """
        return self._fetch_session_tabular("intervals", session_key)

    # ── Weather ────────────────────────────────────────────────────────────────

    def get_weather(self, session_key: int) -> pd.DataFrame:
        """Return weather readings for a session.

        Expected columns: ``date``, ``air_temperature``, ``track_temperature``,
        ``humidity``, ``pressure``, ``rainfall``, ``wind_direction``,
        ``wind_speed``.
        """
        return self._fetch_session_tabular("weather", session_key)

    # ── Race control ───────────────────────────────────────────────────────────

    def get_race_control(self, session_key: int) -> list[RaceControlMessage]:
        """Return race control messages (flags, SC, DRS, etc.) for a session."""
        key = CacheManager.make_key(_SOURCE, "race_control", str(session_key))
        cached = self._cache.get(key)
        if cached is not None:
            return [RaceControlMessage(**m) for m in cached]

        data = self._get_list("race_control", params={"session_key": session_key})
        messages = [_parse_race_control(item) for item in data]
        self._cache.put(
            key,
            [m.model_dump(mode="json") for m in messages],
            ttl_seconds=TTL_LIVE,
            source=_SOURCE,
        )
        return messages

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def close(self) -> None:
        self._session.close()

    def __enter__(self) -> "OpenF1Adapter":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    # ── Internals ──────────────────────────────────────────────────────────────

    def _guard_year(self, year: int) -> None:
        if year < self._min_year:
            raise DataNotAvailableError(f"openf1 only supports year >= {self._min_year}, got {year}")

    def _fetch_session_tabular(self, path: str, session_key: int) -> pd.DataFrame:
        """Fetch a per-session tabular endpoint with TTL_LIVE caching."""
        key = CacheManager.make_key(_SOURCE, path, str(session_key))
        return self._fetch_tabular(
            path,
            params={"session_key": session_key},
            cache_key=key,
            ttl=TTL_LIVE,
        )

    def _fetch_tabular(
        self,
        path: str,
        params: dict[str, Any],
        cache_key: str,
        ttl: int,
    ) -> pd.DataFrame:
        """Shared fetch-and-cache helper for endpoints that return JSON arrays."""
        cached = self._cache.get(cache_key)
        if cached is not None:
            return pd.DataFrame(cached)

        data = self._get_list(path, params=params)
        self._cache.put(cache_key, data, ttl_seconds=ttl, source=_SOURCE)
        return pd.DataFrame(data)

    def _get_list(self, path: str, params: dict[str, Any]) -> list[dict]:
        """Call the shared session and narrow the response to a list of objects.

        openf1 always returns a JSON array at the top level. This helper
        raises :class:`APIError` if the API ever returns something else.
        """
        result = self._session.get(path, params=params)
        if not isinstance(result, list):
            raise APIError(
                source=_SOURCE,
                message=f"expected JSON array, got {type(result).__name__}",
            )
        return result


# ── Module helpers ─────────────────────────────────────────────────────────────


def _parse_race_control(item: dict) -> RaceControlMessage:
    """Map a raw openf1 /race_control row to a RaceControlMessage."""
    raw_date = item.get("date")
    timestamp: datetime | None = None
    if raw_date:
        try:
            timestamp = datetime.fromisoformat(str(raw_date).replace("Z", "+00:00"))
        except ValueError:
            timestamp = None

    driver_number = item.get("driver_number")
    return RaceControlMessage(
        timestamp=timestamp,
        lap_number=item.get("lap_number"),
        category=str(item.get("category") or ""),
        message=str(item.get("message") or ""),
        flag=item.get("flag"),
        scope=item.get("scope"),
        sector=item.get("sector"),
        driver_number=str(driver_number) if driver_number is not None else None,
    )
