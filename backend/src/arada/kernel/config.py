"""Centralised, typed configuration (Permanent Command §28).

Every tunable lives here and nowhere else. Secrets are ``SecretStr`` so they
never appear in ``repr()``, logs or error messages. Hostnames are never
literals in code: ``root_domain`` is configuration and is currently TBD
(ADR-026).
"""

from __future__ import annotations

import base64
import binascii
import hashlib
from enum import StrEnum
from functools import lru_cache
from typing import Literal

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

TelegramEnvironment = Literal["production", "test"]

# SHA-256 fingerprints of the two Ed25519 public keys Telegram publishes for
# Mini App ``initData`` signatures (core.telegram.org/bots/webapps
# #validating-data-for-third-party-use, verified 2026-10-01; ADR-012). The key
# used for verification always comes from configuration. These fingerprints
# exist only so that a deployment can never pair the wrong key with its
# environment, and so that production refuses anything but the production key.
TELEGRAM_KEY_FINGERPRINTS: dict[str, TelegramEnvironment] = {
    "bb05ef4a95bd4f628f66eb95606254daa0281a7ff269dd326c8ce7d4c670c0a1": "production",
    "8f7cb56f29bb50b78bcde54350e3425ca5e40eadf5eb62fcd41f071f990e23bc": "test",
}


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
    # Tenant roles holding money, staff or security permissions (ADR-035).
    require_mfa_for_privileged_tenant_roles: bool = True
    totp_issuer: str = "ARADA"

    # Tenancy
    invitation_ttl_hours: int = Field(default=72, ge=1, le=24 * 30)

    # Telegram Mini App authentication (ADR-012, PHASE_2_PLAN.md §5, §9).
    # Telegram's test and production environments are completely separate;
    # one deployment talks to exactly one, with that environment's public key.
    # Without a key, every Telegram login fails closed.
    telegram_environment: TelegramEnvironment = "test"
    telegram_public_key_hex: str | None = None
    # Freshness and replay are our policy: Telegram defines neither.
    telegram_init_data_max_age_seconds: int = Field(default=3600, ge=60, le=86_400)
    telegram_init_data_future_skew_seconds: int = Field(default=60, ge=0, le=300)
    telegram_init_data_reuse_window_seconds: int = Field(default=600, ge=0, le=3600)
    telegram_init_data_max_uses: int = Field(default=20, ge=1, le=1000)

    # Customer sessions (ADR-036): opaque, server-side, bound to one tenant.
    customer_session_idle_timeout_minutes: int = Field(default=30, ge=1)
    customer_session_absolute_timeout_hours: int = Field(default=12, ge=1)

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

    @field_validator("telegram_public_key_hex")
    @classmethod
    def _validate_telegram_key(cls, value: str | None) -> str | None:
        if value is None or value.strip() == "":
            return None
        key = value.strip().lower()
        if len(key) != 64 or any(c not in "0123456789abcdef" for c in key):
            raise ValueError("telegram_public_key_hex must be 64 hex characters (32 bytes)")
        try:
            Ed25519PublicKey.from_public_bytes(bytes.fromhex(key))
        except ValueError as exc:
            raise ValueError("telegram_public_key_hex is not a valid Ed25519 public key") from exc
        return key

    @model_validator(mode="after")
    def _telegram_key_matches_environment(self) -> Settings:
        """A known Telegram key must belong to the configured environment."""
        known = self.telegram_key_environment
        if known is not None and known != self.telegram_environment:
            raise ValueError(
                f"telegram_public_key_hex is Telegram's {known} key but "
                f"telegram_environment is {self.telegram_environment}"
            )
        return self

    @model_validator(mode="after")
    def _production_guards(self) -> Settings:
        if self.environment is Environment.PRODUCTION:
            problems: list[str] = []
            if self.telegram_environment != "production":
                problems.append("telegram_environment must be production")
            if self.telegram_key_environment != "production":
                problems.append("telegram_public_key_hex must be Telegram's production key")
            if not self.require_mfa_for_privileged_scopes:
                problems.append("require_mfa_for_privileged_scopes must be true")
            if not self.require_mfa_for_privileged_tenant_roles:
                problems.append("require_mfa_for_privileged_tenant_roles must be true")
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
    def telegram_key_environment(self) -> TelegramEnvironment | None:
        """Which Telegram environment the configured key belongs to, if known."""
        if self.telegram_public_key_hex is None:
            return None
        fingerprint = hashlib.sha256(bytes.fromhex(self.telegram_public_key_hex)).hexdigest()
        return TELEGRAM_KEY_FINGERPRINTS.get(fingerprint)

    @property
    def kek(self) -> bytes:
        return base64.b64decode(self.kek_base64.get_secret_value())


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()  # values come from the environment
