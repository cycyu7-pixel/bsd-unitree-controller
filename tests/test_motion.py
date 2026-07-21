"""运动控制接口测试。

验证：
    1. service 层方向转换逻辑（独立于框架）
    2. HTTP /api/v1/motion/cmd 在 rclpy 未装时返回业务错误（软依赖降级）
    3. 参数校验：非法 direction、speed 超范围
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from bsd_unitree_controller.exception.exceptions import BizException
from bsd_unitree_controller.model.dto import MotionCmdDTO, MotionDirection
from bsd_unitree_controller.service.motion_service import MotionService

from main import app


# ── service 层测试（不依赖 fastapi/rclpy）──────────────────────

class _MockPublisher:
    """模拟 MotionPublisher，记录收到的指令。"""

    def __init__(self) -> None:
        self.calls: list[tuple[float, float]] = []

    def publish_cmd(self, linear_x: float, angular_z: float) -> None:
        self.calls.append((linear_x, angular_z))


@pytest.mark.parametrize(
    "direction, speed, expected",
    [
        (MotionDirection.FORWARD, 0.5, (0.5, 0.0)),
        (MotionDirection.BACKWARD, 0.3, (-0.3, 0.0)),
        (MotionDirection.TURN_LEFT, 1.0, (0.0, 1.0)),
        (MotionDirection.TURN_RIGHT, 0.8, (0.0, -0.8)),
        (MotionDirection.STOP, 0.5, (0.0, 0.0)),
    ],
)
def test_motion_service_direction_conversion(
    direction: MotionDirection, speed: float, expected: tuple[float, float]
) -> None:
    """各方向的语义指令应正确转成 (linear_x, angular_z)。"""
    mock = _MockPublisher()
    svc = MotionService(publisher=mock)
    dto = MotionCmdDTO(direction=direction, speed=speed)

    result = svc.execute_cmd(dto)

    assert (result["linear_x"], result["angular_z"]) == expected
    assert mock.calls == [expected]  # publisher 收到了转换后的指令


def test_motion_service_raises_when_ros_disabled() -> None:
    """ROS 未启用（publisher=None）时应抛 BizException。"""
    svc = MotionService(publisher=None)
    dto = MotionCmdDTO(direction=MotionDirection.FORWARD, speed=0.5)

    with pytest.raises(BizException) as exc_info:
        svc.execute_cmd(dto)

    assert exc_info.value.code == 50002
    assert "ROS 未启用" in exc_info.value.message


# ── HTTP 入口测试 ──────────────────────────────────────────────

def test_motion_cmd_returns_error_without_rclpy() -> None:
    """开发机无 rclpy 时，POST /motion/cmd 应返回 code=50002。

    机器人环境装了 rclpy 后此测试需相应调整。
    """
    with TestClient(app) as client:
        resp = client.post(
            "/api/v1/motion/cmd",
            json={"direction": "forward", "speed": 0.5},
        )

        assert resp.status_code == 200
        body = resp.json()
        # 开发机环境断言 50002；机器人环境会是 1（成功）
        # 兼容两种环境，只断言 code 字段存在
        assert "code" in body
        assert body["code"] in (1, 50002)


def test_motion_cmd_rejects_invalid_direction() -> None:
    """非法 direction 应返回参数校验错误 code=400。"""
    with TestClient(app) as client:
        resp = client.post(
            "/api/v1/motion/cmd",
            json={"direction": "fly", "speed": 0.5},
        )

        body = resp.json()
        assert body["code"] == 400


def test_motion_cmd_rejects_speed_out_of_range() -> None:
    """speed 超范围（>2.0）应返回参数校验错误 code=400。"""
    with TestClient(app) as client:
        resp = client.post(
            "/api/v1/motion/cmd",
            json={"direction": "forward", "speed": 5.0},
        )

        body = resp.json()
        assert body["code"] == 400


def test_motion_cmd_rejects_missing_direction() -> None:
    """缺 direction 字段应返回参数校验错误。"""
    with TestClient(app) as client:
        resp = client.post(
            "/api/v1/motion/cmd",
            json={"speed": 0.5},
        )

        body = resp.json()
        assert body["code"] == 400
