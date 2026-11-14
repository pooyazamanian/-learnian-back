"""Pure auth rules: no database, no HTTP."""

from __future__ import annotations

import pytest

from lurnian.core.config import Settings, validate_production_settings
from lurnian.core.exceptions import ValidationError
from lurnian.core.security import (
    generate_numeric_code,
    hash_numeric_code,
    numeric_code_matches,
)
from lurnian.modules.auth.domain.phone import normalize_phone

DEFAULT_COUNTRY = "98"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("09121234567", "+989121234567"),
        ("+98 912 123 4567", "+989121234567"),
        ("+989121234567", "+989121234567"),
        ("00989121234567", "+989121234567"),
        ("989121234567", "+989121234567"),
        ("0912-123-4567", "+989121234567"),
        (" 0912 123 4567 ", "+989121234567"),
    ],
)
def test_common_phone_formats_normalize_to_one_value(raw: str, expected: str) -> None:
    """Clients may type any local shape; storage sees exactly one."""
    assert normalize_phone(raw, default_country_code=DEFAULT_COUNTRY) == expected


@pytest.mark.parametrize("raw", ["", "abc", "+0123", "12", "+98"])
def test_invalid_phone_is_a_client_error(raw: str) -> None:
    """A bad number fails as a 400 with a code the client can branch on."""
    with pytest.raises(ValidationError) as caught:
        normalize_phone(raw, default_country_code=DEFAULT_COUNTRY)
    assert caught.value.code == "invalid_phone"
    assert caught.value.status_code == 400


def test_otp_code_is_numeric_and_fixed_length() -> None:
    """The SMS text and the validator both assume digits only."""
    code = generate_numeric_code(6)
    assert len(code) == 6
    assert code.isdigit()


def test_otp_hash_needs_the_server_pepper() -> None:
    """A leaked digest is useless without the pepper."""
    digest = hash_numeric_code("123456", pepper="pepper-a")
    assert numeric_code_matches("123456", digest, pepper="pepper-a")
    assert not numeric_code_matches("123456", digest, pepper="pepper-b")
    assert not numeric_code_matches("654321", digest, pepper="pepper-a")


def test_token_lifetimes_match_the_v1_contract() -> None:
    """Access is short-lived; refresh and the session cap are one year."""
    settings = Settings(_env_file=None)
    assert settings.access_token_ttl_minutes == 30
    assert settings.refresh_token_ttl_days == 365
    assert settings.session_absolute_ttl_days >= settings.refresh_token_ttl_days


def test_production_refuses_development_secrets() -> None:
    """Booting production with the default JWT secret is an auth bypass."""
    settings = Settings(_env_file=None, environment="production")
    with pytest.raises(RuntimeError) as caught:
        validate_production_settings(settings)
    message = str(caught.value)
    assert "DEBUG" in message
    assert "JWT_SECRET" in message
    assert "OTP_PEPPER" in message


def test_production_refuses_echoing_codes() -> None:
    """Returning the OTP in the response is a development-only convenience."""
    settings = Settings(
        _env_file=None,
        environment="production",
        debug=False,
        jwt_secret="a" * 48,
        otp_pepper="b" * 48,
        otp_expose_in_response=True,
    )
    with pytest.raises(RuntimeError, match="OTP_EXPOSE_IN_RESPONSE"):
        validate_production_settings(settings)


def test_hardened_production_settings_are_accepted() -> None:
    settings = Settings(
        _env_file=None,
        environment="production",
        debug=False,
        jwt_secret="a" * 48,
        otp_pepper="b" * 48,
        otp_expose_in_response=False,
    )
    validate_production_settings(settings)
