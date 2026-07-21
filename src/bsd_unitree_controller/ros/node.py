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
    from geometry_msgs.msg import Twist

    _RCLPY_AVAILABLE: bool = True
    _BaseNode = Node
except ImportError:
    _RCLPY_AVAILABLE = False

    # 占位基类：保证本模块在无 rclpy 环境下仍可 import，避免 ImportError
    class _BaseNode:  # type: ignore[no-redef]
        """rclpy 未装时的占位基类，仅用于类型注解，不会被实例化。"""

        pass


# /cmd_vel 是 ROS 生态通用的运动控制话题名，大多数底盘节点默认订阅
CMD_VEL_TOPIC = "/cmd_vel"


class ControllerNode(_BaseNode):
    """机器人控制 ROS 节点。

    后续在此扩展：
        - create_publisher: 发布控制指令到运动控制节点
        - create_subscription: 订阅机器人状态
        - create_service: 提供本节点可被调用的服务

    节点名从 config.ros.node_name 读取（后续接入时改 __init__ 签名），
    当前骨架阶段硬编码默认值为 "controller"。
    """

    def __init__(self, node_name: str = "controller") -> None:
        """初始化节点。

        Args:
            node_name: ROS 节点名，默认 "controller"。
        """
        if not _RCLPY_AVAILABLE:
            raise RuntimeError("rclpy 未安装，无法创建 ROS 节点")
        super().__init__(node_name)
        self.get_logger().info(f"ControllerNode 已启动: {node_name}")

        # ── 运动控制 publisher：发布 Twist 到 /cmd_vel ──────────────
        # 运动控制节点（底盘）订阅 /cmd_vel，收到 Twist 后驱动电机
        # queue_size=10 表示缓冲 10 条指令，超出丢弃旧的
        self._cmd_pub = self.create_publisher(Twist, CMD_VEL_TOPIC, 10)
        self.get_logger().info(f"运动控制 publisher 已注册: {CMD_VEL_TOPIC}")

        # ── 注册 ROS service：其他节点可通过 ros2 service call 调用 ──
        # ~/is_alive 会解析成 /<node_name>/is_alive，即 /controller/is_alive
        # 用 std_srvs/Trigger（ROS 自带），请求空，返回 success + message
        # 业务逻辑调 HealthService，与 HTTP /api/v1/alive 共享同一份逻辑
        from bsd_unitree_controller.service.health_service import HealthService

        self._health_service = HealthService(provider=self)
        self.create_service(Trigger, "~/is_alive", self._handle_is_alive)
        self.get_logger().info("ROS service 已注册: ~/is_alive")

    # ── 运动指令发布（供 MotionService 调用）──────────────────────

    def publish_cmd(self, linear_x: float, angular_z: float) -> None:
        """发布运动指令到 /cmd_vel。

        本方法只做 ROS 通信：构造 Twist 消息并 publish。
        业务逻辑（方向->速度的转换）在 MotionService 层，本方法不参与。
        满足 MotionPublisher 协议，service 通过依赖注入调用。

        Args:
            linear_x: 线速度 m/s，正=前进，负=后退。
            angular_z: 角速度 rad/s，正=左转，负=右转。
        """
        if not _RCLPY_AVAILABLE:
            raise RuntimeError("rclpy 未安装，无法发布运动指令")
        msg = Twist()
        msg.linear.x = linear_x
        msg.angular.z = angular_z
        self._cmd_pub.publish(msg)
        self.get_logger().info(
            f"已发布运动指令: linear_x={linear_x:.2f}, angular_z={angular_z:.2f}"
        )

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

    @property
    def is_alive(self) -> bool:
        """节点是否存活。

        供健康检查路由 /api/v1/ros/status 调用。
        context.is_valid() 在节点未销毁且 rclpy 仍 ok 时为 True。
        """
        if not _RCLPY_AVAILABLE:
            return False
        return bool(self.context.is_valid())


# ── ROS 生命周期函数（供 lifespan 调用）──────────────────────────

def is_ros_available() -> bool:
    """rclpy 是否可用（软依赖检查）。

    Returns:
        True 表示 rclpy 已安装且可正常 import。
    """
    return _RCLPY_AVAILABLE


def init_ros(node_name: str = "controller") -> Optional[ControllerNode]:
    """初始化 ROS 并返回节点实例。

    rclpy 未安装时返回 None，调用方据此决定是否启用 ROS 功能。
    rclpy 已安装但 init 失败时抛异常（由上层捕获）。

    Args:
        node_name: ROS 节点名。

    Returns:
        ControllerNode 实例，或 None（rclpy 未装）。
    """
    if not _RCLPY_AVAILABLE:
        return None
    rclpy.init()
    return ControllerNode(node_name)


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
