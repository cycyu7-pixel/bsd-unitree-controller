"""AGV 调度接口路由。

包含两个接口：
    - POST /api/v1/agv/call     呼叫 AGV 小车到工位
    - POST /api/v1/agv/arrived  AGV 到位回调（对方调我们）

本层只做：参数接收 -> 调 service -> 包装返回，不写业务逻辑。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from bsd_unitree_controller.client.http_client import HttpClient
from bsd_unitree_controller.core.config import config as _global_config
from bsd_unitree_controller.core.deps import get_http_client
from bsd_unitree_controller.model.dto import AgvCallDTO, AgvReturnDTO
from bsd_unitree_controller.model.response import Result
from bsd_unitree_controller.service.agv_service import AgvService

router = APIRouter(prefix="/agv", tags=["AGV 调度"])


# ── AGV 到位回调入参 ──────────────────────────────────────────
# 对方回调参数格式：{"workstation":"W03","container":"T0383614"}

class AgvArrivedDTO(BaseModel):
    """AGV 到位回调入参。

    对方（AGV 调度系统）回调时传一大堆字段，本系统当前只关心 container。
    workstation 对方不一定传，设为可选，缺失时用空串占位。
    其余字段靠 extra="allow" 自动接收，不校验也不报错。
    """

    model_config = {"extra": "allow"}  # 允许额外字段，兼容对方传 taskCode/robotId 等一大堆字段

    workstation: str | None = Field(None, description="工位号，对方不一定传")
    container: str = Field(..., description="容器/货架编号")


# ── 呼叫 AGV ─────────────────────────────────────────────────

@router.post("/call", summary="呼叫 AGV 小车")
def call_agv(
    dto: AgvCallDTO | None = None,
    http_client: HttpClient = Depends(get_http_client),
) -> Result[dict]:
    """呼叫 AGV 小车到配置的工位。

    所有字段可选，不传时用默认值，传了就覆盖。
    - barcode: 默认空字符串
    - podCategory: 默认 "2"
    - workstation: 默认从 config.yaml 读取

    Returns:
        Result，data 含实际使用的 workstation 和对方返回的原始响应。

    Raises:
        UpstreamException: AGV 调度系统返回失败时抛出（code=50001）。
    """
    service = AgvService(config=_global_config.agv, http_client=http_client)
    data = service.call_agv(dto)
    return Result.ok(data=data)


# ── AGV 到位回调 ─────────────────────────────────────────────

@router.post("/arrived", summary="AGV 到位回调")
def agv_arrived(
    dto: AgvArrivedDTO,
    http_client: HttpClient = Depends(get_http_client),
) -> dict:
    """AGV 到位回调接口。

    AGV 小车到位后，调度系统调本接口通知。
    本接口按对方期望格式返回 {"success": true, "message": "..."}，
    **不包 Result**，直接返回原始 dict。

    Args:
        dto: 回调入参，字段宽松接收。

    Returns:
        dict，{"success": true, "message": "AGV 到位通知已接收"}。
    """
    service = AgvService(config=_global_config.agv, http_client=http_client)
    return service.handle_arrived(dto.model_dump())


# ── AGV 返库 ─────────────────────────────────────────────────

@router.post("/return", summary="AGV 返库")
def return_agv(
    dto: AgvReturnDTO | None = None,
    http_client: HttpClient = Depends(get_http_client),
) -> Result[dict]:
    """触发 AGV 返库。

    所有字段可选，不传时用默认值，传了就覆盖。
    - podCategory: 默认空字符串
    - podNo: 默认用到位回调缓存的 container
    - type: 默认 "FK"
    - workstationNo: 默认从 config.yaml 读取

    Returns:
        Result，data 含实际使用的 workstation、container 和对方返回的原始响应。

    Raises:
        BizException: 无 container 可用时抛出（code=50004）。
        UpstreamException: AGV 调度系统返回失败时抛出（code=50001）。
    """
    service = AgvService(config=_global_config.agv, http_client=http_client)
    data = service.return_agv(dto)
    return Result.ok(data=data)
