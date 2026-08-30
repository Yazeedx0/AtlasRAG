"""Aggregate router for the versioned API surface.

The version prefix lives here and nowhere else; each feature router under
``routes/`` declares its own resource prefix and tags. That keeps a version bump a
one-line change, while adding an endpoint group touches only its own module plus
one ``include_router`` call below.
"""

from fastapi import APIRouter

from apps.api.routes import health
from apps.api.routes.iam import authentication

api_router = APIRouter()
api_router.include_router(health.router)

versioned_api_router = APIRouter(prefix="/api/v1")
versioned_api_router.include_router(authentication.router)
api_router.include_router(versioned_api_router)

