"""Runtime schedule config + external content sources.

Revision ID: 003
Revises: 002
Create Date: 2026-09-03
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---- schedule_config: a single editable row -------------------------
    op.create_table(
        "schedule_config",
        sa.Column("id", sa.Integer, primary_key=True),
        # ["09:00", "13:00", ...] — publish times, local to TIMEZONE
        sa.Column("slots", postgresql.JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        # max posts scheduled per active day
        sa.Column("daily_limit", sa.Integer, nullable=False, server_default="3"),
        # weekday numbers that are active, Mon=0 .. Sun=6
        sa.Column(
            "weekdays",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[0,1,2,3,4,5,6]'::jsonb"),
        ),
        # optional window the schedule is active within (null = open-ended)
        sa.Column("active_from", sa.Date, nullable=True),
        sa.Column("active_until", sa.Date, nullable=True),
        # when true, the folder/Drive poller publishes for real (not a dry run)
        sa.Column("auto_publish", sa.Boolean, nullable=False, server_default="false"),
        # when true, each scheduled post still pauses for human approval
        sa.Column("require_approval", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default="true"),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")
        ),
    )
    op.execute(
        sa.text("""
        CREATE TRIGGER set_schedule_config_updated_at
        BEFORE UPDATE ON schedule_config
        FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    """)
    )

    # ---- content_sources: where new posts are pulled from --------------
    op.create_table(
        "content_sources",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("kind", sa.String(32), nullable=False),  # gdrive | s3 | local
        sa.Column("name", sa.Text, nullable=False),
        # kind-specific location: Drive folder id, S3 prefix, local path
        sa.Column("location", sa.Text, nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default="true"),
        sa.Column("last_polled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text, nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")
        ),
    )

    # track the external id (e.g. Drive file id) so we import each file once
    op.add_column("content_uploads", sa.Column("external_id", sa.Text, nullable=True))
    op.add_column(
        "content_uploads",
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        "ix_content_uploads_external_id", "content_uploads", ["external_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_content_uploads_external_id", table_name="content_uploads")
    op.drop_column("content_uploads", "source_id")
    op.drop_column("content_uploads", "external_id")
    op.drop_table("content_sources")
    op.execute(sa.text("DROP TRIGGER IF EXISTS set_schedule_config_updated_at ON schedule_config"))
    op.drop_table("schedule_config")
