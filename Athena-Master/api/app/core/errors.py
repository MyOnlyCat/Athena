import logging

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

logger = logging.getLogger(__name__)


class AppError(Exception):
    def __init__(self, code: str, message: str, *, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": exc.code, "message": exc.message},
    )


async def http_error_handler(_: Request, exc: HTTPException) -> JSONResponse:
    errors = {
        404: ("NOT_FOUND", "请求的资源不存在"),
        405: ("METHOD_NOT_ALLOWED", "请求方法不受支持"),
    }
    code, message = errors.get(exc.status_code, ("HTTP_ERROR", "请求处理失败"))
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": code, "message": message},
    )


async def validation_error_handler(_: Request, __: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={"code": "INVALID_REQUEST", "message": "请求参数无效"},
    )


async def temporary_unavailable_handler(
    _: Request,
    exc: Exception,
) -> JSONResponse:
    logger.error("Master database operation failed (%s)", type(exc).__name__)
    return JSONResponse(
        status_code=503,
        content={
            "code": "MASTER_TEMPORARILY_UNAVAILABLE",
            "message": "主节点暂时不可用，请稍后重试",
        },
    )
