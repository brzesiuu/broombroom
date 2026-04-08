"""Loader functions that compose adapters into aggregate data structures.

Loaders are the single call site analysis / UI code should use to reach
for weekend or season data — they orchestrate the jolpica, fastf1, and
openf1 adapters, handle coverage rules, and return typed models defined
in ``broombroom.data.models``.
"""

from broombroom.data.loaders.season_loader import (
    load_constructor_championship,
    load_driver_championship,
    load_season_results,
    load_season_schedule,
)
from broombroom.data.loaders.session_loader import load_race_weekend

__all__ = [
    "load_constructor_championship",
    "load_driver_championship",
    "load_race_weekend",
    "load_season_results",
    "load_season_schedule",
]
