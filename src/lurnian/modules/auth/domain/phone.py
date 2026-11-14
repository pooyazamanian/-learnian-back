"""Phone number normalization.

Clients send what people type (``0912 345 6789``, ``+98 912…``, ``0098912…``),
but the database stores exactly one shape: E.164. Uniqueness, OTP delivery and
account lookup then compare apples to apples.
"""

from __future__ import annotations

import re

from lurnian.core.exceptions import ValidationError

_SEPARATORS = re.compile(r"[\s\-().]")
_E164 = re.compile(r"^\+[1-9]\d{7,14}$")


def normalize_phone(raw: str, *, default_country_code: str) -> str:
    """Return ``raw`` as an E.164 number or raise a validation error.

    ``default_country_code`` is the digits-only calling code (``"98"``) applied
    when the caller omits the country prefix.
    """
    value = _SEPARATORS.sub("", raw.strip())
    if not value:
        raise _invalid()
    if value.startswith("00"):
        value = f"+{value[2:]}"

    if value.startswith("+"):
        candidate = value
    elif value.startswith("0"):
        candidate = f"+{default_country_code}{value[1:]}"
    elif value.startswith(default_country_code) and len(value) >= 9:
        candidate = f"+{value}"
    else:
        candidate = f"+{default_country_code}{value}"

    if not _E164.fullmatch(candidate):
        raise _invalid()
    return candidate


def _invalid() -> ValidationError:
    """Return the one error shape clients learn for a bad number."""
    return ValidationError(
        "Phone number must be a valid international number, e.g. +989121234567",
        code="invalid_phone",
    )
