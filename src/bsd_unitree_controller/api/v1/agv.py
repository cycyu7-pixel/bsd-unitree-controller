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
from bsd_unitree_controller.model.response import Result
from bsd_unitree_controller.service.agv_service import AgvService

router = APIRouter(prefix="/agv", tags=["AGV 调度"])


# ── AGV 到位回调入参 ──────────────────────────────────────────
# 对方回调传什么字段未完全确定，先用宽松的 dict 接收
# 后续确认对方格式后可改成具体字段

class AgvArrivedDTO(BaseModel):
    """AGV 到位回调入参。

    字段宽松接收，对方传什么都进来，service 层记录日志。
    后续确认对方格式后可细化字段。
    """

    model_config = {"extra": "allow"}  # 允许额外字段，不校验

    workstation: str | None = Field(None, description="工位号（对方可能传）")


# ── 呼叫 AGV ─────────────────────────────────────────────────

@router.post("/call", summary="呼叫 AGV 小车")
def call_agv(
    http_client: HttpClient = Depends(get_http_client),
) -> Result[dict]:
    """呼叫 AGV 小车到配置的工位。

    工位号从 config.yaml 的 agv.workstation 读取，不从前端传参。
    调用 AGV 调度系统接口，对方返回 success=true 表示呼叫成功。
    小车实际到位后会回调 /api/v1/agv/arrived 通知本服务。

    Returns:
        Result，data 含 workstation 和对方返回的原始响应。

    Raises:
        UpstreamException: AGV 调度系统返回失败时抛出（code=50001）。
    """
    service = AgvService(config=_global_config.agv, http_client=http_client)
    data = service.call_agv()
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
