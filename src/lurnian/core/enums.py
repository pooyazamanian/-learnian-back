"""Closed value sets mirrored to PostgreSQL enum types.

Every PostgreSQL ``ENUM`` in the schema is declared exactly once here. Models
bind to these Python enums through :func:`pg_enum`, and the baseline migration
imports :data:`ENUM_VALUES`, so the database types and the application enums
cannot drift apart.

Open-ended value sets (event types, notification categories) are deliberately
*not* enums: they live in ``text`` columns and grow without a migration.
"""

from __future__ import annotations

import enum
from typing import Final

from sqlalchemy.dialects import postgresql


class UserStatus(enum.StrEnum):
    ACTIVE = "active"
    PENDING = "pending"
    SUSPENDED = "suspended"
    DEACTIVATED = "deactivated"
    PENDING_DELETION = "pending_deletion"


class IdentityProvider(enum.StrEnum):
    GOOGLE = "google"
    APPLE = "apple"


class CredentialKind(enum.StrEnum):
    PASSWORD = "password"
    TOTP = "totp"
    RECOVERY_CODES = "recovery_codes"


class ChallengeChannel(enum.StrEnum):
    EMAIL = "email"
    SMS = "sms"


class ChallengePurpose(enum.StrEnum):
    SIGNUP = "signup"
    LOGIN = "login"
    IDENTIFIER_VERIFY = "identifier_verify"
    PASSWORD_RESET = "password_reset"
    IDENTITY_LINK = "identity_link"
    TOTP_RESET = "totp_reset"


class DevicePlatform(enum.StrEnum):
    IOS = "ios"
    ANDROID = "android"
    WEB = "web"


class PushProvider(enum.StrEnum):
    APNS = "apns"
    FCM = "fcm"
    WEB_PUSH = "web_push"


class AuthMethod(enum.StrEnum):
    PASSWORD = "password"
    GOOGLE = "google"
    APPLE = "apple"
    SMS_OTP = "sms_otp"
    EMAIL_OTP = "email_otp"


class SessionRevokedReason(enum.StrEnum):
    LOGOUT = "logout"
    LOGOUT_ALL = "logout_all"
    REUSE_DETECTED = "reuse_detected"
    PASSWORD_CHANGE = "password_change"
    ADMIN = "admin"
    EXPIRED = "expired"


