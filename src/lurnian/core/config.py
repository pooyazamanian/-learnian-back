"""Application configuration using Pydantic Settings."""

from functools import lru_cache
from typing import Final, Literal

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

#: Values that are only acceptable on a developer machine.
DEFAULT_JWT_SECRET: Final = "dev-only-change-me"
DEFAULT_OTP_PEPPER: Final = "dev-only-otp-pepper"
MIN_SECRET_LENGTH: Final = 32


class Settings(BaseSettings):
    """Strongly typed application configuration loaded from environment variables."""

    # Application settings
    app_name: str = "Lurnian Backend"
    app_version: str = "0.1.0"
    environment: Literal["development", "staging", "production"] = "development"
    debug: bool = True
    api_v1_prefix: str = "/api/v1"

    # Server settings
    host: str = "127.0.0.1"
    port: int = 8000

    # Logging settings
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    # Authentication settings
    jwt_secret: SecretStr = SecretStr("dev-only-change-me")
    jwt_issuer: str = "lurnian"
    # Access tokens are short-lived because they cannot be revoked; the refresh
    # token is the long-lived half and rotates on every use. A session can never
    # outlive its refresh token, so the absolute cap is at least the refresh TTL.
    access_token_ttl_minutes: int = 30
    refresh_token_ttl_days: int = 365
    session_absolute_ttl_days: int = 365

    # Phone sign-in: one-time codes delivered by SMS.
    default_phone_country_code: str = "98"
    otp_length: int = 6
    otp_ttl_seconds: int = 120
    otp_max_attempts: int = 5
    otp_resend_cooldown_seconds: int = 60
    # Hourly ceilings stop a single number (or one address) from turning the
    # endpoint into an SMS bomb and a cost amplifier.
    otp_max_per_number_per_hour: int = 5
    otp_max_per_ip_per_hour: int = 20
    otp_pepper: SecretStr = SecretStr(DEFAULT_OTP_PEPPER)
    # Development convenience only: echo the generated code in the response so
    # the flow can be exercised without an SMS provider. Never enable live.
    otp_expose_in_response: bool = False

    # Database settings
    database_url: SecretStr = SecretStr(
        "postgresql+psycopg://lurnian:lurnian@127.0.0.1:5432/lurnian"
    )
    db_echo: bool = False
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_pool_timeout: float = 30.0
    db_pool_recycle: int = 1800
    db_pool_pre_ping: bool = True
    db_connect_timeout: int = 5
    db_statement_timeout_ms: int = 15_000
    db_lock_timeout_ms: int = 5_000
    db_ready_timeout: float = 2.0

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


def validate_production_settings(settings: Settings) -> None:
    """Refuse to boot production with development-grade secrets or debug on.

    A default secret is a full authentication bypass: anyone can mint a valid
    access token. Failing at startup is the only safe behaviour.
    """
    if settings.environment != "production":
        return

    problems: list[str] = []
    if settings.debug:
        problems.append("DEBUG must be false")
    if settings.jwt_secret.get_secret_value() == DEFAULT_JWT_SECRET:
        problems.append("JWT_SECRET is the development default")
    elif len(settings.jwt_secret.get_secret_value()) < MIN_SECRET_LENGTH:
        problems.append(f"JWT_SECRET must be at least {MIN_SECRET_LENGTH} characters")
    if settings.otp_pepper.get_secret_value() == DEFAULT_OTP_PEPPER:
        problems.append("OTP_PEPPER is the development default")
    elif len(settings.otp_pepper.get_secret_value()) < MIN_SECRET_LENGTH:
        problems.append(f"OTP_PEPPER must be at least {MIN_SECRET_LENGTH} characters")
    if settings.otp_expose_in_response:
        problems.append("OTP_EXPOSE_IN_RESPONSE must be false")

    if problems:
        raise RuntimeError("Unsafe production configuration: " + "; ".join(problems))


@lru_cache
def get_settings() -> Settings:
    """Dependency provider returning cached Settings instance."""
    return Settings()
