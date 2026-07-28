"""AGV 调度接口测试。

验证：
    1. service 层 call_agv 构造正确请求体 + 校验响应
    2. service 层 handle_arrived 记录日志 + 返回确认
    3. HTTP /api/v1/agv/arrived 回调接口返回对方期望格式（不包 Result）
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from bsd_unitree_controller.core.config import AgvConfig
from bsd_unitree_controller.exception.exceptions import UpstreamException
from bsd_unitree_controller.service.agv_service import AgvService

from main import app


# ── service 层测试 ─────────────────────────────────────────────

class _MockHttpClient:
    """模拟 HttpClient，记录收到的请求，返回预设响应。"""

    def __init__(self, response_data: dict, status_code: int = 200):
        self._response_data = response_data
        self._status_code = status_code
        self.calls: list[tuple[str, dict]] = []

    def post(self, url: str, *, json=None, **kwargs):
        self.calls.append((url, json))
        # 模拟 httpx.Response
        class _MockResp:
            def __init__(self, data, code):
                self._data = data
                self.status_code = code
            def json(self):
                return self._data
        return _MockResp(self._response_data, self._status_code)


def test_call_agv_success() -> None:
    """呼叫成功：对方返回 success=true，service 返回 workstation + 响应。"""
    mock = _MockHttpClient({"code": 0, "message": "", "success": True, "result": {}, "timestamp": 0})
    cfg = AgvConfig(workstation="W03")
    svc = AgvService(config=cfg, http_client=mock)

    result = svc.call_agv()

    assert result["workstation"] == "W03"
    assert result["response"]["success"] is True
    # 校验请求体
    assert len(mock.calls) == 1
    url, payload = mock.calls[0]
    assert url == "https://gwwms.bsdits.cn/wcs/hikagv/callRobotComeByType"
    assert payload["workstation"] == "W03"
    assert payload["podCategory"] == "1"
    assert payload["barcode"] == ""


def test_call_agv_failure_raises() -> None:
    """呼叫失败：对方返回 success=false，service 抛 UpstreamException。"""
    mock = _MockHttpClient({"code": 1, "message": "工位不存在", "success": False})
    cfg = AgvConfig(workstation="W99")
    svc = AgvService(config=cfg, http_client=mock)

    try:
        svc.call_agv()
        assert False, "应抛 UpstreamException"
    except UpstreamException as e:
        assert "AGV 调度系统返回失败" in e.message


def test_handle_arrived_returns_success() -> None:
    """到位回调：service 返回 success=true。"""
    mock = _MockHttpClient({})
    cfg = AgvConfig()
    svc = AgvService(config=cfg, http_client=mock)

    result = svc.handle_arrived({"workstation": "W03", "agv_id": "AGV001"})

    assert result["success"] is True
    assert "到位" in result["message"]


# ── HTTP 入口测试 ──────────────────────────────────────────────

def test_agv_arrived_endpoint_returns_raw_dict() -> None:
    """AGV 到位回调接口直接返回 dict（不包 Result），符合对方期望。"""
    with TestClient(app) as client:
        resp = client.post("/api/v1/agv/arrived", json={"workstation": "W03"})

        assert resp.status_code == 200
        body = resp.json()
        # 不包 Result，直接是 {"success": true, "message": "..."}
        assert body["success"] is True
        assert "message" in body
