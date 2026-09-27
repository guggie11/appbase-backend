"""Schemas package."""
from app.schemas.auth import (
    ForgotPasswordRequest,
    LoginRequest,
    RegisterRequest,
    ResendVerificationRequest,
    ResetPasswordRequest,
    TokenResponse,
    UserBriefResponse,
    UserResponse,
)
from app.schemas.common import ErrorDetail, ErrorResponse, PaginatedResponse, SuccessResponse

__all__ = [
    "SuccessResponse",
    "ErrorDetail",
    "ErrorResponse",
    "PaginatedResponse",
    "RegisterRequest",
    "LoginRequest",
    "ForgotPasswordRequest",
    "ResetPasswordRequest",
    "ResendVerificationRequest",
    "TokenResponse",
    "UserResponse",
    "UserBriefResponse",
]
