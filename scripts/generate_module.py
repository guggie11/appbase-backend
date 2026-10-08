#!/usr/bin/env python
"""Generate a complete CRUD module.

Every project built on Appbase will add CRUD modules. Copying the `roles`
module and renaming by hand is mechanical and easy to get wrong — a forgotten
router registration, a missing permission, or a `/{id}` route declared before
its siblings so it swallows them.

    uv run python scripts/generate_module.py Product \
        --fields "name:str,price:int,is_active:bool"

Writes the module files, registers the router, extends the permission
catalogue, and creates a migration that adds the table, the four permissions,
and a menu entry. Pass --dry-run to see the plan without touching anything.
"""
from __future__ import annotations

import argparse
import re
import sys
import uuid
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "app"

#: Field types a module may declare, mapped to their SQLAlchemy column.
#: Refusing an unknown type beats emitting code that will not import.
FIELD_TYPES: dict[str, str] = {
    "str": 'mapped_column(String(255), nullable={nullable})',
    "text": 'mapped_column(Text, nullable={nullable})',
    "int": 'mapped_column(Integer, nullable={nullable})',
    "float": 'mapped_column(Float, nullable={nullable})',
    "bool": 'mapped_column(Boolean, default=False, nullable=False)',
    "datetime": 'mapped_column(DateTime(timezone=False), nullable={nullable})',
    "uuid": 'mapped_column(Uuid(as_uuid=True), nullable={nullable})',
}

#: Columns the base model already provides.
RESERVED_FIELDS = {"id", "created_at", "updated_at"}

#: SQLAlchemy imports needed per type, so the generated model imports
#: exactly what it uses and no more.
TYPE_IMPORTS = {
    "str": "String",
    "text": "Text",
    "int": "Integer",
    "float": "Float",
    "bool": "Boolean",
    "datetime": "DateTime",
    "uuid": "Uuid",
}

PY_TO_ANNOTATION = {
    "str": "str",
    "text": "str",
    "int": "int",
    "float": "float",
    "bool": "bool",
    "datetime": "datetime",
    "uuid": "uuid.UUID",
}


@dataclass
class Field:
    name: str
    py_type: str
    nullable: bool = True

    @property
    def column(self) -> str:
        return FIELD_TYPES[self.py_type].format(nullable=self.nullable)

    @property
    def annotation(self) -> str:
        base = PY_TO_ANNOTATION[self.py_type]
        if self.py_type == "bool":
            return base
        return f"{base} | None" if self.nullable else base

    @property
    def schema_type(self) -> str:
        base = PY_TO_ANNOTATION[self.py_type]
        if self.py_type == "bool":
            return "bool = False"
        return f"{base} | None = None"


def _snake(name: str) -> str:
    """PurchaseOrder -> purchase_order."""
    s = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", name)
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", s)
    return s.lower().strip("_")


def _pluralise(word: str) -> str:
    """Enough English to avoid "categorys" reaching the database."""
    if word.endswith("y") and not word.endswith(("ay", "ey", "iy", "oy", "uy")):
        return word[:-1] + "ies"
    if word.endswith(("s", "x", "z", "ch", "sh")):
        return word + "es"
    return word + "s"


@dataclass
class ModuleSpec:
    name: str
    fields: list[Field] = dataclass_field(default_factory=list)

    @property
    def class_name(self) -> str:
        return self.name[0].upper() + self.name[1:]

    @property
    def singular(self) -> str:
        return _snake(self.name)

    @property
    def plural(self) -> str:
        parts = self.singular.rsplit("_", 1)
        parts[-1] = _pluralise(parts[-1])
        return "_".join(parts)

    @property
    def table(self) -> str:
        return self.plural

    @property
    def route_prefix(self) -> str:
        return "/" + self.plural.replace("_", "-")

    @property
    def label(self) -> str:
        return re.sub(r"(?<!^)(?=[A-Z])", " ", self.class_name)

    def permission(self, action: str) -> str:
        return f"{self.singular}.{action}"


