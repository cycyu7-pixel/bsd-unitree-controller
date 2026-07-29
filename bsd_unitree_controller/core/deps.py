"""公共依赖项。

类比 Spring 的 @Autowired，FastAPI 用 Depends 实现依赖注入。
本文件集中放置路由层会用到的通用依赖：HttpClient、ROS 节点等。
"""
from __future__ import annotations

from typing import Optional

from fastapi import Request

from bsd_unitree_controller.client.http_client import HttpClient
from bsd_unitree_controller.ros.node import ControllerNode


def get_http_client(request: Request) -> HttpClient:
    """从 app.state 取出 HttpClient 实例。

    HttpClient 由 server.py 在 lifespan 启动段创建并挂到 app.state，
    路由通过 `Depends(get_http_client)` 拿到单例，避免每次请求新建连接池。

    Args:
        request: 当前请求对象，用于访问 app.state。

    Returns:
        HttpClient 实例。
    """
    return request.app.state.http_client


def get_ros_node(request: Request) -> Optional[ControllerNode]:
    """从 app.state 取出 ROS 节点实例。

    ROS 节点由 server.py 在 lifespan 启动段创建并挂到 app.state。
    以下情况返回 None（路由据此返回降级响应）：
        - config.ros.enabled=false（配置禁用）
        - rclpy 未安装（开发机环境）
        - rclpy 初始化失败（已记录日志）

    Args:
        request: 当前请求对象，用于访问 app.state。

    Returns:
        ControllerNode 实例，或 None（ROS 未启用）。
    """
    return request.app.state.ros_node
