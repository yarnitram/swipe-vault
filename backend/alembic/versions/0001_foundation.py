"""Phase 0-1 foundation schema: auth, offers, sources, assets, swipes, jobs, audit.

Revision ID: 0001_foundation
Revises:
Create Date: 2026-11-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision: str = "0001_foundation"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = pg.UUID(as_uuid=True)
TS = sa.DateTime(timezone=True)
NOW = sa.text("now()")


def _id() -> sa.Column:
    return sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()"))


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    op.create_table(
        "users",
        _id(),
        sa.Column("email", sa.String(320), nullable=False, unique=True),
        sa.Column("password_hash", sa.Text, nullable=False),
        sa.Column("role", sa.String(32), nullable=False, server_default="admin"),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("created_at", TS, nullable=False, server_default=NOW),
        sa.CheckConstraint("role IN ('admin', 'editor', 'reviewer')", name="ck_users_role"),
    )
    op.create_table(
        "sessions",
        _id(),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("user_id", UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", TS, nullable=False, server_default=NOW),
        sa.Column("expires_at", TS, nullable=False),
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])

    op.create_table(
        "networks",
        _id(),
        sa.Column("slug", sa.String(64), nullable=False, unique=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.true()),
    )

    op.create_table(
        "offers",
        _id(),
        sa.Column("network_id", UUID, sa.ForeignKey("networks.id"), nullable=False),
        sa.Column("external_offer_id", sa.String(200)),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("niche", sa.String(200)),
        sa.Column("vendor_name", sa.String(300)),
        sa.Column("offer_url", sa.Text),
        sa.Column("affiliate_resources_url", sa.Text),
        sa.Column("approval_state", sa.String(32), nullable=False, server_default="unknown"),
        sa.Column("metrics_json", pg.JSONB),
        sa.Column("metrics_source", sa.String(300)),
        sa.Column("metrics_as_of", TS),
        sa.Column("notes", sa.Text),
        sa.Column("last_verified_at", TS),
        sa.Column("created_at", TS, nullable=False, server_default=NOW),
        sa.Column("updated_at", TS, nullable=False, server_default=NOW),
        sa.CheckConstraint(
            "approval_state IN ('unknown', 'requested', 'approved', 'denied', 'revoked')",
            name="ck_offers_approval_state",
        ),
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_offers_network_external_id ON offers (network_id, lower(external_offer_id)) "
        "WHERE external_offer_id IS NOT NULL"
    )
    op.execute("CREATE INDEX ix_offers_title_trgm ON offers USING gin (title gin_trgm_ops)")
    op.create_index("ix_offers_niche", "offers", ["niche"])

    op.create_table(
        "offer_approvals",
        _id(),
        sa.Column("offer_id", UUID, sa.ForeignKey("offers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("notes", sa.Text),
        sa.Column("user_id", UUID, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", TS, nullable=False, server_default=NOW),
        sa.CheckConstraint(
            "state IN ('unknown', 'requested', 'approved', 'denied', 'revoked')",
            name="ck_offer_approvals_state",
        ),
    )
    op.create_index("ix_offer_approvals_offer_id", "offer_approvals", ["offer_id"])

    op.create_table(
        "sources",
        _id(),
        sa.Column("offer_id", UUID, sa.ForeignKey("offers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("url", sa.Text, nullable=False),
        sa.Column("normalized_url", sa.Text, nullable=False),
        sa.Column("source_type", sa.String(32), nullable=False, server_default="affiliate_page"),
        sa.Column("access_state", sa.String(32), nullable=False, server_default="unverified"),
        sa.Column("permission_notes", sa.Text),
        sa.Column("allowed_hosts", pg.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("last_checked_at", TS),
        sa.Column("created_at", TS, nullable=False, server_default=NOW),
        sa.UniqueConstraint("offer_id", "normalized_url", name="uq_sources_offer_normalized_url"),
        sa.CheckConstraint(
            "source_type IN ('affiliate_page', 'offer_page', 'asset_url', 'other')", name="ck_sources_type"
        ),
        sa.CheckConstraint(
            "access_state IN ('unverified', 'authorized', 'restricted', 'approval_required', 'forbidden')",
            name="ck_sources_access_state",
        ),
    )

    op.create_table(
        "assets",
        _id(),
        sa.Column("sha256", sa.String(64), nullable=False, unique=True),
        sa.Column("storage_key", sa.String(200), nullable=False),
        sa.Column("filename", sa.String(500), nullable=False),
        sa.Column("media_type", sa.String(200), nullable=False),
        sa.Column("size_bytes", sa.BigInteger, nullable=False),
        sa.Column("extraction_state", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("extraction_error", sa.Text),
        sa.Column("extractor", sa.String(100)),
        sa.Column("extractor_version", sa.String(50)),
        sa.Column("created_at", TS, nullable=False, server_default=NOW),
        sa.CheckConstraint(
            "extraction_state IN ('pending', 'processing', 'extracted', 'needs_review', 'failed', 'unsupported')",
            name="ck_assets_state",
        ),
    )

    op.create_table(
        "asset_sources",
        _id(),
        sa.Column("asset_id", UUID, sa.ForeignKey("assets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("offer_id", UUID, sa.ForeignKey("offers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_id", UUID, sa.ForeignKey("sources.id", ondelete="SET NULL")),
        sa.Column(
            "parent_asset_source_id", UUID, sa.ForeignKey("asset_sources.id", ondelete="CASCADE")
        ),
        sa.Column("origin", sa.String(32), nullable=False),
        sa.Column("original_filename", sa.String(500), nullable=False),
        sa.Column("lineage_key", sa.Text, nullable=False),
        sa.Column("retrieval_url", sa.Text),
        sa.Column("retrieved_at", TS, nullable=False, server_default=NOW),
        sa.Column("version_label", sa.String(50)),
        sa.Column("notes", sa.Text),
        sa.CheckConstraint("origin IN ('upload', 'scan', 'archive_entry')", name="ck_asset_sources_origin"),
    )
    op.create_index("ix_asset_sources_offer_id", "asset_sources", ["offer_id"])
    op.create_index("ix_asset_sources_asset_id", "asset_sources", ["asset_id"])
    op.create_index("ix_asset_sources_lineage", "asset_sources", ["offer_id", "lineage_key"])

    op.create_table(
        "swipes",
        _id(),
        sa.Column("offer_id", UUID, sa.ForeignKey("offers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(500)),
        sa.Column("review_state", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("current_version_id", UUID),
        sa.Column("lineage_key", sa.Text),
        sa.Column("identity_key", sa.String(200)),
        sa.Column("notes", sa.Text),
        sa.Column("search_document", sa.Text, nullable=False, server_default=""),
        sa.Column(
            "search_tsv",
            pg.TSVECTOR,
            sa.Computed("to_tsvector('english', coalesce(search_document, ''))", persisted=True),
        ),
        sa.Column("created_at", TS, nullable=False, server_default=NOW),
        sa.Column("updated_at", TS, nullable=False, server_default=NOW),
        sa.CheckConstraint(
            "review_state IN ('pending', 'needs_changes', 'approved', 'rejected', 'archived')",
            name="ck_swipes_review_state",
        ),
    )
    op.create_index("ix_swipes_offer_id", "swipes", ["offer_id"])
    op.create_index("ix_swipes_review_state", "swipes", ["review_state"])
    op.create_index("ix_swipes_lineage", "swipes", ["offer_id", "lineage_key", "identity_key"])
    op.execute("CREATE INDEX ix_swipes_search_tsv ON swipes USING gin (search_tsv)")
    op.execute("CREATE INDEX ix_swipes_search_trgm ON swipes USING gin (search_document gin_trgm_ops)")

    op.create_table(
        "swipe_versions",
        _id(),
        sa.Column("swipe_id", UUID, sa.ForeignKey("swipes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version_number", sa.Integer, nullable=False),
        sa.Column("body_text", sa.Text, nullable=False, server_default=""),
        sa.Column("body_html_sanitized", sa.Text),
        sa.Column("preheader", sa.Text),
        sa.Column("ctas_json", pg.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("flags_json", pg.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("normalized_hash", sa.String(64), nullable=False),
        sa.Column("parser_version", sa.String(50), nullable=False),
        sa.Column("confidence", sa.Float, nullable=False),
        sa.Column("section_label", sa.String(300)),
        sa.Column("created_at", TS, nullable=False, server_default=NOW),
        sa.UniqueConstraint("swipe_id", "version_number", name="uq_swipe_versions_number"),
        sa.UniqueConstraint("id", "swipe_id", name="uq_swipe_versions_id_swipe"),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_swipe_versions_confidence"),
    )
    op.create_index("ix_swipe_versions_hash", "swipe_versions", ["normalized_hash"])
    op.execute("CREATE INDEX ix_swipe_versions_body_trgm ON swipe_versions USING gin (body_text gin_trgm_ops)")
    # current_version_id must reference a version of the same swipe (composite FK).
    op.create_foreign_key(
        "fk_swipes_current_version_belongs",
        "swipes",
        "swipe_versions",
        ["current_version_id", "id"],
        ["id", "swipe_id"],
    )

    op.create_table(
        "subject_variants",
        _id(),
        sa.Column(
            "swipe_version_id", UUID, sa.ForeignKey("swipe_versions.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("subject", sa.Text, nullable=False),
        sa.Column("position", sa.Integer, nullable=False),
        sa.UniqueConstraint("swipe_version_id", "position", name="uq_subject_variants_position"),
    )
    op.execute("CREATE INDEX ix_subject_variants_trgm ON subject_variants USING gin (subject gin_trgm_ops)")

    op.create_table(
        "swipe_provenance",
        _id(),
        sa.Column(
            "swipe_version_id", UUID, sa.ForeignKey("swipe_versions.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "asset_source_id", UUID, sa.ForeignKey("asset_sources.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("page_number", sa.Integer),
        sa.Column("section_label", sa.String(300), nullable=False, server_default=""),
        sa.Column("created_at", TS, nullable=False, server_default=NOW),
        sa.UniqueConstraint(
            "swipe_version_id", "asset_source_id", "section_label", name="uq_swipe_provenance_ref"
        ),
    )
    op.create_index("ix_swipe_provenance_asset_source", "swipe_provenance", ["asset_source_id"])

    op.create_table(
        "tags",
        _id(),
        sa.Column("slug", sa.String(100), nullable=False, unique=True),
        sa.Column("label", sa.String(200), nullable=False),
    )
    op.create_table(
        "swipe_tags",
        sa.Column("swipe_id", UUID, sa.ForeignKey("swipes.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("tag_id", UUID, sa.ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
    )
    op.create_index("ix_swipe_tags_tag_id", "swipe_tags", ["tag_id"])

    op.create_table(
        "review_events",
        _id(),
        sa.Column(
            "swipe_version_id", UUID, sa.ForeignKey("swipe_versions.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("user_id", UUID, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("decision", sa.String(32), nullable=False),
        sa.Column("notes", sa.Text),
        sa.Column("created_at", TS, nullable=False, server_default=NOW),
        sa.CheckConstraint(
            "decision IN ('pending', 'needs_changes', 'approved', 'rejected', 'archived')",
            name="ck_review_events_decision",
        ),
    )
    op.create_index("ix_review_events_version", "review_events", ["swipe_version_id"])

    op.create_table(
        "jobs",
        _id(),
        sa.Column("offer_id", UUID, sa.ForeignKey("offers.id", ondelete="SET NULL")),
        sa.Column("source_id", UUID, sa.ForeignKey("sources.id", ondelete="SET NULL")),
        sa.Column("asset_source_id", UUID, sa.ForeignKey("asset_sources.id", ondelete="SET NULL")),
        sa.Column("retry_of_id", UUID, sa.ForeignKey("jobs.id", ondelete="SET NULL")),
        sa.Column("type", sa.String(32), nullable=False),
        sa.Column("state", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("progress_json", pg.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("error_summary", sa.Text),
        sa.Column("heartbeat_at", TS),
        sa.Column("created_by", UUID, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", TS, nullable=False, server_default=NOW),
        sa.Column("started_at", TS),
        sa.Column("finished_at", TS),
        sa.CheckConstraint(
            "state IN ('queued', 'running', 'completed', 'partial', 'failed', 'cancel_requested', 'cancelled')",
            name="ck_jobs_state",
        ),
        sa.CheckConstraint("type IN ('ingest_asset')", name="ck_jobs_type"),
    )
    op.create_index("ix_jobs_state", "jobs", ["state"])
    op.create_index("ix_jobs_offer_id", "jobs", ["offer_id"])

    op.create_table(
        "job_events",
        _id(),
        sa.Column("job_id", UUID, sa.ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("level", sa.String(16), nullable=False, server_default="info"),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("created_at", TS, nullable=False, server_default=NOW),
        sa.CheckConstraint("level IN ('info', 'warning', 'error')", name="ck_job_events_level"),
    )
    op.create_index("ix_job_events_job_id", "job_events", ["job_id"])

    op.create_table(
        "audit_events",
        _id(),
        sa.Column("user_id", UUID, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("entity_type", sa.String(64), nullable=False),
        sa.Column("entity_id", sa.String(64)),
        sa.Column("metadata_json", pg.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", TS, nullable=False, server_default=NOW),
    )
    op.create_index("ix_audit_events_entity", "audit_events", ["entity_type", "entity_id"])

    op.execute(
        "INSERT INTO networks (slug, name, enabled) VALUES "
        "('clickbank', 'ClickBank', true), ('digistore24', 'Digistore24', false), "
        "('buygoods', 'BuyGoods', false)"
    )


def downgrade() -> None:
    op.drop_constraint("fk_swipes_current_version_belongs", "swipes", type_="foreignkey")
    for table in (
        "audit_events",
        "job_events",
        "jobs",
        "review_events",
        "swipe_tags",
        "tags",
        "swipe_provenance",
        "subject_variants",
        "swipe_versions",
        "swipes",
        "asset_sources",
        "assets",
        "sources",
        "offer_approvals",
        "offers",
        "networks",
        "sessions",
        "users",
    ):
        op.drop_table(table)
