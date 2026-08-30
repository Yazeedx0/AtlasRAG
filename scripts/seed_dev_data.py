"""Seed a realistic development company in Keycloak and the AtlasRAG database."""

import argparse
import asyncio
import os
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import cast
from uuid import UUID, uuid4, uuid5

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from atlasrag.bootstrap.core.config import Settings, get_settings
from atlasrag.contracts.authentication import AuthenticatedIdentity
from atlasrag.contracts.authorization_types import DocumentPermission
from atlasrag.contracts.identity_types import LocalUserIdentity
from atlasrag.contracts.permissions import Permission
from atlasrag.modules.identity.enums import PrincipalType
from atlasrag.modules.identity.models import (
    Group,
    GroupMembership,
    PermissionDefinition,
    Principal,
    PrincipalPermission,
    Role,
    UserRole,
)
from atlasrag.modules.identity.repositories.identity import IdentityRepository
from atlasrag.modules.knowledge.models import Document, DocumentACL
from scripts.bootstrap_superadmin import bootstrap_superadmin

DEFAULT_KEYCLOAK_ADMIN_USERNAME = "admin"
DEFAULT_SEED_USERNAME = "atlas-admin"
DEFAULT_SEED_EMAIL = "atlas-admin@atlasrag.local"
DEFAULT_SEED_DISPLAY_NAME = "Atlas Admin"
DEV_CLI_CLIENT_ID = "atlasrag-cli"
SEED_NAMESPACE = UUID("f8ce0c6e-3f6a-4af5-9f5d-1e2a9de3b2f8")


@dataclass(frozen=True, slots=True)
class SeedConfig:
    keycloak_url: str
    realm: str
    admin_username: str
    admin_password: str
    username: str
    password: str
    email: str
    display_name: str
    first_name: str
    last_name: str
    reset_password: bool


@dataclass(frozen=True, slots=True)
class KeycloakUser:
    user_id: str
    created: bool


@dataclass(frozen=True, slots=True)
class DemoUser:
    username: str
    email: str
    display_name: str
    first_name: str
    last_name: str
    role_keys: tuple[str, ...]
    group_keys: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class RoleSeed:
    role_key: str
    name: str
    description: str


@dataclass(frozen=True, slots=True)
class GroupSeed:
    group_key: str
    name: str
    description: str


@dataclass(frozen=True, slots=True)
class DocumentSeed:
    canonical_key: str
    title: str
    description: str
    document_type: str
    department: str
    default_language_code: str
    grants: tuple[tuple[str, DocumentPermission], ...]


DEMO_USERS: tuple[DemoUser, ...] = (
    DemoUser(
        username="alice.engineer",
        email="alice.engineer@atlasrag.local",
        display_name="Alice Engineer",
        first_name="Alice",
        last_name="Engineer",
        role_keys=("employee", "manager", "engineering_lead"),
        group_keys=("engineering", "leadership"),
    ),
    DemoUser(
        username="bob.engineer",
        email="bob.engineer@atlasrag.local",
        display_name="Bob Engineer",
        first_name="Bob",
        last_name="Engineer",
        role_keys=("employee",),
        group_keys=("engineering",),
    ),
    DemoUser(
        username="carol.hr",
        email="carol.hr@atlasrag.local",
        display_name="Carol HR",
        first_name="Carol",
        last_name="HR",
        role_keys=("employee", "manager", "hr_admin"),
        group_keys=("hr", "leadership"),
    ),
    DemoUser(
        username="diana.hr",
        email="diana.hr@atlasrag.local",
        display_name="Diana HR",
        first_name="Diana",
        last_name="HR",
        role_keys=("employee",),
        group_keys=("hr",),
    ),
    DemoUser(
        username="eric.finance",
        email="eric.finance@atlasrag.local",
        display_name="Eric Finance",
        first_name="Eric",
        last_name="Finance",
        role_keys=("employee", "manager", "finance_manager"),
        group_keys=("finance", "leadership"),
    ),
    DemoUser(
        username="fatima.finance",
        email="fatima.finance@atlasrag.local",
        display_name="Fatima Finance",
        first_name="Fatima",
        last_name="Finance",
        role_keys=("employee",),
        group_keys=("finance",),
    ),
    DemoUser(
        username="george.operations",
        email="george.operations@atlasrag.local",
        display_name="George Operations",
        first_name="George",
        last_name="Operations",
        role_keys=("employee", "manager"),
        group_keys=("operations", "leadership"),
    ),
)

