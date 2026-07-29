from typing import Any

from fastapi import Request
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse

HTTP_MESSAGES = {
    404: ("HTTP_NOT_FOUND", "请求的资源不存在"),
    405: ("HTTP_METHOD_NOT_ALLOWED", "请求方法不受支持"),
}


class AppError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 400,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}


def error_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    request_id = request.state.request_id
    return JSONResponse(
        status_code=status_code,
        content={
            "code": code,
            "message": message,
            "request_id": request_id,
            "details": details or {},
        },
        headers={"X-Request-Id": request_id},
    )


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    return error_response(
        request,
        status_code=exc.status_code,
        code=exc.code,
        message=exc.message,
        details=exc.details,
    )


async def http_error_handler(request: Request, exc: HTTPException) -> JSONResponse:
    code, message = HTTP_MESSAGES.get(
        exc.status_code,
        ("HTTP_ERROR", str(exc.detail)),
    )
    return error_response(
        request,
        status_code=exc.status_code,
        code=code,
        message=message,
    )
