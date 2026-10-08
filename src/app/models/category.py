"""Category models: generic reference data other features point at.

A CategoryGroup is a themed container ("order-status"); a Category is an item
inside it, optionally nested. Features that need a classification store a
foreign key to categories.id, so the database — not an application-level
check that can fall behind — is what refuses to delete a value still in use.
"""
import uuid

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin


class CategoryGroup(Base, TimestampMixin):
    __tablename__ = "category_groups"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # Other features fetch by this code, never by id, so it must not change
    # once anything points at it.
    code: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(String(300), nullable=True)
    icon: Mapped[str | None] = mapped_column(String(100), nullable=True)
    color: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Groups a project declares as its own; refused deletion in the backend.
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    categories: Mapped[list["Category"]] = relationship(
        back_populates="group", cascade="all, delete-orphan"
    )

    #: Filled per request by the service, not stored. A column would drift
    #: out of date the moment a category is added elsewhere.
    category_count: int = 0


class Category(Base, TimestampMixin):
    __tablename__ = "categories"
    __table_args__ = (
        # "draft" may exist in several groups, but only once per group.
        UniqueConstraint("group_id", "code", name="uq_category_group_code"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    group_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("category_groups.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Nesting is free: a depth limit is a product rule, not a platform one.
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("categories.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    code: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[str | None] = mapped_column(String(300), nullable=True)
    icon: Mapped[str | None] = mapped_column(String(100), nullable=True)
    color: Mapped[str | None] = mapped_column(String(20), nullable=True)
    order_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_system: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # active | deprecated. Deprecating keeps every existing reference intact
    # while removing the value from pickers elsewhere.
    status: Mapped[str] = mapped_column(
        String(20), default="active", nullable=False, index=True
    )
    deprecated_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    group: Mapped["CategoryGroup"] = relationship(back_populates="categories")
    children: Mapped[list["Category"]] = relationship(back_populates="parent")
    parent: Mapped["Category | None"] = relationship(
        back_populates="children", remote_side=[id]
    )
