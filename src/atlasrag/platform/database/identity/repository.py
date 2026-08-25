import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

# Pragmatic modular-monolith exception: the identity persistence adapter
# imports the ORM models directly from modules.identity.models instead of
# resolving tables via Base.metadata, to avoid hidden import-order coupling
# (a metadata lookup only works once something else has imported the models
# module first). This does cross the modules -> platform layering direction;
# it is scoped to this adapter and should not be treated as a precedent for
# platform code reaching into other modules.
from atlasrag.modules.identity.enums import IdentifierType, PrincipalType
from atlasrag.modules.identity.models import Principal, UserIdentifier, Users

from atlasrag.contracts.authentication import AuthenticatedIdentity
from atlasrag.contracts.identity import LocalUserIdentity
from atlasrag.contracts.identity_errors import (
    IdentityAlreadyProvisioned,
    IdentityDataIntegrityError,
)

_ACTIVE_IDENTITY_CONSTRAINT = "uq_user_identifiers_active_identity"


def _is_active_identity_conflict(error: IntegrityError) -> bool:
    orig = error.orig
    constraint_name = getattr(orig, "constraint_name", None)
    if constraint_name is not None:
        return constraint_name == _ACTIVE_IDENTITY_CONSTRAINT

    # Fallback for drivers that don't expose structured constraint info.
    return _ACTIVE_IDENTITY_CONSTRAINT in str(orig)


class SqlAlchemyIdentityRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find_by_oidc_subject(
        self,
        *,
        issuer: str,
        subject: str,
    ) -> LocalUserIdentity | None:
        # Anchor on UserIdentifier and LEFT JOIN outward so a matched
        # identifier row with no corresponding Users/Principal row is
        # distinguishable from no identifier row existing at all.
        statement = (
            select(
                UserIdentifier.id,
                Principal.id,
                Principal.is_active,
                Principal.deleted_at,
            )
            .select_from(UserIdentifier)
            .outerjoin(Users, Users.principal_id == UserIdentifier.user_principal_id)
            .outerjoin(Principal, Principal.id == Users.principal_id)
            .where(
                UserIdentifier.identifier_type == IdentifierType.OIDC_SUBJECT,
                UserIdentifier.issuer == issuer,
                UserIdentifier.normalized_value == subject,
                UserIdentifier.valid_to.is_(None),
            )
        )

        row = (await self._session.execute(statement)).one_or_none()

        if row is None:
            return None

        identifier_id, principal_id, is_active, deleted_at = row

        if principal_id is None:
            raise IdentityDataIntegrityError(
                f"user_identifier {identifier_id} has no resolvable "
                "User/Principal via user_principal_id"
            )

        return LocalUserIdentity(
            principal_id=principal_id,
            is_active=is_active,
            deleted_at=deleted_at,
        )

    async def provision_user(
        self,
        identity: AuthenticatedIdentity,
    ) -> uuid.UUID:
        principal_id = uuid.uuid4()

        await self._session.execute(
            Principal.__table__.insert().values(
                id=principal_id,
                type=PrincipalType.USER,
            )
        )
        await self._session.execute(
            Users.__table__.insert().values(
                principal_id=principal_id,
                display_name=identity.display_name or identity.subject,
            )
        )

        try:
            await self._session.execute(
                UserIdentifier.__table__.insert().values(
                    id=uuid.uuid4(),
                    user_principal_id=principal_id,
                    identifier_type=IdentifierType.OIDC_SUBJECT.value,
                    identifier_value=identity.subject,
                    normalized_value=identity.subject,
                    issuer=identity.issuer,
                )
            )
        except IntegrityError as error:
            if not _is_active_identity_conflict(error):
                raise
            raise IdentityAlreadyProvisioned from error

        return principal_id
