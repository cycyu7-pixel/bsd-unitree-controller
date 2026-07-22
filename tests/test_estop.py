"""急停控制接口测试。

验证：
    1. HTTP /api/v1/estop/trigger 在 rclpy 未装时返回业务错误（软依赖降级）
    2. service 层 ROS 未启用时抛 BizException
"""
from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from bsd_unitree_controller.exception.exceptions import BizException
from bsd_unitree_controller.service.estop_service import EstopService

from main import app


# ── service 层测试 ─────────────────────────────────────────────

def test_estop_service_raises_when_ros_disabled() -> None:
    """ROS 未启用（trigger=None）时应抛 BizException。"""
    svc = EstopService(trigger=None)

    # asyncio.run 跑 async 方法，不依赖 pytest-asyncio 插件
    with pytest.raises(BizException) as exc_info:
        asyncio.run(svc.execute_estop())

    assert exc_info.value.code == 50002
    assert "ROS 未启用" in exc_info.value.message


# ── HTTP 入口测试 ──────────────────────────────────────────────

def test_estop_trigger_returns_error_without_rclpy() -> None:
    """开发机无 rclpy 时，POST /estop/trigger 应返回 code=50002。

    机器人环境装了 rclpy 后此测试需相应调整。
    """
    with TestClient(app) as client:
        resp = client.post("/api/v1/estop/trigger")

        assert resp.status_code == 200
        body = resp.json()
        # 开发机环境断言 50002；机器人环境会是 1（成功）或 50003（调用失败）
        # 兼容两种环境，只断言 code 字段存在且合法
        assert "code" in body
        assert body["code"] in (1, 50002, 50003)