def parse_fields(raw: str) -> list[Field]:
    """Parse "name:str,price:int" into fields.

    A bare name defaults to str — the common case for a first column.
    """
    fields: list[Field] = []
    for chunk in (c.strip() for c in raw.split(",")):
        if not chunk:
            continue
        name, _, py_type = chunk.partition(":")
        name = name.strip()
        py_type = (py_type or "str").strip()

        if name in RESERVED_FIELDS:
            raise ValueError(
                f"'{name}' is reserved — the base model already provides it"
            )
        if not re.fullmatch(r"[a-z][a-z0-9_]*", name):
            raise ValueError(
                f"invalid field name '{name}' — use lower_snake_case"
            )
        if py_type not in FIELD_TYPES:
            raise ValueError(
                f"unknown field type '{py_type}' for '{name}'; "
                f"choose from: {', '.join(sorted(FIELD_TYPES))}"
            )
        fields.append(Field(name=name, py_type=py_type))
    return fields


# ---------------------------------------------------------------------------
# Renderers
# ---------------------------------------------------------------------------


def render_model(spec: ModuleSpec) -> str:
    needed = sorted({TYPE_IMPORTS[f.py_type] for f in spec.fields} | {"Uuid"})
    columns = "\n".join(
        f"    {f.name}: Mapped[{f.annotation}] = {f.column}" for f in spec.fields
    )
    return f'''"""{spec.class_name} model."""
import uuid
{"from datetime import datetime" if any(f.py_type == "datetime" for f in spec.fields) else ""}
from sqlalchemy import {", ".join(needed)}
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class {spec.class_name}(Base, TimestampMixin):
    __tablename__ = "{spec.table}"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
{columns}
'''


def render_schema(spec: ModuleSpec) -> str:
    response_fields = "\n".join(
        f"    {f.name}: {f.schema_type}" for f in spec.fields
    )
    # Create keeps bools defaulted and everything else optional-safe.
    create_fields = "\n".join(
        f"    {f.name}: {f.schema_type}" for f in spec.fields
    )
    # Update must make every field optional, otherwise callers are forced to
    # resend the whole object to change one column.
    update_fields = "\n".join(
        f"    {f.name}: {PY_TO_ANNOTATION[f.py_type]} | None = None"
        for f in spec.fields
    )
    return f'''"""{spec.class_name} schemas."""
import uuid
from datetime import datetime

from pydantic import BaseModel


class {spec.class_name}Response(BaseModel):
    id: uuid.UUID
{response_fields}
    created_at: datetime
    updated_at: datetime

    model_config = {{"from_attributes": True}}


class Create{spec.class_name}Request(BaseModel):
{create_fields}


class Update{spec.class_name}Request(BaseModel):
{update_fields}
'''


def render_service(spec: ModuleSpec) -> str:
    cls = spec.class_name
    assignments = "\n".join(
        f"    if payload.{f.name} is not None:\n"
        f"        row.{f.name} = payload.{f.name}"
        for f in spec.fields
    )
    create_args = ",\n        ".join(f"{f.name}=payload.{f.name}" for f in spec.fields)
    return f'''"""{cls} business logic."""
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.models.{spec.singular} import {cls}
from app.schemas.{spec.singular} import Create{cls}Request, Update{cls}Request


async def list_{spec.plural}(
    db: AsyncSession,
    page: int = 1,
    per_page: int = 10,
) -> tuple[list[{cls}], int]:
    query = select({cls}).order_by({cls}.created_at.desc())
    # A total taken from the page itself would be a guess.
    total = (
        await db.execute(select(func.count()).select_from({cls}))
    ).scalar_one()

    rows = (
        await db.execute(query.offset((page - 1) * per_page).limit(per_page))
    ).scalars().all()
    return list(rows), total


async def get_{spec.singular}(db: AsyncSession, {spec.singular}_id: uuid.UUID) -> {cls}:
    row = (
        await db.execute(select({cls}).where({cls}.id == {spec.singular}_id))
    ).scalar_one_or_none()
    if row is None:
        raise AppException(
            code="NOT_FOUND", message="{spec.label} tidak ditemukan", status_code=404
        )
    return row


async def create_{spec.singular}(db: AsyncSession, payload: Create{cls}Request) -> {cls}:
    row = {cls}(
        id=uuid.uuid4(),
        {create_args},
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def update_{spec.singular}(
    db: AsyncSession, {spec.singular}_id: uuid.UUID, payload: Update{cls}Request
) -> {cls}:
    row = await get_{spec.singular}(db, {spec.singular}_id)
{assignments}
    await db.commit()
    await db.refresh(row)
    return row


async def delete_{spec.singular}(db: AsyncSession, {spec.singular}_id: uuid.UUID) -> None:
    row = await get_{spec.singular}(db, {spec.singular}_id)
    await db.delete(row)
    await db.commit()
'''


