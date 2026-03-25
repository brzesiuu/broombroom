"""jolpica-f1 API adapter.

Provides typed access to the jolpica-f1 REST API (Ergast-compatible successor).
All responses are cached — finished seasons get infinite TTL, current season gets 30 min.

API base: https://api.jolpi.ca/ergast/f1/
Docs: https://github.com/jolpica/jolpica-f1
"""

from datetime import date, timedelta
from pathlib import Path

from broombroom.config import settings
from broombroom.data.cache.cache_manager import CacheManager, TTL_INFINITE, TTL_SCHEDULE, TTL_STANDINGS
from broombroom.data.models.results import (
    ConstructorStanding,
    DriverStanding,
    QualiResult,
    RaceResult,
)
from broombroom.data.models.event import RaceEvent, SessionType
from broombroom.errors import DataNotAvailableError
from broombroom.http import RateLimitedSession
from broombroom.logging import get_logger

log = get_logger(__name__)

_SOURCE = "jolpica"
_CURRENT_SEASON = date.today().year


class JolpicaAdapter:
    """Typed client for the jolpica-f1 REST API with caching.

    Args:
        base_url: API root URL (defaults to settings value).
        cache_dir: Directory for the application cache.
        rate_per_second: Max requests per second (default 1).
    """

    def __init__(
        self,
        base_url: str | None = None,
        cache_dir: Path | None = None,
        rate_per_second: float | None = None,
    ) -> None:
        self._session = RateLimitedSession(
            base_url=base_url or settings.jolpica_base_url,
            rate_per_second=rate_per_second or settings.jolpica_rate_limit_per_second,
            timeout=settings.http_timeout_seconds,
            max_retries=settings.http_max_retries,
        )
        self._cache = CacheManager(cache_dir or settings.app_cache_dir)

    # ── Season schedule ────────────────────────────────────────────────────────

    def get_season_schedule(self, year: int) -> list[RaceEvent]:
        """Return all race events for the given season."""
        key = CacheManager.make_key(_SOURCE, "schedule", str(year))
        ttl = TTL_SCHEDULE if year >= _CURRENT_SEASON else TTL_INFINITE

        cached = self._cache.get(key)
        if cached is not None:
            return [RaceEvent(**e) for e in cached]

        data = self._get(f"f1/{year}.json", limit=100)
        races = data.get("MRData", {}).get("RaceTable", {}).get("Races", [])
        events = [self._parse_race_event(r, year) for r in races]

        self._cache.put(key, [e.model_dump(mode="json") for e in events], ttl_seconds=ttl, source=_SOURCE)
        return events

    # ── Race results ───────────────────────────────────────────────────────────

    def get_race_results(self, year: int, round_number: int) -> list[RaceResult]:
        """Return classified results for a race."""
        key = CacheManager.make_key(_SOURCE, "race_results", str(year), str(round_number))
        ttl = TTL_INFINITE  # once a race is over, results never change

        cached = self._cache.get(key)
        if cached is not None:
            return [RaceResult(**r) for r in cached]

        data = self._get(f"f1/{year}/{round_number}/results.json", limit=25)
        races = data.get("MRData", {}).get("RaceTable", {}).get("Races", [])
        if not races:
            raise DataNotAvailableError(f"No race results found for {year} round {round_number}")

        results = [self._parse_race_result(r, year, round_number) for r in races[0].get("Results", [])]
        self._cache.put(key, [r.model_dump(mode="json") for r in results], ttl_seconds=ttl, source=_SOURCE)
        return results

    # ── Qualifying results ─────────────────────────────────────────────────────

    def get_qualifying_results(self, year: int, round_number: int) -> list[QualiResult]:
        """Return qualifying results for a race weekend."""
        key = CacheManager.make_key(_SOURCE, "quali_results", str(year), str(round_number))
        ttl = TTL_INFINITE

        cached = self._cache.get(key)
        if cached is not None:
            return [QualiResult(**r) for r in cached]

        data = self._get(f"f1/{year}/{round_number}/qualifying.json", limit=25)
        races = data.get("MRData", {}).get("RaceTable", {}).get("Races", [])
        if not races:
            raise DataNotAvailableError(f"No qualifying results for {year} round {round_number}")

        results = [self._parse_quali_result(r, year, round_number) for r in races[0].get("QualifyingResults", [])]
        self._cache.put(key, [r.model_dump(mode="json") for r in results], ttl_seconds=ttl, source=_SOURCE)
        return results

    # ── Standings ──────────────────────────────────────────────────────────────

    def get_driver_standings(self, year: int, round_number: int | None = None) -> list[DriverStanding]:
        """Return driver championship standings.

        Args:
            year: Season year.
            round_number: Standing after this round. None = end of season / latest.
        """
        round_str = str(round_number) if round_number else "current"
        key = CacheManager.make_key(_SOURCE, "driver_standings", str(year), round_str)
        ttl = TTL_STANDINGS if year >= _CURRENT_SEASON else TTL_INFINITE

        cached = self._cache.get(key)
        if cached is not None:
            return [DriverStanding(**s) for s in cached]

        path = f"f1/{year}/{round_str}/driverStandings.json" if round_number else f"f1/{year}/driverStandings.json"
        data = self._get(path, limit=25)
        standings_list = (
            data.get("MRData", {})
            .get("StandingsTable", {})
            .get("StandingsLists", [])
        )
        if not standings_list:
            raise DataNotAvailableError(f"No driver standings for {year} round {round_str}")

        round_used = int(standings_list[0].get("round", round_number or 0))
        standings = [
            self._parse_driver_standing(s, year, round_used)
            for s in standings_list[0].get("DriverStandings", [])
        ]
        self._cache.put(key, [s.model_dump(mode="json") for s in standings], ttl_seconds=ttl, source=_SOURCE)
        return standings

    def get_constructor_standings(self, year: int, round_number: int | None = None) -> list[ConstructorStanding]:
        """Return constructor championship standings."""
        round_str = str(round_number) if round_number else "current"
        key = CacheManager.make_key(_SOURCE, "constructor_standings", str(year), round_str)
        ttl = TTL_STANDINGS if year >= _CURRENT_SEASON else TTL_INFINITE

        cached = self._cache.get(key)
        if cached is not None:
            return [ConstructorStanding(**s) for s in cached]

        path = (
            f"f1/{year}/{round_number}/constructorStandings.json"
            if round_number
            else f"f1/{year}/constructorStandings.json"
        )
        data = self._get(path, limit=25)
        standings_list = (
            data.get("MRData", {})
            .get("StandingsTable", {})
            .get("StandingsLists", [])
        )
        if not standings_list:
            raise DataNotAvailableError(f"No constructor standings for {year} round {round_str}")

        round_used = int(standings_list[0].get("round", round_number or 0))
        standings = [
            self._parse_constructor_standing(s, year, round_used)
            for s in standings_list[0].get("ConstructorStandings", [])
        ]
        self._cache.put(key, [s.model_dump(mode="json") for s in standings], ttl_seconds=ttl, source=_SOURCE)
        return standings

    # ── HTTP helper ────────────────────────────────────────────────────────────

    def _get(self, path: str, limit: int = 30) -> dict:
        return self._session.get(path, params={"limit": limit})

    # ── Parsers ────────────────────────────────────────────────────────────────

    @staticmethod
    def _parse_race_event(race: dict, year: int) -> RaceEvent:
        return RaceEvent(
            season=year,
            round_number=int(race["round"]),
            event_name=race["raceName"],
            circuit_key=race["Circuit"]["circuitId"],
            country=race["Circuit"]["Location"]["country"],
            locality=race["Circuit"]["Location"]["locality"],
            date=date.fromisoformat(race["date"]),
            sessions=[SessionType.RACE],
        )

    @staticmethod
    def _parse_race_result(result: dict, year: int, round_number: int) -> RaceResult:
        pos_str = result.get("position")
        finish_pos = int(pos_str) if pos_str and pos_str.isdigit() else None

        fastest_lap_time: timedelta | None = None
        fastest_lap = result.get("FastestLap", {})
        fl_time_str = fastest_lap.get("Time", {}).get("time")
        if fl_time_str:
            parts = fl_time_str.split(":")
            if len(parts) == 2:
                minutes, rest = parts
                seconds, *millis = rest.split(".")
                ms = int(millis[0]) * 1000 if millis else 0
                fastest_lap_time = timedelta(
                    minutes=int(minutes), seconds=int(seconds), milliseconds=ms
                )

        return RaceResult(
            season=year,
            round_number=round_number,
            driver_id=result["Driver"]["driverId"],
            driver_code=result["Driver"].get("code", result["Driver"]["driverId"][:3].upper()),
            constructor_id=result["Constructor"]["constructorId"],
            grid_position=int(result.get("grid", 0)),
            finish_position=finish_pos,
            status=result.get("status", "Unknown"),
            points=float(result.get("points", 0)),
            fastest_lap=fastest_lap.get("rank") == "1",
            fastest_lap_time=fastest_lap_time,
            laps_completed=int(result.get("laps", 0)),
        )

    @staticmethod
    def _parse_quali_result(result: dict, year: int, round_number: int) -> QualiResult:
        def _parse_time(t: str | None) -> timedelta | None:
            if not t:
                return None
            parts = t.split(":")
            if len(parts) == 2:
                minutes, rest = parts
                seconds, *millis = rest.split(".")
                ms = int(millis[0]) * 1000 if millis else 0
                return timedelta(minutes=int(minutes), seconds=int(seconds), milliseconds=ms)
            return None

        return QualiResult(
            season=year,
            round_number=round_number,
            driver_id=result["Driver"]["driverId"],
            driver_code=result["Driver"].get("code", result["Driver"]["driverId"][:3].upper()),
            constructor_id=result["Constructor"]["constructorId"],
            position=int(result["position"]),
            q1_time=_parse_time(result.get("Q1")),
            q2_time=_parse_time(result.get("Q2")),
            q3_time=_parse_time(result.get("Q3")),
        )

    @staticmethod
    def _parse_driver_standing(standing: dict, year: int, round_number: int) -> DriverStanding:
        driver = standing["Driver"]
        return DriverStanding(
            season=year,
            round_number=round_number,
            position=int(standing["position"]),
            driver_id=driver["driverId"],
            driver_code=driver.get("code", driver["driverId"][:3].upper()),
            constructor_id=standing["Constructors"][0]["constructorId"] if standing.get("Constructors") else "",
            points=float(standing["points"]),
            wins=int(standing["wins"]),
        )

    @staticmethod
    def _parse_constructor_standing(standing: dict, year: int, round_number: int) -> ConstructorStanding:
        constructor = standing["Constructor"]
        return ConstructorStanding(
            season=year,
            round_number=round_number,
            position=int(standing["position"]),
            constructor_id=constructor["constructorId"],
            constructor_name=constructor["name"],
            points=float(standing["points"]),
            wins=int(standing["wins"]),
        )

    def close(self) -> None:
        self._session.close()

    def __enter__(self) -> "JolpicaAdapter":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()
