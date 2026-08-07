"""EPC 条码读取接口测试。

验证：
    1. service 层 start_scan 构造正确请求 + 校验响应
    2. service 层 handle_callback 校验一致性后缓存 epc
    3. HTTP /api/v1/epc/callback 回调接口返回对方期望格式（不包 Result）

存储方式类比 AgvService._last_container：类变量跨请求共享。
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from bsd_unitree_controller.core.config import EpcConfig
from bsd_unitree_controller.exception.exceptions import UpstreamException
from bsd_unitree_controller.model.dto import EpcCallbackDTO
from bsd_unitree_controller.service.epc_service import EpcService

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


def _reset_epc_cache() -> None:
    """每个测试前清空 EpcService 类变量，避免测试间互相污染。"""
    EpcService._last_request_id = None
    EpcService._last_epc = None
    EpcService._retry_count = 0


# ── start_scan 测试 ────────────────────────────────────────────

def test_start_scan_success() -> None:
    """发起扫描成功：RFID 返回 success=true，service 返回 requestId 并缓存。"""
    _reset_epc_cache()
    mock = _MockHttpClient({
        "success": True,
        "message": "scan accepted",
        "data": {"requestId": "a1b2c3d4e5f6"},
    })
    cfg = EpcConfig()
    svc = EpcService(config=cfg, http_client=mock)

    result = svc.start_scan()

    assert result["requestId"] == "a1b2c3d4e5f6"
    # 校验 requestId 已缓存到类变量
    assert EpcService._last_request_id == "a1b2c3d4e5f6"
    # 发起新扫描应清空旧 epc
    assert EpcService._last_epc is None
    # 校验请求：无参数，URL 正确
    assert len(mock.calls) == 1
    url, payload, headers = mock.calls[0]
    assert url == "http://localhost:8080/api/rfid/scan"
    # 无参数，json 应为 None
    assert payload is None


def test_start_scan_failure_raises() -> None:
    """发起扫描失败：RFID 返回 success=false，service 抛 UpstreamException。"""
    _reset_epc_cache()
    mock = _MockHttpClient({
        "success": False,
        "message": "读写器未连接",
    })
    cfg = EpcConfig()
    svc = EpcService(config=cfg, http_client=mock)

    try:
        svc.start_scan()
        assert False, "应抛 UpstreamException"
    except UpstreamException as e:
        assert "RFID 服务返回失败" in e.message


def test_start_scan_empty_request_id_raises() -> None:
    """发起扫描成功但 requestId 为空，抛 UpstreamException。"""
    _reset_epc_cache()
    mock = _MockHttpClient({
        "success": True,
        "message": "scan accepted",
        "data": {"requestId": ""},
    })
    cfg = EpcConfig()
    svc = EpcService(config=cfg, http_client=mock)

    try:
        svc.start_scan()
        assert False, "应抛 UpstreamException"
    except UpstreamException as e:
        assert "requestId 为空" in e.message


# ── handle_callback 测试 ───────────────────────────────────────

def test_handle_callback_success_updates_epc() -> None:
    """回调正常：requestId 匹配，epc 缓存更新。"""
    _reset_epc_cache()
    cfg = EpcConfig()
    svc = EpcService(config=cfg, http_client=_MockHttpClient({}))

    # 先发起扫描，缓存 requestId
    svc._http = _MockHttpClient({
        "success": True,
        "data": {"requestId": "req-001"},
    })
    svc.start_scan()

    # 模拟回调（requestId 匹配）
    result = svc.handle_callback(EpcCallbackDTO(
        requestId="req-001",
        epc="EPC1234567890",
        error=None,
    ))

    assert result["success"] is True
    assert "req-001" in result["message"]
    assert "EPC1234567890" in result["message"]
    # 校验 epc 已缓存
    assert EpcService._last_epc == "EPC1234567890"
    assert EpcService._last_request_id == "req-001"


def test_handle_callback_failure_triggers_auto_rescan() -> None:
    """回调失败：error 不为空，清理缓存并自动重扫（多发起一次扫描）。"""
    _reset_epc_cache()
    cfg = EpcConfig()
    mock = _MockHttpClient({
        "success": True,
        "data": {"requestId": "req-x"},
    })
    svc = EpcService(config=cfg, http_client=mock)

    # 发起扫描（第 1 次 post）
    svc.start_scan()
    assert len(mock.calls) == 1
    assert EpcService._last_request_id == "req-x"

    # 模拟回调（超时失败，error 不为空）→ 应自动重扫
    result = svc.handle_callback(EpcCallbackDTO(
        requestId="req-x",
        epc=None,
        error="扫描超时（35s），未读取到 EPC，请重新发起扫描",
    ))

    assert result["success"] is True
    assert "自动重扫" in result["message"]
    # 重试计数 +1，且自动重扫又发起了一次扫描
    assert EpcService._retry_count == 1
    assert len(mock.calls) == 2  # start_scan + 自动重扫
    # 重扫后缓存新 requestId（mock 固定返回 req-x），epc 保持为空
    assert EpcService._last_request_id == "req-x"
    assert EpcService._last_epc is None


def test_handle_callback_matched_but_no_epc_fails() -> None:
    """回调匹配但没读到 epc（epc 为空）：视为失败，触发自动重扫。"""
    _reset_epc_cache()
    cfg = EpcConfig()
    mock = _MockHttpClient({
        "success": True,
        "data": {"requestId": "req-x"},
    })
    svc = EpcService(config=cfg, http_client=mock)

    # 发起扫描（第 1 次 post）
    svc.start_scan()

    # 模拟回调：匹配但 epc 为空、error 也为空（异常情况）
    result = svc.handle_callback(EpcCallbackDTO(
        requestId="req-x",
        epc=None,
        error=None,
    ))

    assert result["success"] is True
    assert "自动重扫" in result["message"]
    assert EpcService._retry_count == 1
    assert len(mock.calls) == 2
    assert EpcService._last_request_id == "req-x"
    assert EpcService._last_epc is None


def test_handle_callback_failure_then_rescan_success() -> None:
    """失败自动重扫后，重扫对应的新回调成功，epc 正常缓存且重置重试计数。"""
    _reset_epc_cache()
    cfg = EpcConfig()
    mock = _MockHttpClient({
        "success": True,
        "data": {"requestId": "req-x"},
    })
    svc = EpcService(config=cfg, http_client=mock)

    # 发起扫描，缓存 requestId=req-x
    svc.start_scan()
    assert EpcService._last_request_id == "req-x"

    # 失败回调 → 自动重扫（requestId 仍为 req-x），重试计数 +1
    svc.handle_callback(EpcCallbackDTO(
        requestId="req-x",
        epc=None,
        error="扫描超时（35s），未读取到 EPC，请重新发起扫描",
    ))
    assert EpcService._retry_count == 1
    assert EpcService._last_request_id == "req-x"
    assert EpcService._last_epc is None

    # 重扫后的回调成功（requestId 匹配当前 req-x）
    result = svc.handle_callback(EpcCallbackDTO(
        requestId="req-x",
        epc="EPC-RESCAN",
        error=None,
    ))
    assert result["success"] is True
    assert EpcService._last_epc == "EPC-RESCAN"
    assert EpcService._last_request_id == "req-x"
    # 成功后重试计数重置
    assert EpcService._retry_count == 0


def test_retry_stops_at_max_retries() -> None:
    """重试次数达到 MAX_RETRIES 后停止，不再自动重扫。"""
    _reset_epc_cache()
    cfg = EpcConfig()
    mock = _MockHttpClient({})
    svc = EpcService(config=cfg, http_client=mock)

    # 手动模拟已重试 MAX_RETRIES-1 次，缓存一个匹配的 requestId
    EpcService._retry_count = EpcService.MAX_RETRIES - 1
    EpcService._last_request_id = "req-last"
    mock.calls.clear()

    # 最后一次失败回调
    result = svc.handle_callback(EpcCallbackDTO(
        requestId="req-last",
        epc=None,
        error="扫描超时（35s），未读取到 EPC，请重新发起扫描",
    ))

    assert result["success"] is True
    assert "最大重试次数" in result["message"]
    # 达到上限后不再发起新扫描
    assert len(mock.calls) == 0
    # 缓存被清空，重试计数重置
    assert EpcService._last_request_id is None
    assert EpcService._last_epc is None
    assert EpcService._retry_count == 0


def test_handle_callback_request_id_mismatch_ignored() -> None:
    """回调 requestId 与当前扫描不匹配：忽略，不污染 epc 缓存。"""
    _reset_epc_cache()
    cfg = EpcConfig()
    svc = EpcService(config=cfg, http_client=_MockHttpClient({}))

    # 先发起扫描，缓存 requestId=req-001，epc 已读到
    svc._http = _MockHttpClient({
        "success": True,
        "data": {"requestId": "req-001"},
    })
    svc.start_scan()
    svc.handle_callback(EpcCallbackDTO(
        requestId="req-001",
        epc="EPC-CORRECT",
        error=None,
    ))
    assert EpcService._last_epc == "EPC-CORRECT"

    # 模拟一个不匹配的回调（过期/无关回调）
    result = svc.handle_callback(EpcCallbackDTO(
        requestId="req-other",
        epc="EPC-WRONG",
        error=None,
    ))

    assert result["success"] is True
    assert "不匹配" in result["message"]
    # epc 缓存不被污染，仍是之前正确的值
    assert EpcService._last_epc == "EPC-CORRECT"
    assert EpcService._last_request_id == "req-001"


def test_handle_callback_without_scan_ignored() -> None:
    """没有发起过扫描就收到回调：requestId 为 None 不匹配，忽略。"""
    _reset_epc_cache()
    cfg = EpcConfig()
    svc = EpcService(config=cfg, http_client=_MockHttpClient({}))

    result = svc.handle_callback(EpcCallbackDTO(
        requestId="req-orphan",
        epc="EPC-ORPHAN",
        error=None,
    ))

    assert result["success"] is True
    assert "不匹配" in result["message"]
    # 缓存没被污染
    assert EpcService._last_epc is None
    assert EpcService._last_request_id is None


def test_new_scan_clears_old_epc() -> None:
    """再次发起扫描时，旧的 epc 缓存应被清空。"""
    _reset_epc_cache()
    cfg = EpcConfig()
    svc = EpcService(config=cfg, http_client=_MockHttpClient({}))

    # 第一次扫描 + 回调
    svc._http = _MockHttpClient({
        "success": True,
        "data": {"requestId": "req-001"},
    })
    svc.start_scan()
    svc.handle_callback(EpcCallbackDTO(
        requestId="req-001",
        epc="EPC-FIRST",
        error=None,
    ))
    assert EpcService._last_epc == "EPC-FIRST"

    # 第二次扫描，应清空旧 epc
    svc._http = _MockHttpClient({
        "success": True,
        "data": {"requestId": "req-002"},
    })
    svc.start_scan()

    assert EpcService._last_request_id == "req-002"
    assert EpcService._last_epc is None


# ── HTTP 入口测试 ──────────────────────────────────────────────

def test_epc_callback_endpoint_returns_raw_dict() -> None:
    """EPC 回调接口直接返回 dict（不包 Result），符合对方期望。"""
    _reset_epc_cache()
    # 先发起扫描，让 _last_request_id 有值，回调才能匹配
    cfg = EpcConfig()
    svc = EpcService(config=cfg, http_client=_MockHttpClient({
        "success": True,
        "data": {"requestId": "req-http-001"},
    }))
    svc.start_scan()

    with TestClient(app) as client:
        resp = client.post("/api/v1/epc/callback", json={
            "requestId": "req-http-001",
            "epc": "EPC-HTTP-TEST",
            "error": None,
        })

        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert "req-http-001" in body["message"]


def test_epc_callback_endpoint_mismatch_returns_raw_dict() -> None:
    """EPC 回调接口接收 requestId 不匹配场景，仍返回 raw dict（不触发重扫）。

    注：失败回调会自动重扫（需真实 http_client 调 RFID 服务），测试环境无该服务，
    因此 HTTP 层只验证不触发重扫的不匹配分支，失败重扫逻辑在 service 层测试覆盖。
    """
    _reset_epc_cache()
    with TestClient(app) as client:
        resp = client.post("/api/v1/epc/callback", json={
            "requestId": "req-http-orphan",
            "epc": None,
            "error": "扫描超时（35s），未读取到 EPC，请重新发起扫描",
        })

        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert "不匹配" in body["message"]