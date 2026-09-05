import aioboto3
from botocore.exceptions import BotoCoreError, ClientError

from atlasrag.contracts.error.object_storage_errors import (
    ObjectNotFound,
    ObjectStorageUnavailable,
)

_NOT_FOUND_ERROR_CODES = frozenset({"NoSuchKey", "404"})


class MinioObjectStorage:
    def __init__(
        self,
        *,
        endpoint_url: str,
        use_ssl: bool,
        access_key: str,
        secret_key: str,
        bucket: str,
        region: str,
    ) -> None:
        self._bucket = bucket
        self._session = aioboto3.Session()
        self._client_kwargs = {
            "service_name": "s3",
            "endpoint_url": endpoint_url,
            "use_ssl": use_ssl,
            "aws_access_key_id": access_key,
            "aws_secret_access_key": secret_key,
            "region_name": region,
        }

    async def put(
        self,
        *,
        key: str,
        content: bytes,
        content_type: str,
    ) -> None:
        async with self._session.client(**self._client_kwargs) as client:
            await client.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=content,
                ContentType=content_type,
            )

    async def get(
        self,
        *,
        key: str,
    ) -> bytes:
        try:
            async with self._session.client(**self._client_kwargs) as client:
                response = await client.get_object(Bucket=self._bucket, Key=key)
                async with response["Body"] as body:
                    return await body.read()
        except ClientError as error:
            if _is_not_found(error):
                raise ObjectNotFound(key=key) from error
            raise ObjectStorageUnavailable(operation="get", key=key) from error
        except BotoCoreError as error:
            raise ObjectStorageUnavailable(operation="get", key=key) from error

    async def delete(
        self,
        *,
        key: str,
    ) -> None:
        async with self._session.client(**self._client_kwargs) as client:
            await client.delete_object(Bucket=self._bucket, Key=key)

    async def exists(
        self,
        *,
        key: str,
    ) -> bool:
        async with self._session.client(**self._client_kwargs) as client:
            try:
                await client.head_object(Bucket=self._bucket, Key=key)
            except ClientError as error:
                if _is_not_found(error):
                    return False
                raise
            return True


def _is_not_found(error: ClientError) -> bool:
    code = error.response.get("Error", {}).get("Code")
    return code in _NOT_FOUND_ERROR_CODES


__all__ = ["MinioObjectStorage"]
