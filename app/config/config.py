"""Application configuration loaded from .env via pydantic-settings."""
import os
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, field_validator


class Settings(BaseSettings):
    # Naukri credentials
    NAUKRI_EMAIL: str = Field(default="", description="Naukri account email")
    NAUKRI_PASSWORD: str = Field(default="", description="Naukri account password")

    # LLM
    GROQ_API_KEY: str = Field(default="", description="Groq API key")
    GROQ_MODEL: str = Field(
        default="openai/gpt-oss-120b",
        description="Groq model name",
    )
    LLM_TEMPERATURE: float = Field(default=0.3, ge=0.0, le=2.0)

    # Runtime behaviour
    DRY_RUN: bool = Field(
        default=False,
        description="If true, never submit applications; only log what would happen.",
    )
    DAILY_APPLY_LIMIT: int = Field(
        default=49,
        ge=1,
        description="Maximum number of applications per day.",
    )
    MAX_BATCH_SIZE: int = Field(default=5, ge=1, description="Jobs per batch")
    MAX_EXPERIENCE_YEARS: int = Field(default=10, description="Skip jobs requiring more years of experience")
    HEADLESS: bool = Field(default=False, description="Run browser without GUI")
    SLOW_MO_MS: int = Field(default=60, ge=0, description="Playwright slow motion delay in ms")
    VIEWPORT_WIDTH: int = Field(default=1280)
    VIEWPORT_HEIGHT: int = Field(default=720)

    # Session persistence
    STORAGE_STATE_PATH: str = Field(
        default="storage_state.json",
        description="Path to Playwright storage state file for session reuse.",
    )

    # Job scoring / filtering
    PREFERRED_LOCATIONS: str = Field(
        default="",
        description="Comma-separated list of preferred locations (first match wins).",
    )
    PREFERRED_ROLES: str = Field(
        default="",
        description="Comma-separated list of preferred role keywords.",
    )
    SALARY_MIN_LPA: float = Field(
        default=0.0,
        ge=0.0,
        description="Minimum salary in LPA to consider a job.",
    )
    JOB_SCORE_THRESHOLD: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="Minimum composite score (0-100) for a job to be selected.",
    )

    # Cache
    DB_PATH: str = Field(default="data/db.json", description="Path to local Q&A JSON cache")
    LLM_CACHE_DB_PATH: str = Field(
        default="naukri_autoai_memory.db",
        description="Path to SQLite LLM cache database",
    )
    SEMANTIC_CACHE_THRESHOLD: float = Field(
        default=0.85,
        ge=0.0,
        le=1.0,
        description="Cosine similarity threshold for semantic cache hits.",
    )

    # Diagnostics
    DIAGNOSTICS_DIR: str = Field(
        default="data/diagnostics",
        description="Directory for per-run logs and screenshots.",
    )
    SCREENSHOT_ON_ERROR: bool = Field(
        default=True,
        description="Take a page screenshot when an error is logged.",
    )

    # Notifications
    SMTP_HOST: str = Field(default="", description="SMTP server host")
    SMTP_PORT: int = Field(default=587, ge=1)
    SMTP_USERNAME: str = Field(default="")
    SMTP_PASSWORD: str = Field(default="")
    SMTP_FROM: str = Field(default="")
    SMTP_TO: str = Field(default="")

    # Approval gate
    REQUIRE_APPROVAL: bool = Field(
        default=False,
        description="If true, pause before applying and wait for user 'y' confirmation.",
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    @field_validator("NAUKRI_EMAIL")
    @classmethod
    def _require_email(cls, v: str) -> str:
        if not v:
            raise ValueError("NAUKRI_EMAIL is required in .env")
        return v

    @field_validator("NAUKRI_PASSWORD")
    @classmethod
    def _require_password(cls, v: str) -> str:
        if not v:
            raise ValueError("NAUKRI_PASSWORD is required in .env")
        return v

    @field_validator("GROQ_API_KEY")
    @classmethod
    def _require_groq_key(cls, v: str) -> str:
        if not v:
            raise ValueError("GROQ_API_KEY is required in .env")
        return v

    @field_validator("PREFERRED_LOCATIONS")
    @classmethod
    def _split_locations(cls, v: str) -> str:
        return v  # stored as-is; consumers split on comma

    @field_validator("PREFERRED_ROLES")
    @classmethod
    def _split_roles(cls, v: str) -> str:
        return v


settings = Settings()

# Backwards-compatible module-level constants used by existing code
EMAIL = settings.NAUKRI_EMAIL
PASSWORD = settings.NAUKRI_PASSWORD
GROQ_API_KEY = settings.GROQ_API_KEY
MAX_EXPERIENCE_YEARS = settings.MAX_EXPERIENCE_YEARS
DAILY_APPLY_LIMIT = settings.DAILY_APPLY_LIMIT
MAX_BATCH_SIZE = settings.MAX_BATCH_SIZE
HEADLESS = settings.HEADLESS
SLOW_MO_MS = settings.SLOW_MO_MS
VIEWPORT_WIDTH = settings.VIEWPORT_WIDTH
VIEWPORT_HEIGHT = settings.VIEWPORT_HEIGHT
STORAGE_STATE_PATH = settings.STORAGE_STATE_PATH
DIAGNOSTICS_DIR = settings.DIAGNOSTICS_DIR
SCREENSHOT_ON_ERROR = settings.SCREENSHOT_ON_ERROR
PREFERRED_ROLES = [
    role.strip().lower()
    for role in settings.PREFERRED_ROLES.split(",")
    if role.strip()
]
PREFERRED_LOCATIONS = [
    loc.strip()
    for loc in settings.PREFERRED_LOCATIONS.split(",")
    if loc.strip()
]
