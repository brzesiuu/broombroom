"""Models for analysis layer outputs.

These are the typed results returned by functions in broombroom/analysis/.
They are consumed by the viz/ and prediction/ layers.
"""

from datetime import timedelta

from pydantic import BaseModel, Field

from broombroom.data.models.stint import Compound


class DriverFormSummary(BaseModel):
    """Rolling form metrics for a driver over the last N races."""

    driver_id: str
    driver_code: str
    constructor_id: str
    last_n_races: int
    avg_points: float
    avg_finish_position: float
    podium_rate: float = Field(ge=0.0, le=1.0)
    dnf_rate: float = Field(ge=0.0, le=1.0)
    points_trend: list[float] = Field(default_factory=list)  # per-race points (sparkline)
    positions_trend: list[int | None] = Field(default_factory=list)  # finish pos per race


class TeamFormSummary(BaseModel):
    """Rolling form metrics for a constructor over the last N races."""

    constructor_id: str
    constructor_name: str
    last_n_races: int
    avg_points: float
    avg_finish_position: float
    podium_rate: float = Field(ge=0.0, le=1.0)
    points_trend: list[float] = Field(default_factory=list)


class SectorBreakdown(BaseModel):
    """Sector time analysis for a set of drivers relative to theoretical best."""

    circuit_key: str
    session_type: str
    drivers: list[str]  # driver codes included
    # Per-driver sector deltas vs theoretical best (positive = slower)
    s1_delta: dict[str, float] = Field(default_factory=dict)
    s2_delta: dict[str, float] = Field(default_factory=dict)
    s3_delta: dict[str, float] = Field(default_factory=dict)
    theoretical_best: timedelta | None = None


class HeadToHeadResult(BaseModel):
    """Head-to-head comparison between exactly two drivers."""

    driver_a: str
    driver_b: str
    session_type: str  # "Q", "R", etc.

    # Qualifying comparison
    quali_wins_a: int = 0  # rounds where A was faster in quali
    quali_wins_b: int = 0
    quali_gap_seconds: list[float] = Field(default_factory=list)  # A - B per round, negative = A faster

    # Race pace comparison
    race_pace_wins_a: int = 0
    race_pace_wins_b: int = 0
    race_pace_gap_seconds: list[float] = Field(default_factory=list)

    @property
    def total_sessions(self) -> int:
        return self.quali_wins_a + self.quali_wins_b


class DegradationResult(BaseModel):
    """Polynomial tyre degradation fit for a driver on a compound."""

    driver_code: str
    compound: Compound
    circuit_key: str
    sample_count: int  # number of clean laps used for fitting
    polynomial_degree: int = 2
    coefficients: list[float]  # highest degree first (numpy convention)
    r_squared: float = Field(ge=0.0, le=1.0)
    predicted_delta_at_lap: dict[int, float] = Field(default_factory=dict)  # lap_in_stint -> delta_seconds


class DriverRadarMetrics(BaseModel):
    """6-axis radar chart metrics for a driver, all normalised 0–1 vs field.

    1.0 = best in field for that metric. Computed by analysis/driver.py.
    """

    driver_code: str
    sessions_used: int

    max_speed_score: float = Field(ge=0.0, le=1.0)
    braking_consistency: float = Field(ge=0.0, le=1.0)  # 1 - CV of braking distances
    corner_entry_score: float = Field(ge=0.0, le=1.0)  # min speed in corners vs best
    corner_exit_score: float = Field(ge=0.0, le=1.0)  # speed at exit vs best
    sector_1_score: float = Field(ge=0.0, le=1.0)
    sector_2_score: float = Field(ge=0.0, le=1.0)
    sector_3_score: float = Field(ge=0.0, le=1.0)


class WeatherCorrelation(BaseModel):
    """Correlation between weather conditions and lap time at a circuit."""

    circuit_key: str
    sample_count: int
    track_temp_correlation: float  # Pearson r: track_temp vs lap_time_delta
    humidity_correlation: float
    estimated_wet_delta_seconds: float  # estimated lap time loss in wet vs dry
    confidence: float = Field(ge=0.0, le=1.0)  # based on sample count


class UndercutWindow(BaseModel):
    """Analysis of whether an undercut opportunity existed in a race."""

    attacker_driver: str
    defender_driver: str
    circuit_key: str
    window_start_lap: int | None  # first lap where undercut was viable
    window_end_lap: int | None
    estimated_gain_seconds: float | None  # expected net gain if executed
    was_executed: bool = False
    execution_lap: int | None = None


class MiniSectorComparison(BaseModel):
    """25-sector mini-sector time comparison between two drivers."""

    driver_a: str
    driver_b: str
    lap_number_a: int
    lap_number_b: int
    # delta per mini-sector: positive means driver A was faster
    sector_deltas: list[float]  # length 25
    sector_distances: list[float]  # distance at start of each mini-sector


class CornerSpeedProfile(BaseModel):
    """Min/max speed per corner for one driver on a circuit."""

    driver_code: str
    circuit_key: str
    # Keyed by corner label (e.g. "T1", "T2A")
    min_speed_kph: dict[str, float] = Field(default_factory=dict)
    max_speed_kph: dict[str, float] = Field(default_factory=dict)
    braking_point_m: dict[str, float] = Field(default_factory=dict)  # distance from corner


class CircuitHistoryStats(BaseModel):
    """Historical statistics for a circuit across past seasons."""

    circuit_key: str
    seasons_covered: list[int]
    avg_safety_car_probability: float = Field(ge=0.0, le=1.0)
    avg_dnf_rate: float = Field(ge=0.0, le=1.0)
    avg_lap_count: float
    historical_pole_times: dict[int, float] = Field(default_factory=dict)  # season -> seconds
