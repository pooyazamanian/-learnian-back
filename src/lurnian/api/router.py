"""Version 1 router: the only place modules are attached to the API surface.

Modules never import each other's routers, and ``main`` never imports a module
directly; adding a feature means adding one ``include_router`` line here.
"""

from __future__ import annotations

from fastapi import APIRouter

from lurnian.modules.auth.presentation.router import router as auth_router
from lurnian.modules.review.router import router as review_router


def build_v1_router() -> APIRouter:
    """Return the aggregate router mounted under ``settings.api_v1_prefix``."""
    router = APIRouter()
    router.include_router(auth_router)
    router.include_router(review_router)
    return router