def render_router(spec: ModuleSpec) -> str:
    cls = spec.class_name
    sing, plur = spec.singular, spec.plural
    # Static routes are emitted before "/{id}". Declared the other way round,
    # the catch-all swallows its siblings — this has bitten this codebase
    # twice already (/roles/{id}/duplicate, /users/bulk).
    return f'''"""{cls} API router."""
import contextlib
import uuid

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_permission
from app.api.v1.{sing} import service
from app.core.audit import log_action
from app.schemas.common import PaginatedResponse, SuccessResponse
from app.schemas.{sing} import (
    Create{cls}Request,
    {cls}Response,
    Update{cls}Request,
)

router = APIRouter(prefix="{spec.route_prefix}", tags=["{plur}"])


@router.get("/", response_model=PaginatedResponse[{cls}Response])
async def list_{plur}(
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=10, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("{spec.permission("read")}")),
):
    rows, total = await service.list_{plur}(db, page=page, per_page=per_page)
    return PaginatedResponse(data=rows, total=total, page=page, per_page=per_page)


@router.post("/", response_model=SuccessResponse[{cls}Response], status_code=201)
async def create_{sing}(
    payload: Create{cls}Request,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("{spec.permission("create")}")),
):
    row = await service.create_{sing}(db, payload)
    with contextlib.suppress(Exception):
        await log_action(
            db, action="{sing}.create", actor_id=current_user.get("sub"),
            resource_id=str(row.id), request=request,
        )
    return SuccessResponse(data=row)


@router.get("/{{{sing}_id}}", response_model=SuccessResponse[{cls}Response])
async def get_{sing}(
    {sing}_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_permission("{spec.permission("read")}")),
):
    return SuccessResponse(data=await service.get_{sing}(db, {sing}_id))


@router.put("/{{{sing}_id}}", response_model=SuccessResponse[{cls}Response])
async def update_{sing}(
    {sing}_id: uuid.UUID,
    payload: Update{cls}Request,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("{spec.permission("update")}")),
):
    row = await service.update_{sing}(db, {sing}_id, payload)
    with contextlib.suppress(Exception):
        await log_action(
            db, action="{sing}.update", actor_id=current_user.get("sub"),
            resource_id=str({sing}_id), request=request,
        )
    return SuccessResponse(data=row)


@router.delete("/{{{sing}_id}}", response_model=SuccessResponse[dict])
async def delete_{sing}(
    {sing}_id: uuid.UUID,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(require_permission("{spec.permission("delete")}")),
):
    await service.delete_{sing}(db, {sing}_id)
    with contextlib.suppress(Exception):
        await log_action(
            db, action="{sing}.delete", actor_id=current_user.get("sub"),
            resource_id=str({sing}_id), request=request,
        )
    return SuccessResponse(data={{"deleted": True}})
'''


#: SQLAlchemy column constructors for the migration body.
MIGRATION_COLUMNS = {
    "str": 'sa.String(255), nullable=True',
    "text": 'sa.Text(), nullable=True',
    "int": 'sa.Integer(), nullable=True',
    "float": 'sa.Float(), nullable=True',
    "bool": 'sa.Boolean(), nullable=False, server_default=sa.false()',
    "datetime": 'sa.DateTime(timezone=False), nullable=True',
    "uuid": 'sa.Uuid(as_uuid=True), nullable=True',
}

