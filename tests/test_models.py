"""Guards that the SQLAlchemy metadata matches the approved database design.

These tests do not need a running PostgreSQL: they check the shape of the
metadata, the enum catalog and the coverage of the baseline migration.
"""

from __future__ import annotations

import pathlib
import re

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from lurnian import models as _models
from lurnian.core.database import Base
from lurnian.core.enums import ENUM_VALUES

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent

EXPECTED_TABLES = {
    # D1 Identity
    "users",
    "user_identities",
    "user_credentials",
    "verification_challenges",
    # D2 Security
    "user_devices",
    "user_sessions",
    "refresh_tokens",
    "security_events",
    "user_security_settings",
    "roles",
    "user_roles",
    # D3 Profile
    "user_profiles",
    "user_settings",
    "user_learning_settings",
    # D4 Billing
    "subscription_plans",
    "plan_features",
    "plan_feature_values",
    "user_subscriptions",
    "orders",
    "payments",
    "user_entitlements",
    # D5 Learning
    "languages",
    "vocabulary",
    "vocabulary_translations",
    "vocabulary_examples",
    "learning_decks",
    "deck_vocabulary",
    "user_vocabulary",
    # D6 Review
    "review_cards",
    "fsrs_card_states",
    "review_history",
    "fsrs_settings",
    "fsrs_parameters",
    # D7 Notification
    "notification_preferences",
    "scheduled_notifications",
    "notification_history",
    # D8 Platform
    "audit_logs",
    "outbox_events",
}


def test_every_model_module_is_registered() -> None:
    """The aggregate import must expose every model module."""
    assert len(_models.MODEL_MODULES) == 7


def test_table_inventory_matches_design() -> None:
    """Exactly the 38 designed tables exist, no more and no less."""
    assert len(EXPECTED_TABLES) == 38
    assert set(Base.metadata.tables) == EXPECTED_TABLES


def test_every_table_has_a_primary_key() -> None:
    """A table without a primary key cannot be updated or replicated safely."""
    missing = [
        table.name
        for table in Base.metadata.tables.values()
        if not table.primary_key.columns
    ]
    assert missing == []


def test_timestamps_are_timezone_aware() -> None:
    """P-01: every timestamp column is TIMESTAMPTZ."""
    offenders = [
        f"{table.name}.{column.name}"
        for table in Base.metadata.tables.values()
        for column in table.columns
        if isinstance(column.type, sa.DateTime) and not column.type.timezone
    ]
    assert offenders == []


def test_foreign_keys_resolve() -> None:
    """Every foreign key points at a real table in the metadata."""
    for table in Base.metadata.tables.values():
        for foreign_key in table.foreign_keys:
            assert foreign_key.column.table is not None
            assert foreign_key.column.table.name in EXPECTED_TABLES


def test_enum_catalog_is_complete_and_used() -> None:
    """31 enum types exist, and no column references an unregistered one."""
    assert len(ENUM_VALUES) == 31
    for table in Base.metadata.tables.values():
        for column in table.columns:
            column_type = column.type
            if isinstance(column_type, postgresql.ARRAY):
                column_type = column_type.item_type
            if isinstance(column_type, postgresql.ENUM):
                assert column_type.name in ENUM_VALUES


def test_identifiers_fit_postgresql_limits() -> None:
    """Explicit names must not exceed the 63-character identifier limit."""
    oversized = [
        name
        for table in Base.metadata.tables.values()
        for name in (
            *[constraint.name for constraint in table.constraints if constraint.name],
            *[index.name for index in table.indexes],
        )
        if len(name) > 63
    ]
    assert oversized == []


def test_ddl_compiles_for_postgresql() -> None:
    """Every table and index renders as valid PostgreSQL DDL."""
    dialect = postgresql.dialect()
    for table in Base.metadata.sorted_tables:
        assert str(sa.schema.CreateTable(table).compile(dialect=dialect))
        for index in table.indexes:
            assert str(sa.schema.CreateIndex(index).compile(dialect=dialect))


def test_baseline_migration_creates_every_table() -> None:
    """The first revision must stay in step with the model layer."""
    source = (
        PROJECT_ROOT / "alembic" / "versions" / "0001_initial_schema.py"
    ).read_text(encoding="utf-8")
    created = set(re.findall(r"op\.create_table\(\s+\"([a-z_]+)\"", source))
    assert created == EXPECTED_TABLES
