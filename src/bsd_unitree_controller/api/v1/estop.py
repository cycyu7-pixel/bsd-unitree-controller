"""急停控制接口路由。

外部通过 HTTP 调用，触发机器人急停。
本层只做：依赖注入 -> 调 service -> 包装 Result，不写业务逻辑。

注意：急停是 ROS service 调用（异步），路由用 async def。
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends

from bsd_unitree_controller.core.deps import get_ros_node
from bsd_unitree_controller.model.response import Result
from bsd_unitree_controller.ros.node import ControllerNode
from bsd_unitree_controller.service.estop_service import EstopService

router = APIRouter(prefix="/estop", tags=["急停控制"])


@router.post("/trigger", summary="触发急停")
async def trigger_estop(
    ros_node: Optional[ControllerNode] = Depends(get_ros_node),
) -> Result[dict]:
    """触发机器人急停。

    通过 HTTP 调用，经 service 层调用 ROS service /g1/estop/trigger。
    急停是 ROS service 调用（非 topic publish），异步等待结果。

    Returns:
        Result，data 含 success（急停是否触发成功）和 message（机器人返回的信息）。

    Raises:
        BizException: ROS 未启用（code=50002）或 service 调用失败（code=50003）。
    """
    # 构造 service，注入 ROS 节点（ros_node 可为 None，service 内部抛 BizException）
    service = EstopService(trigger=ros_node)
    # 调 service 执行业务逻辑，await 等待 ROS service 响应
    data = await service.execute_estop()
    return Result.ok(data=data)