PERMISSION_LABELS = {
    "read": ("View {label}", "See the {lower} list and open individual records."),
    "create": ("Create {label}", "Add a new {lower} record."),
    "update": ("Edit {label}", "Change an existing {lower} record."),
    "delete": ("Delete {label}", "Permanently remove a {lower} record."),
}


def render_migration(spec: ModuleSpec, down_revision: str, revision: str | None = None) -> str:
    revision = revision or uuid.uuid4().hex[:12]
    cols = "\n".join(
        f'        sa.Column("{f.name}", {MIGRATION_COLUMNS[f.py_type]}),'
        for f in spec.fields
    )
    perm_rows = ",\n".join(
        '    ("{slug}", "{name}", "{module}", "{action}", "{group}", "{desc}", {danger})'.format(
            slug=spec.permission(action),
            name=PERMISSION_LABELS[action][0].format(label=spec.label),
            module=spec.singular,
            action=action,
            group=spec.label,
            desc=PERMISSION_LABELS[action][1].format(lower=spec.label.lower()),
            danger="True" if action == "delete" else "False",
        )
        for action in ("read", "create", "update", "delete")
    )
    return f'''"""create {spec.table}

Adds the table, its four permissions, and a menu entry. Without the menu
entry the module exists but nobody can navigate to it; without the
permissions every endpoint refuses everyone.

Revision ID: {revision}
Revises: {down_revision}
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "{revision}"
down_revision: str | None = "{down_revision}"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# slug, name, module, action, group, description, is_dangerous
PERMISSIONS = [
{perm_rows},
]


def upgrade() -> None:
    op.create_table(
        "{spec.table}",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
{cols}
        sa.Column(
            "created_at", sa.DateTime(timezone=False),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=False),
            server_default=sa.func.now(), nullable=False,
        ),
    )

    conn = op.get_bind()

    # Idempotent: a half-applied migration must not explode on re-run.
    for slug, name, module, action, group, description, dangerous in PERMISSIONS:
        conn.execute(
            sa.text(
                """
                INSERT INTO permissions
                    (id, slug, name, module, action, "group", description,
                     is_dangerous, created_at)
                SELECT gen_random_uuid(), :slug, :name, :module, :action,
                       :grp, :description, :dangerous, now()
                WHERE NOT EXISTS (
                    SELECT 1 FROM permissions WHERE slug = :slug
                )
                """
            ).bindparams(
                slug=slug, name=name, module=module, action=action,
                grp=group, description=description, dangerous=dangerous,
            )
        )

    # Super Admin holds everything, including what was just added.
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

    # Bound to the read permission, so any role granted it sees the entry.
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
            label="{spec.label}", icon="Box", path="{spec.route_prefix}",
            perm="{spec.permission("read")}",
        )
    )


def downgrade() -> None:
    conn = op.get_bind()
    slugs = [p[0] for p in PERMISSIONS]

    conn.execute(
        sa.text("DELETE FROM menus WHERE path = :path").bindparams(
            path="{spec.route_prefix}"
        )
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
    op.drop_table("{spec.table}")
'''