DEMO_ROLES: tuple[RoleSeed, ...] = (
    RoleSeed("employee", "Employee", "Default role for Atlas Corp employees."),
    RoleSeed("manager", "Manager", "Can manage knowledge documents."),
    RoleSeed(
        "engineering_lead",
        "Engineering Lead",
        "Can manage engineering knowledge access.",
    ),
    RoleSeed("hr_admin", "HR Administrator", "Can manage groups and knowledge access."),
    RoleSeed(
        "finance_manager",
        "Finance Manager",
        "Can manage finance knowledge access.",
    ),
    RoleSeed("superadmin", "Superadmin", "Built-in role with every application capability."),
)

DEMO_GROUPS: tuple[GroupSeed, ...] = (
    GroupSeed("all-employees", "All Employees", "Everyone employed by Atlas Corp."),
    GroupSeed("engineering", "Engineering", "Engineering department."),
    GroupSeed("hr", "Human Resources", "Human Resources department."),
    GroupSeed("finance", "Finance", "Finance department."),
    GroupSeed("operations", "Operations", "Operations department."),
    GroupSeed("leadership", "Leadership", "Department and company leadership."),
)

GROUP_GROUP_MEMBERSHIPS: tuple[tuple[str, str], ...] = (
    ("all-employees", "engineering"),
    ("all-employees", "hr"),
    ("all-employees", "finance"),
    ("all-employees", "operations"),
    ("all-employees", "leadership"),
)

ROLE_PERMISSIONS: Mapping[str, tuple[Permission, ...]] = {
    "employee": (),
    "manager": (Permission.KNOWLEDGE_DOCUMENTS_MANAGE,),
    "engineering_lead": (Permission.KNOWLEDGE_DOCUMENT_ACL_MANAGE,),
    "hr_admin": (
        Permission.IAM_GROUPS_MANAGE,
        Permission.KNOWLEDGE_DOCUMENT_ACL_MANAGE,
    ),
    "finance_manager": (Permission.KNOWLEDGE_DOCUMENT_ACL_MANAGE,),
    "superadmin": tuple(Permission),
}

DEMO_DOCUMENTS: tuple[DocumentSeed, ...] = (
    DocumentSeed(
        canonical_key="employee-handbook",
        title="Atlas Corp Employee Handbook",
        description="Company-wide policies, benefits, and employee guidance.",
        document_type="policy",
        department="company",
        default_language_code="en",
        grants=(("group:all-employees", DocumentPermission.READ),),
    ),
    DocumentSeed(
        canonical_key="security-policy",
        title="Information Security Policy",
        description="Security responsibilities, incident reporting, and acceptable use.",
        document_type="policy",
        department="company",
        default_language_code="en",
        grants=(
            ("group:all-employees", DocumentPermission.READ),
            ("group:leadership", DocumentPermission.MANAGE),
        ),
    ),
    DocumentSeed(
        canonical_key="engineering-runbook",
        title="Engineering Operations Runbook",
        description="Service ownership, deployment, and incident-response procedures.",
        document_type="runbook",
        department="engineering",
        default_language_code="en",
        grants=(
            ("group:engineering", DocumentPermission.READ),
            ("role:engineering_lead", DocumentPermission.MANAGE),
        ),
    ),
    DocumentSeed(
        canonical_key="hr-benefits",
        title="Benefits and Leave Guide",
        description="Benefits enrollment, leave policy, and HR procedures.",
        document_type="policy",
        department="hr",
        default_language_code="en",
        grants=(
            ("group:hr", DocumentPermission.READ),
            ("role:hr_admin", DocumentPermission.MANAGE),
        ),
    ),
    DocumentSeed(
        canonical_key="finance-forecast",
        title="Finance Planning and Forecast",
        description="Budget planning, forecasting, and financial operating guidance.",
        document_type="report",
        department="finance",
        default_language_code="en",
        grants=(
            ("group:finance", DocumentPermission.READ),
            ("role:finance_manager", DocumentPermission.MANAGE),
        ),
    ),
    DocumentSeed(
        canonical_key="operations-playbook",
        title="Operations Playbook",
        description="Workplace operations, procurement, and vendor procedures.",
        document_type="guide",
        department="operations",
        default_language_code="en",
        grants=(
            ("group:operations", DocumentPermission.READ),
            ("role:manager", DocumentPermission.MANAGE),
        ),
    ),
)


