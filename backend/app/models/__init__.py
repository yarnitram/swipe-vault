"""SQLAlchemy ORM models. Schema changes must go through Alembic migrations."""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    DateTime,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(UTC)


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


def _ts(nullable: bool = False, default: bool = True) -> Mapped[Any]:
    return mapped_column(DateTime(timezone=True), nullable=nullable, default=utcnow if default else None)


class Base(DeclarativeBase):
    pass


APPROVAL_STATES = ("unknown", "requested", "approved", "denied", "revoked")
SOURCE_TYPES = ("affiliate_page", "offer_page", "asset_url", "other")
ACCESS_STATES = ("unverified", "authorized", "restricted", "approval_required", "forbidden")
EXTRACTION_STATES = ("pending", "processing", "extracted", "needs_review", "failed", "unsupported")
ASSET_ORIGINS = ("upload", "scan", "archive_entry")
REVIEW_STATES = ("pending", "needs_changes", "approved", "rejected", "archived")
JOB_STATES = ("queued", "running", "completed", "partial", "failed", "cancel_requested", "cancelled")
JOB_TERMINAL_STATES = ("completed", "partial", "failed", "cancelled")
JOB_TYPES = ("ingest_asset",)


def _in(col: str, values: tuple[str, ...]) -> str:
    return f"{col} IN ({', '.join(repr(v) for v in values)})"


class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = _uuid_pk()
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, default="admin")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = _ts()
    __table_args__ = (CheckConstraint("role IN ('admin', 'editor', 'reviewer')", name="ck_users_role"),)


class UserSession(Base):
    __tablename__ = "sessions"
    id: Mapped[uuid.UUID] = _uuid_pk()
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    created_at: Mapped[datetime] = _ts()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    user: Mapped[User] = relationship()


class Network(Base):
    __tablename__ = "networks"
    id: Mapped[uuid.UUID] = _uuid_pk()
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Offer(Base):
    __tablename__ = "offers"
    id: Mapped[uuid.UUID] = _uuid_pk()
    network_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("networks.id"), nullable=False)
    external_offer_id: Mapped[str | None] = mapped_column(String(200))
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    niche: Mapped[str | None] = mapped_column(String(200))
    vendor_name: Mapped[str | None] = mapped_column(String(300))
    offer_url: Mapped[str | None] = mapped_column(Text)
    affiliate_resources_url: Mapped[str | None] = mapped_column(Text)
    approval_state: Mapped[str] = mapped_column(String(32), nullable=False, default="unknown")
    metrics_json: Mapped[dict | None] = mapped_column(JSONB)
    metrics_source: Mapped[str | None] = mapped_column(String(300))
    metrics_as_of: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notes: Mapped[str | None] = mapped_column(Text)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    network: Mapped[Network] = relationship(lazy="joined")
    __table_args__ = (CheckConstraint(_in("approval_state", APPROVAL_STATES), name="ck_offers_approval_state"),)


class OfferApproval(Base):
    __tablename__ = "offer_approvals"
    id: Mapped[uuid.UUID] = _uuid_pk()
    offer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("offers.id", ondelete="CASCADE"), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = _ts()
    user: Mapped[User | None] = relationship(lazy="joined")
    __table_args__ = (CheckConstraint(_in("state", APPROVAL_STATES), name="ck_offer_approvals_state"),)


class Source(Base):
    __tablename__ = "sources"
    id: Mapped[uuid.UUID] = _uuid_pk()
    offer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("offers.id", ondelete="CASCADE"), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_url: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False, default="affiliate_page")
    access_state: Mapped[str] = mapped_column(String(32), nullable=False, default="unverified")
    permission_notes: Mapped[str | None] = mapped_column(Text)
    allowed_hosts: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _ts()
    __table_args__ = (
        UniqueConstraint("offer_id", "normalized_url", name="uq_sources_offer_normalized_url"),
        CheckConstraint(_in("source_type", SOURCE_TYPES), name="ck_sources_type"),
        CheckConstraint(_in("access_state", ACCESS_STATES), name="ck_sources_access_state"),
    )


