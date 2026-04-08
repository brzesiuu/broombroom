"""Circuit and track models."""

from typing import Literal

from pydantic import BaseModel, Field


class Corner(BaseModel):
    """A single corner on the circuit, annotated from fastf1 CircuitInfo."""

    number: int = Field(ge=1)
    letter: str = ""  # "A", "B" for chicane entries, "" for single corners
    angle: float  # turn angle in degrees (approximate)
    distance: float = Field(ge=0.0)  # meters from start/finish line
    speed_category: Literal["low", "medium", "high"] = "medium"

    @property
    def label(self) -> str:
        return f"T{self.number}{self.letter}"


class DRSZone(BaseModel):
    """A single DRS detection + activation zone."""

    zone_number: int
    detection_distance: float  # meters from S/F
    activation_distance: float
    end_distance: float


class CircuitInfo(BaseModel):
    """Full circuit description including track geometry from fastf1."""

    circuit_key: str
    name: str
    country: str
    locality: str
    # Not always available at adapter load time — analysis layer can derive it
    # from telemetry (fastf1 does not expose lap length as a scalar).
    lap_length_km: float | None = Field(default=None, gt=0.0)
    corners: list[Corner] = Field(default_factory=list)
    drs_zones: list[DRSZone] = Field(default_factory=list)
    rotation: float = 0.0  # track map rotation in degrees (fastf1 convention)
    # Track path coordinates (from fastf1 CircuitInfo, normalized to meters)
    x_coords: list[float] = Field(default_factory=list)
    y_coords: list[float] = Field(default_factory=list)

    @property
    def total_corners(self) -> int:
        return len(self.corners)

    @property
    def drs_zone_count(self) -> int:
        return len(self.drs_zones)

    def corners_by_speed(self, category: Literal["low", "medium", "high"]) -> list[Corner]:
        return [c for c in self.corners if c.speed_category == category]


class CircuitProfile(BaseModel):
    """Computed circuit characteristics — input to ML models and compatibility scoring.

    Derived from CircuitInfo by analysis/circuit.py::classify_circuit().
    """

    circuit_key: str
    name: str

    # Corner composition (fractions sum to ~1.0)
    low_speed_corner_pct: float = Field(ge=0.0, le=1.0)
    medium_speed_corner_pct: float = Field(ge=0.0, le=1.0)
    high_speed_corner_pct: float = Field(ge=0.0, le=1.0)

    total_corners: int = Field(ge=0)
    drs_zone_count: int = Field(ge=0)
    lap_length_km: float = Field(gt=0.0)

    # Estimated straight length (sum of track segments with no cornering)
    estimated_straight_length_km: float = Field(ge=0.0)

    # Downforce level implied by the circuit: high = Monaco, low = Monza
    implied_downforce_level: Literal["low", "medium", "high"] = "medium"

    # Optional elevation data (not always available)
    elevation_change_m: float | None = None

    # Circuit type for high-level categorisation
    circuit_type: Literal["street", "permanent", "hybrid"] = "permanent"