def _keycloak_endpoint(settings: Settings) -> tuple[str, str]:
    issuer = str(settings.KEYCLOAK_ISSUER).rstrip("/")
    base_url, separator, realm = issuer.rpartition("/realms/")
    if not separator or not base_url or not realm:
        raise RuntimeError("KEYCLOAK_ISSUER must end with /realms/<realm>")
    return base_url, realm


def _json_object(response: httpx.Response) -> Mapping[str, object]:
    payload = response.json()
    if not isinstance(payload, Mapping):
        raise RuntimeError("Keycloak returned an unexpected JSON object")
    return cast(Mapping[str, object], payload)


async def _get_admin_token(
    client: httpx.AsyncClient,
    *,
    keycloak_url: str,
    admin_username: str,
    admin_password: str,
) -> str:
    response = await client.post(
        f"{keycloak_url}/realms/master/protocol/openid-connect/token",
        data={
            "grant_type": "password",
            "client_id": "admin-cli",
            "username": admin_username,
            "password": admin_password,
        },
    )
    if response.status_code != 200:
        raise RuntimeError(
            "Keycloak admin authentication failed "
            f"with status {response.status_code}: {response.text}"
        )

    payload = _json_object(response)
    access_token = payload.get("access_token")
    if not isinstance(access_token, str) or not access_token:
        raise RuntimeError("Keycloak admin response did not contain an access token")
    return access_token


def _admin_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _find_keycloak_user(
    client: httpx.AsyncClient,
    *,
    users_url: str,
    headers: Mapping[str, str],
    username: str,
) -> Mapping[str, object] | None:
    response = await client.get(
        users_url,
        headers=headers,
        params={"username": username, "exact": "true"},
    )
    if response.status_code != 200:
        raise RuntimeError(
            f"Keycloak user lookup failed with status {response.status_code}: "
            f"{response.text}"
        )

    payload = response.json()
    if not isinstance(payload, list):
        raise RuntimeError("Keycloak user lookup returned an unexpected JSON payload")

    users = [
        cast(Mapping[str, object], user)
        for user in payload
        if isinstance(user, Mapping)
    ]
    if len(users) > 1:
        raise RuntimeError(f"Keycloak returned multiple users for username {username!r}")
    return users[0] if users else None


async def _ensure_keycloak_cli_client(
    client: httpx.AsyncClient,
    *,
    realm_url: str,
    headers: Mapping[str, str],
) -> None:
    clients_url = f"{realm_url}/clients"
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

    client_representation: dict[str, object] = {
        "clientId": DEV_CLI_CLIENT_ID,
        "name": "AtlasRAG Development CLI",
        "enabled": True,
        "protocol": "openid-connect",
        "publicClient": True,
        "bearerOnly": False,
        "standardFlowEnabled": False,
        "implicitFlowEnabled": False,
        "directAccessGrantsEnabled": True,
        "serviceAccountsEnabled": False,
        "authorizationServicesEnabled": False,
        "protocolMappers": [
            {
                "name": "AtlasRAG API audience",
                "protocol": "openid-connect",
                "protocolMapper": "oidc-audience-mapper",
                "consentRequired": False,
                "config": {
                    "included.client.audience": "atlasrag-api",
                    "id.token.claim": "false",
                    "access.token.claim": "true",
                    "userinfo.token.claim": "false",
                },
            }
        ],
    }

    if not clients:
        response = await client.post(
            clients_url,
            headers=headers,
            json=client_representation,
        )
        if response.status_code != 201:
            raise RuntimeError(
                f"Keycloak client creation failed with status {response.status_code}: "
                f"{response.text}"
            )
        return

    client_id = clients[0].get("id")
    if not isinstance(client_id, str) or not client_id:
        raise RuntimeError("Keycloak CLI client does not contain a valid id")

    response = await client.put(
        f"{clients_url}/{client_id}",
        headers=headers,
        json=client_representation,
    )
    if response.status_code != 204:
        raise RuntimeError(
            f"Keycloak client update failed with status {response.status_code}: "
            f"{response.text}"
        )


