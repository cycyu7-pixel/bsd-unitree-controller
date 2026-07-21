"""基础接口路由。

类比 Spring Boot 的 @RestController，每个函数对应一个接口。
本层只做：参数接收 -> 调下游（service/client/ros）-> 包装成 Result 返回。
不写业务判断，业务逻辑放 service 层。
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends

from bsd_unitree_controller.client.http_client import HttpClient
from bsd_unitree_controller.core.deps import get_http_client, get_ros_node
from bsd_unitree_controller.model.common import HealthVO
from bsd_unitree_controller.model.response import Result
from bsd_unitree_controller.ros.node import ControllerNode
from bsd_unitree_controller.service.health_service import HealthService

router = APIRouter(tags=["基础接口"])


# ── 健康检查 ───────────────────────────────────────────────────
@router.get("/test", summary="健康检查")
def health() -> Result[HealthVO]:
    """健康检查接口。

    返回服务状态，供运维/网关探活使用。不依赖任何下游资源。
    """
    return Result.ok(data=HealthVO(status="up"))


# ── HTTP 封装验证：访问百度主页 ────────────────────────────────
@router.get("/baidu", summary="访问百度主页")
def fetch_baidu(
    client: HttpClient = Depends(get_http_client),
) -> Result[str]:
    """调用本接口会通过 HttpClient 访问百度主页，验证 HTTP 封装可用。

    作为 HttpClient.get() 的用法示例：传完整 URL，拿到 Response 自行解析。
    生产环境上线前应移除该接口。
    """
    # 传完整 URL 发起 GET 请求，响应由调用方按需解析
    resp = client.get("https://www.baidu.com")
    return Result.ok(data="success")


# ── ROS 节点状态（直接读 app.state，不走 service）──────────────
@router.get("/ros/status", summary="ROS 节点状态")
def ros_status(
    ros_node: Optional[ControllerNode] = Depends(get_ros_node),
) -> Result[dict]:
    """查询 ROS 节点状态。

    用于确认 ROS 集成是否生效：
        - rclpy 未装/配置禁用 -> status=disabled
        - 节点已启动且 context 有效 -> status=alive
        - 节点已启动但 context 失效 -> status=dead

    Returns:
        Result，data 含 status 和 node_name（disabled 时含 reason）。
    """
    if ros_node is None:
        # 三种可能：配置禁用 / rclpy 未装 / 初始化失败（后两者日志已记录）
        return Result.ok(data={
            "status": "disabled",
            "reason": "ROS 未启用（检查 config.ros.enabled 或 rclpy 是否安装）",
        })
    return Result.ok(data={
        "status": "alive" if ros_node.is_alive else "dead",
        "node_name": ros_node.get_name(),
    })


# ── 存活检查（走 service 层，HTTP 和 ROS 共享业务逻辑）─────────
@router.get("/alive", summary="节点存活检查")
def alive(
    ros_node: Optional[ControllerNode] = Depends(get_ros_node),
) -> Result[dict]:
    """节点存活检查接口。

    演示标准分层：HTTP 入口调 HealthService，业务逻辑与 ROS service 共享。
    路由层只做：依赖注入 -> 调 service -> 包装 Result，无业务判断。

    Returns:
        Result，data 含 status（alive/disabled/dead）、node_name、timestamp。
    """
    # 构造 service，注入状态提供者（ros_node 可为 None，service 内部处理）
    service = HealthService(provider=ros_node)
    # 调 service 拿业务结果，路由层不写业务逻辑
    data = service.check_alive()
    return Result.ok(data=data)