def render_tests(spec: ModuleSpec) -> str:
    cls, sing = spec.class_name, spec.singular
    prefix = f"/api/v1{spec.route_prefix}"
    # Build a literal payload instead of nesting f-strings.
    literals = {"str": '"sample"', "text": '"sample"', "int": "1",
                "float": "1.0", "bool": "True", "datetime": "None", "uuid": "None"}
    payload = ", ".join(f'"{f.name}": {literals[f.py_type]}' for f in spec.fields)

    return f'''"""{cls} endpoints.

Generated by scripts/generate_module.py. The permission checks below are the
point: without them an endpoint is open to any logged-in user.
"""
import pytest
from sqlalchemy import select

from app.core.seed import seed_permissions, seed_roles
from app.models.rbac import Permission, RolePermission

PASSWORD = "Str0ng@Pass1"
PREFIX = "{prefix}"
PAYLOAD = {{{payload}}}


async def _actor(async_client, test_db, create_test_user, create_role,
                 assign_role, email, slugs):
    """A user holding exactly the given permission slugs."""
    await seed_permissions(test_db)
    await seed_roles(test_db)
    role = await create_role(f"{sing}-{{email.split('@')[0]}}")
    for slug in slugs:
        perm = (
            await test_db.execute(select(Permission).where(Permission.slug == slug))
        ).scalar_one()
        test_db.add(RolePermission(role_id=role.id, permission_id=perm.id))
    await test_db.commit()

    user = await create_test_user(email=email, password=PASSWORD)
    await assign_role(user, role)
    res = await async_client.post(
        "/api/v1/auth/login", json={{"email": email, "password": PASSWORD}}
    )
    assert res.status_code == 200, res.text
    return {{
        "Authorization": f"Bearer {{res.json()['data']['access_token']}}",
        # Write requests are rejected without it.
        "X-CSRF-Token": res.cookies.get("csrf_token", ""),
    }}


@pytest.mark.asyncio
async def test_create_then_read_back(
    async_client, test_db, create_test_user, create_role, assign_role
):
    headers = await _actor(
        async_client, test_db, create_test_user, create_role, assign_role,
        "{sing}-writer@example.com",
        ["{spec.permission("read")}", "{spec.permission("create")}"],
    )

    created = await async_client.post(PREFIX + "/", json=PAYLOAD, headers=headers)
    assert created.status_code == 201, created.text
    row_id = created.json()["data"]["id"]

    fetched = await async_client.get(f"{{PREFIX}}/{{row_id}}", headers=headers)
    assert fetched.status_code == 200, fetched.text


@pytest.mark.asyncio
async def test_list_is_paginated(
    async_client, test_db, create_test_user, create_role, assign_role
):
    headers = await _actor(
        async_client, test_db, create_test_user, create_role, assign_role,
        "{sing}-reader@example.com", ["{spec.permission("read")}"],
    )
    res = await async_client.get(PREFIX + "/?page=1&per_page=5", headers=headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert "total" in body and "data" in body


@pytest.mark.asyncio
async def test_update_changes_the_row(
    async_client, test_db, create_test_user, create_role, assign_role
):
    headers = await _actor(
        async_client, test_db, create_test_user, create_role, assign_role,
        "{sing}-editor@example.com",
        ["{spec.permission("read")}", "{spec.permission("create")}",
         "{spec.permission("update")}"],
    )
    created = await async_client.post(PREFIX + "/", json=PAYLOAD, headers=headers)
    row_id = created.json()["data"]["id"]

    res = await async_client.put(
        f"{{PREFIX}}/{{row_id}}", json=PAYLOAD, headers=headers
    )
    assert res.status_code == 200, res.text


@pytest.mark.asyncio
async def test_delete_removes_the_row(
    async_client, test_db, create_test_user, create_role, assign_role
):
    headers = await _actor(
        async_client, test_db, create_test_user, create_role, assign_role,
        "{sing}-remover@example.com",
        ["{spec.permission("read")}", "{spec.permission("create")}",
         "{spec.permission("delete")}"],
    )
    created = await async_client.post(PREFIX + "/", json=PAYLOAD, headers=headers)
    row_id = created.json()["data"]["id"]

    res = await async_client.delete(f"{{PREFIX}}/{{row_id}}", headers=headers)
    assert res.status_code == 200, res.text

    gone = await async_client.get(f"{{PREFIX}}/{{row_id}}", headers=headers)
    assert gone.status_code == 404


@pytest.mark.asyncio
async def test_read_only_user_cannot_create(
    async_client, test_db, create_test_user, create_role, assign_role
):
    """The guard must actually refuse, not merely be present."""
    headers = await _actor(
        async_client, test_db, create_test_user, create_role, assign_role,
        "{sing}-viewer@example.com", ["{spec.permission("read")}"],
    )
    res = await async_client.post(PREFIX + "/", json=PAYLOAD, headers=headers)
    assert res.status_code == 403, res.status_code


@pytest.mark.asyncio
async def test_editor_cannot_delete(
    async_client, test_db, create_test_user, create_role, assign_role
):
    """View and edit without delete — the reason actions are separate."""
    headers = await _actor(
        async_client, test_db, create_test_user, create_role, assign_role,
        "{sing}-noDelete@example.com",
        ["{spec.permission("read")}", "{spec.permission("create")}",
         "{spec.permission("update")}"],
    )
    created = await async_client.post(PREFIX + "/", json=PAYLOAD, headers=headers)
    row_id = created.json()["data"]["id"]

    res = await async_client.delete(f"{{PREFIX}}/{{row_id}}", headers=headers)
    assert res.status_code == 403, res.status_code
'''