async def _ensure_keycloak_user(
    client: httpx.AsyncClient,
    *,
    config: SeedConfig,
) -> KeycloakUser:
    realm_url = f"{config.keycloak_url}/admin/realms/{config.realm}"
    headers = _admin_headers(
        await _get_admin_token(
            client,
            keycloak_url=config.keycloak_url,
            admin_username=config.admin_username,
            admin_password=config.admin_password,
        )
    )
    users_url = f"{realm_url}/users"
    await _ensure_keycloak_cli_client(
        client,
        realm_url=realm_url,
        headers=headers,
    )
    existing_user = await _find_keycloak_user(
        client,
        users_url=users_url,
        headers=headers,
        username=config.username,
    )

    if existing_user is None:
        response = await client.post(
            users_url,
            headers=headers,
            json={
                "username": config.username,
                "email": config.email,
                "firstName": config.first_name,
                "lastName": config.last_name,
                "emailVerified": True,
                "enabled": True,
                "requiredActions": [],
                "credentials": [
                    {
                        "type": "password",
                        "value": config.password,
                        "temporary": False,
                    }
                ],
            },
        )
        if response.status_code != 201:
            raise RuntimeError(
                f"Keycloak user creation failed with status {response.status_code}: "
                f"{response.text}"
            )
        existing_user = await _find_keycloak_user(
            client,
            users_url=users_url,
            headers=headers,
            username=config.username,
        )
        if existing_user is None:
            raise RuntimeError("Keycloak created the user but it could not be found afterward")
        created = True
    else:
        created = False

    user_id = existing_user.get("id")
    if not isinstance(user_id, str) or not user_id:
        raise RuntimeError("Keycloak user does not contain a valid id")

    if existing_user.get("enabled") is False:
        raise RuntimeError(f"Keycloak user {config.username!r} is disabled")

    if not created:
        response = await client.put(
            f"{users_url}/{user_id}",
            headers=headers,
            json={
                "id": user_id,
                "username": config.username,
                "email": config.email,
                "firstName": config.first_name,
                "lastName": config.last_name,
                "emailVerified": True,
                "enabled": True,
                "requiredActions": [],
            },
        )
        if response.status_code != 204:
            raise RuntimeError(
                f"Keycloak user setup failed with status {response.status_code}: "
                f"{response.text}"
            )

    if config.reset_password and not created:
        response = await client.put(
            f"{users_url}/{user_id}/reset-password",
            headers=headers,
            json={
                "type": "password",
                "value": config.password,
                "temporary": False,
            },
        )
        if response.status_code != 204:
            raise RuntimeError(
                f"Keycloak password reset failed with status {response.status_code}: "
                f"{response.text}"
            )

    return KeycloakUser(user_id=user_id, created=created)


