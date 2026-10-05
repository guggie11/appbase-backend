"""add required_permission to menus

Menus were bound to roles, which meant every new role had to be remembered
and added to every relevant menu. Binding to a permission lets new roles
inherit visibility automatically.

Revision ID: e4c3d2b1f6a8
Revises: d3b2c1a4e5f7
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e4c3d2b1f6a8"
down_revision: str | None = "d3b2c1a4e5f7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "menus",
        sa.Column("required_permission", sa.String(length=100), nullable=True),
    )

    # Wire the seeded admin menus to the rights they actually need, so the
    # feature is live on upgrade instead of waiting for a manual pass.
    # Menus left NULL stay public, which is the previous behaviour.
    for path, slug in [
        ("/users", "users.read"),
        ("/roles", "roles.read"),
        ("/menus", "menu.manage"),
        ("/settings", "settings.read"),
        ("/audit-logs", "audit.read"),
    ]:
        op.execute(
            sa.text(
                "UPDATE menus SET required_permission = :slug WHERE path = :path"
            ).bindparams(slug=slug, path=path)
        )


def downgrade() -> None:
    op.drop_column("menus", "required_permission")
