import asyncio
from typing import cast

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from atlasrag.bootstrap.core.config import get_settings
from atlasrag.contracts.permissions import Permission


async def read_permission_seed(database_url: str) -> tuple[set[str], set[str]]:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            permission_keys = {
                str(value)
                for value in await connection.scalars(
                    text("SELECT permission_key FROM iam.permissions")
                )
            }
            superadmin_permission_keys = {
                str(value)
                for value in await connection.scalars(
                    text(
                        "SELECT pp.permission_key "
                        "FROM iam.principal_permissions AS pp "
                        "JOIN iam.roles AS r ON r.principal_id = pp.principal_id "
                        "WHERE r.role_key = 'superadmin' AND pp.revoked_at IS NULL"
                    )
                )
            }
        return permission_keys, superadmin_permission_keys
    finally:
        await engine.dispose()


async def read_downgrade_state(database_url: str) -> tuple[str | None, int]:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            permission_table = cast(
                str | None,
                await connection.scalar(
                    text("SELECT to_regclass('iam.permissions')::text")
                ),
            )
            superadmin_count = await connection.scalar(
                text("SELECT count(*) FROM iam.roles WHERE role_key = 'superadmin'")
            )
        return permission_table, int(superadmin_count or 0)
    finally:
        await engine.dispose()


@pytest.mark.integration
def test_permission_migration_upgrade_seeds_all_capabilities_and_downgrades(
    postgres_url: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ATLAS_DATABASE_URL", postgres_url)
    get_settings.cache_clear()
    configuration = Config("alembic.ini")

    try:
        command.upgrade(configuration, "0013")

        permission_keys, superadmin_permission_keys = asyncio.run(
            read_permission_seed(postgres_url)
        )
        expected_keys = {permission.value for permission in Permission}
        assert permission_keys == expected_keys
        assert superadmin_permission_keys == expected_keys

        command.downgrade(configuration, "0012")

        permission_table, superadmin_count = asyncio.run(
            read_downgrade_state(postgres_url)
        )
        assert permission_table is None
        assert superadmin_count == 0
    finally:
        command.downgrade(configuration, "base")
        get_settings.cache_clear()
