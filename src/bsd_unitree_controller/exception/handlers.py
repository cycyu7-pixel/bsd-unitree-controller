"""全局异常处理器。

类比 Spring Boot 的 @RestControllerAdvice + @ExceptionHandler：
把各种异常统一转成 Result.fail() 返回给调用方，避免堆栈外泄。
"""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from loguru import logger

from bsd_unitree_controller.exception.exceptions import BizException
from bsd_unitree_controller.model.response import Result


def register_exception_handlers(app: FastAPI) -> None:
    """在 FastAPI app 上注册全局异常处理器。"""

    # ── 业务异常：按异常自带的 code/message 返回 ──────────────────
    @app.exception_handler(BizException)
    async def handle_biz_exception(_: Request, exc: BizException):
        logger.warning("业务异常: {}", exc)
        return JSONResponse(
            status_code=200,                       # HTTP 层面仍返回 200
            content=Result.fail(code=exc.code, message=exc.message).model_dump(),
        )

    # ── 参数校验异常：FastAPI 自动抛出，统一转 400 ────────────────
    @app.exception_handler(RequestValidationError)
    async def handle_validation_exception(_: Request, exc: RequestValidationError):
        logger.warning("参数校验失败: {}", exc.errors())
        return JSONResponse(
            status_code=200,
            content=Result.fail(code=400, message="参数校验失败", data=exc.errors()).model_dump(),
        )

    # ── 兜底异常：未捕获的异常，避免堆栈外泄 ─────────────────────
    @app.exception_handler(Exception)
    async def handle_unexpected_exception(_: Request, exc: Exception):
        logger.exception("未捕获异常: {}", exc)
        return JSONResponse(
            status_code=500,
            content=Result.fail(code=500, message="服务器内部错误").model_dump(),
        )
