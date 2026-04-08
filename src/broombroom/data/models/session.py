"""Session-level metadata and loaded-session wrapper.

Two complementary types:

- ``SessionMeta`` — a Pydantic model carrying only scalar session metadata.
  Serialisable, hashable, safe to log and cache.
- ``SessionData`` — a frozen dataclass that bundles ``SessionMeta`` with the
  DataFrames that an adapter loaded eagerly (laps, weather, results).

DataFrames stay as DataFrames — only scalar metadata goes through Pydantic.
Telemetry is NOT included here; it is loaded lazily via the adapter because
it is large and most callers do not need it.
"""

from dataclasses import dataclass
from datetime import datetime

import pandas as pd
from pydantic import BaseModel, Field

from broombroom.data.models.event import SessionType


class SessionMeta(BaseModel):
    """Scalar metadata describing a loaded session."""

    season: int = Field(ge=1950, le=2100)
    round_number: int = Field(ge=1, le=30)
    event_name: str
    circuit_key: str
    session_type: SessionType
    # fastf1's human-readable session name (e.g. "Race", "Practice 1")
    session_name: str
    session_date: datetime | None = None
    total_laps: int | None = Field(default=None, ge=0)


@dataclass(frozen=True, eq=False)
class SessionData:
    """Eagerly-loaded session: metadata plus laps, weather, and results DataFrames.

    Constructed by ``FastF1Adapter.get_session``. Telemetry is intentionally
    absent — call ``FastF1Adapter.get_lap_telemetry`` when a specific lap's
    telemetry trace is needed.

    ``eq=False`` because pandas DataFrame equality does not return a bool and
    would break the auto-generated ``__eq__``.
    """

    meta: SessionMeta
    laps: pd.DataFrame
    weather: pd.DataFrame
    results: pd.DataFrame
