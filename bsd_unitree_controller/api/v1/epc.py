"""EPC 条码读取接口路由。

包含两个接口：
    - POST /api/v1/epc/start-scan  发起 EPC 扫描
    - POST /api/v1/epc/callback    EPC 扫描结果回调（RFID 服务调我们）

本层只做：参数接收 -> 调 service -> 包装返回，不写业务逻辑。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from bsd_unitree_controller.client.http_client import HttpClient
from bsd_unitree_controller.core.config import config as _global_config
from bsd_unitree_controller.core.deps import get_http_client
from bsd_unitree_controller.model.dto import EpcCallbackDTO
from bsd_unitree_controller.model.response import Result
from bsd_unitree_controller.service.epc_service import EpcService

router = APIRouter(prefix="/epc", tags=["EPC 条码读取"])


# ── 发起 EPC 扫描 ──────────────────────────────────────────────

@router.post("/start-scan", summary="发起 EPC 扫描")
def start_scan(
    http_client: HttpClient = Depends(get_http_client),
) -> Result[dict]:
    """调用 RFID 服务发起 EPC 扫描，返回 requestId。

    RFID 服务异步扫描 EPC 条码，扫描完成后会回调 /api/v1/epc/callback。
    超时 35s 未读到 EPC 也算失败，回调中 error 字段不为 null。

    Returns:
        Result，data 含 requestId，供回调时匹配。

    Raises:
        UpstreamException: RFID 服务调用失败或返回失败时抛出（code=50001）。
    """
    svc = EpcService(config=_global_config.epc, http_client=http_client)
    data = svc.start_scan()
    return Result.ok(data=data)


# ── EPC 扫描结果回调 ───────────────────────────────────────────

@router.post("/callback", summary="EPC 扫描结果回调")
def epc_callback(
    dto: EpcCallbackDTO,
    http_client: HttpClient = Depends(get_http_client),
) -> dict:
    """接收 RFID 服务扫描结果回调。

    RFID 读写器扫描到 EPC 条码或超时失败后，RFID 服务调本接口通知。
    本接口按对方期望格式返回 {"success": true, "message": "..."}，
    **不包 Result**，直接返回原始 dict。
    扫描失败时会自动重新发起扫描（次数受 MAX_RETRIES 限制），因此需要 http_client。

    Args:
        dto: 回调入参，含 requestId、epc、error。

    Returns:
        dict，{"success": true, "message": "..."}。
    """
    svc = EpcService(config=_global_config.epc, http_client=http_client)
    return svc.handle_callback(dto)