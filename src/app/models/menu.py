"""Menu models: Menu, MenuRole."""
import uuid

from sqlalchemy import Boolean, ForeignKey, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class Menu(Base, TimestampMixin):
    __tablename__ = "menus"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    label: Mapped[str] = mapped_column(String(100), nullable=False)
    icon: Mapped[str | None] = mapped_column(String(100), nullable=True)
    path: Mapped[str | None] = mapped_column(String(255), nullable=True)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("menus.id", ondelete="SET NULL"), nullable=True
    )
    order_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    # Permission slug required to see this item, e.g. "users.read".
    # NULL means the item is public. Binding to a permission rather than to a
    # role means new roles inherit visibility automatically.
    required_permission: Mapped[str | None] = mapped_column(String(100), nullable=True)

    children: Mapped[list["Menu"]] = relationship(back_populates="parent")
    parent: Mapped["Menu | None"] = relationship(back_populates="children", remote_side=[id])
    menu_roles: Mapped[list["MenuRole"]] = relationship(back_populates="menu")


class MenuRole(Base):
    __tablename__ = "menu_roles"

    menu_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("menus.id", ondelete="CASCADE"), primary_key=True
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True
    )

    menu: Mapped["Menu"] = relationship(back_populates="menu_roles")
    role: Mapped["Role"] = relationship(back_populates="menu_roles")  # type: ignore[name-defined]  # noqa: F821


# Resolve forward reference
from app.models.rbac import Role  # noqa: E402, F401


def _fix_timestamps() -> None:
    """Ensure Menu.created_at/updated_at columns are named correctly."""


_fix_timestamps()
