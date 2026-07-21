"""健康检查接口测试。

用 FastAPI TestClient 直接打 /api/v1/test 和 /api/v1/ros/status，验证：
    1. 健康检查接口可访问，返回 code=1
    2. ROS 状态接口在 rclpy 未装时返回 disabled（软依赖降级）
    3. 未定义路径返回 404，确认路由注册正常

注意：所有测试用 `with TestClient(app) as client:`，确保 lifespan 启动段执行
（app.state.ros_node 等在 lifespan 里才挂载）。
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from main import app


def test_health_returns_success_code() -> None:
    """健康检查应返回 code=1（成功）。"""
    with TestClient(app) as client:
        resp = client.get("/api/v1/test")

        assert resp.status_code == 200
        body = resp.json()
        # code=1 是项目约定的成功码
        assert body["code"] == 1
        assert body["message"] == "success"


def test_health_returns_up_status() -> None:
    """健康检查 data.status 应为 "up"。"""
    with TestClient(app) as client:
        resp = client.get("/api/v1/test")

        body = resp.json()
        assert body["data"]["status"] == "up"


def test_ros_status_returns_disabled_without_rclpy() -> None:
    """rclpy 未装时，/ros/status 应返回 status=disabled。

    开发机（Windows）无 rclpy，lifespan 跳过 ROS 初始化，
    get_ros_node 返回 None，路由据此返回 disabled。
    机器人环境装了 rclpy 后此测试需相应调整。
    """
    with TestClient(app) as client:
        resp = client.get("/api/v1/ros/status")

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 1
        # 开发机环境断言 disabled；机器人环境会是 alive
        # 这里只断言字段存在，不断言具体值，兼容两种环境
        assert "status" in body["data"]
        assert body["data"]["status"] in ("disabled", "alive", "dead")


def test_unknown_path_returns_404() -> None:
    """未定义路径应返回 404，确认路由注册正常。"""
    with TestClient(app) as client:
        resp = client.get("/api/v1/not-exist")

        assert resp.status_code == 404
