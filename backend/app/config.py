"""Environment-driven configuration.

Single source of truth for settings (design doc §35 Deployment Architecture).
Tunable thresholds referenced by later phases (mastery cut-offs, load caps,
ranking weights) belong here too, kept in one place per ARCHITECTURE_CONTRACTS.md §14.
"""
from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    env: Literal["dev", "test", "prod"] = "dev"
    api_v1_prefix: str = "/api"

    # Database
    database_url: str = Field(
        default="postgresql+asyncpg://edupath:edupath@localhost:5432/edupath",
    )

    # Feature flags (design §35)
    replay_mode: bool = False
    demo_mode: bool = False

    # LLM Gateway (provider-agnostic tiers; design §7, §33.2)
    llm_provider: str = "none"
    llm_api_key: str = ""
    llm_small_model: str = ""
    llm_mid_model: str = ""
    llm_strong_model: str = ""
    llm_base_url: str = "https://api.anthropic.com"
    llm_timeout_s: float = 8.0  # design §38.3: live call first (8 s), then the recorded response
    llm_record: bool = False  # record successful live responses into the replay table (implied by demo_mode)
    # Optional pricing so AgentRun/AgentStep can report cost where a provider returns token usage.
    llm_cost_per_1k_input_usd: float = 0.0
    llm_cost_per_1k_output_usd: float = 0.0

    # Session / auth boundary (placeholder until Phase 2 auth is designed)
    session_secret: str = "dev-only-insecure-secret-change-me"

    # GitHub tool (design §26.2 github_repo_summary) — optional; unauthenticated
    # requests work but are more tightly rate-limited by GitHub's API.
    github_token: str = ""

    # Document storage (design §35: local volume in dev; S3-compatible in prod)
    document_storage_dir: str = "./storage/documents"

    # Curated domain pack (data/dataset). Empty -> the repo-relative default; Docker mounts ./data at /data.
    dataset_dir: str = ""
    # Seed the catalog on API startup when the catalog is empty (Compose relies on this).
    auto_seed_catalog: bool = True

    # CORS
    frontend_origin: str = "http://localhost:3000"

    # Logging
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
