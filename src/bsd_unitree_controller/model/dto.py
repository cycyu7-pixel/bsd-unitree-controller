"""运动控制相关 DTO。

外部 HTTP 调用方传语义化指令（forward/backward/stop 等），
不直接暴露 ROS 的 Twist 坐标系，降低调用方理解成本。
DTO -> Twist 的转换在 service 层做。
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class MotionDirection(str, Enum):
    """运动方向枚举。

    继承 str + Enum，FastAPI 会自动在 OpenAPI 文档里生成可选值列表。
    """

    FORWARD = "forward"       # 前进
    BACKWARD = "backward"     # 后退
    TURN_LEFT = "turn_left"   # 原地左转
    TURN_RIGHT = "turn_right"  # 原地右转
    STOP = "stop"             # 停止


class MotionCmdDTO(BaseModel):
    """运动指令入参。

    外部通过 HTTP POST /api/v1/motion/cmd 传入，
    service 层转成 geometry_msgs/Twist 后通过 ROS 发布。

    Attributes:
        direction: 运动方向，见 MotionDirection 枚举。
        speed: 速度大小，单位 m/s（线速度）或 rad/s（角速度）。
               forward/backward 时为线速度，turn_left/turn_right 时为角速度。
               stop 时忽略此字段。取值范围 0.0~2.0，默认 0.5。
    """

    direction: MotionDirection = Field(..., description="运动方向")
    speed: float = Field(0.5, ge=0.0, le=2.0, description="速度 m/s 或 rad/s，默认 0.5")
