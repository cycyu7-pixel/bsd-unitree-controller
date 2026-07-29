"""机器人本体控制接口路由。

类比 Spring Boot 的 @RestController，每个函数对应一个接口。
本层只做：参数接收 -> 调下游（service/ros）-> 包装成 Result 返回，不写业务逻辑。

包含：
    - 健康检查、存活检查（查询类）
    - 急停控制（动作类）
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends

from bsd_unitree_controller.core.deps import get_http_client, get_ros_node
from bsd_unitree_controller.client.http_client import HttpClient
from bsd_unitree_controller.model.common import HealthVO
from bsd_unitree_controller.model.response import Result
from bsd_unitree_controller.ros.node import ControllerNode
from bsd_unitree_controller.service.controller_service import HealthService, EstopService

router = APIRouter(tags=["机器人本体控制"])


# ── 查询类接口 ───────────────────────────────────────────────

@router.get("/test", summary="健康检查")
def health() -> Result[HealthVO]:
    """健康检查接口。

    返回服务状态，供运维/网关探活使用。不依赖任何下游资源，
    只要 HTTP 进程能响应就返回 up。
    """
    return Result.ok(data=HealthVO(status="up"))


@router.get("/alive", summary="节点存活检查")
def alive(
    ros_node: Optional[ControllerNode] = Depends(get_ros_node),
) -> Result[dict]:
    """节点存活检查接口。

    走 service 层，HTTP 和 ROS service ~/is_alive 共享 HealthService。
    反映 ROS 节点真实状态：
        - alive：ROS 节点正常运行
        - disabled：rclpy 未装或配置禁用（开发机/纯 HTTP 模式）
        - dead：ROS 节点已启动但 context 失效

    Returns:
        Result，data 含 status、node_name、timestamp。
    """
    service = HealthService(provider=ros_node)
    data = service.check_alive()
    return Result.ok(data=data)


# ── 动作类接口 ───────────────────────────────────────────────

@router.post("/estop/trigger", summary="触发急停")
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
    service = EstopService(trigger=ros_node)
    data = await service.execute_estop()
    return Result.ok(data=data)
