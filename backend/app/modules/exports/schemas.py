from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class ExportTaskCreate(BaseModel):
    itinerary_id: str
    version_id: str | None = None
    version_no: int | None = Field(default=None, ge=1)
    format: Literal["docx"] = "docx"

    @model_validator(mode="after")
    def require_version_reference(self) -> "ExportTaskCreate":
        if not self.version_id and self.version_no is None:
            raise ValueError("version_id or version_no is required")
        return self


class ExportTaskResponse(BaseModel):
    id: str
    itinerary_id: str
    version_no: int
    format: Literal["docx"]
    status: str
    progress: int
    output_available: bool
    attempt_count: int
    last_error_code: str | None
    last_error_message: str | None
    finished_at: datetime | None
    expires_at: datetime | None


class ExportDownloadUrlResponse(BaseModel):
    url: str
    expires_at: datetime
