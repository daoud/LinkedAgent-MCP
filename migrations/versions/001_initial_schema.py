"""Initial schema: 6 tables, indexes, and updated_at triggers.

Revision ID: 001
Revises:
Create Date: 2026-04-30
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Trigger function that keeps updated_at current on every UPDATE
    op.execute(sa.text("""
        CREATE OR REPLACE FUNCTION update_updated_at_column()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """))

    # ---- content_uploads ------------------------------------------------
    op.create_table(
        "content_uploads",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("file_name", sa.Text, nullable=False),
        sa.Column("storage_path", sa.Text, nullable=False),
        sa.Column("storage_type", sa.String(16), nullable=False),
        sa.Column("mime_type", sa.Text),
        sa.Column("file_type", sa.String(32), nullable=False),
        sa.Column("content_hash", sa.Text, nullable=False),
        sa.Column("file_size_bytes", sa.BigInteger),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("error_message", sa.Text),
        sa.Column(
            "uploaded_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")
        ),
        sa.Column("processed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")
        ),
    )
    op.create_index("ix_content_uploads_content_hash", "content_uploads", ["content_hash"])
    op.create_index("ix_content_uploads_status", "content_uploads", ["status"])

    # ---- posts ----------------------------------------------------------
    op.create_table(
        "posts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "upload_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("content_uploads.id"),
        ),
        sa.Column("raw_content", sa.Text),
        sa.Column("transformed_text", sa.Text),
        sa.Column("post_hash", sa.Text, unique=True),
        sa.Column("scheduled_slot", sa.Time),
        sa.Column("scheduled_date", sa.Date),
        sa.Column("linkedin_post_id", sa.Text),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("retry_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text),
        sa.Column("failed_at_node", sa.Text),
        sa.Column("tokens_used", sa.Integer),
        sa.Column("cost_usd", sa.Numeric(8, 6)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")
        ),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")
        ),
    )
    op.create_index("ix_posts_upload_id", "posts", ["upload_id"])
    op.create_index("ix_posts_status", "posts", ["status"])

    # ---- approval_queue -------------------------------------------------
    op.create_table(
        "approval_queue",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "post_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("posts.id"),
            nullable=False,
        ),
        sa.Column("preview_text", sa.Text, nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True)),
        sa.Column("decision", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("decided_by", sa.Text),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")
        ),
    )
    op.create_index("ix_approval_queue_post_id", "approval_queue", ["post_id"])
    op.create_index("ix_approval_queue_decision", "approval_queue", ["decision"])

    # ---- logs -----------------------------------------------------------
    op.create_table(
        "logs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("post_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("posts.id")),
        sa.Column(
            "upload_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("content_uploads.id"),
        ),
        sa.Column("node_name", sa.Text),
        sa.Column("level", sa.String(16), nullable=False),
        sa.Column("message", sa.Text, nullable=False),
        sa.Column("metadata", postgresql.JSONB),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")
        ),
    )
    op.create_index("ix_logs_post_id", "logs", ["post_id"])
    op.create_index("ix_logs_created_at", "logs", ["created_at"])

    # ---- prompt_templates -----------------------------------------------
    op.create_table(
        "prompt_templates",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("template_text", sa.Text, nullable=False),
        sa.Column("variables", postgresql.JSONB),
        sa.Column("is_active", sa.Boolean, server_default=sa.false()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")
        ),
    )
    # Partial unique index — enforces at most one active template at a time
    op.execute(sa.text(
        "CREATE UNIQUE INDEX ix_prompt_templates_one_active "
        "ON prompt_templates (is_active) WHERE is_active = true"
    ))

    # ---- llm_costs ------------------------------------------------------
    op.create_table(
        "llm_costs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "post_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("posts.id"),
            nullable=False,
        ),
        sa.Column("model", sa.Text, nullable=False),
        sa.Column("input_tokens", sa.Integer, nullable=False),
        sa.Column("output_tokens", sa.Integer, nullable=False),
        sa.Column("cost_usd", sa.Numeric(10, 6), nullable=False),
        sa.Column(
            "recorded_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")
        ),
    )
    op.create_index("ix_llm_costs_post_id", "llm_costs", ["post_id"])

    # ---- updated_at triggers --------------------------------------------
    op.execute(sa.text("""
        CREATE TRIGGER set_content_uploads_updated_at
        BEFORE UPDATE ON content_uploads
        FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    """))
    op.execute(sa.text("""
        CREATE TRIGGER set_posts_updated_at
        BEFORE UPDATE ON posts
        FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
    """))


def downgrade() -> None:
    op.execute(sa.text("DROP TRIGGER IF EXISTS set_posts_updated_at ON posts"))
    op.execute(sa.text("DROP TRIGGER IF EXISTS set_content_uploads_updated_at ON content_uploads"))
    op.drop_table("llm_costs")
    op.drop_table("prompt_templates")
    op.drop_table("logs")
    op.drop_table("approval_queue")
    op.drop_table("posts")
    op.drop_table("content_uploads")
    op.execute(sa.text("DROP FUNCTION IF EXISTS update_updated_at_column()"))