async def _ensure_local_user(
    *,
    issuer: str,
    subject: str,
    display_name: str,
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[UUID, bool]:
    identity = AuthenticatedIdentity(
        issuer=issuer,
        subject=subject,
        display_name=display_name,
    )

    async with session_factory() as session:
        repository = IdentityRepository(session)
        existing = await repository.find_by_oidc_subject(
            issuer=issuer,
            subject=subject,
        )
        if existing is not None:
            _ensure_local_identity_is_active(existing)
            return existing.principal_id, False

        principal_id = await repository.provision_user(identity)
        await session.commit()
        return principal_id, True


def _ensure_local_identity_is_active(identity: LocalUserIdentity) -> None:
    if identity.deleted_at is not None or not identity.is_active:
        raise RuntimeError(
            f"Local identity for principal {identity.principal_id} is inactive or retired"
        )


def _seed_uuid(kind: str, key: str) -> UUID:
    return uuid5(SEED_NAMESPACE, f"{kind}:{key}")


def _demo_users(config: SeedConfig) -> tuple[DemoUser, ...]:
    admin = DemoUser(
        username=config.username,
        email=config.email,
        display_name=config.display_name,
        first_name=config.first_name,
        last_name=config.last_name,
        role_keys=("superadmin",),
        group_keys=("leadership",),
    )
    return (admin, *DEMO_USERS)


async def _ensure_role(
    session: AsyncSession,
    role_seed: RoleSeed,
) -> UUID:
    role = await session.scalar(
        select(Role).where(Role.role_key == role_seed.role_key)
    )
    if role is not None:
        principal = await session.get(Principal, role.principal_id)
        if principal is None or principal.type != PrincipalType.ROLE:
            raise RuntimeError(
                f"Role {role_seed.role_key!r} is not backed by a role principal"
            )
        role.name = role_seed.name
        role.description = role_seed.description
        return role.principal_id

    principal_id = _seed_uuid("role", role_seed.role_key)
    principal = await session.get(Principal, principal_id)
    if principal is not None:
        if principal.type != PrincipalType.ROLE:
            raise RuntimeError(
                f"Seed principal {principal_id} is not a role principal"
            )
    else:
        session.add(Principal(id=principal_id, type=PrincipalType.ROLE))
        await session.flush()

    session.add(
        Role(
            principal_id=principal_id,
            role_key=role_seed.role_key,
            name=role_seed.name,
            description=role_seed.description,
        )
    )
    await session.flush()
    return principal_id


async def _ensure_group(
    session: AsyncSession,
    group_seed: GroupSeed,
) -> UUID:
    group = await session.scalar(
        select(Group).where(Group.group_key == group_seed.group_key)
    )
    if group is not None:
        principal = await session.get(Principal, group.principal_id)
        if principal is None or principal.type != PrincipalType.GROUP:
            raise RuntimeError(
                f"Group {group_seed.group_key!r} is not backed by a group principal"
            )
        group.name = group_seed.name
        group.description = group_seed.description
        return group.principal_id

    principal_id = _seed_uuid("group", group_seed.group_key)
    principal = await session.get(Principal, principal_id)
    if principal is not None:
        if principal.type != PrincipalType.GROUP:
            raise RuntimeError(
                f"Seed principal {principal_id} is not a group principal"
            )
    else:
        session.add(Principal(id=principal_id, type=PrincipalType.GROUP))
        await session.flush()

    session.add(
        Group(
            principal_id=principal_id,
            group_key=group_seed.group_key,
            name=group_seed.name,
            description=group_seed.description,
        )
    )
    await session.flush()
    return principal_id


async def _ensure_role_permission(
    session: AsyncSession,
    *,
    role_principal_id: UUID,
    permission: Permission,
    granted_by_principal_id: UUID,
    granted_at: datetime,
) -> None:
    existing = await session.scalar(
        select(PrincipalPermission.id).where(
            PrincipalPermission.principal_id == role_principal_id,
            PrincipalPermission.permission_key == permission.value,
            PrincipalPermission.revoked_at.is_(None),
        )
    )
    if existing is not None:
        return

    session.add(
        PrincipalPermission(
            id=uuid4(),
            principal_id=role_principal_id,
            permission_key=permission.value,
            granted_at=granted_at,
            granted_by_principal_id=granted_by_principal_id,
        )
    )


async def _ensure_role_assignment(
    session: AsyncSession,
    *,
    user_principal_id: UUID,
    role_principal_id: UUID,
    assigned_by_principal_id: UUID,
    assigned_at: datetime,
) -> None:
    existing = await session.scalar(
        select(UserRole.id).where(
            UserRole.user_principal_id == user_principal_id,
            UserRole.role_principal_id == role_principal_id,
            UserRole.revoked_at.is_(None),
        )
    )
    if existing is not None:
        return

    session.add(
        UserRole(
            id=uuid4(),
            user_principal_id=user_principal_id,
            role_principal_id=role_principal_id,
            assigned_at=assigned_at,
            assigned_by_principal_id=assigned_by_principal_id,
        )
    )


async def _ensure_group_membership(
    session: AsyncSession,
    *,
    group_principal_id: UUID,
    member_principal_id: UUID,
    member_type: PrincipalType,
    added_by_principal_id: UUID,
    added_at: datetime,
) -> None:
    existing = await session.scalar(
        select(GroupMembership.id).where(
            GroupMembership.group_principal_id == group_principal_id,
            GroupMembership.member_principal_id == member_principal_id,
            GroupMembership.removed_at.is_(None),
        )
    )
    if existing is not None:
        return

    session.add(
        GroupMembership(
            id=uuid4(),
            group_principal_id=group_principal_id,
            member_principal_id=member_principal_id,
            member_type=member_type,
            added_at=added_at,
            added_by_principal_id=added_by_principal_id,
        )
    )


async def _ensure_document(
    session: AsyncSession,
    document_seed: DocumentSeed,
) -> UUID:
    document = await session.scalar(
        select(Document).where(Document.canonical_key == document_seed.canonical_key)
    )
    metadata = {
        "seed": "atlas-corp-demo",
        "department": document_seed.department,
    }
    if document is not None:
        document.title = document_seed.title
        document.description = document_seed.description
        document.document_type = document_seed.document_type
        document.department = document_seed.department
        document.default_language_code = document_seed.default_language_code
        document.metadata_ = metadata
        document.deleted_at = None
        return document.id

    document_id = _seed_uuid("document", document_seed.canonical_key)
    session.add(
        Document(
            id=document_id,
            canonical_key=document_seed.canonical_key,
            title=document_seed.title,
            description=document_seed.description,
            document_type=document_seed.document_type,
            department=document_seed.department,
            default_language_code=document_seed.default_language_code,
            metadata_=metadata,
        )
    )
    await session.flush()
    return document_id


async def _ensure_document_grant(
    session: AsyncSession,
    *,
    document_id: UUID,
    principal_id: UUID,
    permission: DocumentPermission,
    granted_by_principal_id: UUID,
    granted_at: datetime,
) -> None:
    existing = await session.scalar(
        select(DocumentACL.id).where(
            DocumentACL.document_id == document_id,
            DocumentACL.principal_id == principal_id,
            DocumentACL.permission == permission,
            DocumentACL.revoked_at.is_(None),
        )
    )
    if existing is not None:
        return

    session.add(
        DocumentACL(
            id=uuid4(),
            document_id=document_id,
            principal_id=principal_id,
            permission=permission,
            granted_at=granted_at,
            granted_by_principal_id=granted_by_principal_id,
        )
    )


def _resolve_principal_reference(
    reference: str,
    *,
    user_principal_ids: Mapping[str, UUID],
    role_principal_ids: Mapping[str, UUID],
    group_principal_ids: Mapping[str, UUID],
) -> tuple[UUID, PrincipalType]:
    principal_kind, separator, principal_key = reference.partition(":")
    if not separator or not principal_key:
        raise RuntimeError(f"Invalid seed principal reference: {reference!r}")

    if principal_kind == "user":
        principal_id = user_principal_ids.get(principal_key)
        principal_type = PrincipalType.USER
    elif principal_kind == "role":
        principal_id = role_principal_ids.get(principal_key)
        principal_type = PrincipalType.ROLE
    elif principal_kind == "group":
        principal_id = group_principal_ids.get(principal_key)
        principal_type = PrincipalType.GROUP
    else:
        raise RuntimeError(f"Unknown seed principal kind: {principal_kind!r}")

    if principal_id is None:
        raise RuntimeError(f"Unknown seed principal reference: {reference!r}")
    return principal_id, principal_type


async def _seed_database(
    *,
    demo_users: tuple[DemoUser, ...],
    user_principal_ids: Mapping[str, UUID],
    admin_principal_id: UUID,
) -> None:
    from atlasrag.platform.database.session import async_session_factory

    now = datetime.now(UTC)
    async with async_session_factory() as session:
        async with session.begin():
            role_principal_ids = {
                role_seed.role_key: await _ensure_role(session, role_seed)
                for role_seed in DEMO_ROLES
            }
            group_principal_ids = {
                group_seed.group_key: await _ensure_group(session, group_seed)
                for group_seed in DEMO_GROUPS
            }
            document_ids = {
                document_seed.canonical_key: await _ensure_document(session, document_seed)
                for document_seed in DEMO_DOCUMENTS
            }
            await session.flush()

            required_permissions = {
                permission.value
                for permissions in ROLE_PERMISSIONS.values()
                for permission in permissions
            }
            existing_permissions = set(
                (
                    await session.scalars(
                        select(PermissionDefinition.permission_key).where(
                            PermissionDefinition.permission_key.in_(required_permissions)
                        )
                    )
                ).all()
            )
            missing_permissions = required_permissions - existing_permissions
            if missing_permissions:
                missing = ", ".join(sorted(missing_permissions))
                raise RuntimeError(
                    "Required permission definitions are missing; run migrations first: "
                    f"{missing}"
                )

            for role_key, permissions in ROLE_PERMISSIONS.items():
                for permission in permissions:
                    await _ensure_role_permission(
                        session,
                        role_principal_id=role_principal_ids[role_key],
                        permission=permission,
                        granted_by_principal_id=admin_principal_id,
                        granted_at=now,
                    )

            for user in demo_users:
                user_id = user_principal_ids[user.username]
                for role_key in user.role_keys:
                    await _ensure_role_assignment(
                        session,
                        user_principal_id=user_id,
                        role_principal_id=role_principal_ids[role_key],
                        assigned_by_principal_id=admin_principal_id,
                        assigned_at=now,
                    )
                for group_key in user.group_keys:
                    await _ensure_group_membership(
                        session,
                        group_principal_id=group_principal_ids[group_key],
                        member_principal_id=user_id,
                        member_type=PrincipalType.USER,
                        added_by_principal_id=admin_principal_id,
                        added_at=now,
                    )

            for parent_group_key, child_group_key in GROUP_GROUP_MEMBERSHIPS:
                await _ensure_group_membership(
                    session,
                    group_principal_id=group_principal_ids[parent_group_key],
                    member_principal_id=group_principal_ids[child_group_key],
                    member_type=PrincipalType.GROUP,
                    added_by_principal_id=admin_principal_id,
                    added_at=now,
                )

            for document_seed in DEMO_DOCUMENTS:
                for reference, permission in document_seed.grants:
                    principal_id, _ = _resolve_principal_reference(
                        reference,
                        user_principal_ids=user_principal_ids,
                        role_principal_ids=role_principal_ids,
                        group_principal_ids=group_principal_ids,
                    )
                    await _ensure_document_grant(
                        session,
                        document_id=document_ids[document_seed.canonical_key],
                        principal_id=principal_id,
                        permission=permission,
                        granted_by_principal_id=admin_principal_id,
                        granted_at=now,
                    )


async def _run(config: SeedConfig) -> None:
    settings = get_settings()
    issuer = str(settings.KEYCLOAK_ISSUER).rstrip("/")
    demo_users = _demo_users(config)

    usernames = [user.username for user in demo_users]
    if len(usernames) != len(set(usernames)):
        raise RuntimeError("Seed user usernames must be unique")

    keycloak_users: dict[str, KeycloakUser] = {}
    async with httpx.AsyncClient(timeout=10.0) as client:
        for user in demo_users:
            user_config = replace(
                config,
                username=user.username,
                email=user.email,
                display_name=user.display_name,
                first_name=user.first_name,
                last_name=user.last_name,
            )
            keycloak_users[user.username] = await _ensure_keycloak_user(
                client,
                config=user_config,
            )

    from atlasrag.platform.database.session import async_session_factory

    user_principal_ids: dict[str, UUID] = {}
    local_users_created = 0
    for user in demo_users:
        principal_id, local_user_created = await _ensure_local_user(
            issuer=issuer,
            subject=keycloak_users[user.username].user_id,
            display_name=user.display_name,
            session_factory=async_session_factory,
        )
        user_principal_ids[user.username] = principal_id
        local_users_created += int(local_user_created)

    admin_user = demo_users[0]
    admin_keycloak_user = keycloak_users[admin_user.username]
    result = await bootstrap_superadmin(
        issuer=issuer,
        subject=admin_keycloak_user.user_id,
        session_factory=async_session_factory,
    )
    await _seed_database(
        demo_users=demo_users,
        user_principal_ids=user_principal_ids,
        admin_principal_id=user_principal_ids[admin_user.username],
    )

    keycloak_users_created = sum(user.created for user in keycloak_users.values())
    superadmin_action = "assigned" if result.assigned else "already assigned"
    print(
        f"Keycloak users created: {keycloak_users_created}/{len(demo_users)}\n"
        f"Local users created: {local_users_created}/{len(demo_users)}\n"
        f"Superadmin role {superadmin_action}: {user_principal_ids[admin_user.username]}\n"
        "Seeded roles: employee, manager, engineering_lead, hr_admin, finance_manager, "
        "superadmin\n"
        "Seeded groups: all-employees, engineering, hr, finance, operations, leadership\n"
        f"Seeded documents: {len(DEMO_DOCUMENTS)}"
    )


def _parse_args(settings: Settings) -> SeedConfig:
    default_keycloak_url, default_realm = _keycloak_endpoint(settings)
    parser = argparse.ArgumentParser(
        description="Seed a development company in Keycloak and AtlasRAG."
    )
    parser.add_argument(
        "--keycloak-url",
        default=os.getenv("ATLAS_KEYCLOAK_URL", default_keycloak_url),
    )
    parser.add_argument(
        "--realm",
        default=os.getenv("ATLAS_KEYCLOAK_REALM", default_realm),
    )
    parser.add_argument(
        "--admin-username",
        default=os.getenv(
            "ATLAS_KEYCLOAK_ADMIN_USERNAME",
            settings.KEYCLOAK_ADMIN_USERNAME or DEFAULT_KEYCLOAK_ADMIN_USERNAME,
        ),
    )
    parser.add_argument(
        "--admin-password",
        default=os.getenv(
            "ATLAS_KEYCLOAK_ADMIN_PASSWORD",
            settings.KEYCLOAK_ADMIN_PASSWORD,
        ),
    )
    parser.add_argument(
        "--username",
        default=os.getenv(
            "ATLAS_SEED_USER_USERNAME",
            settings.SEED_USER_USERNAME or DEFAULT_SEED_USERNAME,
        ),
    )
    parser.add_argument(
        "--password",
        default=os.getenv("ATLAS_SEED_USER_PASSWORD", settings.SEED_USER_PASSWORD),
    )
    parser.add_argument(
        "--email",
        default=os.getenv(
            "ATLAS_SEED_USER_EMAIL",
            settings.SEED_USER_EMAIL or DEFAULT_SEED_EMAIL,
        ),
    )
    parser.add_argument(
        "--display-name",
        default=os.getenv(
            "ATLAS_SEED_USER_DISPLAY_NAME",
            settings.SEED_USER_DISPLAY_NAME or DEFAULT_SEED_DISPLAY_NAME,
        ),
    )
    parser.add_argument(
        "--first-name",
        default=os.getenv("ATLAS_SEED_USER_FIRST_NAME", settings.SEED_USER_FIRST_NAME),
    )
    parser.add_argument(
        "--last-name",
        default=os.getenv("ATLAS_SEED_USER_LAST_NAME", settings.SEED_USER_LAST_NAME),
    )
    parser.add_argument(
        "--reset-password",
        action="store_true",
        help="Reset the password when seeded Keycloak users already exist.",
    )
    arguments = parser.parse_args()

    if not arguments.admin_password:
        parser.error(
            "--admin-password or ATLAS_KEYCLOAK_ADMIN_PASSWORD is required"
        )
    if not arguments.password:
        parser.error(
            "--password or ATLAS_SEED_USER_PASSWORD is required for all demo users"
        )

    return SeedConfig(
        keycloak_url=arguments.keycloak_url.rstrip("/"),
        realm=arguments.realm,
        admin_username=arguments.admin_username,
        admin_password=arguments.admin_password,
        username=arguments.username,
        password=arguments.password,
        email=arguments.email,
        display_name=arguments.display_name,
        first_name=arguments.first_name,
        last_name=arguments.last_name,
        reset_password=arguments.reset_password,
    )


def main() -> None:
    settings = get_settings()
    asyncio.run(_run(_parse_args(settings)))


if __name__ == "__main__":
    main()
