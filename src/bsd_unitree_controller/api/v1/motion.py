"""运动控制接口路由。

外部通过 HTTP 调用，控制机器人前进/后退/转向/停止。
本层只做：参数接收 -> 调 service -> 包装 Result，不写业务逻辑。
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends

from bsd_unitree_controller.core.deps import get_ros_node
from bsd_unitree_controller.model.dto import MotionCmdDTO
from bsd_unitree_controller.model.response import Result
from bsd_unitree_controller.ros.node import ControllerNode
from bsd_unitree_controller.service.motion_service import MotionService

router = APIRouter(prefix="/motion", tags=["运动控制"])


@router.post("/cmd", summary="下发运动指令")
def send_cmd(
    dto: MotionCmdDTO,
    ros_node: Optional[ControllerNode] = Depends(get_ros_node),
) -> Result[dict]:
    """下发运动指令到机器人。

    外部通过 HTTP POST 传入语义化指令（direction + speed），
    service 层转成 ROS Twist 后通过 /cmd_vel 发布，
    运动控制节点订阅后驱动电机。

    fire-and-forget 模式：发一次指令机器人按该速度持续运动，
    发 stop 或新指令才会改变。类似按住手柄摇杆。

    Args:
        dto: 运动指令，direction 取值 forward/backward/turn_left/turn_right/stop，
             speed 取 0.0~2.0，默认 0.5。

    Returns:
        Result，data 含实际下发的 linear_x 和 angular_z（m/s 和 rad/s）。

    Raises:
        BizException: ROS 未启用时抛出（code=50001）。
    """
    # 构造 service，注入 ROS 节点（ros_node 可为 None，service 内部抛异常）
    service = MotionService(publisher=ros_node)
    # 调 service 执行业务逻辑，路由层不写业务判断
    data = service.execute_cmd(dto)
    return Result.ok(data=data)
