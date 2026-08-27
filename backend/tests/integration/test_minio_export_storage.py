from __future__ import annotations

import hashlib
import os
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import pytest

from app.core.settings import Settings
from app.integrations.object_storage.s3 import S3ObjectStorage


RUN_MINIO_INTEGRATION_TESTS = os.getenv("RUN_MINIO_INTEGRATION_TESTS", "").lower() == "true"
DOCX_MIME_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@pytest.mark.anyio
@pytest.mark.skipif(
    not RUN_MINIO_INTEGRATION_TESTS,
    reason="Set RUN_MINIO_INTEGRATION_TESTS=true to run MinIO integration tests.",
)
async def test_s3_export_object_upload_head_and_attachment_presign() -> None:
    """Exercise configured private storage without downloading the presigned URL."""
    payload = b"PK\x03\x04minio-export-smoke-docx"
    digest = hashlib.sha256(payload).hexdigest()
    filename = "minio-export-smoke.docx"
    key = f"exports/integration-smoke/{uuid4()}.docx"
    storage = S3ObjectStorage(Settings())

    try:
        await storage.upload_bytes(key=key, data=payload, mime_type=DOCX_MIME_TYPE, sha256=digest)

        size, mime_type, etag, stored_digest = await storage.head_object(key=key)
        assert size == len(payload)
        assert mime_type == DOCX_MIME_TYPE
        assert etag
        assert stored_digest == digest

        presigned_url = await storage.presign_attachment_get(key=key, filename=filename, expires_in=300)
        parsed_url = urlparse(presigned_url)
        query = parse_qs(parsed_url.query)
        assert parsed_url.scheme in {"http", "https"}
        assert parsed_url.netloc
        assert query.get("response-content-disposition") == [f'attachment; filename="{filename}"']
        assert query.get("response-content-type") == [DOCX_MIME_TYPE]
    finally:
        await storage.delete_object(key=key)
