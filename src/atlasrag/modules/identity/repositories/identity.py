import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from atlasrag.contracts.authentication import AuthenticatedIdentity
from atlasrag.contracts.identity_errors import IdentityAlreadyProvisioned
from atlasrag.contracts.identity_types import LocalUserIdentity
from atlasrag.modules.identity.enums import IdentifierType, PrincipalType
from atlasrag.modules.identity.models import Principal, UserIdentifier, Users
from atlasrag.platform.database.integrity import is_integrity_error_for_constraint

_ACTIVE_IDENTITY_CONSTRAINT = "uq_user_identifiers_active_identity"


class SqlAlchemyIdentityRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find_by_oidc_subject(
        self,
        *,
        issuer: str,
        subject: str,
    ) -> LocalUserIdentity | None:
        statement = (
            select(
                Principal.id,
                Principal.is_active,
                Principal.deleted_at,
            )
            .select_from(UserIdentifier)
            .join(Users, Users.principal_id == UserIdentifier.user_principal_id)
            .join(Principal, Principal.id == Users.principal_id)
            .where(
                UserIdentifier.identifier_type == IdentifierType.OIDC_SUBJECT.value,
                UserIdentifier.issuer == issuer,
                UserIdentifier.normalized_value == subject,
                UserIdentifier.valid_to.is_(None),
            )
        )

        row = (await self._session.execute(statement)).one_or_none()

        if row is None:
            return None

        principal_id, is_active, deleted_at = row

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
                deleted_at=None,
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
                    verified_at=None,
                    valid_to=None,
                )
            )
        except IntegrityError as error:
            if not is_integrity_error_for_constraint(
                error=error,
                constraint_name=_ACTIVE_IDENTITY_CONSTRAINT,
            ):
                raise
            raise IdentityAlreadyProvisioned from error

        return principal_id
