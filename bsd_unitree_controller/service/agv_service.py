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

    注意：_last_container 是类变量，跨请求共享。
    FastAPI 每次请求创建新 AgvService 实例，所以不能存实例变量上。
    """

    # 类变量：跨请求共享到位回调缓存的 container
    _last_container: str | None = None

    def __init__(self, config: AgvConfig, http_client: HttpCaller) -> None:
        """初始化服务。

        Args:
            config: AGV 配置（base_url / call_path / workstation）。
            http_client: HTTP 客户端，用于调 AGV 调度系统接口。
        """
        self._config = config
        self._http = http_client
        # AGV 调度系统固定请求头（鉴权用）
        self._headers = {
            "usercode": "116173",
            "X-Access-Token": "1",
        }

    def call_agv(self, dto=None) -> dict:
        """呼叫 AGV 小车到配置的工位。

        构造请求体调用 AGV 调度系统。
        字段优先级：DTO 传入 > 配置/写死默认值。
        AGV 调度系统返回 success=true 表示呼叫成功（小车开始移动）。
        小车实际到位后会回调 /api/v1/agv/arrived 通知本服务。

        Args:
            dto: 呼叫 AGV 入参 DTO，None 时用默认值。字段可选，传了就覆盖默认值。

        Returns:
            dict，含实际使用的 workstation 和对方返回的原始响应。

        Raises:
            UpstreamException: AGV 调度系统返回非 2xx 或 success=false 时抛出。
        """
        # 拼完整 URL
        url = f"{self._config.base_url}{self._config.call_path}"

        # 字段优先级：DTO 传入 > 默认值
        barcode = (dto.barcode if dto and dto.barcode is not None else "") or ""
        pod_category = (dto.podCategory if dto and dto.podCategory is not None else "2") or "2"
        workstation = (dto.workstation if dto and dto.workstation is not None else self._config.workstation) or self._config.workstation

        # 构造请求体
        payload = {
            "barcode": barcode,
            "podCategory": pod_category,
            "workstation": workstation,
        }

        logger.info("呼叫 AGV: url={}, payload={}", url, payload)

        # 调 AGV 调度系统（带固定鉴权请求头）
        resp = self._http.post(url, json=payload, headers=self._headers)
        data = resp.json()

        # 业务校验：对方返回 success=false 表示呼叫失败
        if not data.get("success", False):
            raise UpstreamException(
                f"AGV 调度系统返回失败: code={data.get('code')}, message={data.get('message')}"
            )

        logger.info("AGV 呼叫成功: workstation={}", workstation)
        return {
            "workstation": workstation,
            "response": data,
        }

    def handle_arrived(self, payload: Mapping[str, Any]) -> dict:
        """处理 AGV 到位回调。

        AGV 到位后，调度系统回调本接口通知。对方传完整字段（podCode/robotId/
        taskCode/位置/电量等），本系统当前只取 podCode 缓存供返库用，
        其余字段记录日志便于排查，后续可扩展处理。

        Args:
            payload: 对方回调传来的完整数据。

        Returns:
            dict，按对方期望格式返回 {"success": true, "message": "..."}。
        """
        # 取关键字段（container 是对方实际用的字段名，podCode 兼容）
        container = payload.get("container") or payload.get("podCode") or ""
        task_code = payload.get("taskCode") or ""
        robot_id = payload.get("robotId") or ""
        robot_type = payload.get("robotType") or ""
        status_code = payload.get("statusCode")
        battery = payload.get("batteryLevel")

        # 完整记录对方传的参数，便于排查
        logger.info(
            "AGV 已到位: container={}, taskCode={}, robotId={}, robotType={}, "
            "statusCode={}, battery={}%, posX={}, posY={}",
            container, task_code, robot_id, robot_type,
            status_code, battery,
            payload.get("posX"), payload.get("posY"),
        )

        # container 缓存到类变量，供 return_agv 使用（返库时作为 podNo）
        # 注意：FastAPI 每次请求创建新实例，所以不能存实例变量
        AgvService._last_container = container
        logger.info("AGV 到位缓存 container: [{}]", container)

        # 后续扩展点：到位后可通知 ROS 节点或触发业务流程
        # 例如：ros_node.publish_arrived(payload)

        return {
            "success": True,
            "message": f"AGV 到位通知已接收: container={container}, robotId={robot_id}",
        }

    def return_agv(self, dto=None) -> dict:
        """触发 AGV 返库。

        调 AGV 调度系统返库接口。
        字段优先级：DTO 传入 > 缓存/配置/写死默认值。
        参数映射（默认值）：
            - podCategory: 空字符串
            - podNo: 到位回调缓存的 container
            - type: "FK"
            - workstationNo: 从配置读取的 workstation

        Args:
            dto: 返库入参 DTO，None 时用默认值。字段可选，传了就覆盖默认值。
                 podNo 不传时用缓存的 container。

        Returns:
            dict，含实际使用的 workstation、podNo 和对方返回的原始响应。

        Raises:
            BizException: 没有缓存的 container 且 DTO 也没传 podNo 时抛出。
            UpstreamException: AGV 调度系统返回失败时抛出。
        """
        # podNo 优先级：DTO 传入 > 缓存 container
        pod_no = (dto.podNo if dto and dto.podNo is not None else None)
        if not pod_no:
            pod_no = AgvService._last_container
            logger.info("AGV 返库: 使用缓存的 container=[{}]", pod_no)
        if not pod_no:
            logger.warning("AGV 返库失败: 无 container 可用，请先等待到位回调")
            raise BizException(
                code=50004,
                message="无 container 可用，请先呼叫 AGV 并等待到位回调，或在入参中传 podNo",
            )

        # 其他字段优先级：DTO 传入 > 默认值
        pod_category = (dto.podCategory if dto and dto.podCategory is not None else "") or ""
        type_val = (dto.type if dto and dto.type is not None else "FK") or "FK"
        workstation_no = (dto.workstationNo if dto and dto.workstationNo is not None else self._config.workstation) or self._config.workstation

        # 拼完整 URL
        url = f"{self._config.base_url}{self._config.return_path}"

        # 构造请求体
        payload = {
            "podCategory": pod_category,
            "podNo": pod_no,
            "type": type_val,
            "workstationNo": workstation_no,
        }

        logger.info("AGV 返库: url={}, payload={}, headers={}", url, payload, self._headers)

        # 调 AGV 调度系统（带固定鉴权请求头）
        resp = self._http.post(url, json=payload, headers=self._headers)
        data = resp.json()

        # 业务校验
        if not data.get("success", False):
            raise UpstreamException(
                f"AGV 调度系统返回失败: code={data.get('code')}, message={data.get('message')}"
            )

        logger.info("AGV 返库成功: podNo={}", pod_no)

        # 返库成功后清除缓存，避免下次返库用到旧的 container
        AgvService._last_container = None

        return {
            "workstation": workstation_no,
            "container": pod_no,
            "response": data,
        }
