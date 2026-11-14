"""One-time codes, opaque tokens and stateless access tokens.

Only the standard library is used: HS256 needs nothing more than ``hmac``, and
keeping these helpers dependency-free means the security primitives are
auditable and cannot drift with a transitive package update.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import secrets
import time
import uuid
from dataclasses import dataclass
from typing import Any, Final

from lurnian.core.exceptions import AuthenticationError

_JWT_ALGORITHM: Final = "HS256"
_JWT_TYPE: Final = "JWT"


def _b64encode(raw: bytes) -> str:
    """Return unpadded base64url text."""
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    """Decode unpadded base64url text, raising ``AuthenticationError``."""
    padding = "=" * (-len(value) % 4)
    try:
        return base64.urlsafe_b64decode(value + padding)
    except (binascii.Error, ValueError) as exc:
        raise AuthenticationError("Malformed token") from exc


# --- Numeric one-time codes -------------------------------------------------


def generate_numeric_code(length: int = 6) -> str:
    """Return a numeric code drawn from the OS CSPRNG.

    ``secrets`` is used instead of ``random`` because an OTP is a credential:
    predictable digits would let an attacker guess a live code.
    """
    return "".join(secrets.choice("0123456789") for _ in range(length))


def hash_numeric_code(code: str, *, pepper: str) -> bytes:
    """Return the keyed digest stored in place of the code.

    A six-digit space is small enough to brute-force offline, so the hash is
    HMAC with a server-side pepper: a stolen table alone is not enough to
    recover live codes.
    """
    return hmac.new(
        pepper.encode("utf-8"), code.encode("utf-8"), hashlib.sha256
    ).digest()


def numeric_code_matches(code: str, digest: bytes, *, pepper: str) -> bool:
    """Compare a submitted code with a stored digest in constant time."""
    return hmac.compare_digest(hash_numeric_code(code, pepper=pepper), digest)


# --- Opaque tokens ----------------------------------------------------------


def generate_opaque_token() -> str:
    """Return a high-entropy token to hand to the client once."""
    return secrets.token_urlsafe(32)


def hash_opaque_token(token: str) -> bytes:
    """Return the SHA-256 digest stored in place of an opaque token.

    A plain hash is sufficient: the token is 256 bits of randomness, so there
    is no low-entropy guess space for a slow KDF to protect.
    """
    return hashlib.sha256(token.encode("utf-8")).digest()


# --- Access tokens ----------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AccessTokenClaims:
    """Verified claims carried by an access token."""

    subject: uuid.UUID
    session_id: uuid.UUID
    expires_at: int


def encode_access_token(
    *,
    subject: uuid.UUID,
    session_id: uuid.UUID,
    secret: str,
    issuer: str,
    ttl_seconds: int,
    now: int | None = None,
) -> str:
    """Return a signed HS256 access token.

    Access tokens are stateless and never stored: only ``sub`` and ``sid`` are
    carried, so revocation is decided by the session row, not by the token.
    """
    issued_at = int(time.time()) if now is None else now
    header = {"alg": _JWT_ALGORITHM, "typ": _JWT_TYPE}
    payload = {
        "sub": str(subject),
        "sid": str(session_id),
        "iss": issuer,
        "typ": "access",
        "iat": issued_at,
        "exp": issued_at + ttl_seconds,
    }
    signing_input = ".".join(
        (
            _b64encode(_json_bytes(header)),
            _b64encode(_json_bytes(payload)),
        )
    )
    signature = hmac.new(
        secret.encode("utf-8"), signing_input.encode("ascii"), hashlib.sha256
    ).digest()
    return f"{signing_input}.{_b64encode(signature)}"


def decode_access_token(
    token: str,
    *,
    secret: str,
    issuer: str,
    now: int | None = None,
) -> AccessTokenClaims:
    """Verify signature, issuer and expiry, then return the claims."""
    try:
        header_b64, payload_b64, signature_b64 = token.split(".")
    except ValueError as exc:
        raise AuthenticationError("Malformed access token") from exc

    signing_input = f"{header_b64}.{payload_b64}"
    expected = hmac.new(
        secret.encode("utf-8"), signing_input.encode("ascii"), hashlib.sha256
    ).digest()
    if not hmac.compare_digest(expected, _b64decode(signature_b64)):
        raise AuthenticationError("Invalid access token signature")

    header = _json_dict(_b64decode(header_b64))
    if header.get("alg") != _JWT_ALGORITHM:
        raise AuthenticationError("Unsupported access token algorithm")

    payload = _json_dict(_b64decode(payload_b64))
    if payload.get("typ") != "access" or payload.get("iss") != issuer:
        raise AuthenticationError("Invalid access token claims")

    expires_at = payload.get("exp")
    issued_at = payload.get("iat")
    if not isinstance(expires_at, int) or not isinstance(issued_at, int):
        raise AuthenticationError("Invalid access token claims")

    current = int(time.time()) if now is None else now
    if current >= expires_at:
        raise AuthenticationError("Access token expired")

    try:
        subject = uuid.UUID(str(payload["sub"]))
        session_id = uuid.UUID(str(payload["sid"]))
    except (KeyError, ValueError) as exc:
        raise AuthenticationError("Invalid access token claims") from exc

    return AccessTokenClaims(
        subject=subject, session_id=session_id, expires_at=expires_at
    )


def _json_bytes(payload: dict[str, Any]) -> bytes:
    """Serialize claims deterministically for signing."""
    return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _json_dict(raw: bytes) -> dict[str, Any]:
    """Parse a JSON object claim set, rejecting anything else."""
    try:
        parsed = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise AuthenticationError("Malformed access token") from exc
    if not isinstance(parsed, dict):
        raise AuthenticationError("Malformed access token")
    return parsed
