from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="RYAN_",
        env_file=".env",
        extra="ignore",
    )

    service_name: str = "ryan"
    environment: Literal["sandbox", "test", "production"] = "sandbox"
    database_url: str = Field(default="sqlite:///./ryan.sqlite3")


@lru_cache
def get_settings() -> Settings:
    return Settings()


__all__ = ["Settings", "get_settings"]
