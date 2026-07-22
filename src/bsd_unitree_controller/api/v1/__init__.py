"""v1 版本路由汇总入口。

本包下每个业务模块一个 router 文件，在此汇总成 `v1_router`，
供 `api/__init__.py` 再聚合到 `api_router` 上。
"""
from __future__ import annotations

from fastapi import APIRouter

from bsd_unitree_controller.api.v1.estop import router as estop_router
from bsd_unitree_controller.api.v1.health import router as health_router
from bsd_unitree_controller.api.v1.motion import router as motion_router

# v1 版本总路由，不在这里加 prefix，由上层 api_router 统一加 /api/v1
v1_router = APIRouter()
v1_router.include_router(health_router)
v1_router.include_router(motion_router)
v1_router.include_router(estop_router)
