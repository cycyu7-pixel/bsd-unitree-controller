"""对外 HTTP 接口层。

类比 Spring Boot 的 @RestController：负责接收上游系统的 HTTP 请求，
做参数解析后调 service 层，本层不写业务逻辑。

路由汇总入口在 `api_router`，由 server.py 一次性挂到 FastAPI app 上。
版本前缀在 `api_router` 上统一加，避免散落在各业务模块。
"""
from __future__ import annotations

from fastapi import APIRouter

from bsd_unitree_controller.api.v1 import v1_router

# 顶层 API 路由，统一加版本前缀
api_router = APIRouter(prefix="/api/v1")
api_router.include_router(v1_router)
