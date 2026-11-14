"""Unit tests for the security primitives (no database required)."""

from __future__ import annotations

import uuid

import pytest

from lurnian.core.exceptions import AuthenticationError
from lurnian.core.security import (
    decode_access_token,
    encode_access_token,
    hash_opaque_token,
)

SECRET = "test-secret-value"
ISSUER = "lurnian-tests"


def test_opaque_token_hash_is_stable_and_not_reversible() -> None:
    digest = hash_opaque_token("token-value")
    assert digest == hash_opaque_token("token-value")
    assert digest != hash_opaque_token("token-value-2")
    assert len(digest) == 32


def test_access_token_round_trip() -> None:
    subject = uuid.uuid4()
    session_id = uuid.uuid4()
    token = encode_access_token(
        subject=subject,
        session_id=session_id,
        secret=SECRET,
        issuer=ISSUER,
        ttl_seconds=900,
        now=1_000_000,
    )
    claims = decode_access_token(token, secret=SECRET, issuer=ISSUER, now=1_000_100)
    assert claims.subject == subject
    assert claims.session_id == session_id
    assert claims.expires_at == 1_000_900


def test_access_token_expires() -> None:
    token = encode_access_token(
        subject=uuid.uuid4(),
        session_id=uuid.uuid4(),
        secret=SECRET,
        issuer=ISSUER,
        ttl_seconds=60,
        now=1_000_000,
    )
    with pytest.raises(AuthenticationError):
        decode_access_token(token, secret=SECRET, issuer=ISSUER, now=1_000_060)


def test_access_token_rejects_a_tampered_payload() -> None:
    token = encode_access_token(
        subject=uuid.uuid4(),
        session_id=uuid.uuid4(),
        secret=SECRET,
        issuer=ISSUER,
        ttl_seconds=60,
        now=1_000_000,
    )
    header, payload, signature = token.split(".")
    tampered = f"{header}.{payload[:-2]}AA.{signature}"
    with pytest.raises(AuthenticationError):
        decode_access_token(tampered, secret=SECRET, issuer=ISSUER, now=1_000_001)


def test_access_token_rejects_another_issuer() -> None:
    token = encode_access_token(
        subject=uuid.uuid4(),
        session_id=uuid.uuid4(),
        secret=SECRET,
        issuer=ISSUER,
        ttl_seconds=60,
        now=1_000_000,
    )
    with pytest.raises(AuthenticationError):
        decode_access_token(
            token, secret=SECRET, issuer="another-issuer", now=1_000_001
        )


def test_access_token_rejects_garbage() -> None:
    with pytest.raises(AuthenticationError):
        decode_access_token("not-a-jwt", secret=SECRET, issuer=ISSUER, now=1)
