"""Telemetry metadata models.

The actual telemetry data stays as pandas DataFrames for performance — these
models carry metadata about a telemetry dataset without serialising large arrays.
"""

from datetime import datetime, timedelta

from pydantic import BaseModel, Field


class TelemetryMeta(BaseModel):
    """Metadata for a single driver's telemetry trace on one lap.

    The DataFrame itself is passed separately; this model describes what
    channels are available and some key scalar values for quick inspection.
    """

    driver_code: str
    driver_number: str
    session_key: str
    lap_number: int = Field(ge=1)
    compound: str
    lap_time: timedelta | None = None
    available_channels: list[str] = Field(default_factory=list)
    # Scalar summary values for quick filtering without loading the full trace
    max_speed_kph: float | None = None
    min_speed_kph: float | None = None
    distance_m: float | None = None  # total lap distance covered


class CarDataPoint(BaseModel):
    """Single row from openf1 /car_data endpoint."""

    date: datetime
    driver_number: str
    meeting_key: int
    session_key: int
    speed: int = Field(ge=0)  # km/h
    rpm: int = Field(ge=0)
    n_gear: int = Field(ge=0, le=8)
    throttle: int = Field(ge=0, le=100)  # percentage
    brake: bool
    drs: int  # 0 = off, 8/10/12/14 = various on states


class PositionPoint(BaseModel):
    """Single row from openf1 /position endpoint — on-track position."""

    date: datetime
    driver_number: str
    meeting_key: int
    session_key: int
    position: int = Field(ge=1, le=20)


class WeatherRecord(BaseModel):
    """Weather reading — compatible with both fastf1 and openf1 weather data."""

    # Time reference: either a timedelta from session start (fastf1) or a datetime (openf1)
    session_time: timedelta | None = None
    timestamp: datetime | None = None

    air_temp_c: float
    track_temp_c: float
    humidity_pct: float = Field(ge=0.0, le=100.0)
    pressure_mbar: float | None = None
    wind_direction_deg: int | None = None
    wind_speed_ms: float | None = None
    rainfall: bool = False

    @property
    def is_wet(self) -> bool:
        return self.rainfall

    @property
    def track_temp_delta(self) -> float | None:
        """Track temp minus air temp — proxy for rubber laid down."""
        if self.air_temp_c is not None:
            return self.track_temp_c - self.air_temp_c
        return None


class RaceControlMessage(BaseModel):
    """A race control message (SC, VSC, flag, DRS, etc.)."""

    session_time: timedelta | None = None
    timestamp: datetime | None = None
    lap_number: int | None = None
    category: str  # "Flag", "SafetyCar", "DRS", "Other"
    message: str
    flag: str | None = None  # "GREEN", "YELLOW", "RED", "CHEQUERED", etc.
    scope: str | None = None  # "Track", "Sector", "Driver"
    sector: int | None = None
    driver_number: str | None = None
