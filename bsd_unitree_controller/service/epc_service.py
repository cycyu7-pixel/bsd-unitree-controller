"""EPC 条码读取服务。

本层是业务逻辑的唯一真相源，HTTP 入口调这里。
不 import fastapi，业务逻辑能脱离框架单测。

流程：
    1. start_scan：调 RFID 服务发起扫描，对方返回 requestId，缓存 requestId
    2. handle_callback：RFID 读到 EPC 后回调本系统，用 requestId 校验一致性后缓存 epc
    3. 失败自动重扫：扫描失败时清理缓存，自动重新调 start_scan，用 MAX_RETRIES 限制防止死循环

依赖注入：通过 Protocol 接收 HttpClient，测试时可用 mock 替换。

存储方式类比 AgvService._last_container：用类变量跨请求共享，
FastAPI 每次请求创建新实例，所以不能存实例变量上。
requestId 的作用：回调时用它定位当前那次扫描，保证 epc 读取的一致性，
防止把无关/过期的回调误更新到当前 epc 缓存上。
"""
from __future__ import annotations

from typing import ClassVar, Protocol, runtime_checkable

from loguru import logger

from bsd_unitree_controller.core.config import EpcConfig
from bsd_unitree_controller.exception.exceptions import UpstreamException
from bsd_unitree_controller.model.dto import EpcCallbackDTO


@runtime_checkable
class HttpCaller(Protocol):
    """HTTP 调用者协议。

    任何具备 post(url, json, ...) 方法的对象都满足此协议。
    HttpClient 满足，测试时可用 mock 替换。
    """

    def post(self, url: str, *, json=None, **kwargs):
        """发起 POST 请求。"""
        ...


