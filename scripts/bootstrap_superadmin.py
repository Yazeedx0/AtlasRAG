import argparse
import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from atlasrag.modules.identity.builtin_roles import SUPERADMIN_ROLE_KEY
from atlasrag.modules.identity.enums import IdentifierType
from atlasrag.modules.identity.models import Principal, Role, UserIdentifier, Users
from atlasrag.modules.identity.repositories.role_assignment_repository import (
    RoleAssignmentRepository,
)


@dataclass(frozen=True, slots=True)
class BootstrapResult:
    user_principal_id: UUID
    assigned: bool


async def bootstrap_superadmin(
    *,
    issuer: str,
    subject: str,
    session_factory: async_sessionmaker[AsyncSession],
    clock: Callable[[], datetime] | None = None,
) -> BootstrapResult:
    now = clock or (lambda: datetime.now(UTC))

    async with session_factory() as session:
        user_id = await session.scalar(
            select(UserIdentifier.user_principal_id)
            .join(Users, Users.principal_id == UserIdentifier.user_principal_id)
            .join(Principal, Principal.id == Users.principal_id)
            .where(
                UserIdentifier.identifier_type == IdentifierType.OIDC_SUBJECT.value,
                UserIdentifier.issuer == issuer,
                UserIdentifier.normalized_value == subject,
                UserIdentifier.valid_to.is_(None),
                Principal.is_active.is_(True),
                Principal.deleted_at.is_(None),
            )
        )
        if user_id is None:
            raise RuntimeError(
                "No active local user exists for this issuer and subject. "
                "The user must log in once before bootstrap."
            )

        role_id = await session.scalar(
            select(Role.principal_id).where(Role.role_key == SUPERADMIN_ROLE_KEY)
        )
        if role_id is None:
            raise RuntimeError("The superadmin system role is missing.")

        repository = RoleAssignmentRepository(session)
        if await repository.has_active_assignment(
            user_principal_id=user_id,
            role_principal_id=role_id,
        ):
            return BootstrapResult(user_principal_id=user_id, assigned=False)

        await repository.add_assignment(
            user_principal_id=user_id,
            role_principal_id=role_id,
            assigned_by_principal_id=user_id,
            assigned_at=now(),
        )

        try:
            await session.commit()
        except IntegrityError:
            await session.rollback()
            if await repository.has_active_assignment(
                user_principal_id=user_id,
                role_principal_id=role_id,
            ):
                return BootstrapResult(user_principal_id=user_id, assigned=False)
            raise

        return BootstrapResult(user_principal_id=user_id, assigned=True)


async def _run(issuer: str, subject: str) -> None:
    from atlasrag.platform.database.session import async_session_factory

    result = await bootstrap_superadmin(
        issuer=issuer,
        subject=subject,
        session_factory=async_session_factory,
    )
    action = "assigned" if result.assigned else "already assigned"
    print(f"Superadmin {action} for principal {result.user_principal_id}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Assign the first AtlasRAG superadmin.")
    parser.add_argument("--issuer", required=True)
    parser.add_argument("--subject", required=True)
    arguments = parser.parse_args()
    issuer = cast(str, arguments.issuer)
    subject = cast(str, arguments.subject)
    asyncio.run(_run(issuer, subject))


if __name__ == "__main__":
    main()
