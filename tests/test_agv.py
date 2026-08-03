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

from bsd_unitree_controller.api.server import create_app
from bsd_unitree_controller.core.config import load_config

app = create_app(load_config())


# ── service 层测试 ─────────────────────────────────────────────

class _MockHttpClient:
    """模拟 HttpClient，记录收到的请求，返回预设响应。"""

    def __init__(self, response_data: dict, status_code: int = 200):
        self._response_data = response_data
        self._status_code = status_code
        self.calls: list[tuple[str, dict, dict]] = []  # (url, json, headers)

    def post(self, url: str, *, json=None, headers=None, **kwargs):
        self.calls.append((url, json, headers or {}))
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
    url, payload, headers = mock.calls[0]
    assert url == "https://gwwms.bsdits.cn/wcs/hikagv/callRobotComeByType"
    assert payload["workstation"] == "W03"
    assert payload["podCategory"] == "1"
    assert payload["barcode"] == ""
    # 校验鉴权请求头
    assert headers["usercode"] == "116173"
    assert headers["X-Access-Token"] == "1"


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
    """到位回调：service 返回 success=true，message 含 container。"""
    mock = _MockHttpClient({})
    cfg = AgvConfig()
    svc = AgvService(config=cfg, http_client=mock)

    result = svc.handle_arrived({"workstation": "W03", "container": "T0383614"})

    assert result["success"] is True
    assert "到位" in result["message"]
    assert "T0383614" in result["message"]


# ── HTTP 入口测试 ──────────────────────────────────────────────

def test_agv_arrived_endpoint_returns_raw_dict() -> None:
    """AGV 到位回调接口直接返回 dict（不包 Result），符合对方期望。"""
    with TestClient(app) as client:
        resp = client.post("/api/v1/agv/arrived", json={"workstation": "W03", "container": "T0383614"})

        assert resp.status_code == 200
        body = resp.json()
        # 不包 Result，直接是 {"success": true, "message": "..."}
        assert body["success"] is True
        assert "message" in body
        assert "T0383614" in body["message"]


# ── 返库测试 ──────────────────────────────────────────────────

def test_return_agv_without_container_raises() -> None:
    """没收到到位回调就调返库，应抛 BizException(code=50004)。"""
    from bsd_unitree_controller.exception.exceptions import BizException

    mock = _MockHttpClient({})
    cfg = AgvConfig()
    svc = AgvService(config=cfg, http_client=mock)

    try:
        svc.return_agv()
        assert False, "应抛 BizException"
    except BizException as e:
        assert e.code == 50004
        assert "container" in e.message


def test_return_agv_after_arrived_success() -> None:
    """收到到位回调后调返库，应构造正确请求体并返回成功。"""
    mock = _MockHttpClient({"code": 0, "message": "", "success": True, "result": {}, "timestamp": 0})
    cfg = AgvConfig(workstation="W03")
    svc = AgvService(config=cfg, http_client=mock)

    # 先模拟到位回调，缓存 container
    svc.handle_arrived({"workstation": "W03", "container": "T0383614"})

    # 再调返库
    result = svc.return_agv()

    assert result["container"] == "T0383614"
    assert result["workstation"] == "W03"
    assert result["response"]["success"] is True
    # 校验请求体
    assert len(mock.calls) == 1
    url, payload, headers = mock.calls[0]
    assert "hikAGVCTUInCallRobotBack" in url
    assert payload["podNo"] == "T0383614"
    assert payload["type"] == "FK"
    assert payload["workstationNo"] == "W03"
    assert payload["podCategory"] == ""
    # 校验鉴权请求头
    assert headers["usercode"] == "116173"
    assert headers["X-Access-Token"] == "1"


def test_return_agv_clears_container_cache() -> None:
    """返库成功后应清除 container 缓存，再次调返库应报错。"""
    from bsd_unitree_controller.exception.exceptions import BizException

    mock = _MockHttpClient({"code": 0, "message": "", "success": True, "result": {}, "timestamp": 0})
    cfg = AgvConfig()
    svc = AgvService(config=cfg, http_client=mock)

    # 到位回调缓存 container
    svc.handle_arrived({"workstation": "W03", "container": "T0383614"})
    # 返库（成功后会清除缓存）
    svc.return_agv()

    # 再次返库应报错（缓存已清）
    try:
        svc.return_agv()
        assert False, "缓存清除后再次返库应抛 BizException"
    except BizException as e:
        assert e.code == 50004
