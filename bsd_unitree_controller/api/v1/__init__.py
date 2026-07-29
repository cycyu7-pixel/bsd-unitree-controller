"""v1 版本路由汇总入口。

本包下每个业务模块一个 router 文件，在此汇总成 `v1_router`，
供 `api/__init__.py` 再聚合到 `api_router` 上。
"""
from __future__ import annotations

from fastapi import APIRouter

from bsd_unitree_controller.api.v1.agv import router as agv_router
from bsd_unitree_controller.api.v1.controller import router as controller_router

# v1 版本总路由，不在这里加 prefix，由上层 api_router 统一加 /api/v1
v1_router = APIRouter()
v1_router.include_router(controller_router)
v1_router.include_router(agv_router)
