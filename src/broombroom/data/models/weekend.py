"""Race weekend aggregate model.

``RaceWeekendData`` bundles everything the loaders layer collects for one
Grand Prix weekend across the three data sources (jolpica, fastf1, openf1).
It is the canonical input shape for analysis and viz code that needs more
than a single adapter can provide.

Like :class:`~broombroom.data.models.session.SessionData`, this is a frozen
dataclass (not a Pydantic model): the nested ``SessionData.laps`` etc. are
DataFrames, and ``openf1_weather`` is a DataFrame too — wrapping those in
Pydantic would force serialisation of large tables. Scalar metadata is
already inside the Pydantic members (``event``, ``race_results``, ...).

``eq=False`` because pandas DataFrame equality does not return a bool and
would break the auto-generated ``__eq__``.
"""

from dataclasses import dataclass, field

import pandas as pd

from broombroom.data.models.event import RaceEvent
from broombroom.data.models.results import QualiResult, RaceResult
from broombroom.data.models.session import SessionData
from broombroom.data.models.stint import Stint
from broombroom.data.models.telemetry import RaceControlMessage


@dataclass(frozen=True, eq=False)
class RaceWeekendData:
    """All data the loaders layer gathers for one race weekend.

    Attributes:
        event: Race metadata from jolpica (always present).
        race_results: Classified race results from jolpica (always present).
        quali_results: Qualifying results from jolpica. May be empty when
            qualifying data is missing for very old seasons.
        race_session: fastf1 race session with laps + weather + results.
            ``None`` for years < 2018 (fastf1 coverage floor).
        stints: Tyre stints harmonised from openf1 ``driver_number`` to
            ``driver_code`` via the fastf1 results table. Empty list for
            years < 2023 (openf1 coverage floor) or when openf1 returns
            no stint rows for the session.
        race_control: Race control messages from openf1. Empty for years
            < 2023.
        openf1_weather: Weather DataFrame from openf1. Empty DataFrame for
            years < 2023. Complements ``race_session.weather`` (which comes
            from fastf1 and is keyed on session-relative timestamps).
    """

    event: RaceEvent
    race_results: list[RaceResult]
    quali_results: list[QualiResult]
    race_session: SessionData | None = None
    stints: list[Stint] = field(default_factory=list)
    race_control: list[RaceControlMessage] = field(default_factory=list)
    openf1_weather: pd.DataFrame = field(default_factory=pd.DataFrame)

    @property
    def season(self) -> int:
        return self.event.season

    @property
    def round_number(self) -> int:
        return self.event.round_number

    @property
    def has_telemetry_data(self) -> bool:
        """True when fastf1 race session data is available."""
        return self.race_session is not None

    @property
    def has_openf1_data(self) -> bool:
        """True when any openf1-sourced field was populated."""
        return bool(self.stints) or bool(self.race_control) or not self.openf1_weather.empty
