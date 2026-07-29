"""机器人本体控制服务。

本层是业务逻辑的唯一真相源，HTTP 入口调这里。
不 import fastapi / rclpy / std_srvs，业务逻辑能脱离框架单测。

包含：
    - HealthService：节点存活检查
    - EstopService：急停控制

依赖倒置：通过 Protocol 接收 ROS 节点，ControllerNode 满足协议（鸭子类型），
测试时可用 mock 替换。service 层不直接依赖 rclpy。
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from bsd_unitree_controller.exception.exceptions import BizException

# ROS 未启用时的业务错误码
_ROS_NOT_AVAILABLE_CODE = 50002


# ── 协议定义 ──────────────────────────────────────────────────

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


@runtime_checkable
class EstopTrigger(Protocol):
    """急停触发者协议。

    任何具备 async trigger_estop() 方法的对象都满足此协议。
    ControllerNode 满足，测试时可用 mock 替换。
    """

    async def trigger_estop(self):
        """异步调用急停 service，返回响应。

        Returns:
            service 响应对象，含 success 和 message 字段。
        """
        ...


# ── 存活检查服务 ──────────────────────────────────────────────

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


# ── 急停控制服务 ──────────────────────────────────────────────

class EstopService:
    """急停控制服务。

    业务逻辑集中在此：校验 ROS 是否可用 + 调 node 触发急停 + 转响应。
    HTTP 入口（/api/v1/estop/trigger）调本服务。
    """

    def __init__(self, trigger: EstopTrigger | None = None) -> None:
        """初始化服务。

        Args:
            trigger: 急停触发者，通常传 ControllerNode 实例。
                    None 表示 ROS 未启用（纯 HTTP 模式），此时调用抛 BizException。
        """
        self._trigger = trigger

    async def execute_estop(self) -> dict:
        """执行急停，返回结果 DTO。

        业务逻辑只写这一遍。ROS service 调用是异步的，
        node 层已封装好，本方法直接 await。

        Returns:
            dict，含 success（bool）和 message（str）字段。

        Raises:
            BizException: ROS 未启用或 service 调用失败时抛出。
        """
        # 业务规则校验：ROS 未启用不能触发急停
        if self._trigger is None:
            raise BizException(
                code=_ROS_NOT_AVAILABLE_CODE,
                message="ROS 未启用，无法触发急停（检查 rclpy 是否安装或 ros.enabled 配置）",
            )

        # 调 node 触发急停，await 等待结果
        result = await self._trigger.trigger_estop()

        # 检查响应
        if result is None:
            raise BizException(
                code=50003,
                message="急停 service 调用失败，未返回结果",
            )

        return {
            "success": bool(result.success),
            "message": result.message or "",
        }
