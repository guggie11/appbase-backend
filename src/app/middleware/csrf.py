"""CSRF middleware — validates X-CSRF-Token header against csrf_token cookie."""
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

# Paths skipped from CSRF validation
CSRF_EXEMPT_PATHS = {
    "/api/v1/auth/login",
    "/api/v1/auth/register",
    "/api/v1/auth/refresh",
    "/api/v1/auth/forgot-password",
    "/api/v1/auth/reset-password",
    "/api/v1/auth/verify-email",
    "/api/v1/auth/resend-verification",
    "/api/v1/auth/accept-invitation",
    "/health",
    "/docs",
    "/openapi.json",
}

CSRF_EXEMPT_PREFIXES = {
    "/api/v1/auth/oauth/",
}

CSRF_PROTECTED_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


class CSRFMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        if request.method in CSRF_PROTECTED_METHODS:
            path = request.url.path
            exempt = path in CSRF_EXEMPT_PATHS or any(
                path.startswith(prefix) for prefix in CSRF_EXEMPT_PREFIXES
            )
            if not exempt:
                csrf_header = request.headers.get("X-CSRF-Token")
                csrf_cookie = request.cookies.get("csrf_token")
                if not csrf_header or not csrf_cookie or csrf_header != csrf_cookie:
                    return JSONResponse(
                        status_code=403,
                        content={
                            "error": {
                                "code": "CSRF_TOKEN_INVALID",
                                "message": "CSRF token tidak valid",
                                "details": [],
                                "request_id": None,
                            }
                        },
                    )
        return await call_next(request)
