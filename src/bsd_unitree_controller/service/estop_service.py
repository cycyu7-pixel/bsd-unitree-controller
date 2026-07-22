"""急停控制服务。

本层是业务逻辑的唯一真相源，HTTP 入口调这里。
不 import fastapi / rclpy / std_srvs，业务逻辑能脱离框架单测。

依赖倒置：通过 EstopTrigger 协议接收 ROS 节点，
ControllerNode 满足该协议（鸭子类型），测试时可用 mock 替换。

注意：急停是 ROS service 调用（不是 topic publish），node 层已封装异步细节，
trigger_estop() 返回的是 awaitable，service 层直接 await。
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from bsd_unitree_controller.exception.exceptions import BizException

# ROS 未启用时的业务错误码
_ROS_NOT_AVAILABLE_CODE = 50002


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


class EstopService:
    """急停控制服务。

    业务逻辑集中在此：
        1. 校验 ROS 是否可用
        2. await node.trigger_estop() 触发急停
        3. 把 ROS 响应转成 DTO

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
