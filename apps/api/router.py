"""Aggregate router for the application API surface.

Health probes remain unversioned, while application features are grouped below the
versioned API prefix.
"""

from fastapi import APIRouter

from apps.api.routes import health
from apps.api.routes.iam import authentication, groups, permissions, principals, roles
from apps.api.utilities.exception_handlers import register_exception_handlers

api_router = APIRouter()
api_router.include_router(health.router)

versioned_api_router = APIRouter(prefix="/api/v1")
versioned_api_router.include_router(authentication.router)
versioned_api_router.include_router(groups.router)
versioned_api_router.include_router(permissions.router)
versioned_api_router.include_router(principals.router)
versioned_api_router.include_router(roles.router)
api_router.include_router(versioned_api_router)

__all__ = ["api_router", "register_exception_handlers"]
