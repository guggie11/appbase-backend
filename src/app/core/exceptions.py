"""Application exception classes and handlers."""
from fastapi import Request
from fastapi.responses import JSONResponse


class AppException(Exception):
    def __init__(self, code: str, message: str, status_code: int = 400):
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


async def app_exception_handler(request: Request, exc: AppException) -> JSONResponse:
    request_id = getattr(request.state, "request_id", None)
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.code,
                "message": exc.message,
                "details": [],
                "request_id": str(request_id) if request_id else None,
            }
        },
    )


# Convenience factory functions
def auth_invalid_credentials() -> AppException:
    return AppException("AUTH_INVALID_CREDENTIALS", "Email atau password salah", 401)


def auth_account_locked() -> AppException:
    return AppException("AUTH_ACCOUNT_LOCKED", "Akun dikunci karena terlalu banyak percobaan login", 423)


def auth_email_not_verified() -> AppException:
    return AppException("AUTH_EMAIL_NOT_VERIFIED", "Email belum diverifikasi", 403)


def auth_token_invalid() -> AppException:
    return AppException("AUTH_TOKEN_INVALID", "Token tidak valid", 401)


def auth_token_expired() -> AppException:
    return AppException("AUTH_TOKEN_EXPIRED", "Token telah kadaluarsa", 401)


def auth_token_revoked() -> AppException:
    return AppException("AUTH_TOKEN_REVOKED", "Token telah dicabut", 401)


def auth_email_already_exists() -> AppException:
    return AppException("AUTH_EMAIL_ALREADY_EXISTS", "Email sudah terdaftar", 409)


def auth_user_not_found() -> AppException:
    return AppException("AUTH_USER_NOT_FOUND", "User tidak ditemukan", 404)


def auth_invalid_reset_token() -> AppException:
    return AppException("AUTH_INVALID_RESET_TOKEN", "Token reset password tidak valid atau telah digunakan", 400)


def auth_invalid_verify_token() -> AppException:
    return AppException("AUTH_INVALID_VERIFY_TOKEN", "Token verifikasi tidak valid atau telah digunakan", 400)


def auth_same_password() -> AppException:
    return AppException("AUTH_SAME_PASSWORD", "Password baru tidak boleh sama dengan password sebelumnya", 400)


def auth_invalid_invitation_token() -> AppException:
    return AppException("AUTH_INVALID_INVITATION_TOKEN", "Token undangan tidak valid atau telah digunakan", 400)


def auth_invitation_expired() -> AppException:
    return AppException("AUTH_INVITATION_EXPIRED", "Token undangan telah kadaluarsa", 400)


def auth_rate_limited() -> AppException:
    return AppException("AUTH_RATE_LIMITED", "Terlalu banyak permintaan, coba lagi nanti", 429)
