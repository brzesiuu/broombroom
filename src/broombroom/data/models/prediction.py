"""Prediction layer output models."""

from datetime import UTC, datetime

from pydantic import BaseModel, Field, model_validator


class WeatherForecast(BaseModel):
    """Weather forecast for an upcoming race weekend session."""

    circuit_key: str
    session_date: datetime
    forecast_track_temp_c: float
    historical_avg_track_temp_c: float | None = None
    rain_probability: float = Field(ge=0.0, le=1.0)
    wind_speed_ms: float | None = None
    condition_label: str = "dry"  # "dry", "damp", "wet"

    @property
    def temp_delta_vs_historical(self) -> float | None:
        if self.historical_avg_track_temp_c is not None:
            return self.forecast_track_temp_c - self.historical_avg_track_temp_c
        return None


class DriverProbability(BaseModel):
    """Per-driver prediction output for a single race."""

    driver_id: str
    driver_code: str
    constructor_id: str

    # Win / podium / points probabilities
    win_probability: float = Field(ge=0.0, le=1.0)
    podium_probability: float = Field(ge=0.0, le=1.0)
    points_probability: float = Field(ge=0.0, le=1.0)  # P(top 10)

    # Expected finishing position (weighted average of position distribution)
    expected_position: float = Field(ge=1.0, le=20.0)

    # Confidence interval on expected position
    position_ci_lower: float = Field(ge=1.0, le=20.0)
    position_ci_upper: float = Field(ge=1.0, le=20.0)

    # Recommended strategy (optional — available when tire model is run)
    recommended_strategy: str | None = None  # e.g. "1-stop: M → H"

    @model_validator(mode="after")
    def _ci_ordering(self) -> "DriverProbability":
        if self.position_ci_lower > self.position_ci_upper:
            raise ValueError("position_ci_lower must be <= position_ci_upper")
        return self


class RacePrediction(BaseModel):
    """Full prediction output for an upcoming race.

    All probability fields include mandatory caveats — the UI must display them.
    """

    season: int
    round_number: int
    circuit_key: str
    model_name: str
    model_version: str
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    weather_note: str | None = None  # e.g. "Rain forecast, model trained on dry data"

    driver_predictions: list[DriverProbability]

    # MANDATORY: these must be shown in the UI alongside any probability output.
    caveats: list[str] = Field(
        default_factory=lambda: [
            "Predictions are statistical estimates based on historical data, not guarantees.",
            "Model accuracy degrades significantly for new circuits, mid-season rule changes, "
            "and driver/team transfers.",
            "Always consult confidence intervals — wide intervals indicate high uncertainty.",
        ]
    )

    @property
    def predicted_winner(self) -> DriverProbability | None:
        if not self.driver_predictions:
            return None
        return max(self.driver_predictions, key=lambda d: d.win_probability)

    @property
    def predicted_podium(self) -> list[DriverProbability]:
        return sorted(self.driver_predictions, key=lambda d: d.podium_probability, reverse=True)[:3]


class ModelInfo(BaseModel):
    """Registry entry for a trained model artifact."""

    name: str
    version: str
    model_type: str  # "lightgbm", "lstm", "transformer", "mlp", "user"
    trained_at: datetime | None = None
    training_seasons: list[int] = Field(default_factory=list)
    artifact_path: str  # relative to BB_MODEL_DIR
    # Backtest metrics (None if model has not been backtested yet)
    brier_score: float | None = None
    log_loss: float | None = None
    top1_accuracy: float | None = None
    podium_accuracy: float | None = None
    spearman_rho: float | None = None
    n_races_evaluated: int | None = None


class RaceMetrics(BaseModel):
    """Per-race prediction quality metrics from a backtest run."""

    season: int
    round_number: int
    circuit_key: str
    brier_score: float
    log_loss: float
    top1_correct: bool
    podium_overlap: int = Field(ge=0, le=3)  # 0-3 correct podium predictions
    spearman_rho: float  # rank correlation predicted vs actual


class AggregateMetrics(BaseModel):
    """Aggregate backtest metrics across all evaluated races."""

    n_races: int
    avg_brier_score: float
    avg_log_loss: float
    top1_accuracy: float = Field(ge=0.0, le=1.0)
    avg_podium_overlap: float = Field(ge=0.0, le=3.0)
    avg_spearman_rho: float
    expected_calibration_error: float = Field(ge=0.0)


class BacktestReport(BaseModel):
    """Full backtesting report for a model evaluated on historical seasons."""

    predictor_name: str
    predictor_version: str
    seasons_evaluated: list[int]
    retrain_each_round: bool
    n_races: int
    per_race: list[RaceMetrics]
    aggregate: AggregateMetrics
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    # Calibration data: list of (predicted_prob_bin, empirical_freq) tuples
    calibration_bins: list[float] = Field(default_factory=list)
    calibration_freqs: list[float] = Field(default_factory=list)