class Asset(Base):
    __tablename__ = "assets"
    id: Mapped[uuid.UUID] = _uuid_pk()
    sha256: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    storage_key: Mapped[str] = mapped_column(String(200), nullable=False)
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    media_type: Mapped[str] = mapped_column(String(200), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    extraction_state: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    extraction_error: Mapped[str | None] = mapped_column(Text)
    extractor: Mapped[str | None] = mapped_column(String(100))
    extractor_version: Mapped[str | None] = mapped_column(String(50))
    created_at: Mapped[datetime] = _ts()
    __table_args__ = (CheckConstraint(_in("extraction_state", EXTRACTION_STATES), name="ck_assets_state"),)


class AssetSource(Base):
    """A reference from an offer to an asset (upload, scan retrieval or archive entry)."""

    __tablename__ = "asset_sources"
    id: Mapped[uuid.UUID] = _uuid_pk()
    asset_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), nullable=False)
    offer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("offers.id", ondelete="CASCADE"), nullable=False)
    source_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sources.id", ondelete="SET NULL"))
    parent_asset_source_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("asset_sources.id", ondelete="CASCADE")
    )
    origin: Mapped[str] = mapped_column(String(32), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    lineage_key: Mapped[str] = mapped_column(Text, nullable=False)
    retrieval_url: Mapped[str | None] = mapped_column(Text)
    retrieved_at: Mapped[datetime] = _ts()
    version_label: Mapped[str | None] = mapped_column(String(50))
    notes: Mapped[str | None] = mapped_column(Text)

    asset: Mapped[Asset] = relationship(lazy="joined")
    __table_args__ = (CheckConstraint(_in("origin", ASSET_ORIGINS), name="ck_asset_sources_origin"),)


class Swipe(Base):
    __tablename__ = "swipes"
    id: Mapped[uuid.UUID] = _uuid_pk()
    offer_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("offers.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str | None] = mapped_column(String(500))
    review_state: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    lineage_key: Mapped[str | None] = mapped_column(Text)
    identity_key: Mapped[str | None] = mapped_column(String(200))
    notes: Mapped[str | None] = mapped_column(Text)
    search_document: Mapped[str] = mapped_column(Text, nullable=False, default="")
    search_tsv: Mapped[Any] = mapped_column(
        TSVECTOR, Computed("to_tsvector('english', coalesce(search_document, ''))", persisted=True)
    )
    created_at: Mapped[datetime] = _ts()
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)

    offer: Mapped[Offer] = relationship(lazy="joined")
    __table_args__ = (
        CheckConstraint(_in("review_state", REVIEW_STATES), name="ck_swipes_review_state"),
        ForeignKeyConstraint(
            ["current_version_id", "id"],
            ["swipe_versions.id", "swipe_versions.swipe_id"],
            name="fk_swipes_current_version_belongs",
            use_alter=True,
        ),
    )


class SwipeVersion(Base):
    __tablename__ = "swipe_versions"
    id: Mapped[uuid.UUID] = _uuid_pk()
    swipe_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("swipes.id", ondelete="CASCADE"), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    body_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    body_html_sanitized: Mapped[str | None] = mapped_column(Text)
    preheader: Mapped[str | None] = mapped_column(Text)
    ctas_json: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    flags_json: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    normalized_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(50), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    section_label: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = _ts()

    subjects: Mapped[list["SubjectVariant"]] = relationship(
        order_by="SubjectVariant.position", cascade="all, delete-orphan", lazy="selectin"
    )
    __table_args__ = (
        UniqueConstraint("swipe_id", "version_number", name="uq_swipe_versions_number"),
        UniqueConstraint("id", "swipe_id", name="uq_swipe_versions_id_swipe"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_swipe_versions_confidence"),
    )


class SubjectVariant(Base):
    __tablename__ = "subject_variants"
    id: Mapped[uuid.UUID] = _uuid_pk()
    swipe_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("swipe_versions.id", ondelete="CASCADE"), nullable=False
    )
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    __table_args__ = (UniqueConstraint("swipe_version_id", "position", name="uq_subject_variants_position"),)


class SwipeProvenance(Base):
    __tablename__ = "swipe_provenance"
    id: Mapped[uuid.UUID] = _uuid_pk()
    swipe_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("swipe_versions.id", ondelete="CASCADE"), nullable=False
    )
    asset_source_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("asset_sources.id", ondelete="CASCADE"), nullable=False
    )
    page_number: Mapped[int | None] = mapped_column(Integer)
    section_label: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    created_at: Mapped[datetime] = _ts()
    asset_source: Mapped[AssetSource] = relationship(lazy="joined")
    __table_args__ = (
        UniqueConstraint(
            "swipe_version_id", "asset_source_id", "section_label", name="uq_swipe_provenance_ref"
        ),
    )


class Tag(Base):
    __tablename__ = "tags"
    id: Mapped[uuid.UUID] = _uuid_pk()
    slug: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    label: Mapped[str] = mapped_column(String(200), nullable=False)


class SwipeTag(Base):
    __tablename__ = "swipe_tags"
    swipe_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("swipes.id", ondelete="CASCADE"), primary_key=True)
    tag_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True)


class ReviewEvent(Base):
    __tablename__ = "review_events"
    id: Mapped[uuid.UUID] = _uuid_pk()
    swipe_version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("swipe_versions.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _ts()
    user: Mapped[User | None] = relationship(lazy="joined")
    __table_args__ = (CheckConstraint(_in("decision", REVIEW_STATES), name="ck_review_events_decision"),)


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[uuid.UUID] = _uuid_pk()
    offer_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("offers.id", ondelete="SET NULL"))
    source_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sources.id", ondelete="SET NULL"))
    asset_source_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("asset_sources.id", ondelete="SET NULL")
    )
    retry_of_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("jobs.id", ondelete="SET NULL"))
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    progress_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_summary: Mapped[str | None] = mapped_column(Text)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = _ts()
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    offer: Mapped[Offer | None] = relationship(lazy="joined")
    __table_args__ = (
        CheckConstraint(_in("state", JOB_STATES), name="ck_jobs_state"),
        CheckConstraint(_in("type", JOB_TYPES), name="ck_jobs_type"),
    )


class JobEvent(Base):
    __tablename__ = "job_events"
    id: Mapped[uuid.UUID] = _uuid_pk()
    job_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    level: Mapped[str] = mapped_column(String(16), nullable=False, default="info")
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = _ts()
    __table_args__ = (CheckConstraint("level IN ('info', 'warning', 'error')", name="ck_job_events_level"),)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[uuid.UUID] = _uuid_pk()
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(64))
    metadata_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = _ts()
