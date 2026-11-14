"""Access-token adapter: signs the stateless half of the token pair.

The signing primitive lives in ``core.security``; this class only binds it to the
configured secret, issuer and lifetime so the application layer never sees them.
"""

from __future__ import annotations

import uuid

from lurnian.core.config import Settings
from lurnian.core.security import encode_access_token


class JwtTokenIssuer:
    """Issue HS256 access tokens for one session."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @property
    def access_ttl_seconds(self) -> int:
        return self._settings.access_token_ttl_minutes * 60

    def issue(self, *, user_id: uuid.UUID, session_id: uuid.UUID) -> str:
        return encode_access_token(
            subject=user_id,
            session_id=session_id,
            secret=self._settings.jwt_secret.get_secret_value(),
            issuer=self._settings.jwt_issuer,
            ttl_seconds=self.access_ttl_seconds,
        )
