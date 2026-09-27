from fastapi import APIRouter

from app.api.v1.auth.router import router as auth_router
from app.api.v1.dashboard import router as dashboard_router
from app.api.v1.menus import router as menus_router
from app.api.v1.permissions import router as permissions_router
from app.api.v1.roles.router import router as roles_router
from app.api.v1.users.router import router as users_router

router = APIRouter()
router.include_router(auth_router)
router.include_router(users_router)
router.include_router(roles_router)
router.include_router(permissions_router)
router.include_router(menus_router)
router.include_router(dashboard_router)
