"""seed the default menu

A fresh install received no menu at all: the rows had always been created by
hand, so nobody noticed until a clean clone of v1.4.0 logged in and found a
single entry — Categories, inserted by its own migration. Permissions without
a way to reach them are not an application.

Matched on path, so deployments that already hold these rows are untouched.

Revision ID: c8a7b6d5e4f3
Revises: b7f6e5d4c3a2
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c8a7b6d5e4f3"
down_revision: str | None = "b7f6e5d4c3a2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# label, path, icon, parent path, order, required permission
ROOTS = [
    ("Dashboard", "/dashboard", "LayoutDashboard", 0, None),
    ("Profile", "/profile", "User", 1, None),
    ("Administration", "/administration", "ShieldCheck", 2, None),
]

CHILDREN = [
    ("Users", "/users", "Users", 1, "users.read"),
    ("Roles & Permissions", "/roles", "Shield", 2, "roles.read"),
    # menu.read, not the pre-v1.3 menu.manage catch-all.
    ("Menu Management", "/menus", "Menu", 3, "menu.read"),
    ("Appearance", "/appearance", "Palette", 4, "settings.read"),
    ("Settings", "/settings", "Settings", 5, "settings.read"),
    ("Audit Log", "/audit-logs", "ClipboardList", 6, "audit.read"),
]

INSERT_ROOT = sa.text(
    """
    INSERT INTO menus (id, label, icon, path, parent_id, order_index,
                       is_active, required_permission, created_at, updated_at)
    SELECT gen_random_uuid(), :label, :icon, :path, NULL, :order_index,
           true, :perm, now(), now()
    WHERE NOT EXISTS (SELECT 1 FROM menus WHERE path = :path)
    """
)

INSERT_CHILD = sa.text(
    """
    INSERT INTO menus (id, label, icon, path, parent_id, order_index,
                       is_active, required_permission, created_at, updated_at)
    SELECT gen_random_uuid(), :label, :icon, :path,
           (SELECT id FROM menus WHERE path = '/administration' LIMIT 1),
           :order_index, true, :perm, now(), now()
    WHERE NOT EXISTS (SELECT 1 FROM menus WHERE path = :path)
      AND EXISTS (SELECT 1 FROM menus WHERE path = '/administration')
    """
)


def upgrade() -> None:
    conn = op.get_bind()

    # Roots first: a child cannot reference an id that does not exist yet.
    for label, path, icon, order_index, perm in ROOTS:
        conn.execute(
            INSERT_ROOT.bindparams(
                label=label, icon=icon, path=path,
                order_index=order_index, perm=perm,
            )
        )

    for label, path, icon, order_index, perm in CHILDREN:
        conn.execute(
            INSERT_CHILD.bindparams(
                label=label, icon=icon, path=path,
                order_index=order_index, perm=perm,
            )
        )

    # An install created before v1.3 may still gate Menu Management on the
    # retired catch-all, which no longer grants read.
    conn.execute(
        sa.text(
            "UPDATE menus SET required_permission = 'menu.read' "
            "WHERE path = '/menus' AND required_permission = 'menu.manage'"
        )
    )


def downgrade() -> None:
    conn = op.get_bind()
    paths = [p for _, p, _, _, _ in ROOTS + CHILDREN]

    # Children first, or the parent delete is refused.
    conn.execute(
        sa.text("DELETE FROM menus WHERE path = ANY(:paths)").bindparams(
            paths=[p for _, p, _, _, _ in CHILDREN]
        )
    )
    conn.execute(
        sa.text("DELETE FROM menus WHERE path = ANY(:paths)").bindparams(
            paths=[p for p in paths if p not in
                   [c[1] for c in CHILDREN]]
        )
    )
