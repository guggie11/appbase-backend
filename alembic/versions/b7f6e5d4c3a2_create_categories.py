"""create category groups and categories

Generic reference data other features point at. Nothing is seeded: the
vocabulary belongs to the project using the template, not to the template.

Revision ID: b7f6e5d4c3a2
Revises: a6e5f4d3c2b1
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b7f6e5d4c3a2"
down_revision: str | None = "a6e5f4d3c2b1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# slug, name, module, action, group, description, is_dangerous
PERMISSIONS = [
    ("category.read", "View categories", "category", "read", "Reference Data",
     "See category groups and their items.", False),
    ("category.create", "Create categories", "category", "create", "Reference Data",
     "Add a category group or an item inside one.", False),
    ("category.update", "Edit categories", "category", "update", "Reference Data",
     "Rename, reorder, deprecate, or restore an item.", False),
    ("category.delete", "Delete categories", "category", "delete", "Reference Data",
     "Remove a category that nothing references.", True),
]


def upgrade() -> None:
    op.create_table(
        "category_groups",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(100), nullable=False, unique=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.String(300), nullable=True),
        sa.Column("icon", sa.String(100), nullable=True),
        sa.Column("color", sa.String(20), nullable=True),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=False),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=False),
                  server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_category_groups_code", "category_groups", ["code"])

    op.create_table(
        "categories",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("group_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("parent_id", sa.Uuid(as_uuid=True), nullable=True),
        sa.Column("code", sa.String(100), nullable=False),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("description", sa.String(300), nullable=True),
        sa.Column("icon", sa.String(100), nullable=True),
        sa.Column("color", sa.String(20), nullable=True),
        sa.Column("order_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("deprecated_reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=False),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=False),
                  server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["group_id"], ["category_groups.id"], ondelete="CASCADE"
        ),
        # RESTRICT, not CASCADE: deleting a parent must not silently take its
        # children — and their references — with it.
        sa.ForeignKeyConstraint(
            ["parent_id"], ["categories.id"], ondelete="RESTRICT"
        ),
        # "draft" may exist in several groups, but only once per group.
        sa.UniqueConstraint("group_id", "code", name="uq_category_group_code"),
    )
    op.create_index("ix_categories_group_id", "categories", ["group_id"])
    op.create_index("ix_categories_parent_id", "categories", ["parent_id"])
    op.create_index("ix_categories_code", "categories", ["code"])
    op.create_index("ix_categories_status", "categories", ["status"])

    conn = op.get_bind()

    for slug, name, module, action, group, description, dangerous in PERMISSIONS:
        conn.execute(
            sa.text(
                """
                INSERT INTO permissions
                    (id, slug, name, module, action, "group", description,
                     is_dangerous, created_at)
                SELECT gen_random_uuid(), :slug, :name, :module, :action,
                       :grp, :description, :dangerous, now()
                WHERE NOT EXISTS (SELECT 1 FROM permissions WHERE slug = :slug)
                """
            ).bindparams(
                slug=slug, name=name, module=module, action=action,
                grp=group, description=description, dangerous=dangerous,
            )
        )

    conn.execute(
        sa.text(
            """
            INSERT INTO role_permissions (role_id, permission_id)
            SELECT r.id, p.id
            FROM roles r
            CROSS JOIN permissions p
            WHERE r.slug = 'super-admin'
              AND p.slug = ANY(:slugs)
              AND NOT EXISTS (
                  SELECT 1 FROM role_permissions x
                  WHERE x.role_id = r.id AND x.permission_id = p.id
              )
            """
        ).bindparams(slugs=[p[0] for p in PERMISSIONS])
    )

    conn.execute(
        sa.text(
            """
            INSERT INTO menus
                (id, label, icon, path, order_index, is_active,
                 required_permission, created_at, updated_at)
            SELECT gen_random_uuid(), :label, :icon, :path,
                   COALESCE((SELECT MAX(order_index) + 1 FROM menus), 0),
                   true, :perm, now(), now()
            WHERE NOT EXISTS (SELECT 1 FROM menus WHERE path = :path)
            """
        ).bindparams(
            label="Categories", icon="Tags", path="/categories",
            perm="category.read",
        )
    )


def downgrade() -> None:
    conn = op.get_bind()
    slugs = [p[0] for p in PERMISSIONS]

    conn.execute(
        sa.text("DELETE FROM menus WHERE path = :path").bindparams(path="/categories")
    )
    conn.execute(
        sa.text(
            "DELETE FROM role_permissions WHERE permission_id IN "
            "(SELECT id FROM permissions WHERE slug = ANY(:slugs))"
        ).bindparams(slugs=slugs)
    )
    conn.execute(
        sa.text("DELETE FROM permissions WHERE slug = ANY(:slugs)").bindparams(
            slugs=slugs
        )
    )
    op.drop_table("categories")
    op.drop_table("category_groups")
