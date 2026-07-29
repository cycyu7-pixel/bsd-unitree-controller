"""AGV 调度服务。

本层是业务逻辑的唯一真相源，HTTP 入口调这里。
不 import fastapi，业务逻辑能脱离框架单测。

包含：
    - call_agv：呼叫 AGV 小车到指定工位
    - handle_arrived：处理 AGV 到位回调

依赖注入：通过 Protocol 接收 HttpClient，测试时可用 mock 替换。
"""
from __future__ import annotations

from typing import Any, Mapping, Protocol, runtime_checkable

from loguru import logger

from bsd_unitree_controller.core.config import AgvConfig
from bsd_unitree_controller.exception.exceptions import BizException, UpstreamException


@runtime_checkable
class HttpCaller(Protocol):
    """HTTP 调用者协议。

    任何具备 post(url, json, ...) 方法的对象都满足此协议。
    HttpClient 满足，测试时可用 mock 替换。
    """

    def post(self, url: str, *, json=None, **kwargs):
        """发起 POST 请求。"""
        ...


class AgvService:
    """AGV 调度服务。

    业务逻辑集中在此：
        1. 呼叫 AGV：构造请求体（barcode/podCategory/workstation），调 AGV 调度系统接口
        2. 处理到位：对方回调通知 AGV 到位，记录日志并返回确认

    HTTP 入口（/api/v1/agv/call 和 /api/v1/agv/arrived）调本服务。
    """

    def __init__(self, config: AgvConfig, http_client: HttpCaller) -> None:
        """初始化服务。

        Args:
            config: AGV 配置（base_url / call_path / workstation）。
            http_client: HTTP 客户端，用于调 AGV 调度系统接口。
        """
        self._config = config
        self._http = http_client

    def call_agv(self) -> dict:
        """呼叫 AGV 小车到配置的工位。

        构造请求体调用 AGV 调度系统，workstation 从配置读取。
        AGV 调度系统返回 success=true 表示呼叫成功（小车开始移动）。
        小车实际到位后会回调 /api/v1/agv/arrived 通知本服务。

        Returns:
            dict，含 workstation 和对方返回的原始响应。

        Raises:
            UpstreamException: AGV 调度系统返回非 2xx 或 success=false 时抛出。
        """
        # 拼完整 URL
        url = f"{self._config.base_url}{self._config.call_path}"

        # 构造请求体，workstation 从配置读取
        payload = {
            "barcode": "",
            "podCategory": "1",
            "workstation": self._config.workstation,
        }

        logger.info("呼叫 AGV: url={}, workstation={}", url, self._config.workstation)

        # 调 AGV 调度系统
        resp = self._http.post(url, json=payload)
        data = resp.json()

        # 业务校验：对方返回 success=false 表示呼叫失败
        if not data.get("success", False):
            raise UpstreamException(
                f"AGV 调度系统返回失败: code={data.get('code')}, message={data.get('message')}"
            )

        logger.info("AGV 呼叫成功: workstation={}", self._config.workstation)
        return {
            "workstation": self._config.workstation,
            "response": data,
        }

    def handle_arrived(self, payload: Mapping[str, Any]) -> dict:
        """处理 AGV 到位回调。

        AGV 到位后，调度系统回调本接口通知。当前只记录日志并返回确认，
        后续可扩展（如通知 ROS 节点、触发业务流程等）。

        Args:
            payload: 对方回调传来的数据，字段格式由对方决定，当前用 dict 接收。

        Returns:
            dict，按对方期望格式返回 {"success": true, "message": "..."}。
        """
        logger.info("AGV 已到位: {}", dict(payload))

        # 后续扩展点：到位后可通知 ROS 节点或触发业务流程
        # 例如：ros_node.publish_arrived(payload)

        return {
            "success": True,
            "message": "AGV 到位通知已接收",
        }
