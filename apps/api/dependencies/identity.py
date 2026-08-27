from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.dependencies.authentication import get_authenticated_identity
from atlasrag.bootstrap.core.config import get_settings
from atlasrag.bootstrap.identity import ConfiguredProvisioningPolicy
from atlasrag.contracts.authentication import AuthenticatedIdentity
from atlasrag.contracts.identity_errors import IdentityResolutionError
from atlasrag.modules.identity.repositories.identity_repository import (
    SqlAlchemyIdentityRepository,
)
from atlasrag.modules.identity.repositories.unit_of_work import (
    make_identity_unit_of_work_factory,
)
from atlasrag.modules.identity.services.identity_resolver import IdentityResolver
from atlasrag.platform.database.session import async_session_factory, get_db_session

DatabaseSession = Annotated[AsyncSession, Depends(get_db_session)]


async def get_identity_resolver(session: DatabaseSession) -> IdentityResolver:
    settings = get_settings()
    return IdentityResolver(
        repository=SqlAlchemyIdentityRepository(session),
        uow_factory=make_identity_unit_of_work_factory(async_session_factory),
        policy=ConfiguredProvisioningPolicy(settings.IDENTITY_JIT_ENABLED),
    )


async def get_local_principal_id(
    identity: Annotated[
        AuthenticatedIdentity,
        Depends(get_authenticated_identity),
    ],
    resolver: Annotated[IdentityResolver, Depends(get_identity_resolver)],
) -> UUID:
    """Resolve a verified external identity to an active local Principal."""
    try:
        return await resolver.resolve(identity)
    except IdentityResolutionError as error:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Authenticated identity has no usable local access",
        ) from error
