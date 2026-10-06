"""split catch-all manage permissions into distinct CRUD actions

menu/settings/notifications each shipped a single `.manage` permission, which
made it impossible to grant "view and edit, but never delete". The split adds
per-action rows; the old `.manage` rows stay so nobody loses access.

The permission guard accepts either, so existing grants keep working.

Revision ID: a6e5f4d3c2b1
Revises: f5d4e3c2a1b9
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a6e5f4d3c2b1"
down_revision: str | None = "f5d4e3c2a1b9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# slug, name, module, action, group, description, is_dangerous
NEW_PERMISSIONS = [
    ("menu.create", "Create navigation items", "menu", "create", "Navigation",
     "Add a new item to the navigation menu.", False),
    ("menu.update", "Edit navigation items", "menu", "update", "Navigation",
     "Rename, reorder, or re-point an existing item.", False),
    ("menu.delete", "Delete navigation items", "menu", "delete", "Navigation",
     "Remove an item and its children from the menu.", True),
    ("settings.create", "Add settings", "settings", "create", "Platform",
     "Define a new application setting.", False),
    ("settings.update", "Edit settings", "settings", "update", "Platform",
     "Change branding, limits, and other app settings.", False),
    ("settings.delete", "Delete settings", "settings", "delete", "Platform",
     "Remove an application setting.", True),
    ("notifications.create", "Send notifications", "notifications", "create", "Workspace",
     "Send a notification to other users.", False),
    ("notifications.update", "Edit notifications", "notifications", "update", "Workspace",
     "Mark notifications read or amend them.", False),
    ("notifications.delete", "Delete notifications", "notifications", "delete", "Workspace",
     "Remove notifications.", True),
    ("users.approve", "Approve user requests", "users", "approve", "Users",
     "Approve pending accounts and access requests.", False),
    ("settings.approve", "Approve setting changes", "settings", "approve", "Platform",
     "Sign off changes that need a second pair of eyes.", False),
]


def upgrade() -> None:
    conn = op.get_bind()

    for slug, name, module, action, group, description, dangerous in NEW_PERMISSIONS:
        exists = conn.execute(
            sa.text("SELECT 1 FROM permissions WHERE slug = :slug").bindparams(slug=slug)
        ).first()
        if exists:
            continue
        conn.execute(
            sa.text(
                """
                INSERT INTO permissions
                    (id, slug, name, module, action, "group", description,
                     is_dangerous, created_at)
                VALUES
                    (gen_random_uuid(), :slug, :name, :module, :action, :grp,
                     :description, :dangerous, now())
                """
            ).bindparams(
                slug=slug, name=name, module=module, action=action,
                grp=group, description=description, dangerous=dangerous,
            )
        )

    # Any role that already holds a module's .manage keeps the same powers via
    # the guard, but granting the new rows too makes the matrix show the truth
    # instead of three empty boxes.
    for module in ("menu", "settings", "notifications"):
        conn.execute(
            sa.text(
                """
                INSERT INTO role_permissions (role_id, permission_id)
                SELECT rp.role_id, p_new.id
                FROM role_permissions rp
                JOIN permissions p_old
                  ON p_old.id = rp.permission_id AND p_old.slug = :manage
                JOIN permissions p_new
                  ON p_new.module = :module AND p_new.action IN ('create','update','delete')
                WHERE NOT EXISTS (
                    SELECT 1 FROM role_permissions x
                    WHERE x.role_id = rp.role_id AND x.permission_id = p_new.id
                )
                """
            ).bindparams(manage=f"{module}.manage", module=module)
        )

    # Super Admin must hold everything, including the rows just added.
    conn.execute(
        sa.text(
            """
            INSERT INTO role_permissions (role_id, permission_id)
            SELECT r.id, p.id
            FROM roles r
            CROSS JOIN permissions p
            WHERE r.slug = 'super-admin'
              AND NOT EXISTS (
                  SELECT 1 FROM role_permissions x
                  WHERE x.role_id = r.id AND x.permission_id = p.id
              )
            """
        )
    )


def downgrade() -> None:
    slugs = tuple(p[0] for p in NEW_PERMISSIONS)
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "DELETE FROM role_permissions WHERE permission_id IN "
            "(SELECT id FROM permissions WHERE slug = ANY(:slugs))"
        ).bindparams(slugs=list(slugs))
    )
    conn.execute(
        sa.text("DELETE FROM permissions WHERE slug = ANY(:slugs)").bindparams(
            slugs=list(slugs)
        )
    )
