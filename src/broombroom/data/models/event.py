"""Event and session schedule models."""

from datetime import date
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator


class SessionType(StrEnum):
    PRACTICE_1 = "FP1"
    PRACTICE_2 = "FP2"
    PRACTICE_3 = "FP3"
    QUALIFYING = "Q"
    SPRINT_QUALIFYING = "SQ"
    SPRINT = "S"
    RACE = "R"


class RaceEvent(BaseModel):
    """A single race weekend entry from the season schedule."""

    season: int = Field(ge=1950, le=2100)
    round_number: int = Field(ge=1, le=30)
    event_name: str
    circuit_key: str  # e.g. "monza", "spa"
    country: str
    locality: str  # city
    date: date  # race day date
    sprint: bool = False
    sessions: list[SessionType] = Field(default_factory=list)

    @field_validator("season")
    @classmethod
    def _season_reasonable(cls, v: int) -> int:
        if v < 1950 or v > 2100:
            raise ValueError(f"season must be between 1950 and 2100, got {v}")
        return v


class EventSummary(BaseModel):
    """Lightweight event reference used in dropdowns and selectors."""

    season: int
    round_number: int
    event_name: str
    circuit_key: str
    date: date
    sprint: bool = False


class SeasonSchedule(BaseModel):
    """Full season schedule."""

    season: int
    events: list[RaceEvent]

    @property
    def rounds(self) -> int:
        return len(self.events)

    def get_round(self, round_number: int) -> RaceEvent | None:
        for e in self.events:
            if e.round_number == round_number:
                return e
        return None
