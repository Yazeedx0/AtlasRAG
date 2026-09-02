import asyncio
import re
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from alembic.operations.ops import MigrationScript
from sqlalchemy import Connection, pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from atlasrag import get_settings
from atlasrag.modules.identity import models as _identity_models  # noqa: F401
from atlasrag.modules.ingestion import models as _ingestion_models  # noqa: F401
from atlasrag.modules.knowledge import models as _knowledge_models  # noqa: F401
from atlasrag.platform.database import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


target_metadata = Base.metadata

REVISION_RE = re.compile(r"^(\d{4})\.py$")


def _next_revision_id() -> str:
    script_location = config.get_main_option("script_location")
    assert script_location is not None
    versions_dir = Path(script_location) / "versions"
    existing = [
        int(match.group(1))
        for f in versions_dir.glob("*.py")
        if (match := REVISION_RE.match(f.name))
    ]
    return f"{(max(existing, default=0) + 1):04d}"


def process_revision_directives(context, revision, directives: list[MigrationScript]) -> None:
    script = directives[0]
    next_id = _next_revision_id()
    script.rev_id = next_id
    if script.version_path is not None:
        script.version_path = str(Path(script.version_path).with_name(f"{next_id}.py"))


def get_database_url() -> str:
    return str(get_settings().DATABASE_URL)


def run_migrations_offline() -> None:
    context.configure(
        url=get_database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        process_revision_directives=process_revision_directives,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_schemas=True,
        process_revision_directives=process_revision_directives,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = get_database_url()

    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
