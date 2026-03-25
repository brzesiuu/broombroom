"""Domain exception hierarchy for BroomBroom.

Raise specific subclasses so callers can catch exactly what they care about
without swallowing unrelated errors.
"""


class BroomBroomError(Exception):
    """Base class for all application errors."""


# ── Data layer ────────────────────────────────────────────────────────────────


class DataNotAvailableError(BroomBroomError):
    """Requested data does not exist for the given parameters.

    Examples: requesting openf1 data for a year < 2023, or a session that has
    not yet taken place.
    """


class APIError(BroomBroomError):
    """An external API returned an unexpected response or status code."""

    def __init__(self, source: str, status_code: int | None = None, message: str = "") -> None:
        self.source = source
        self.status_code = status_code
        super().__init__(f"[{source}] HTTP {status_code}: {message}" if status_code else f"[{source}] {message}")


class RateLimitError(APIError):
    """Rate limit exceeded for an external API."""


class CacheError(BroomBroomError):
    """Cache read/write failure (disk full, corrupt file, etc.)."""


# ── Analysis layer ────────────────────────────────────────────────────────────


class InsufficientDataError(BroomBroomError):
    """Not enough laps/sessions to perform the requested analysis.

    E.g., fewer than 3 clean laps available for degradation fitting.
    """


# ── Prediction layer ──────────────────────────────────────────────────────────


class ModelNotTrainedError(BroomBroomError):
    """A model artifact was requested but has not been trained yet."""

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        super().__init__(
            f"Model '{model_name}' has not been trained. "
            "Run `broombroom train` or select a trained model from the registry."
        )


class ModelLoadError(BroomBroomError):
    """Failed to deserialise a model artifact from disk."""


class FeatureError(BroomBroomError):
    """Feature engineering failed — missing columns, NaN in required fields, etc."""


class BacktestError(BroomBroomError):
    """Backtesting run failed or produced invalid results."""


# ── User model errors ─────────────────────────────────────────────────────────


class UserModelError(BroomBroomError):
    """A user-supplied custom model raised an error or violated the Predictor protocol."""
