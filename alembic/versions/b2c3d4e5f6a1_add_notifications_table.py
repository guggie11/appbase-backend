"""add_notifications_table

Revision ID: b2c3d4e5f6a1
Revises: a1b2c3d4e5f6
Create Date: 2026-09-29 12:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b2c3d4e5f6a1"
down_revision: str | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "notifications",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            sa.Uuid(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("message", sa.Text(), nullable=True),
        sa.Column("type", sa.String(20), nullable=False, server_default="info"),
        sa.Column("is_read", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("link", sa.String(255), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=False),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "idx_notifications_user_id_is_read",
        "notifications",
        ["user_id", "is_read"],
    )
    op.create_index(
        "idx_notifications_created_at",
        "notifications",
        ["created_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_notifications_created_at", table_name="notifications")
    op.drop_index("idx_notifications_user_id_is_read", table_name="notifications")
    op.drop_table("notifications")
