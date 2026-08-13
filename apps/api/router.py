"""Aggregate router for the versioned API surface.

The version prefix lives here and nowhere else; each feature router under
``routes/`` declares its own resource prefix and tags. That keeps a version bump a
one-line change, while adding an endpoint group touches only its own module plus
one ``include_router`` call below.
"""

from fastapi import APIRouter

api_router = APIRouter(prefix="/api/v1")

# Feature routers are registered here, e.g.:
#
#     from apps.api.routes import documents
#     api_router.include_router(documents.router)
#
# with `documents.router = APIRouter(prefix="/documents", tags=["documents"])`,
# which resolves to /api/v1/documents.
