"""Application configuration from environment variables."""
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    database_url: str = "postgresql+asyncpg://gridwatch:gridwatch@postgres:5432/gridwatch"
    database_url_sync: str = "postgresql://gridwatch:gridwatch@postgres:5432/gridwatch"

    # AI
    gemini_api_key: str = ""
    local_llm_url: str = "http://host.docker.internal:11434/api/generate"
    local_llm_model: str = "phi3"

    # Debounce & detection tuning
    debounce_window_s: int = 30
    heartbeat_timeout_s: int = 1200  # 20 minutes
    heartbeat_interval_s: int = 900  # 15 minutes
    heartbeat_jitter_s: int = 45
    watchdog_interval_s: int = 60
    verification_interval_s: int = 30
    stale_event_threshold_s: int = 600  # 10 minutes

    # Topology inference
    candidate_radius_m: float = 150.0

    # Ticket lifecycle
    restoration_threshold: float = 0.95
    sustain_window_s: int = 60

    # Scheduled outage
    outage_grace_before_m: int = 15
    outage_overrun_m: int = 40

    # Ingest
    ingest_batch_size: int = 500
    ingest_batch_timeout_ms: int = 100

    # Simulator
    heartbeat_sim_enabled: bool = True

    model_config = {"env_file": ".env", "extra": "ignore"}


settings = Settings()