# ---------------------------------------------------------------------------
# Writing to the repository
# ---------------------------------------------------------------------------


def _latest_revision() -> str:
    """Head of the migration chain, so the new file links onto the end."""
    versions = ROOT / "alembic" / "versions"
    revisions: dict[str, str | None] = {}
    for path in versions.glob("*.py"):
        text = path.read_text()
        rev = re.search(r'^revision: str = "([^"]+)"', text, re.M)
        down = re.search(r'^down_revision: str \| None = (?:"([^"]+)"|None)', text, re.M)
        if rev:
            revisions[rev.group(1)] = down.group(1) if down else None

    if not revisions:
        raise RuntimeError("no migrations found — run alembic at least once")

    parents = {d for d in revisions.values() if d}
    heads = [r for r in revisions if r not in parents]
    if len(heads) != 1:
        raise RuntimeError(
            f"expected one migration head, found {len(heads)}: {heads}"
        )
    return heads[0]


def register_router(spec: ModuleSpec, dry_run: bool = False) -> str:
    """Add the module to the v1 router. Unregistered, it simply does not exist."""
    path = SRC / "api" / "v1" / "router.py"
    text = path.read_text()
    import_line = f"from app.api.v1.{spec.singular}.router import router as {spec.plural}_router"
    include_line = f"router.include_router({spec.plural}_router)"

    if import_line in text:
        return "already registered"

    # Insert in alphabetical order: appending at the end breaks ruff's
    # import sorting (I001) and the project fails CI on its first commit.
    imports = [ln for ln in text.splitlines() if ln.startswith("from app.api.v1.")]
    after = [ln for ln in imports if ln > import_line]
    anchor, joined = (after[0], import_line + "\n" + after[0]) if after else (
        imports[-1], imports[-1] + "\n" + import_line
    )
    text = text.replace(anchor, joined, 1)

    includes = [ln for ln in text.splitlines() if ln.startswith("router.include_router(")]
    text = text.replace(includes[-1], includes[-1] + "\n" + include_line, 1)

    if not dry_run:
        path.write_text(text)
    return "router registered"


def register_permissions(spec: ModuleSpec, dry_run: bool = False) -> str:
    """Extend the seed catalogue so a fresh install gets these permissions too.

    The migration covers existing databases; the seed covers new ones. Both
    are needed, and missing either leaves one kind of install broken.
    """
    path = SRC / "core" / "seed.py"
    text = path.read_text()
    if f'"{spec.permission("read")}"' in text:
        return "already in the catalogue"

    rows = []
    for action in ("read", "create", "update", "delete"):
        name, desc = PERMISSION_LABELS[action]
        rows.append(
            f'    {{"slug": "{spec.permission(action)}", '
            f'"name": "{name.format(label=spec.label)}", '
            f'"module": "{spec.singular}", "action": "{action}",\n'
            f'     "group": "{spec.label}", '
            f'"description": "{desc.format(lower=spec.label.lower())}"'
            + (', "is_dangerous": True' if action == "delete" else "")
            + "},"
        )
    block = f"\n    # ── {spec.label} (generated) ──\n" + "\n".join(rows) + "\n]"

    marker = "\n]\n\n\n# Columns of the Roles & Permissions matrix"
    if marker not in text:
        raise RuntimeError("could not find the end of SEED_PERMISSIONS in seed.py")
    text = text.replace(marker, block + "\n\n\n# Columns of the Roles & Permissions matrix", 1)

    if not dry_run:
        path.write_text(text)
    return "permissions added to the catalogue"


