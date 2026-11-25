"""Phase 2 & 3 schema: scan_source job type, brand_profiles, drafts, and exports.

Revision ID: 0002_collection_and_drafts
Revises: 0001_foundation
Create Date: 2026-11-25
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql as pg

from alembic import op

revision: str = "0002_collection_and_drafts"
down_revision: str | None = "0001_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = pg.UUID(as_uuid=True)
TS = sa.DateTime(timezone=True)
NOW = sa.text("now()")


def _id() -> sa.Column:
    return sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()"))


def upgrade() -> None:
    op.drop_constraint("ck_jobs_type", "jobs", type_="check")
    op.create_check_constraint("ck_jobs_type", "jobs", "type IN ('ingest_asset', 'scan_source')")

    op.create_table(
        "brand_profiles",
        _id(),
        sa.Column("name", sa.String(200), nullable=False, unique=True),
        sa.Column("slug", sa.String(100), nullable=False, unique=True),
        sa.Column("sender_identity_ref", sa.String(300)),
        sa.Column("affiliate_settings_json", pg.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("disclosure_text", sa.Text, nullable=False, server_default=""),
        sa.Column("footer_template", sa.Text, nullable=False, server_default=""),
        sa.Column("integration_ref", sa.String(200)),
        sa.Column("created_at", TS, nullable=False, server_default=NOW),
        sa.Column("updated_at", TS, nullable=False, server_default=NOW),
    )

    op.create_table(
        "drafts",
        _id(),
        sa.Column(
            "swipe_version_id", UUID, sa.ForeignKey("swipe_versions.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column("brand_id", UUID, sa.ForeignKey("brand_profiles.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("subject", sa.Text, nullable=False),
        sa.Column("preheader", sa.Text),
        sa.Column("affiliate_url", sa.Text),
        sa.Column("body_html", sa.Text, nullable=False, server_default=""),
        sa.Column("body_text", sa.Text, nullable=False, server_default=""),
        sa.Column("status", sa.String(32), nullable=False, server_default="editing"),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("approved_version", sa.Integer),
        sa.Column("approved_at", TS),
        sa.Column("approved_by", UUID, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("review_checks_json", pg.JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("sequence_position", sa.Integer),
        sa.Column("suggested_day_offset", sa.Integer),
        sa.Column("created_by", UUID, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", TS, nullable=False, server_default=NOW),
        sa.Column("updated_at", TS, nullable=False, server_default=NOW),
        sa.CheckConstraint("status IN ('editing', 'approved', 'exported', 'archived')", name="ck_drafts_status"),
        sa.CheckConstraint("version >= 1", name="ck_drafts_version_positive"),
    )
    op.create_index("ix_drafts_brand_id", "drafts", ["brand_id"])
    op.create_index("ix_drafts_status", "drafts", ["status"])
    op.create_index("ix_drafts_swipe_version_id", "drafts", ["swipe_version_id"])

    op.create_table(
        "exports",
        _id(),
        sa.Column("draft_id", UUID, sa.ForeignKey("drafts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("draft_version", sa.Integer, nullable=False),
        sa.Column("target", sa.String(32), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False, unique=True),
        sa.Column("remote_id", sa.String(200)),
        sa.Column("remote_url", sa.Text),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("error_summary", sa.Text),
        sa.Column("created_by", UUID, sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", TS, nullable=False, server_default=NOW),
        sa.Column("updated_at", TS, nullable=False, server_default=NOW),
        sa.CheckConstraint("target IN ('listmonk', 'local_download')", name="ck_exports_target"),
        sa.CheckConstraint(
            "status IN ('pending', 'completed', 'failed', 'needs_reconciliation')", name="ck_exports_status"
        ),
    )
    op.create_index("ix_exports_draft_id", "exports", ["draft_id"])

    op.execute(
        """
        INSERT INTO brand_profiles (
            name, slug, sender_identity_ref, affiliate_settings_json,
            disclosure_text, footer_template, integration_ref
        ) VALUES (
            'MyFitterU',
            'myfitteru',
            'MyFitterU Wellness Editorial <newsletter@myfitteru.example.com>',
            '{"default_tracking_param": "tid", "allowed_affiliate_hosts": ["hop.clickbank.net"]}'::jsonb,
            'Affiliate Disclosure: This email contains affiliate links. If you purchase through these links, MyFitterU may earn a commission at no additional cost to you. Health and fitness information is for educational purposes only and is not medical advice.',
            'Sent by MyFitterU Editorial Desk | Physical mailing address on file | Unsubscribe: {{ TrackLink "unsubscribe" }}',
            'listmonk-default'
        )
        """
    )


def downgrade() -> None:
    op.drop_table("exports")
    op.drop_table("drafts")
    op.drop_table("brand_profiles")
    op.drop_constraint("ck_jobs_type", "jobs", type_="check")
    op.create_check_constraint("ck_jobs_type", "jobs", "type IN ('ingest_asset')")
