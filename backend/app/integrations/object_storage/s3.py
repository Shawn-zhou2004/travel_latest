import asyncio
from typing import Protocol

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from app.core.settings import Settings


class StorageUnavailable(Exception):
    pass


class ObjectStorage(Protocol):
    async def presign_put(self, *, key: str, mime_type: str, sha256: str, expires_in: int) -> str: ...

    async def head_object(self, *, key: str) -> tuple[int, str, str, str | None]: ...

    async def presign_get(self, *, key: str, expires_in: int) -> str: ...

    async def presign_attachment_get(self, *, key: str, filename: str, expires_in: int) -> str: ...

    async def upload_bytes(self, *, key: str, data: bytes, mime_type: str, sha256: str) -> str: ...

    async def delete_object(self, *, key: str) -> None: ...


class S3ObjectStorage:
    def __init__(self, settings: Settings | None = None, *, bucket: str | None = None) -> None:
        settings = settings or Settings()
        selected_bucket = bucket or settings.s3_bucket_private
        missing = [
            name
            for name, value in (
                ("s3_endpoint_url", settings.s3_endpoint_url),
                ("s3_region", settings.s3_region),
                ("s3_access_key_id", settings.s3_access_key_id),
                ("s3_secret_access_key", settings.s3_secret_access_key),
                ("s3_bucket", selected_bucket),
            )
            if not value
        ]
        if missing:
            raise StorageUnavailable("Private object storage is not configured.")
        self.bucket = selected_bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            region_name=settings.s3_region,
            aws_access_key_id=settings.s3_access_key_id,
            aws_secret_access_key=settings.s3_secret_access_key,
            config=Config(s3={"addressing_style": "path" if settings.s3_use_path_style else "virtual"}),
        )

    async def presign_put(self, *, key: str, mime_type: str, sha256: str, expires_in: int) -> str:
        return await self._call(
            self.client.generate_presigned_url,
            "put_object",
            Params={"Bucket": self.bucket, "Key": key, "ContentType": mime_type, "Metadata": {"sha256": sha256}},
            ExpiresIn=expires_in,
            HttpMethod="PUT",
        )

    async def head_object(self, *, key: str) -> tuple[int, str, str, str | None]:
        response = await self._call(self.client.head_object, Bucket=self.bucket, Key=key)
        return (
            response["ContentLength"],
            response.get("ContentType", ""),
            response.get("ETag", "").strip('"'),
            response.get("Metadata", {}).get("sha256"),
        )

    async def presign_get(self, *, key: str, expires_in: int) -> str:
        return await self._call(
            self.client.generate_presigned_url,
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=expires_in,
        )

    async def presign_attachment_get(self, *, key: str, filename: str, expires_in: int) -> str:
        return await self._call(
            self.client.generate_presigned_url,
            "get_object",
            Params={
                "Bucket": self.bucket,
                "Key": key,
                "ResponseContentDisposition": f'attachment; filename="{filename}"',
                "ResponseContentType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            },
            ExpiresIn=expires_in,
        )

    async def upload_bytes(self, *, key: str, data: bytes, mime_type: str, sha256: str) -> str:
        response = await self._call(
            self.client.put_object,
            Bucket=self.bucket,
            Key=key,
            Body=data,
            ContentType=mime_type,
            Metadata={"sha256": sha256},
        )
        return str(response.get("ETag", "")).strip('"')  # type: ignore[union-attr]

    async def delete_object(self, *, key: str) -> None:
        await self._call(self.client.delete_object, Bucket=self.bucket, Key=key)

    @staticmethod
    async def _call(function: object, *args: object, **kwargs: object) -> object:
        try:
            return await asyncio.to_thread(function, *args, **kwargs)  # type: ignore[arg-type]
        except (BotoCoreError, ClientError) as error:
            raise StorageUnavailable("Private object storage is unavailable.") from error
