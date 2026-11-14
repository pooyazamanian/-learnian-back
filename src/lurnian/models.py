"""Aggregate import of every model module.

``Base.metadata`` is only complete once each module's models have been
imported. Alembic and the model tests import this module so that the full
schema is registered exactly once, with no ordering concerns.
"""

from __future__ import annotations

from types import ModuleType

from lurnian.modules.auth.infrastructure import models as _auth
from lurnian.modules.billing import models as _billing
from lurnian.modules.learning import models as _learning
from lurnian.modules.notification import models as _notification
from lurnian.modules.platform import models as _platform
from lurnian.modules.profile import models as _profile
from lurnian.modules.review import models as _review

#: Every module that contributes tables to ``Base.metadata``.
MODEL_MODULES: tuple[ModuleType, ...] = (
    _auth,
    _profile,
    _billing,
    _learning,
    _review,
    _notification,
    _platform,
)
