import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[2]
DEV_JWT_SECRET = "dev-only-insecure-jwt-secret-change-me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT_DIR / ".env", extra="ignore")

    app_name: str = "AI Interview Coach"
    environment: str = "dev"

    database_url: str = "postgresql+asyncpg://coach:coach@localhost:5432/coach"
    redis_url: str = "redis://localhost:6379/0"

    # Must be overridden in any shared/deployed environment
    jwt_secret: str = DEV_JWT_SECRET
    jwt_lifetime_s: int = 60 * 60 * 24

    models_config_path: Path = ROOT_DIR / "config" / "models.yaml"
    # MODEL_PROFILE=free -> config/models.free.yaml (Groq free tier); unset -> models_config_path
    model_profile: str | None = None
    rubric_config_path: Path = ROOT_DIR / "config" / "rubric.yaml"

    upload_dir: Path = ROOT_DIR / "data" / "uploads"
    max_upload_mb: int = 5

    # LiteLLM reads provider keys from os.environ; get_settings() exports these there.
    anthropic_api_key: str | None = None
    groq_api_key: str | None = None
    openai_api_key: str | None = None

    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    langfuse_host: str = "https://cloud.langfuse.com"


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    if s.environment != "dev" and s.jwt_secret == DEV_JWT_SECRET:
        raise RuntimeError("JWT_SECRET must be set outside the dev environment")
    # pydantic-settings reads .env into this object but not into os.environ, where LiteLLM looks. Without
    # this, keys only worked when LiteLLM's own .env search happened to find the file.
    for name in ("anthropic_api_key", "groq_api_key", "openai_api_key"):
        if value := getattr(s, name):
            os.environ.setdefault(name.upper(), value)
    return s


@lru_cache
def load_models(path: Path | None = None) -> dict[str, dict[str, Any]]:
    s = get_settings()
    path = path or (ROOT_DIR / "config" / f"models.{s.model_profile}.yaml" if s.model_profile else s.models_config_path)
    with open(path, encoding="utf-8") as f:
        config = yaml.safe_load(f)
    return {k: v for k, v in config.items() if not k.startswith("_")}  # "_name" keys are YAML anchors


@lru_cache
def load_rubric(path: Path | None = None) -> dict[str, dict[str, dict[str, Any]]]:
    path = path or get_settings().rubric_config_path
    with open(path, encoding="utf-8") as f:
        rubric = yaml.safe_load(f)
    for kind, dims in rubric.items():
        total = sum(d["weight"] for d in dims.values())
        if abs(total - 1.0) > 1e-6:
            raise ValueError(f"rubric.yaml: weights for {kind!r} sum to {total}, expected 1.0")
    return rubric
