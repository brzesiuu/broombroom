"""Tyre stint and compound models."""

from enum import StrEnum

from pydantic import BaseModel, Field, model_validator


class Compound(StrEnum):
    SOFT = "SOFT"
    MEDIUM = "MEDIUM"
    HARD = "HARD"
    INTERMEDIATE = "INTERMEDIATE"
    WET = "WET"
    UNKNOWN = "UNKNOWN"

    @classmethod
    def from_fastf1(cls, value: str | None) -> "Compound":
        """Normalise a fastf1 compound string to a Compound enum value."""
        if value is None:
            return cls.UNKNOWN
        mapping = {
            "SOFT": cls.SOFT,
            "MEDIUM": cls.MEDIUM,
            "HARD": cls.HARD,
            "INTERMEDIATE": cls.INTERMEDIATE,
            "INTER": cls.INTERMEDIATE,
            "WET": cls.WET,
        }
        return mapping.get(value.upper(), cls.UNKNOWN)

    @property
    def color(self) -> str:
        """Canonical hex color used in all visualizations."""
        colors = {
            Compound.SOFT: "#FF3333",
            Compound.MEDIUM: "#FFD700",
            Compound.HARD: "#EEEEEE",
            Compound.INTERMEDIATE: "#39B54A",
            Compound.WET: "#0067FF",
            Compound.UNKNOWN: "#AAAAAA",
        }
        return colors[self]

    @property
    def is_slick(self) -> bool:
        return self in (Compound.SOFT, Compound.MEDIUM, Compound.HARD)


class Stint(BaseModel):
    """A single tyre stint for one driver."""

    driver_code: str
    stint_number: int = Field(ge=1)
    compound: Compound
    start_lap: int = Field(ge=1)
    end_lap: int = Field(ge=1)
    tyre_age_at_start: int = Field(ge=0)  # laps already on tyre when stint began

    @model_validator(mode="after")
    def _end_after_start(self) -> "Stint":
        if self.end_lap < self.start_lap:
            raise ValueError(f"end_lap ({self.end_lap}) must be >= start_lap ({self.start_lap})")
        return self

    @property
    def length(self) -> int:
        return self.end_lap - self.start_lap + 1

    @property
    def max_tyre_age(self) -> int:
        return self.tyre_age_at_start + self.length - 1


class PitStop(BaseModel):
    """A single pit stop entry."""

    driver_code: str
    stop_number: int = Field(ge=1)
    lap: int = Field(ge=1)
    duration_seconds: float | None = None  # stationary time only
    total_time_seconds: float | None = None  # including in/out lap penalty


class TyreStrategy(BaseModel):
    """Full race strategy for one driver — collection of stints."""

    driver_code: str
    stints: list[Stint]
    pit_stops: list[PitStop] = Field(default_factory=list)

    @property
    def stop_count(self) -> int:
        return len(self.stints) - 1

    @property
    def compounds_used(self) -> list[Compound]:
        return [s.compound for s in self.stints]
