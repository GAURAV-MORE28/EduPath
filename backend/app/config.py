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

    # Session / auth boundary (placeholder until Phase 2 auth is designed)
    session_secret: str = "dev-only-insecure-secret-change-me"

    # GitHub tool (design §26.2 github_repo_summary) — optional; unauthenticated
    # requests work but are more tightly rate-limited by GitHub's API.
    github_token: str = ""

    # Document storage (design §35: local volume in dev; S3-compatible in prod)
    document_storage_dir: str = "./storage/documents"

    # CORS
    frontend_origin: str = "http://localhost:3000"

    # Logging
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
