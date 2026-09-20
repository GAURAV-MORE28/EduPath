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
    # "none" | "groq" | "huggingface" | "anthropic". groq/huggingface speak the OpenAI chat-completions dialect.
    llm_base_url: str = ""  # empty = the provider's own default
    llm_json_mode: bool = True  # ask OpenAI-compatible providers for `response_format: json_object`
    llm_reasoning_effort: str = "low"  # sent only to openai/gpt-oss-* models (low | medium | high)
    llm_timeout_s: float = 8.0  # design §38.3: live call first (8 s), then the recorded response
    llm_record: bool = False  # record successful live responses into the replay table (implied by demo_mode)
    # Optional pricing so AgentRun/AgentStep can report cost where a provider returns token usage.
    llm_cost_per_1k_input_usd: float = 0.0
    llm_cost_per_1k_output_usd: float = 0.0

    # Embeddings (design §14.3 dense retrieval, §22 skill normalization). "none" = deterministic hashed
    # embedding; "huggingface" = Qwen3-Embedding through the HF router (truncated to EMBEDDING_DIM, Matryoshka).
    # Catalog embeddings must be produced by the SAME provider as query embeddings -- after changing this,
    # run `python scripts/reembed_catalog.py`.
    embedding_provider: str = "none"
    embedding_model: str = "Qwen/Qwen3-Embedding-0.6B"
    embedding_base_url: str = "https://router.huggingface.co/deepinfra/v1/openai"
    hf_token: str = ""

    # Vision fallback for scanned PDFs / images (design §22.1). "none" | "huggingface".
    vlm_provider: str = "none"
    vlm_model: str = "deepseek-ai/DeepSeek-V4.1-Flash:novita"
    vlm_base_url: str = "https://router.huggingface.co/v1"

    # Web-search fallback (design §14.3 point 6, O4). "none" | "tavily". Results are always `unvetted`.
    web_search_provider: str = "none"
    tavily_api_key: str = ""
    web_search_allowed_domains: str = ""  # comma-separated; empty = a built-in learning-site allowlist

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
