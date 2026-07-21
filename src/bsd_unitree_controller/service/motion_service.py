"""运动控制服务。

本层是业务逻辑的唯一真相源，HTTP 入口调这里。
不 import fastapi / rclpy / geometry_msgs，业务逻辑能脱离框架单测。

依赖倒置：通过 MotionPublisher 协议接收 ROS 节点，
ControllerNode 满足该协议（鸭子类型），测试时可用 mock 替换。
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from bsd_unitree_controller.exception.exceptions import BizException
from bsd_unitree_controller.model.dto import MotionCmdDTO, MotionDirection

# ROS 未启用时的业务错误码
_ROS_NOT_AVAILABLE_CODE = 50002


@runtime_checkable
class MotionPublisher(Protocol):
    """运动指令发布者协议。

    任何具备 publish_cmd(linear_x, angular_z) 方法的对象都满足此协议。
    ControllerNode 满足，测试时可用 mock 替换。
    """

    def publish_cmd(self, linear_x: float, angular_z: float) -> None:
        """发布运动指令。

        Args:
            linear_x: 线速度 m/s，正=前进，负=后退。
            angular_z: 角速度 rad/s，正=左转，负=右转。
        """
        ...


class MotionService:
    """运动控制服务。

    业务逻辑集中在此：
        1. 校验指令（Pydantic 已做基础校验，这里做业务规则校验）
        2. 语义指令转 ROS 速度参数（linear_x / angular_z）
        3. 调 node 发布

    HTTP 入口（/api/v1/motion/cmd）调本服务。
    后续若加 ROS service 入口，也调同一个方法，业务逻辑零冗余。
    """

    def __init__(self, publisher: MotionPublisher | None = None) -> None:
        """初始化服务。

        Args:
            publisher: 运动指令发布者，通常传 ControllerNode 实例。
                      None 表示 ROS 未启用（纯 HTTP 模式），此时发布会抛 BizException。
        """
        self._publisher = publisher

    def execute_cmd(self, dto: MotionCmdDTO) -> dict:
        """执行运动指令，返回执行结果 DTO。

        业务逻辑只写这一遍，HTTP 和 ROS 入口共用。

        Args:
            dto: 运动指令入参（方向 + 速度）。

        Returns:
            dict，含 direction、speed、linear_x、angular_z 字段，
            供入口层包装成响应。

        Raises:
            BizException: ROS 未启用时（publisher 为 None）抛出，code=50002。
        """
        # 业务规则校验：ROS 未启用不能发指令
        if self._publisher is None:
            raise BizException(
                code=_ROS_NOT_AVAILABLE_CODE,
                message="ROS 未启用，无法发布运动指令（检查 rclpy 是否安装或 ros.enabled 配置）",
            )

        # 语义指令转 ROS 速度参数（业务核心逻辑）
        linear_x, angular_z = self._to_velocity(dto.direction, dto.speed)

        # 调 node 发布，service 不直接碰 ROS 消息类型
        self._publisher.publish_cmd(linear_x, angular_z)

        return {
            "direction": dto.direction.value,
            "speed": dto.speed,
            "linear_x": linear_x,
            "angular_z": angular_z,
        }

    @staticmethod
    def _to_velocity(direction: MotionDirection, speed: float) -> tuple[float, float]:
        """语义指令转 ROS 速度参数。

        Twist 坐标系约定：
            linear.x  正=前进，负=后退
            angular.z 正=左转，负=右转

        Args:
            direction: 运动方向。
            speed: 速度大小。

        Returns:
            (linear_x, angular_z) 元组。
        """
        if direction == MotionDirection.FORWARD:
            return (speed, 0.0)
        if direction == MotionDirection.BACKWARD:
            return (-speed, 0.0)
        if direction == MotionDirection.TURN_LEFT:
            return (0.0, speed)
        if direction == MotionDirection.TURN_RIGHT:
            return (0.0, -speed)
        # STOP
        return (0.0, 0.0)
