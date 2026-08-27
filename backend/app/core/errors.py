from typing import Any

from fastapi import Request
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field
from starlette.responses import JSONResponse

from app.core.request_context import get_request_id


class ErrorResponse(BaseModel):
    code: str
    message: str
    request_id: str
    details: dict[str, Any] = Field(default_factory=dict)


def error_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    payload = ErrorResponse(
        code=code,
        message=message,
        request_id=get_request_id(request),
        details=details or {},
    )
    return JSONResponse(status_code=status_code, content=jsonable_encoder(payload.model_dump()))
