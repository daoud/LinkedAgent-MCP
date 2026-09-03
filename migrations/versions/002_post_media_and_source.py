"""Add media + source columns to posts (for the dashboard compose + image flow).

Revision ID: 002
Revises: 001
Create Date: 2026-09-03
"""

import sqlalchemy as sa
from alembic import op

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("posts", sa.Column("image_path", sa.Text(), nullable=True))
    op.add_column("posts", sa.Column("image_asset_urn", sa.Text(), nullable=True))
    # How the post was created: "watcher" | "api" | "compose" | "compose-text"
    op.add_column(
        "posts",
        sa.Column("source", sa.String(32), nullable=False, server_default="api"),
    )
    op.add_column("posts", sa.Column("tone", sa.Text(), nullable=True))
    op.add_column("posts", sa.Column("title", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("posts", "title")
    op.drop_column("posts", "tone")
    op.drop_column("posts", "source")
    op.drop_column("posts", "image_asset_urn")
    op.drop_column("posts", "image_path")
