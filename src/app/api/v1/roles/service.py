"""Role business logic service."""
import re
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppException
from app.models.rbac import Permission, Role, RolePermission, UserRole


def _slugify(name: str) -> str:
    slug = name.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-")


async def list_roles(
    db: AsyncSession,
    page: int = 1,
    per_page: int = 10,
    is_active: bool | None = None,
) -> tuple[list[Role], int]:
    query = select(Role)
    count_query = select(func.count()).select_from(Role)

    if is_active is not None:
        query = query.where(Role.is_active == is_active)
        count_query = count_query.where(Role.is_active == is_active)

    total_result = await db.execute(count_query)
    total = total_result.scalar_one()

    query = query.order_by(Role.created_at).offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    roles = result.scalars().all()

    # Attach how many users hold each role. One aggregate query for the page,
    # not one per row — and a real number rather than the schema default,
    # which would silently report 0 for every role.
    await _attach_user_counts(db, roles)
    return list(roles), total


async def _attach_user_counts(db: AsyncSession, roles) -> None:
    if not roles:
        return
    ids = [r.id for r in roles]
    rows = await db.execute(
        select(UserRole.role_id, func.count(UserRole.user_id))
        .where(UserRole.role_id.in_(ids))
        .group_by(UserRole.role_id)
    )
    counts = dict(rows.all())
    for role in roles:
        role.user_count = counts.get(role.id, 0)


async def get_role(db: AsyncSession, role_id: uuid.UUID) -> Role:
    result = await db.execute(select(Role).where(Role.id == role_id))
    role = result.scalar_one_or_none()
    if not role:
        raise AppException(code="ROLES_NOT_FOUND", message="Role tidak ditemukan", status_code=404)
    return role


async def create_role(db: AsyncSession, name: str, description: str | None = None) -> Role:
    slug = _slugify(name)
    # Check slug uniqueness
    existing = await db.execute(select(Role).where(Role.slug == slug))
    if existing.scalar_one_or_none():
        raise AppException(code="ROLES_SLUG_ALREADY_EXISTS", message="Role dengan nama ini sudah ada", status_code=409)

    role = Role(id=uuid.uuid4(), name=name, slug=slug, description=description, is_system=False, is_active=True)
    db.add(role)
    await db.commit()
    await db.refresh(role)
    return role


def _reject_if_platform(role: Role) -> None:
    """Platform roles own the system and must stay immutable via the API.

    Hiding the button in the UI is cosmetic — anyone can still call the
    endpoint. If Super Admin's permissions were stripped, the deployment
    would lock itself out with no way back in.
    """
    if getattr(role, "kind", "custom") == "platform":
        raise AppException(
            code="ROLES_PLATFORM_ROLE_LOCKED",
            message="Platform role tidak dapat diubah atau dihapus",
            status_code=403,
        )


async def update_role(
    db: AsyncSession,
    role_id: uuid.UUID,
    name: str | None = None,
    description: str | None = None,
    is_active: bool | None = None,
) -> Role:
    role = await get_role(db, role_id)
    _reject_if_platform(role)

    if name is not None:
        if role.is_system:
            # System roles: only allow updating name display, not slug
            role.name = name
        else:
            slug = _slugify(name)
            # Check uniqueness (excluding current)
            existing = await db.execute(select(Role).where(Role.slug == slug, Role.id != role_id))
            if existing.scalar_one_or_none():
                raise AppException(code="ROLES_SLUG_ALREADY_EXISTS", message="Role dengan nama ini sudah ada", status_code=409)
            role.name = name
            role.slug = slug

    if description is not None:
        role.description = description

    if is_active is not None:
        role.is_active = is_active

    await db.commit()
    await db.refresh(role)
    return role


async def duplicate_role(db: AsyncSession, role_id: uuid.UUID, name: str) -> Role:
    """Copy a role along with every permission it grants.

    Building a near-identical role otherwise means re-ticking twenty boxes by
    hand. Platform roles are copyable — the lock protects the original, and a
    copy starts life as an ordinary custom role.
    """
    source = await get_role(db, role_id)

    slug = _slugify(name)
    existing = await db.execute(select(Role).where(Role.slug == slug))
    if existing.scalar_one_or_none():
        raise AppException(
            code="ROLES_SLUG_ALREADY_EXISTS",
            message="Role dengan nama ini sudah ada",
            status_code=409,
        )

    copy = Role(
        id=uuid.uuid4(),
        name=name,
        slug=slug,
        description=source.description,
        is_system=False,
        is_active=True,
        kind="custom",
    )
    db.add(copy)
    await db.flush()

    rows = await db.execute(
        select(RolePermission.permission_id).where(RolePermission.role_id == source.id)
    )
    for (permission_id,) in rows.all():
        db.add(RolePermission(role_id=copy.id, permission_id=permission_id))

    await db.commit()
    await db.refresh(copy)
    return copy


async def delete_role(db: AsyncSession, role_id: uuid.UUID) -> None:
    role = await get_role(db, role_id)
    _reject_if_platform(role)
    if role.is_system:
        raise AppException(
            code="ROLES_CANNOT_DELETE_SYSTEM_ROLE",
            message="Role sistem tidak dapat dihapus",
            status_code=400,
        )
    await db.delete(role)
    await db.commit()


async def get_role_permissions(db: AsyncSession, role_id: uuid.UUID) -> list[Permission]:
    # Verify role exists
    await get_role(db, role_id)

    result = await db.execute(
        select(Permission)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .where(RolePermission.role_id == role_id)
        .order_by(Permission.module, Permission.action)
    )
    return list(result.scalars().all())


async def assign_permissions(
    db: AsyncSession, role_id: uuid.UUID, permission_ids: list[uuid.UUID]
) -> list[Permission]:
    role = await get_role(db, role_id)
    # The dangerous one: stripping these would lock the deployment out.
    _reject_if_platform(role)

    # Validate permissions exist
    for pid in permission_ids:
        result = await db.execute(select(Permission).where(Permission.id == pid))
        perm = result.scalar_one_or_none()
        if not perm:
            raise AppException(
                code="PERMISSIONS_NOT_FOUND",
                message=f"Permission {pid} tidak ditemukan",
                status_code=404,
            )

    # Delete existing role_permissions
    existing = await db.execute(
        select(RolePermission).where(RolePermission.role_id == role.id)
    )
    for rp in existing.scalars().all():
        await db.delete(rp)

    # Re-insert
    for pid in permission_ids:
        rp = RolePermission(role_id=role.id, permission_id=pid)
        db.add(rp)

    await db.commit()

    return await get_role_permissions(db, role_id)
