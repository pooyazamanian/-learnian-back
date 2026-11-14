"""Billing domain: plan catalog, subscriptions, orders, payments, entitlements.

There is no ``is_premium`` flag anywhere. Every access decision is answered by
``user_entitlements``, which records both derived (subscription/trial) and
manually granted sources, and is written in the same transaction as the
subscription change that produced it.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CHAR,
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    SmallInteger,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from lurnian.core.database import Base
from lurnian.core.enums import (
    BillingPeriod,
    EntitlementSource,
    FeatureValueType,
    OrderStatus,
    PaymentMethod,
    PaymentProvider,
    PaymentStatus,
    PlanTier,
    SubscriptionStatus,
    pg_enum,
)
from lurnian.core.types import TimestampMixin, new_uuid


class SubscriptionPlan(Base, TimestampMixin):
    """Purchasable plan plus the free plan. Retired plans are deactivated."""

    __tablename__ = "subscription_plans"
    __table_args__ = (
        CheckConstraint(
            "(billing_period = 'none') = (price_minor IS NULL)",
            name="price_matches_period",
        ),
        CheckConstraint(
            "price_minor IS NULL OR price_minor >= 0", name="price_non_negative"
        ),
        CheckConstraint("trial_days BETWEEN 0 AND 90", name="trial_days_range"),
        Index("ix_subscription_plans_code", "code", unique=True),
        Index("ix_subscription_plans_active_sort", "is_active", "sort_order"),
    )

    id: Mapped[int] = mapped_column(
        SmallInteger, Identity(always=False), primary_key=True
    )
    code: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    # Display only; never the basis of an access decision.
    tier: Mapped[PlanTier] = mapped_column(pg_enum(PlanTier), nullable=False)
    billing_period: Mapped[BillingPeriod] = mapped_column(
        pg_enum(BillingPeriod), nullable=False
    )
    price_minor: Mapped[int | None] = mapped_column(BigInteger)
    currency: Mapped[str | None] = mapped_column(CHAR(3))
    trial_days: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("0")
    )
    is_active: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"))
    sort_order: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, server_default=text("0")
    )


class PlanFeature(Base):
    """Catalog of product capabilities that plans can grant or limit."""

    __tablename__ = "plan_features"
    __table_args__ = (
        CheckConstraint(
            "value_type <> 'quota' OR unit IS NOT NULL", name="quota_requires_unit"
        ),
        Index("ix_plan_features_code", "code", unique=True),
    )

    id: Mapped[int] = mapped_column(
        SmallInteger, Identity(always=False), primary_key=True
    )
    code: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    value_type: Mapped[FeatureValueType] = mapped_column(
        pg_enum(FeatureValueType), nullable=False, server_default=text("'boolean'")
    )
    unit: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(nullable=False, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PlanFeatureValue(Base):
    """Value of one capability in one plan: disabled vs enabled-with-limit."""

    __tablename__ = "plan_feature_values"
    __table_args__ = (
        CheckConstraint(
            "limit_value IS NULL OR limit_value >= 0", name="limit_non_negative"
        ),
        Index("ix_plan_feature_values_feature_id", "feature_id"),
    )

    plan_id: Mapped[int] = mapped_column(
        ForeignKey("subscription_plans.id", ondelete="CASCADE"), primary_key=True
    )
    feature_id: Mapped[int] = mapped_column(
        ForeignKey("plan_features.id", ondelete="RESTRICT"), primary_key=True
    )
    is_enabled: Mapped[bool] = mapped_column(
        nullable=False, server_default=text("false")
    )
    limit_value: Mapped[int | None] = mapped_column(Integer)


class UserSubscription(Base, TimestampMixin):
    """A subscription period; at most one non-terminal row per user."""

    __tablename__ = "user_subscriptions"
    __table_args__ = (
        CheckConstraint(
            "current_period_end > current_period_start",
            name="period_end_after_start",
        ),
        CheckConstraint(
            "cancel_at_period_end = false OR canceled_at IS NOT NULL",
            name="cancel_request_has_timestamp",
        ),
        Index("ix_user_subscriptions_user_status", "user_id", "status"),
        Index("ix_user_subscriptions_expiring", "status", "current_period_end"),
        Index(
            "uq_user_subscriptions_open",
            "user_id",
            unique=True,
            postgresql_where=text("status IN ('trialing', 'active', 'past_due')"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    plan_id: Mapped[int] = mapped_column(
        ForeignKey("subscription_plans.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[SubscriptionStatus] = mapped_column(
        pg_enum(SubscriptionStatus), nullable=False, server_default=text("'active'")
    )
    current_period_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    current_period_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    cancel_at_period_end: Mapped[bool] = mapped_column(
        nullable=False, server_default=text("false")
    )
    canceled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    trial_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provider: Mapped[PaymentProvider | None] = mapped_column(pg_enum(PaymentProvider))
    provider_subscription_id: Mapped[str | None] = mapped_column(Text)


class Order(Base, TimestampMixin):
    """Intent to buy a plan, with amounts snapshotted at placement time."""

    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "idempotency_key", name="uq_orders_user_idempotency_key"
        ),
        CheckConstraint("amount_minor >= 0", name="amount_non_negative"),
        CheckConstraint(
            "subtotal_minor >= amount_minor", name="discount_within_subtotal"
        ),
        CheckConstraint(
            "expires_at IS NULL OR expires_at > placed_at",
            name="expiry_after_placement",
        ),
        Index("ix_orders_user_placed", "user_id", text("placed_at DESC")),
        Index("ix_orders_pending_expiry", "status", "expires_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    plan_id: Mapped[int] = mapped_column(
        ForeignKey("subscription_plans.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[OrderStatus] = mapped_column(
        pg_enum(OrderStatus), nullable=False, server_default=text("'pending'")
    )
    subtotal_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    discount_minor: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("0")
    )
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(Text, nullable=False)
    placed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    canceled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Payment(Base):
    """One payment attempt on an order; failed attempts are kept.

    No PAN or CVV is ever stored - only the provider reference and error codes.
    """

    __tablename__ = "payments"
    __table_args__ = (
        CheckConstraint("amount_minor > 0", name="amount_positive"),
        CheckConstraint(
            "status <> 'failed' OR failed_at IS NOT NULL",
            name="failed_payment_has_timestamp",
        ),
        Index("ix_payments_order_id", "order_id"),
        Index("ix_payments_user_created", "user_id", text("created_at DESC")),
        Index(
            "uq_payments_provider_payment",
            "provider",
            "provider_payment_id",
            unique=True,
            postgresql_where=text("provider_payment_id IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    order_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("orders.id", ondelete="RESTRICT"), nullable=False
    )
    # Deliberate duplication: per-user reporting and access checks avoid a join.
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    provider: Mapped[PaymentProvider] = mapped_column(
        pg_enum(PaymentProvider), nullable=False
    )
    provider_payment_id: Mapped[str | None] = mapped_column(Text)
    status: Mapped[PaymentStatus] = mapped_column(
        pg_enum(PaymentStatus), nullable=False, server_default=text("'initiated'")
    )
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    method: Mapped[PaymentMethod | None] = mapped_column(pg_enum(PaymentMethod))
    failure_code: Mapped[str | None] = mapped_column(Text)
    failure_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    authorized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    captured_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    refunded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UserEntitlement(Base):
    """Effective access row: the single source of truth for feature access.

    ``NULLS NOT DISTINCT`` makes the unique constraint treat a missing
    ``source_id`` as one value, so a manual grant cannot be duplicated.
    """

    __tablename__ = "user_entitlements"
    __table_args__ = (
        CheckConstraint(
            "limit_value IS NULL OR limit_value >= 0", name="limit_non_negative"
        ),
        CheckConstraint(
            "expires_at IS NULL OR expires_at > granted_at",
            name="expiry_after_grant",
        ),
        Index("ix_user_entitlements_user_feature", "user_id", "feature_id"),
        Index(
            "ix_user_entitlements_active_user",
            "user_id",
            postgresql_where=text("revoked_at IS NULL"),
        ),
        Index(
            "uq_user_entitlements_source",
            "user_id",
            "feature_id",
            "source_type",
            "source_id",
            unique=True,
            postgresql_nulls_not_distinct=True,
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=new_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    feature_id: Mapped[int] = mapped_column(
        ForeignKey("plan_features.id", ondelete="RESTRICT"), nullable=False
    )
    source_type: Mapped[EntitlementSource] = mapped_column(
        pg_enum(EntitlementSource), nullable=False
    )
    source_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    is_enabled: Mapped[bool] = mapped_column(
        nullable=False, server_default=text("false")
    )
    limit_value: Mapped[int | None] = mapped_column(Integer)
    granted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
