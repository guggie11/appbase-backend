import pathlib
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address

from app.api.v1.router import router as v1_router
from app.core.config import settings
from app.core.exceptions import AppException, app_exception_handler
from app.middleware.correlation import CorrelationIdMiddleware
from app.middleware.csrf import CSRFMiddleware
from app.middleware.security_headers import SecurityHeadersMiddleware

limiter = Limiter(key_func=get_remote_address)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup: seed roles & permissions
    try:
        from app.core.database import AsyncSessionLocal
        from app.core.seed import seed_permissions, seed_roles, seed_settings

        async with AsyncSessionLocal() as db:
            await seed_permissions(db)
            await seed_roles(db)
            await seed_settings(db)
    except Exception:
        # Don't fail startup if DB is unavailable (e.g., tests)
        pass
    yield
    # shutdown


app = FastAPI(
    title=settings.APP_NAME,
    debug=settings.DEBUG,
    lifespan=lifespan,
)

# Attach limiter to app state (required by SlowAPI)
app.state.limiter = limiter

# Exception handlers
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_exception_handler(AppException, app_exception_handler)  # type: ignore[arg-type]

# Static files for avatars
pathlib.Path("static/avatars").mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory="static"), name="static")

# Middlewares (order matters — outermost = last added)
app.add_middleware(SlowAPIMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(CSRFMiddleware)
app.add_middleware(CorrelationIdMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health_check():
    return {"status": "ok"}


app.include_router(v1_router, prefix="/api/v1")
