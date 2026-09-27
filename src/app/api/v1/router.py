from fastapi import APIRouter

from app.api.v1.auth.router import router as auth_router
from app.api.v1.permissions import router as permissions_router
from app.api.v1.roles.router import router as roles_router
from app.api.v1.users.router import router as users_router

router = APIRouter()
router.include_router(auth_router)
router.include_router(users_router)
router.include_router(roles_router)
router.include_router(permissions_router)
