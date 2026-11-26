"""Application configuration loaded from environment variables."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Interop connection
    interop_url: str = Field(default="", alias="INTEROP_URL")
    interop_user: str = Field(default="", alias="INTEROP_USER")
    interop_password: str = Field(default="", alias="INTEROP_PASSWORD")
    workflow_mock_mode: bool = Field(default=False, alias="WORKFLOW_MOCK_MODE")

    # From-scratch workflow model
    local_ai_train_epochs: int = Field(default=30, alias="LOCAL_AI_TRAIN_EPOCHS", ge=1, le=500)

    # Packs directory
    workflow_packs_dir: str = Field(default="", alias="WORKFLOW_PACKS_DIR")

    # App
    app_name: str = "Workflow Studio API"
    app_version: str = "3.2.0"
    cors_origins: list[str] = [
        "http://127.0.0.1:4200",
        "http://localhost:4200",
    ]

    @property
    def backend_root(self) -> Path:
        return Path(__file__).resolve().parents[2]

    @property
    def app_root(self) -> Path:
        return Path(__file__).resolve().parents[1]

    @property
    def definitions_dir(self) -> Path:
        return self.app_root / "definitions"

    @property
    def packs_dir(self) -> Path:
        if self.workflow_packs_dir:
            return Path(self.workflow_packs_dir)
        return self.backend_root / "packs"


@lru_cache
def get_settings() -> Settings:
    return Settings()