class SecuritySeverity(enum.StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class ActorType(enum.StrEnum):
    USER = "user"
    ADMIN = "admin"
    SYSTEM = "system"
    SERVICE = "service"


class ThemePreference(enum.StrEnum):
    SYSTEM = "system"
    LIGHT = "light"
    DARK = "dark"


class PlanTier(enum.StrEnum):
    FREE = "free"
    PREMIUM = "premium"


class BillingPeriod(enum.StrEnum):
    NONE = "none"
    MONTHLY = "monthly"
    YEARLY = "yearly"


class FeatureValueType(enum.StrEnum):
    BOOLEAN = "boolean"
    QUOTA = "quota"


class SubscriptionStatus(enum.StrEnum):
    TRIALING = "trialing"
    ACTIVE = "active"
    PAST_DUE = "past_due"
    CANCELED = "canceled"
    EXPIRED = "expired"


class OrderStatus(enum.StrEnum):
    PENDING = "pending"
    PAID = "paid"
    FAILED = "failed"
    CANCELED = "canceled"
    REFUNDED = "refunded"
    EXPIRED = "expired"


class PaymentProvider(enum.StrEnum):
    MANUAL = "manual"
    ZARINPAL = "zarinpal"
    STRIPE = "stripe"


class PaymentStatus(enum.StrEnum):
    INITIATED = "initiated"
    AUTHORIZED = "authorized"
    CAPTURED = "captured"
    FAILED = "failed"
    CANCELED = "canceled"
    REFUNDED = "refunded"
    PARTIALLY_REFUNDED = "partially_refunded"


class PaymentMethod(enum.StrEnum):
    CARD = "card"
    WALLET = "wallet"
    APPLE_PAY = "apple_pay"
    GOOGLE_PAY = "google_pay"


class EntitlementSource(enum.StrEnum):
    SUBSCRIPTION = "subscription"
    TRIAL = "trial"
    PROMOTION = "promotion"
    GRANT = "grant"


class TextDirection(enum.StrEnum):
    LTR = "ltr"
    RTL = "rtl"


class PartOfSpeech(enum.StrEnum):
    NOUN = "noun"
    VERB = "verb"
    ADJECTIVE = "adjective"
    ADVERB = "adverb"
    PHRASE = "phrase"
    PREPOSITION = "preposition"
    PRONOUN = "pronoun"
    CONJUNCTION = "conjunction"
    INTERJECTION = "interjection"
    DETERMINER = "determiner"
    OTHER = "other"


class CefrLevel(enum.StrEnum):
    A1 = "a1"
    A2 = "a2"
    B1 = "b1"
    B2 = "b2"
    C1 = "c1"
    C2 = "c2"


class ExampleSource(enum.StrEnum):
    CURATED = "curated"
    GENERATED = "generated"
    USER = "user"


class DeckVisibility(enum.StrEnum):
    PRIVATE = "private"
    UNLISTED = "unlisted"
    PUBLIC = "public"


class UserVocabularyStatus(enum.StrEnum):
    LEARNING = "learning"
    KNOWN = "known"
    IGNORED = "ignored"
    SUSPENDED = "suspended"


class UserVocabularySource(enum.StrEnum):
    MANUAL = "manual"
    DECK = "deck"
    IMPORT = "import"


class ReviewCardMode(enum.StrEnum):
    WORD_TO_FA = "word_to_fa"
    WORD_TO_EN = "word_to_en"
    FA_TO_WORD = "fa_to_word"
    EN_TO_WORD = "en_to_word"


class FsrsState(enum.StrEnum):
    NEW = "new"
    LEARNING = "learning"
    REVIEW = "review"
    RELEARNING = "relearning"


class FsrsParameterSource(enum.StrEnum):
    DEFAULT = "default"
    OPTIMIZED = "optimized"


ENUM_NAMES: Final[dict[type[enum.StrEnum], str]] = {
    UserStatus: "user_status",
    IdentityProvider: "identity_provider",
    CredentialKind: "credential_kind",
    ChallengeChannel: "challenge_channel",
    ChallengePurpose: "challenge_purpose",
    DevicePlatform: "device_platform",
    PushProvider: "push_provider",
    AuthMethod: "auth_method",
    SessionRevokedReason: "session_revoked_reason",
    SecuritySeverity: "security_severity",
    ActorType: "actor_type",
    ThemePreference: "theme_preference",
    PlanTier: "plan_tier",
    BillingPeriod: "billing_period",
    FeatureValueType: "feature_value_type",
    SubscriptionStatus: "subscription_status",
    OrderStatus: "order_status",
    PaymentProvider: "payment_provider",
    PaymentStatus: "payment_status",
    PaymentMethod: "payment_method",
    EntitlementSource: "entitlement_source",
    TextDirection: "text_direction",
    PartOfSpeech: "part_of_speech",
    CefrLevel: "cefr_level",
    ExampleSource: "example_source",
    DeckVisibility: "deck_visibility",
    UserVocabularyStatus: "user_vocabulary_status",
    UserVocabularySource: "user_vocabulary_source",
    ReviewCardMode: "review_card_mode",
    FsrsState: "fsrs_state",
    FsrsParameterSource: "fsrs_parameter_source",
}

#: ``{type_name: values}`` consumed by the baseline migration.
ENUM_VALUES: Final[dict[str, tuple[str, ...]]] = {
    name: tuple(member.value for member in python_enum)
    for python_enum, name in ENUM_NAMES.items()
}


def pg_enum(python_enum: type[enum.StrEnum]) -> postgresql.ENUM:
    """Return the PostgreSQL type bound to ``python_enum``.

    ``create_type=False`` keeps the models from emitting ``CREATE TYPE``; the
    migration owns type creation so that offline ``--sql`` generation stays
    deterministic.
    """
    return postgresql.ENUM(
        python_enum,
        name=ENUM_NAMES[python_enum],
        create_type=False,
        values_callable=_enum_values,
        validate_strings=True,
    )


def _enum_values(python_enum: type[enum.StrEnum]) -> list[str]:
    """Return the wire values of an enum, in declaration order."""
    return [member.value for member in python_enum]
