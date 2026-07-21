"""机器人状态查询服务。

本层是业务逻辑的唯一真相源，HTTP 入口和 ROS 入口都调这里。
不 import fastapi / rclpy，业务逻辑能脱离框架单测。

依赖倒置：本服务不直接依赖 ControllerNode（那会引入 rclpy），
而是定义 StatusProvider 协议，由调用方传入实现了该协议的对象。
ControllerNode 天然满足这个协议（鸭子类型），无需显式继承。
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class StatusProvider(Protocol):
    """状态提供者协议。

    任何具备 is_alive 属性和 get_name() 方法的对象都满足此协议。
    ControllerNode 满足，测试时可用任意 mock 对象满足。
    """

    @property
    def is_alive(self) -> bool:
        """节点是否存活。"""
        ...

    def get_name(self) -> str:
        """节点名。"""
        ...


class HealthService:
    """机器人存活检查服务。

    业务逻辑集中在此：判断节点是否存活、组装返回数据。
    HTTP 入口（/api/v1/alive）和 ROS 入口（~/is_alive service）都调本服务。
    """

    def __init__(self, provider: StatusProvider | None = None) -> None:
        """初始化服务。

        Args:
            provider: 状态提供者，通常传 ControllerNode 实例。
                      None 表示 ROS 未启用（纯 HTTP 模式），此时存活检查返回 disabled。
        """
        self._provider = provider

    def check_alive(self) -> dict:
        """检查节点存活状态，返回 DTO（dict）。

        业务逻辑只写这一遍，HTTP 和 ROS 入口共用。
        入口层负责把返回的 dict 翻译成各自的响应格式（JSON / ROS 消息）。

        Returns:
            dict，含三个字段：
                - status: "alive" / "disabled" / "dead"
                - node_name: 节点名，disabled 时为空串
                - timestamp: 检查时间戳（ISO 格式字符串）
        """
        from datetime import datetime

        # ROS 未启用（rclpy 未装或配置禁用），返回 disabled
        if self._provider is None:
            return {
                "status": "disabled",
                "node_name": "",
                "timestamp": datetime.now().isoformat(),
            }

        # 根据节点 context 有效性判断存活
        is_alive = self._provider.is_alive
        return {
            "status": "alive" if is_alive else "dead",
            "node_name": self._provider.get_name(),
            "timestamp": datetime.now().isoformat(),
        }
