from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "AirOps Decision Support API"
    environment: str = "development"          # anything else => secrets are validated at startup
    api_prefix: str = "/api"

    database_url: str = "postgresql+psycopg://airops:airops@localhost:5432/airops"
    jwt_secret: str = "CHANGE-ME-USE-A-32-CHAR-LOCAL-SECRET-ONLY"
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 60

    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # Hard ceiling for any solver job. The per-job timeout is derived from the job's own
    # time_limit (see JobManager.timeout_for) and never exceeds this.
    job_max_seconds: int = 900
    job_overhead_seconds: int = 60
    job_poll_interval_ms: int = 250

    sample_data_dir: str = "sample_data"
    benchmark_dir: str = "evaluation/results"
    serve_fixtures: bool = True               # set false outside development

    seed_admin_username: str | None = None
    seed_admin_password: str | None = None

    # Optional real weather adapter. Disabled by default.
    weather_provider: str = "simulated"
    open_meteo_lat: float | None = None
    open_meteo_lon: float | None = None

    model_config = SettingsConfigDict(env_file=".env", env_prefix="AIROPS_", extra="ignore")

    def assert_safe(self) -> None:
        """Refuse to start outside development with a placeholder or short JWT secret."""
        if self.environment.lower() == "development":
            return
        if len(self.jwt_secret) < 32 or self.jwt_secret.upper().startswith("CHANGE-ME"):
            raise RuntimeError("AIROPS_JWT_SECRET must be a random secret of >= 32 chars when "
                               "AIROPS_ENVIRONMENT is not 'development'")


settings = Settings()
