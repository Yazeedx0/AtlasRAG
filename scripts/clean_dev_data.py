"""Remove the Atlas Corp development seed from Keycloak and AtlasRAG."""

import asyncio
import os
from collections.abc import Mapping
from typing import cast

import httpx
from sqlalchemy import delete, or_, select

from atlasrag.bootstrap.core.config import get_settings
from atlasrag.modules.identity.enums import IdentifierType
from atlasrag.modules.identity.models import (
    Group,
    GroupMembership,
    Principal,
    PrincipalPermission,
    Role,
    UserIdentifier,
    UserRole,
    Users,
)
from atlasrag.modules.knowledge.models import Document, DocumentACL
from scripts.seed_dev_data import (
    DEMO_DOCUMENTS,
    DEMO_GROUPS,
    DEMO_ROLES,
    DEMO_USERS,
    DEV_CLI_CLIENT_ID,
    _find_keycloak_user,
    _get_admin_token,
    _keycloak_endpoint,
)


def _seed_usernames() -> tuple[str, ...]:
    settings = get_settings()
    configured_admin = os.getenv(
        "ATLAS_SEED_USER_USERNAME",
        settings.SEED_USER_USERNAME,
    )
    return tuple(dict.fromkeys((configured_admin, *(user.username for user in DEMO_USERS))))


async def _clean_database(
    *,
    issuer: str,
    keycloak_user_ids: Mapping[str, str],
) -> tuple[int, int, int, int]:
    from atlasrag.platform.database.session import async_session_factory

    subjects = tuple(keycloak_user_ids.values())
    async with async_session_factory() as session:
        async with session.begin():
            user_principal_ids = set(
                (
                    await session.scalars(
                        select(UserIdentifier.user_principal_id).where(
                            UserIdentifier.identifier_type == IdentifierType.OIDC_SUBJECT.value,
                            UserIdentifier.issuer == issuer,
                            UserIdentifier.identifier_value.in_(subjects),
                            UserIdentifier.valid_to.is_(None),
                        )
                    )
                ).all()
            )

            role_keys = tuple(
                role.role_key for role in DEMO_ROLES if role.role_key != "superadmin"
            )
            role_rows = (
                await session.execute(
                    select(Role.role_key, Role.principal_id).where(
                        Role.role_key.in_(role_keys)
                    )
                )
            ).all()
            role_principal_ids = {row.principal_id for row in role_rows}

            group_keys = tuple(group.group_key for group in DEMO_GROUPS)
            group_rows = (
                await session.execute(
                    select(Group.group_key, Group.principal_id).where(
                        Group.group_key.in_(group_keys)
                    )
                )
            ).all()
            group_principal_ids = {row.principal_id for row in group_rows}

            document_keys = tuple(
                document.canonical_key for document in DEMO_DOCUMENTS
            )
            document_ids = set(
                (
                    await session.scalars(
                        select(Document.id).where(
                            Document.canonical_key.in_(document_keys)
                        )
                    )
                ).all()
            )

            if document_ids:
                await session.execute(
                    delete(DocumentACL).where(DocumentACL.document_id.in_(document_ids))
                )

            membership_filters = []
            if group_principal_ids:
                membership_filters.extend(
                    (
                        GroupMembership.group_principal_id.in_(group_principal_ids),
                        GroupMembership.member_principal_id.in_(group_principal_ids),
                    )
                )
            if user_principal_ids:
                membership_filters.append(
                    GroupMembership.member_principal_id.in_(user_principal_ids)
                )
            if membership_filters:
                await session.execute(delete(GroupMembership).where(or_(*membership_filters)))

            assignment_filters = []
            if user_principal_ids:
                assignment_filters.append(UserRole.user_principal_id.in_(user_principal_ids))
            if role_principal_ids:
                assignment_filters.append(UserRole.role_principal_id.in_(role_principal_ids))
            if assignment_filters:
                await session.execute(delete(UserRole).where(or_(*assignment_filters)))

            if role_principal_ids:
                await session.execute(
                    delete(PrincipalPermission).where(
                        PrincipalPermission.principal_id.in_(role_principal_ids)
                    )
                )

            if document_ids:
                await session.execute(delete(Document).where(Document.id.in_(document_ids)))
            if group_principal_ids:
                await session.execute(
                    delete(Group).where(Group.principal_id.in_(group_principal_ids))
                )
            if role_principal_ids:
                await session.execute(
                    delete(Role).where(Role.principal_id.in_(role_principal_ids))
                )

            if user_principal_ids:
                await session.execute(
                    delete(UserIdentifier).where(
                        UserIdentifier.user_principal_id.in_(user_principal_ids)
                    )
                )
                await session.execute(
                    delete(Users).where(Users.principal_id.in_(user_principal_ids))
                )

            principal_ids = user_principal_ids | role_principal_ids | group_principal_ids
            if principal_ids:
                await session.execute(delete(Principal).where(Principal.id.in_(principal_ids)))

    return (
        len(user_principal_ids),
        len(role_principal_ids),
        len(group_principal_ids),
        len(document_ids),
    )


