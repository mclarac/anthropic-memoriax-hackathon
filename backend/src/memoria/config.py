"""Runtime settings, read from MEMORIA_* environment variables and an optional .env file."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated, Literal

from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from memoria.chain_prompts import MODEL


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MEMORIA_", env_file=".env", extra="ignore", populate_by_name=True,
    )

    mode: Literal["live", "fake"] = "live"
    data_dir: Path = Path("./data")
    tts_url: str = "http://tts:8880"
    model: str = MODEL
    # The key keeps its standard name so the Anthropic SDK and this app read the same variable.
    anthropic_api_key: SecretStr | None = Field(
        default=None, validation_alias=AliasChoices("ANTHROPIC_API_KEY", "anthropic_api_key"),
    )
    # NoDecode: let the validator accept a comma-separated list as well as JSON.
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:3000"]

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if not isinstance(value, str):
            return value
        text = value.strip()
        if text.startswith("["):
            return json.loads(text)
        return [part.strip() for part in text.split(",") if part.strip()]
