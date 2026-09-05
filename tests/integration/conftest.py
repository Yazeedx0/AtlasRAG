import os
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from uuid import uuid4

import aioboto3
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from testcontainers.core.container import DockerContainer
from testcontainers.core.wait_strategies import HttpWaitStrategy
from testcontainers.postgres import PostgresContainer

from atlasrag.modules.identity import models as _identity_models  # noqa: F401
from atlasrag.modules.ingestion import models as _ingestion_models  # noqa: F401
from atlasrag.modules.knowledge import models as _knowledge_models  # noqa: F401
from atlasrag.platform.database import Base
from atlasrag.platform.jobs import models as _job_models  # noqa: F401
from atlasrag.platform.storage import MinioObjectStorage

_MINIO_IMAGE = "minio/minio:RELEASE.2025-04-22T22-12-26Z"
_MINIO_ACCESS_KEY = "atlas-test"
_MINIO_SECRET_KEY = "atlas-test-password"
_MINIO_BUCKET = "atlasrag-tests"
_MINIO_PORT = 9000
_MINIO_REGION = "us-east-1"


@dataclass(frozen=True, slots=True)
class MinioTestConfig:
    endpoint_url: str
    access_key: str
    secret_key: str
    bucket: str
    region: str


def _asyncpg_url(url: str) -> str:
    if url.startswith("postgresql+asyncpg://"):
        return url
    if url.startswith("postgresql+psycopg2://"):
        return "postgresql+asyncpg://" + url.removeprefix("postgresql+psycopg2://")
    return "postgresql+asyncpg://" + url.removeprefix("postgresql://")


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    configured_url = os.getenv("ATLAS_TEST_DATABASE_URL")
    if configured_url is not None:
        yield _asyncpg_url(configured_url)
        return

    with PostgresContainer("postgres:16-alpine") as postgres:
        yield _asyncpg_url(postgres.get_connection_url())


@pytest.fixture(scope="session")
def minio_test_config() -> Iterator[MinioTestConfig]:
    container = (
        DockerContainer(_MINIO_IMAGE)
        .with_exposed_ports(_MINIO_PORT)
        .with_env("MINIO_ROOT_USER", _MINIO_ACCESS_KEY)
        .with_env("MINIO_ROOT_PASSWORD", _MINIO_SECRET_KEY)
        .with_command(f"server /data --address :{_MINIO_PORT}")
        .waiting_for(
            HttpWaitStrategy(_MINIO_PORT, "/minio/health/live").with_startup_timeout(60)
        )
    )
    with container:
        host = container.get_container_host_ip()
        port = container.get_exposed_port(_MINIO_PORT)
        yield MinioTestConfig(
            endpoint_url=f"http://{host}:{port}",
            access_key=_MINIO_ACCESS_KEY,
            secret_key=_MINIO_SECRET_KEY,
            bucket=_MINIO_BUCKET,
            region=_MINIO_REGION,
        )


@pytest_asyncio.fixture
async def minio_object_storage(
    minio_test_config: MinioTestConfig,
) -> AsyncIterator[MinioObjectStorage]:
    bucket = f"{minio_test_config.bucket}-{uuid4().hex}"
    session = aioboto3.Session()
    async with session.client(
        "s3",
        endpoint_url=minio_test_config.endpoint_url,
        use_ssl=False,
        aws_access_key_id=minio_test_config.access_key,
        aws_secret_access_key=minio_test_config.secret_key,
        region_name=minio_test_config.region,
    ) as client:
        await client.create_bucket(Bucket=bucket)

    yield MinioObjectStorage(
        endpoint_url=minio_test_config.endpoint_url,
        use_ssl=False,
        access_key=minio_test_config.access_key,
        secret_key=minio_test_config.secret_key,
        bucket=bucket,
        region=minio_test_config.region,
    )


@pytest_asyncio.fixture
async def identity_database(
    postgres_url: str,
) -> AsyncIterator[tuple[AsyncEngine, async_sessionmaker[AsyncSession]]]:
    engine = create_async_engine(postgres_url, pool_pre_ping=True)

    async with engine.begin() as connection:
        await connection.execute(text("CREATE SCHEMA IF NOT EXISTS iam"))
        await connection.execute(text("CREATE SCHEMA IF NOT EXISTS knowledge"))
        await connection.execute(text("CREATE SCHEMA IF NOT EXISTS platform"))
        await connection.execute(text("CREATE EXTENSION IF NOT EXISTS btree_gist"))
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(
        bind=engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    try:
        yield engine, session_factory
    finally:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
        await engine.dispose()
