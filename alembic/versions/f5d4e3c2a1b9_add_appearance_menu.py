"""add the Appearance menu entry

The Admin Console gained an Appearance tab separate from the technical
Settings page. Every tab must have a matching sidebar entry, otherwise the
two navigation systems disagree about what exists.

Revision ID: f5d4e3c2a1b9
Revises: e4c3d2b1f6a8
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f5d4e3c2a1b9"
down_revision: str | None = "e4c3d2b1f6a8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    conn = op.get_bind()

    existing = conn.execute(
        sa.text("SELECT id FROM menus WHERE path = '/appearance'")
    ).first()
    if existing:
        return

    # Sit next to Settings, under the same parent, just above it.
    settings = conn.execute(
        sa.text("SELECT parent_id, order_index FROM menus WHERE path = '/settings'")
    ).first()
    if settings is None:
        # No seeded admin menu on this deployment; nothing to attach to.
        return

    parent_id, order_index = settings

    conn.execute(
        sa.text(
            """
            INSERT INTO menus (id, label, icon, path, parent_id, order_index,
                               is_active, required_permission, created_at, updated_at)
            VALUES (gen_random_uuid(), 'Appearance', 'Palette', '/appearance',
                    :parent_id, :order_index, true, 'settings.read', now(), now())
            """
        ).bindparams(parent_id=parent_id, order_index=max(0, order_index - 1))
    )


def downgrade() -> None:
    op.execute("DELETE FROM menus WHERE path = '/appearance'")
