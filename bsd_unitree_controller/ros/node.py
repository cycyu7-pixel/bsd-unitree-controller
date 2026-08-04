"""ROS 2 节点封装。

类比 Spring Boot 里带 @Component 的基础设施 Bean：本类只负责 ROS 通信，
不写业务逻辑。后续接入 publisher/subscriber/service 在此扩展。

软依赖设计：
    rclpy 通过 try/except import，未装时 _RCLPY_AVAILABLE=False，
    所有 ROS 相关函数返回 None 或不报错，保证 Windows 开发机仍可启动 HTTP 服务。
    机器人部署环境（Ubuntu + ROS Humble）装好 rclpy 后，ROS 自动启用。
"""
from __future__ import annotations

import threading
from typing import Optional

# ── 软依赖：rclpy 未装时降级为占位基类 ────────────────────────────
try:
    import rclpy
    from rclpy.node import Node
    from std_srvs.srv import Trigger

    _RCLPY_AVAILABLE: bool = True
    _BaseNode = Node
except ImportError:
    _RCLPY_AVAILABLE = False

    # 占位基类：保证本模块在无 rclpy 环境下仍可 import，避免 ImportError
    class _BaseNode:  # type: ignore[no-redef]
        """rclpy 未装时的占位基类，仅用于类型注解，不会被实例化。"""

        pass


# G1 急停 service 名（std_srvs/Trigger 类型）
ESTOP_SERVICE = "/g1/estop/trigger"


class ControllerNode(_BaseNode):
    """机器人控制 ROS 节点。

    后续在此扩展：
        - create_publisher: 发布控制指令到运动控制节点
        - create_subscription: 订阅机器人状态
        - create_service: 提供本节点可被调用的服务

    节点名从 config.ros.node_name 读取（后续接入时改 __init__ 签名），
    当前骨架阶段硬编码默认值为 "web_controller"。
    """

    def __init__(
        self,
        node_name: str = "web_controller",
        http_client=None,
        agv_config=None,
    ) -> None:
        """初始化节点。

        Args:
            node_name: ROS 节点名，默认 "web_controller"。
            http_client: HttpClient 实例，供 AgvService 调用外部 HTTP 接口。
                        None 时不注册 AGV service。
            agv_config: AgvConfig 实例，AGV 调度配置。
                        None 时不注册 AGV service。
        """
        if not _RCLPY_AVAILABLE:
            raise RuntimeError("rclpy 未安装，无法创建 ROS 节点")
        super().__init__(node_name)
        self.get_logger().info(f"ControllerNode 已启动: {node_name}")

        # ── 急停 service client：调用 /g1/estop/trigger ─────────────
        # G1 的急停是 ROS service（std_srvs/Trigger），不是 topic
        # 用 create_client 创建客户端，调用时用 call_async 不阻塞 event loop
        self._estop_client = self.create_client(Trigger, ESTOP_SERVICE)
        self.get_logger().info(f"急停 service client 已创建: {ESTOP_SERVICE}")

        # ── 存活检查 service：~/is_alive ───────────────────────────
        # 业务逻辑调 HealthService，与 HTTP /api/v1/alive 共享同一份逻辑
        from bsd_unitree_controller.service.controller_service import HealthService

        self._health_service = HealthService(provider=self)
        self.create_service(Trigger, "~/is_alive", self._handle_is_alive)
        self.get_logger().info("ROS service 已注册: ~/is_alive")

        # ── AGV service：~/call_agv + ~/return_agv ─────────────────
        # 业务逻辑调 AgvService，与 HTTP /api/v1/agv/* 共享同一份逻辑
        # 用自定义 srv 类型（CallAgv/ReturnAgv），支持传参覆盖默认值
        # 需要 http_client 和 agv_config，缺任一则不注册
        if http_client is not None and agv_config is not None:
            from bsd_unitree_controller.service.agv_service import AgvService

            self._agv_service = AgvService(config=agv_config, http_client=http_client)
            self.create_service(Trigger, "~/call_agv", self._handle_call_agv)
            self.create_service(Trigger, "~/return_agv", self._handle_return_agv)
            self.get_logger().info("ROS service 已注册: ~/call_agv, ~/return_agv")
        else:
            self._agv_service = None
            self.get_logger().warning("http_client 或 agv_config 未提供，跳过 AGV service 注册")

    # ── 急停 service 调用（供 EstopService 调用）──────────────────

    async def trigger_estop(self):
        """异步调用急停 service /g1/estop/trigger。

        本方法封装 ROS service 调用的全部异步细节：
        1. 等待 service 上线
        2. call_async 发送请求，拿到 rclpy future
        3. 在线程池里 spin_until_future_complete，不阻塞 event loop
        4. 返回 Trigger.Response

        满足 EstopTrigger 协议，service 通过依赖注入调用。
        service 层直接 await 本方法，无需关心 rclpy future 细节。

        Returns:
            Trigger.Response 对象，含 success(bool) 和 message(string)。

        Raises:
            RuntimeError: rclpy 未安装或 service 不可用时抛出。
        """
        if not _RCLPY_AVAILABLE:
            raise RuntimeError("rclpy 未安装，无法调用急停 service")

        # 等待 service 上线（最多等 1 秒，避免无限阻塞）
        if not self._estop_client.service_is_ready():
            if not self._estop_client.wait_for_service(timeout_sec=1.0):
                raise RuntimeError(f"急停 service 不可用: {ESTOP_SERVICE}")

        # 异步调用，立即返回 rclpy future
        req = Trigger.Request()
        future = self._estop_client.call_async(req)
        self.get_logger().warning("已发送急停请求")

        # 在线程池里 spin 等待 future 完成，不阻塞 event loop
        import asyncio
        await asyncio.to_thread(
            rclpy.spin_until_future_complete, self, future, timeout_sec=3.0
        )

        return future.result()

    # ── 存活检查 service 回调 ─────────────────────────────────────

    def _handle_is_alive(self, request, response) -> object:
        """ROS service 回调：处理 ~/is_alive 调用。

        本方法只做翻译：调 HealthService 拿业务结果，转成 ROS 消息字段。
        业务逻辑在 service 层，与 HTTP 入口共享，无冗余。

        Args:
            request: Trigger.Request，无字段。
            response: Trigger.Response，含 success(bool) 和 message(string)。

        Returns:
            填充后的 response。
        """
        # 调 service 层，与 HTTP /api/v1/alive 调同一个方法
        data = self._health_service.check_alive()
        # 翻译成 ROS 消息字段
        response.success = data["status"] == "alive"
        response.message = f"{data['status']}|node={data['node_name']}|ts={data['timestamp']}"
        return response

    def _handle_call_agv(self, request, response) -> object:
        """ROS service 回调：处理 ~/call_agv 调用。

        用 Trigger（无参），调 service 层时传 None，用默认值。
        需要传参时用 HTTP 接口 /api/v1/agv/call。

        Args:
            request: Trigger.Request，无字段。
            response: Trigger.Response，含 success(bool) 和 message(string)。

        Returns:
            填充后的 response。
        """
        if self._agv_service is None:
            response.success = False
            response.message = "AGV service 未启用（缺少 http_client 或 agv_config）"
            return response

        try:
            # 调 service 层，传 None 用默认值
            data = self._agv_service.call_agv(None)
            response.success = True
            response.message = f"AGV 呼叫成功|workstation={data['workstation']}"
        except Exception as exc:
            response.success = False
            response.message = f"AGV 呼叫失败: {exc}"
        return response

    def _handle_return_agv(self, request, response) -> object:
        """ROS service 回调：处理 ~/return_agv 调用。

        用 Trigger（无参），调 service 层时传 None，用默认值。
        需要传参时用 HTTP 接口 /api/v1/agv/return。

        Args:
            request: Trigger.Request，无字段。
            response: Trigger.Response，含 success(bool) 和 message(string)。

        Returns:
            填充后的 response。
        """
        if self._agv_service is None:
            response.success = False
            response.message = "AGV service 未启用（缺少 http_client 或 agv_config）"
            return response

        try:
            # 调 service 层，传 None 用默认值
            data = self._agv_service.return_agv(None)
            response.success = True
            response.message = f"AGV 返库成功|workstation={data['workstation']}, container={data['container']}"
        except Exception as exc:
            # 无 container 或 AGV 调度系统失败，转成 ROS service 失败响应
            response.success = False
            response.message = f"AGV 返库失败: {exc}"
        return response

    @property
    def is_alive(self) -> bool:
        """节点是否存活。

        供健康检查路由 /api/v1/alive 和 /api/v1/ros/status 调用。
        rclpy.ok() 在 rclpy 初始化且未 shutdown 时为 True。
        """
        if not _RCLPY_AVAILABLE:
            return False
        return bool(rclpy.ok())