class EpcService:
    """EPC 条码读取服务。

    业务逻辑集中在此：
        1. 发起扫描：调 RFID 服务，缓存 requestId，返回给调用方
        2. 处理回调：RFID 读到 EPC 后回调，用 requestId 校验一致性后缓存 epc
        3. 失败自动重扫：失败清理缓存后自动重新发起扫描，MAX_RETRIES 限制防死循环

    HTTP 入口（/api/v1/epc/start-scan 和 /api/v1/epc/callback）调本服务。

    注意：以下都是类变量，跨请求共享。
    FastAPI 每次请求创建新 EpcService 实例，所以不能存实例变量上。
    用法和 AgvService._last_container 完全一致：发起扫描存 -> 回调校验/更新 -> 后续读取 -> 用完清。
    """

    # 扫描失败最大自动重试次数，防止死循环
    MAX_RETRIES: ClassVar[int] = 3

    # 类变量：跨请求共享当前扫描的 requestId、读到的 epc、连续失败重试计数
    _last_request_id: ClassVar[str | None] = None
    _last_epc: ClassVar[str | None] = None
    _retry_count: ClassVar[int] = 0

    def __init__(self, config: EpcConfig, http_client: HttpCaller | None) -> None:
        """初始化服务。

        Args:
            config: EPC 配置（base_url / scan_path）。
            http_client: HTTP 客户端，用于调 RFID 服务接口。
        """
        self._config = config
        self._http = http_client

    # ── 发起扫描 ─────────────────────────────────────────────────

    def start_scan(self) -> dict:
        """发起 EPC 扫描（主动调用，全新一轮）。

        调 RFID 服务发起扫描，对方返回 requestId 后缓存到类变量，
        同时清空旧的 epc 缓存。主动发起时重置重试计数，重试计数从本轮重新计算。

        Returns:
            dict，含 {"requestId": "uuid"}。

        Raises:
            UpstreamException: RFID 服务调用失败或返回失败时抛出。
        """
        # 主动发起视为全新一轮，重置重试计数
        EpcService._retry_count = 0
        return self._do_scan()

    def _do_scan(self) -> dict:
        """实际发起扫描逻辑（主动扫描和失败重扫共用）。

        不重置重试计数，仅缓存 requestId 并清空 epc。

        Returns:
            dict，含 {"requestId": "uuid"}。

        Raises:
            UpstreamException: RFID 服务调用失败或返回失败时抛出。
        """
        url = f"{self._config.base_url}{self._config.scan_path}"

        logger.info("EPC 发起扫描: url={}", url)

        # 调 RFID 服务（无参数）
        resp = self._http.post(url)
        data = resp.json()

        # 业务校验：对方返回 success=false 表示发起失败
        if not data.get("success", False):
            raise UpstreamException(
                f"RFID 服务返回失败: message={data.get('message')}"
            )

        # 提取 requestId
        request_id = data.get("data", {}).get("requestId", "")
        if not request_id:
            raise UpstreamException("RFID 服务返回的 requestId 为空")

        # 缓存 requestId，清空旧 epc（等待本次扫描的回调覆盖）
        EpcService._last_request_id = request_id
        EpcService._last_epc = None

        logger.info("EPC 扫描已发起: requestId={}", request_id)
        return {"requestId": request_id}

    # ── 处理回调 ─────────────────────────────────────────────────

    def handle_callback(self, dto: EpcCallbackDTO) -> dict:
        """处理 EPC 扫描结果回调。

        RFID 服务扫描到 EPC 或超时失败后，回调本接口（三个入参：requestId/epc/error）。
        处理规则：
            1. 一致性校验：dto.requestId 必须与当前缓存的 _last_request_id 匹配，
               不匹配视为过期/无关回调，忽略，不污染当前缓存
            2. 成功：requestId 匹配 && 有 epc && error 为 null → 保存 _last_epc，重置重试计数
            3. 失败：requestId 匹配但 error 不为空（或没读到 epc）→ 清理缓存，
               自动重新调用 _do_scan 发起下一轮扫描；重试次数达到 MAX_RETRIES 则停止，
               避免死循环

        Args:
            dto: 回调入参，含 requestId、epc、error。

        Returns:
            dict，按对方期望格式返回 {"success": true, "message": "..."}。
        """
        request_id = dto.requestId
        epc = dto.epc
        error = dto.error

        logger.info(
            "EPC 扫描回调: requestId={}, epc={}, error={}",
            request_id, epc, error,
        )

        # 1. 一致性校验：防止把无关/过期回调误更新到当前 epc
        if request_id != EpcService._last_request_id:
            logger.warning(
                "EPC 回调 requestId 与当前扫描不匹配，已忽略: 收到={}, 当前缓存={}",
                request_id, EpcService._last_request_id,
            )
            return {
                "success": True,
                "message": f"EPC 回调 requestId 不匹配，已忽略: requestId={request_id}",
            }

        # 2. 成功：uuid 对上 && 有 epc && error 为 null → 保存 epc
        if error is None and epc:
            EpcService._last_epc = epc
            EpcService._retry_count = 0  # 成功，重置重试计数
            logger.info("EPC 扫描成功: requestId={}, epc={}", request_id, epc)
            return {
                "success": True,
                "message": f"EPC 回调已接收: requestId={request_id}, epc={epc}",
            }

        # 3. 失败：error 不为空（或没读到 epc）→ 清理缓存，自动重扫（限次数）
        logger.warning(
            "EPC 扫描失败: requestId={}, epc={}, error={}",
            request_id, epc, error,
        )
        EpcService._last_request_id = None
        EpcService._last_epc = None
        EpcService._retry_count += 1

        if EpcService._retry_count < EpcService.MAX_RETRIES:
            # 未达上限，自动重新发起扫描
            logger.info(
                "EPC 扫描失败，自动重扫: 第 {} 次 / 最多 {} 次",
                EpcService._retry_count, EpcService.MAX_RETRIES,
            )
            self._do_scan()
            return {
                "success": True,
                "message": (
                    f"EPC 扫描失败，已自动重扫: 第 {EpcService._retry_count} 次 / "
                    f"最多 {EpcService.MAX_RETRIES} 次"
                ),
            }

        # 达到上限，停止，准备人工处理
        logger.error(
            "EPC 扫描失败且已达最大重试次数 {} 次，停止自动重扫，请人工处理",
            EpcService.MAX_RETRIES,
        )
        EpcService._retry_count = 0  # 重置，方便上层重新主动发起新一轮
        return {
            "success": True,
            "message": (
                f"EPC 扫描失败，已达最大重试次数 {EpcService.MAX_RETRIES} 次，"
                f"已停止自动重扫，请重新发起扫描"
            ),
        }