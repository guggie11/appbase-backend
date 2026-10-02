"""add permission metadata and role kind

Permissions were bare slugs with no description or grouping, and roles had no
way to mark the one that must never be edited.

Revision ID: d3b2c1a4e5f7
Revises: c2a1b3d4e5f6
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d3b2c1a4e5f7"
down_revision: str | None = "c2a1b3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("permissions", sa.Column("description", sa.Text(), nullable=True))
    op.add_column("permissions", sa.Column("group", sa.String(length=50), nullable=True))
    op.add_column(
        "permissions",
        sa.Column(
            "is_dangerous", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
    )
    op.add_column(
        "roles",
        sa.Column(
            "kind", sa.String(length=20), nullable=False, server_default="custom"
        ),
    )

    # Existing deployments: mark the seeded roles so the platform lock applies
    # immediately, before the seed runs.
    op.execute("UPDATE roles SET kind = 'platform' WHERE slug = 'super-admin'")
    op.execute("UPDATE roles SET kind = 'built-in' WHERE slug = 'user'")


def downgrade() -> None:
    op.drop_column("roles", "kind")
    op.drop_column("permissions", "is_dangerous")
    op.drop_column("permissions", "group")
    op.drop_column("permissions", "description")
