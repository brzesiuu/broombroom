"""Central application configuration via pydantic-settings.

All environment variables are prefixed with BB_. Copy .env.example to .env
to configure locally. Never hardcode values here — use the Settings instance.
"""

from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="BB_",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # ── Cache ──────────────────────────────────────────────────────────────────
    cache_dir: Path = Path("data/cache")
    fastf1_cache_dir: Path = Path("data/cache/fastf1")
    app_cache_dir: Path = Path("data/cache/app")

    # ── Logging ────────────────────────────────────────────────────────────────
    log_format: str = "pretty"  # "pretty" | "json"
    log_level: str = "INFO"

    # ── API behaviour ──────────────────────────────────────────────────────────
    jolpica_base_url: str = "https://api.jolpi.ca/ergast"
    openf1_base_url: str = "https://api.openf1.org/v1"
    openf1_rate_limit_per_second: int = 3
    jolpica_rate_limit_per_second: int = 1
    http_timeout_seconds: int = 30
    http_max_retries: int = 3

    # ── Feature flags ──────────────────────────────────────────────────────────
    enable_openf1: bool = True
    enable_realtime: bool = False

    # ── ML / Experiments ───────────────────────────────────────────────────────
    model_dir: Path = Path("data/models")
    mlflow_tracking_uri: str = "data/mlflow"
    prediction_min_year: int = 2018  # fastf1 coverage starts 2018

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, v: str) -> str:
        allowed = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = v.upper()
        if upper not in allowed:
            raise ValueError(f"log_level must be one of {allowed}, got {v!r}")
        return upper

    @field_validator("log_format")
    @classmethod
    def _validate_log_format(cls, v: str) -> str:
        allowed = {"pretty", "json"}
        lower = v.lower()
        if lower not in allowed:
            raise ValueError(f"log_format must be one of {allowed}, got {v!r}")
        return lower

    def ensure_dirs(self) -> None:
        """Create all required local directories if they do not exist."""
        for d in (
            self.fastf1_cache_dir,
            self.app_cache_dir,
            self.model_dir,
            Path(self.mlflow_tracking_uri),
        ):
            d.mkdir(parents=True, exist_ok=True)


# Module-level singleton — import this everywhere.
settings = Settings()