async def _clean_keycloak(
    *,
    keycloak_url: str,
    realm: str,
    admin_username: str,
    admin_password: str,
    usernames: tuple[str, ...],
) -> tuple[int, bool]:
    async with httpx.AsyncClient(timeout=10.0) as client:
        token = await _get_admin_token(
            client,
            keycloak_url=keycloak_url,
            admin_username=admin_username,
            admin_password=admin_password,
        )
        headers = {"Authorization": f"Bearer {token}"}
        users_url = f"{keycloak_url}/admin/realms/{realm}/users"
        removed_users = 0

        for username in usernames:
            user = await _find_keycloak_user(
                client,
                users_url=users_url,
                headers=headers,
                username=username,
            )
            if user is None:
                continue
            user_id = user.get("id")
            if not isinstance(user_id, str) or not user_id:
                raise RuntimeError(f"Keycloak user {username!r} does not contain a valid id")
            response = await client.delete(f"{users_url}/{user_id}", headers=headers)
            if response.status_code != 204:
                raise RuntimeError(
                    f"Keycloak user deletion failed with status {response.status_code}: "
                    f"{response.text}"
                )
            removed_users += 1

        clients_url = f"{keycloak_url}/admin/realms/{realm}/clients"
        response = await client.get(
            clients_url,
            headers=headers,
            params={"clientId": DEV_CLI_CLIENT_ID, "exact": "true"},
        )
        if response.status_code != 200:
            raise RuntimeError(
                f"Keycloak client lookup failed with status {response.status_code}: "
                f"{response.text}"
            )
        payload = response.json()
        if not isinstance(payload, list):
            raise RuntimeError("Keycloak client lookup returned an unexpected JSON payload")

        clients = [
            cast(Mapping[str, object], item)
            for item in payload
            if isinstance(item, Mapping)
        ]
        if len(clients) > 1:
            raise RuntimeError(f"Keycloak returned multiple clients for {DEV_CLI_CLIENT_ID!r}")
        if not clients:
            return removed_users, False

        client_id = clients[0].get("id")
        if not isinstance(client_id, str) or not client_id:
            raise RuntimeError("Keycloak CLI client does not contain a valid id")
        response = await client.delete(f"{clients_url}/{client_id}", headers=headers)
        if response.status_code != 204:
            raise RuntimeError(
                f"Keycloak client deletion failed with status {response.status_code}: "
                f"{response.text}"
            )
        return removed_users, True


async def _run() -> None:
    settings = get_settings()
    keycloak_url, realm = _keycloak_endpoint(settings)
    admin_password = os.getenv(
        "ATLAS_KEYCLOAK_ADMIN_PASSWORD",
        settings.KEYCLOAK_ADMIN_PASSWORD,
    )
    if not admin_password:
        raise RuntimeError(
            "ATLAS_KEYCLOAK_ADMIN_PASSWORD or KEYCLOAK_ADMIN_PASSWORD is required"
        )

    usernames = _seed_usernames()
    async with httpx.AsyncClient(timeout=10.0) as client:
        token = await _get_admin_token(
            client,
            keycloak_url=keycloak_url,
            admin_username=os.getenv(
                "ATLAS_KEYCLOAK_ADMIN_USERNAME",
                settings.KEYCLOAK_ADMIN_USERNAME,
            ),
            admin_password=admin_password,
        )
        headers = {"Authorization": f"Bearer {token}"}
        users_url = f"{keycloak_url}/admin/realms/{realm}/users"
        keycloak_user_ids: dict[str, str] = {}
        for username in usernames:
            user = await _find_keycloak_user(
                client,
                users_url=users_url,
                headers=headers,
                username=username,
            )
            if user is None:
                continue
            user_id = user.get("id")
            if not isinstance(user_id, str) or not user_id:
                raise RuntimeError(f"Keycloak user {username!r} does not contain a valid id")
            keycloak_user_ids[username] = user_id

    database_counts = await _clean_database(
        issuer=str(settings.KEYCLOAK_ISSUER).rstrip("/"),
        keycloak_user_ids=keycloak_user_ids,
    )
    keycloak_counts = await _clean_keycloak(
        keycloak_url=keycloak_url,
        realm=realm,
        admin_username=os.getenv(
            "ATLAS_KEYCLOAK_ADMIN_USERNAME",
            settings.KEYCLOAK_ADMIN_USERNAME,
        ),
        admin_password=admin_password,
        usernames=usernames,
    )
    print(
        "Removed database seed records: "
        f"users={database_counts[0]}, roles={database_counts[1]}, "
        f"groups={database_counts[2]}, documents={database_counts[3]}\n"
        f"Removed Keycloak users: {keycloak_counts[0]}\n"
        f"Removed Keycloak CLI client: {'yes' if keycloak_counts[1] else 'no'}"
    )


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
