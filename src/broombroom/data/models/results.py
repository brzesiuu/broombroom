"""Race results and standings models."""

from datetime import timedelta

from pydantic import BaseModel, Field, field_validator, model_validator


class RaceResult(BaseModel):
    """Single driver result for one race."""

    season: int
    round_number: int
    driver_id: str  # e.g. "max_verstappen" (jolpica format)
    driver_code: str  # e.g. "VER"
    constructor_id: str  # e.g. "red_bull"
    grid_position: int  # 0 = pit lane start
    finish_position: int | None  # None = DNF / DNS / DSQ
    status: str  # "Finished", "+1 Lap", "Accident", etc.
    points: float = Field(ge=0.0)
    fastest_lap: bool = False
    fastest_lap_time: timedelta | None = None
    laps_completed: int = Field(default=0, ge=0)

    @property
    def classified(self) -> bool:
        return self.finish_position is not None

    @property
    def dnf(self) -> bool:
        return not self.classified

    @field_validator("driver_code")
    @classmethod
    def _upper_code(cls, v: str) -> str:
        return v.upper()


class QualiResult(BaseModel):
    """Single driver qualifying result."""

    season: int
    round_number: int
    driver_id: str
    driver_code: str
    constructor_id: str
    position: int = Field(ge=1)
    q1_time: timedelta | None = None
    q2_time: timedelta | None = None
    q3_time: timedelta | None = None

    @property
    def best_time(self) -> timedelta | None:
        """Return the best Q time set (Q3 > Q2 > Q1)."""
        return self.q3_time or self.q2_time or self.q1_time

    @field_validator("driver_code")
    @classmethod
    def _upper_code(cls, v: str) -> str:
        return v.upper()

    @model_validator(mode="after")
    def _q2_requires_q1(self) -> "QualiResult":
        if self.q2_time is not None and self.q1_time is None:
            raise ValueError("q2_time set but q1_time is None — invalid qualifying data")
        if self.q3_time is not None and self.q2_time is None:
            raise ValueError("q3_time set but q2_time is None — invalid qualifying data")
        return self


class DriverStanding(BaseModel):
    """Driver championship standing at a given point in the season."""

    season: int
    round_number: int  # standing after this round (0 = pre-season)
    position: int = Field(ge=1)
    driver_id: str
    driver_code: str
    constructor_id: str
    points: float = Field(ge=0.0)
    wins: int = Field(ge=0)

    @field_validator("driver_code")
    @classmethod
    def _upper_code(cls, v: str) -> str:
        return v.upper()


class ConstructorStanding(BaseModel):
    """Constructor championship standing at a given point in the season."""

    season: int
    round_number: int
    position: int = Field(ge=1)
    constructor_id: str
    constructor_name: str
    points: float = Field(ge=0.0)
    wins: int = Field(ge=0)
