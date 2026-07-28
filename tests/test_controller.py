"""机器人本体控制接口测试。

验证：
    1. 健康检查 /api/v1/test
    2. 存活检查 /api/v1/alive（走 service 层，rclpy 未装时返回 disabled）
    3. 急停 /api/v1/estop/trigger（rclpy 未装时返回业务错误）
    4. service 层独立测试（不依赖 fastapi/rclpy）
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from bsd_unitree_controller.exception.exceptions import BizException
from bsd_unitree_controller.service.controller_service import HealthService, EstopService

from main import app


# ── service 层测试（不依赖 fastapi/rclpy）──────────────────────

def test_health_service_disabled_when_no_provider() -> None:
    """无 provider（ROS 未启用）时返回 disabled。"""
    svc = HealthService(provider=None)
    data = svc.check_alive()
    assert data["status"] == "disabled"
    assert data["node_name"] == ""
    assert "timestamp" in data


def test_health_service_alive_with_mock_provider() -> None:
    """mock provider 返回 alive。"""
    class MockNode:
        @property
        def is_alive(self): return True
        def get_name(self): return "mock_node"

    svc = HealthService(provider=MockNode())
    data = svc.check_alive()
    assert data["status"] == "alive"
    assert data["node_name"] == "mock_node"


def test_estop_service_raises_when_ros_disabled() -> None:
    """ROS 未启用（trigger=None）时应抛 BizException。"""
    svc = EstopService(trigger=None)
    with pytest.raises(BizException) as exc_info:
        asyncio.run(svc.execute_estop())
    assert exc_info.value.code == 50002
    assert "ROS 未启用" in exc_info.value.message


# ── HTTP 入口测试 ──────────────────────────────────────────────

def test_health_endpoint() -> None:
    """健康检查 /api/v1/test 返回 code=1。"""
    with TestClient(app) as client:
        resp = client.get("/api/v1/test")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 1
        assert body["data"]["status"] == "up"


def test_alive_endpoint() -> None:
    """存活检查 /api/v1/alive 返回 code=1，开发机为 disabled。"""
    with TestClient(app) as client:
        resp = client.get("/api/v1/alive")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 1
        assert body["data"]["status"] in ("disabled", "alive", "dead")


def test_estop_trigger_endpoint() -> None:
    """急停 /api/v1/estop/trigger 在 rclpy 未装时返回业务错误。"""
    with TestClient(app) as client:
        resp = client.post("/api/v1/estop/trigger")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] in (1, 50002, 50003)


def test_unknown_path_returns_404() -> None:
    """未定义路径返回 404。"""
    with TestClient(app) as client:
        resp = client.get("/api/v1/not-exist")
        assert resp.status_code == 404
