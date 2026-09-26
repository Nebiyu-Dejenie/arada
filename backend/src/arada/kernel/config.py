"""Centralised, typed configuration (Permanent Command §28).

Every tunable lives here and nowhere else. Secrets are ``SecretStr`` so they
never appear in ``repr()``, logs or error messages. Hostnames are never
literals in code: ``root_domain`` is configuration and is currently TBD
(ADR-026).
"""

from __future__ import annotations

import base64
import binascii
from enum import StrEnum
from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    DEVELOPMENT = "development"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ARADA_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: Environment = Environment.DEVELOPMENT

    # ROOT_DOMAIN is TBD (ADR-026). Nothing in Phase 1 depends on it.
    root_domain: str | None = None

    # Database: one DSN per role (06_DATABASE_MODEL.md §2). The owner DSN is
    # used only by migrations; the application never holds it at runtime.
    database_url: SecretStr
    database_platform_reader_url: SecretStr
    database_owner_url: SecretStr | None = None
    db_pool_size: int = Field(default=5, ge=1, le=100)
    db_max_overflow: int = Field(default=5, ge=0, le=100)
    db_statement_timeout_ms: int = Field(default=15_000, ge=100)

    # Key-encryption key for envelope encryption (ADR-017), base64 of 32 bytes.
    kek_base64: SecretStr
    kek_version: int = Field(default=1, ge=1)

    # Logging / API surface
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_format: Literal["json", "console"] = "json"
    expose_api_docs: bool = True
    max_request_body_bytes: int = Field(default=1_048_576, ge=1024)

    # Authentication (09_SECURITY.md §3)
    session_idle_timeout_minutes: int = Field(default=30, ge=1)
    session_absolute_timeout_hours: int = Field(default=12, ge=1)
    login_max_failures: int = Field(default=10, ge=3)
    login_lockout_minutes: int = Field(default=15, ge=1)
    require_mfa_for_privileged_scopes: bool = True
    totp_issuer: str = "ARADA"

    # Tenancy
    invitation_ttl_hours: int = Field(default=72, ge=1, le=24 * 30)

    @field_validator("root_domain")
    @classmethod
    def _normalise_root_domain(cls, value: str | None) -> str | None:
        if value is None or value.strip() == "":
            return None
        return value.strip().lower().rstrip(".")

    @field_validator("kek_base64")
    @classmethod
    def _validate_kek(cls, value: SecretStr) -> SecretStr:
        try:
            raw = base64.b64decode(value.get_secret_value(), validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValueError("kek_base64 must be valid base64") from exc
        if len(raw) != 32:
            raise ValueError("kek_base64 must decode to exactly 32 bytes")
        return value

    @model_validator(mode="after")
    def _production_guards(self) -> Settings:
        if self.environment is Environment.PRODUCTION:
            problems: list[str] = []
            if not self.require_mfa_for_privileged_scopes:
                problems.append("require_mfa_for_privileged_scopes must be true")
            if self.log_format != "json":
                problems.append("log_format must be json")
            if self.expose_api_docs:
                problems.append("expose_api_docs must be false")
            if self.root_domain is None:
                problems.append("root_domain must be set (it is TBD until the domain phase)")
            if problems:
                raise ValueError("unsafe production configuration: " + "; ".join(problems))
        return self

    @property
    def kek(self) -> bytes:
        return base64.b64decode(self.kek_base64.get_secret_value())


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # values come from the environment
