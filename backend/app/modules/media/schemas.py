from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class UploadRequestCreate(BaseModel):
    purpose: str = Field(min_length=1, max_length=64)
    mime_type: Literal["image/jpeg", "image/png", "image/webp"]
    size_bytes: int = Field(gt=0, le=10 * 1024 * 1024)
    sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")


class UploadRequestResponse(BaseModel):
    asset_id: str
    upload_url: str
    headers: dict[str, str]
    expires_at: datetime


class UploadCompletionRequest(BaseModel):
    etag: str = Field(min_length=1, max_length=128)
    size_bytes: int = Field(gt=0, le=10 * 1024 * 1024)


class MediaAssetResponse(BaseModel):
    id: str
    status: str
    mime_type: str
    size_bytes: int


class DownloadUrlResponse(BaseModel):
    url: str
    expires_at: datetime