# ── ROS 生命周期函数（供 lifespan 调用）──────────────────────────

def is_ros_available() -> bool:
    """rclpy 是否可用（软依赖检查）。

    Returns:
        True 表示 rclpy 已安装且可正常 import。
    """
    return _RCLPY_AVAILABLE


def init_ros(
    node_name: str = "web_controller",
    http_client=None,
    agv_config=None,
) -> Optional[ControllerNode]:
    """初始化 ROS 并返回节点实例。

    rclpy 未安装时返回 None，调用方据此决定是否启用 ROS 功能。
    rclpy 已安装但 init 失败时抛异常（由上层捕获）。

    Args:
        node_name: ROS 节点名。
        http_client: HttpClient 实例，传给 ControllerNode 供 AgvService 使用。
        agv_config: AgvConfig 实例，传给 ControllerNode 供 AgvService 使用。

    Returns:
        ControllerNode 实例，或 None（rclpy 未装）。
    """
    if not _RCLPY_AVAILABLE:
        return None
    rclpy.init()
    return ControllerNode(node_name, http_client=http_client, agv_config=agv_config)


def shutdown_ros(node: Optional[ControllerNode]) -> None:
    """关闭 ROS 节点并清理资源。

    node 为 None 时什么都不做（rclpy 未装的场景）。
    """
    if node is None:
        return
    node.destroy_node()
    if rclpy.ok():
        rclpy.shutdown()


def spin_in_thread(node: ControllerNode) -> threading.Thread:
    """起 daemon 线程跑 rclpy.spin，返回线程对象供主流程管理。

    rclpy.spin 是阻塞调用，放 daemon 线程避免卡住 uvicorn 主线程。
    daemon=True 保证主进程退出时线程自动结束，不卡关闭流程。
    rclpy 底层 C 库等待消息时释放 GIL，不会阻塞主线程的 asyncio loop。

    Args:
        node: 已初始化的 ControllerNode 实例。

    Returns:
        已启动的 daemon 线程对象。
    """
    t = threading.Thread(target=rclpy.spin, args=(node,), daemon=True)
    t.start()
    return t
