"""Models package — import all models so Alembic can detect them."""
from app.models.audit import AppSetting, AuditLog
from app.models.base import Base, TimestampMixin
from app.models.menu import Menu, MenuRole
from app.models.notification import Notification
from app.models.rbac import Permission, Role, RolePermission, UserRole
from app.models.token import LoginAttempt, RefreshToken
from app.models.user import EmailVerification, PasswordHistory, PasswordReset, User, UserInvitation

__all__ = [
    "Base",
    "TimestampMixin",
    "User",
    "EmailVerification",
    "PasswordReset",
    "PasswordHistory",
    "UserInvitation",
    "RefreshToken",
    "LoginAttempt",
    "Role",
    "Permission",
    "RolePermission",
    "UserRole",
    "Menu",
    "MenuRole",
    "AuditLog",
    "AppSetting",
    "Notification",
]
