from __future__ import annotations

import hashlib
import os
from uuid import uuid4

import httpx
import pytest

from app.core.settings import Settings
from app.integrations.object_storage.s3 import S3ObjectStorage


RUN_MINIO_INTEGRATION_TESTS = os.getenv("RUN_MINIO_INTEGRATION_TESTS", "").lower() == "true"
IMAGE_JPEG_MIME_TYPE = "image/jpeg"
# Fixed valid JPEG bytes keep the expected metadata hash deterministic.
JPEG_BYTES = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xd9"
JPEG_SHA256 = hashlib.sha256(JPEG_BYTES).hexdigest()


@pytest.mark.anyio
@pytest.mark.skipif(
    not RUN_MINIO_INTEGRATION_TESTS,
    reason="Set RUN_MINIO_INTEGRATION_TESTS=true to run MinIO integration tests.",
)
async def test_s3_media_direct_presigned_put_and_head() -> None:
    """Exercise the browser-style direct upload contract against configured private storage."""
    key = f"media/integration-smoke/{uuid4()}.jpg"
    storage = S3ObjectStorage(Settings())

    try:
        upload_url = await storage.presign_put(
            key=key,
            mime_type=IMAGE_JPEG_MIME_TYPE,
            sha256=JPEG_SHA256,
            expires_in=300,
        )
        async with httpx.AsyncClient() as client:
            response = await client.put(
                upload_url,
                content=JPEG_BYTES,
                headers={
                    "Content-Type": IMAGE_JPEG_MIME_TYPE,
                    "x-amz-meta-sha256": JPEG_SHA256,
                },
            )

        # Do not include the response body or request URL in assertion output: it contains the signature.
        assert response.status_code in {200, 204}

        size, mime_type, etag, stored_digest = await storage.head_object(key=key)
        assert size == len(JPEG_BYTES)
        assert mime_type == IMAGE_JPEG_MIME_TYPE
        assert etag
        assert stored_digest == JPEG_SHA256
    finally:
        await storage.delete_object(key=key)