def register_test_model(spec: ModuleSpec, dry_run: bool = False) -> str:
    """Make the test database create the new table.

    conftest imports each model explicitly to populate the metadata, so a
    module left out of that list has no table and every one of its tests
    fails on "no such table".
    """
    path = ROOT / "tests" / "conftest.py"
    text = path.read_text()
    line = f"    import app.models.{spec.singular}  # noqa: F401"
    if line in text:
        return "already imported"

    imports = [
        ln for ln in text.splitlines()
        if ln.strip().startswith("import app.models.")
    ]
    if not imports:
        return "could not find the model imports — add it by hand"

    # Alphabetical, for the same ruff reason as the router.
    after = [ln for ln in imports if ln > line]
    anchor, joined = (after[0], line + "\n" + after[0]) if after else (
        imports[-1], imports[-1] + "\n" + line
    )
    text = text.replace(anchor, joined, 1)
    if not dry_run:
        path.write_text(text)
    return "model imported for table creation"


def generate(spec: ModuleSpec, dry_run: bool = False) -> list[str]:
    """Write every file. Returns a human-readable summary."""
    module_dir = SRC / "api" / "v1" / spec.singular
    down_revision = _latest_revision()
    revision = uuid.uuid4().hex[:12]

    targets = {
        SRC / "models" / f"{spec.singular}.py": render_model(spec),
        SRC / "schemas" / f"{spec.singular}.py": render_schema(spec),
        module_dir / "__init__.py": f'"""{spec.class_name} module."""\n',
        module_dir / "service.py": render_service(spec),
        module_dir / "router.py": render_router(spec),
        ROOT / "alembic" / "versions" / f"{revision}_create_{spec.table}.py":
            render_migration(spec, down_revision=down_revision, revision=revision),
        ROOT / "tests" / f"test_{spec.plural}.py": render_tests(spec),
    }

    # Refuse rather than overwrite: silently replacing someone's module is
    # the worst possible outcome of a generator.
    clashes = [p for p in targets if p.exists() and p.name != "__init__.py"]
    if clashes:
        raise FileExistsError(
            "refusing to overwrite:\n  "
            + "\n  ".join(str(p.relative_to(ROOT)) for p in clashes)
        )

    summary = []
    for path, content in targets.items():
        if not dry_run:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        summary.append(f"  + {path.relative_to(ROOT)}")

    summary.append(f"  ~ src/app/api/v1/router.py — {register_router(spec, dry_run)}")
    summary.append(f"  ~ src/app/core/seed.py — {register_permissions(spec, dry_run)}")
    summary.append(f"  ~ tests/conftest.py — {register_test_model(spec, dry_run)}")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate a CRUD module",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "example:\n"
            "  uv run python scripts/generate_module.py Product \\\n"
            '      --fields "name:str,price:int,is_active:bool"\n\n'
            f"field types: {', '.join(sorted(FIELD_TYPES))}"
        ),
    )
    parser.add_argument("name", help="module name in PascalCase, e.g. Product")
    parser.add_argument(
        "--fields", default="name:str",
        help='comma-separated "name:type" pairs; type defaults to str',
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="show what would be written without touching anything",
    )
    args = parser.parse_args(argv)

    if not re.fullmatch(r"[A-Z][A-Za-z0-9]*", args.name):
        print(
            f"error: '{args.name}' must be PascalCase, e.g. Product or PurchaseOrder",
            file=sys.stderr,
        )
        return 2

    try:
        spec = ModuleSpec(name=args.name, fields=parse_fields(args.fields))
        summary = generate(spec, dry_run=args.dry_run)
    except (ValueError, FileExistsError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    header = "would write" if args.dry_run else "wrote"
    print(f"{header} module '{spec.class_name}' ({spec.table}):")
    print("\n".join(summary))
    print(
        "\npermissions: "
        + ", ".join(spec.permission(a) for a in ("read", "create", "update", "delete"))
    )
    if not args.dry_run:
        print(
            "\nnext:\n"
            "  uv run alembic upgrade head\n"
            f"  uv run pytest tests/test_{spec.plural}.py"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
