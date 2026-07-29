"""HTTP 客户端封装。

类比 FeignClient + RestTemplate：封装 httpx + tenacity，
对上层提供带重试、超时、日志、异常包装的通用 HTTP 调用能力。

本类只提供通用 get/post 方法，不写任何业务逻辑。
调用方传完整 URL + 参数即可发起请求，业务方法由调用方自行编写。
各上游 URL 在业务代码里按需硬编码，本类不持有任何 base_url。

重试策略：
    - 仅网络层错误（httpx.RequestError，含超时、连接失败）重试
    - HTTP 4xx/5xx 视为业务错误，抛 UpstreamException，不重试
    - 指数退避：1s, 2s, 4s...，上限 10s
    - 重试次数从实例配置读取（config.upstream.retry + 1，含首次调用）
"""
from __future__ import annotations

from typing import Any, Mapping, Optional

import httpx
from loguru import logger
from tenacity import (
    Retrying,
    before_sleep_log,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from bsd_unitree_controller.core.config import AppConfig, UpstreamConfig
from bsd_unitree_controller.exception.exceptions import UpstreamException

# tenacity 重试日志 logger，单独 bind 便于过滤
_retry_logger = logger.bind(name="http_client")


class HttpClient:
    """通用 HTTP 客户端。

    封装 httpx.Client（连接池复用），底层调用带 tenacity 重试。
    上层通过 get/post 方法调任何外部 HTTP 服务，必须传完整 URL。

    重试参数绑在实例上，从传入的 config 读取，避免模块级常量与实例配置脱节。
    """

    def __init__(self, config: AppConfig) -> None:
        """初始化 HttpClient。

        Args:
            config: 全局配置，取 upstream 段构造 httpx.Client 和重试参数。
        """
        self._config: UpstreamConfig = config.upstream
        # 不设 base_url，所有请求由调用方传完整 URL
        self._client = httpx.Client(
            timeout=self._config.timeout,
        )
        # 重试次数（含首次调用），类比 Spring Retry 的 maxAttempts
        self._retry_attempts: int = self._config.retry + 1

    # ── 通用调用方法（带 tenacity 重试）──────────────────────────

    def _build_retrying(self) -> Retrying:
        """构造 Retrying 实例，参数绑当前实例配置。

        用 Retrying 而非 @retry 装饰器的原因：
            @retry 在类定义时绑定，无法读取实例属性 self._retry_attempts。
            Retrying 在方法内构造，可灵活使用实例配置，便于测试时传入不同重试次数。
        """
        return Retrying(
            stop=stop_after_attempt(self._retry_attempts),
            wait=wait_exponential(multiplier=1, min=1, max=10),
            retry=retry_if_exception_type(httpx.RequestError),
            before_sleep=before_sleep_log(_retry_logger, "WARNING"),
            reraise=True,   # 重试用尽后抛原始异常，不包成 RetryError
        )

    def _request(
        self,
        method: str,
        url: str,
        *,
        params: Optional[Mapping[str, Any]] = None,
        json: Optional[Any] = None,
        data: Optional[Any] = None,
        headers: Optional[Mapping[str, str]] = None,
    ) -> httpx.Response:
        """统一 HTTP 请求入口，带重试。

        网络层错误（连接失败、超时）自动重试，HTTP 4xx/5xx 不重试直接抛。
        本方法为内部方法，上层应使用 get/post。

        Args:
            method: HTTP 方法，如 "GET" / "POST"。
            url: 请求 URL，必须是完整 URL（带 http(s)://）。
            params: URL query 参数。
            json: JSON body，会自动序列化并设置 Content-Type。
            data: 表单或原始 body，与 json 二选一。
            headers: 自定义请求头。

        Returns:
            httpx.Response 响应对象，调用方自行 .json() / .text() 解析。

        Raises:
            UpstreamException: HTTP 状态码非 2xx 时抛出，不重试。
            httpx.RequestError: 重试用尽后抛出原始网络异常。
        """
        retrying = self._build_retrying()
        for attempt in retrying:
            with attempt:
                resp = self._client.request(
                    method, url,
                    params=params, json=json, data=data, headers=headers,
                )
                # 业务错误（4xx/5xx）不在重试范围，立即抛 UpstreamException
                if resp.status_code >= 400:
                    raise UpstreamException(
                        f"HTTP 调用返回非成功状态: {resp.status_code} {resp.text}"
                    )
                return resp
        # 理论上不会执行到这里，tenacity 要么返回要么抛异常
        raise UpstreamException("HTTP 调用未返回有效响应")

    # ── 公开调用方法 ────────────────────────────────────────────

    def get(
        self,
        url: str,
        *,
        params: Optional[Mapping[str, Any]] = None,
        headers: Optional[Mapping[str, str]] = None,
    ) -> httpx.Response:
        """发起 GET 请求。

        Args:
            url: 请求 URL，必须是完整 URL（带 http(s)://）。
            params: URL query 参数，如 {"page": 1, "size": 10}。
            headers: 自定义请求头。

        Returns:
            httpx.Response 响应对象。

        Raises:
            UpstreamException: HTTP 状态码非 2xx 时抛出。
        """
        return self._request("GET", url, params=params, headers=headers)

    def post(
        self,
        url: str,
        *,
        json: Optional[Any] = None,
        data: Optional[Any] = None,
        params: Optional[Mapping[str, Any]] = None,
        headers: Optional[Mapping[str, str]] = None,
    ) -> httpx.Response:
        """发起 POST 请求。

        json 和 data 二选一：json 传 JSON body，data 传表单或原始 body。

        Args:
            url: 请求 URL，必须是完整 URL（带 http(s)://）。
            json: JSON body，会自动序列化，如 {"name": "test", "age": 18}。
            data: 表单或原始 body，如 {"field": "value"}（表单）或 bytes（原始）。
            params: URL query 参数。
            headers: 自定义请求头。

        Returns:
            httpx.Response 响应对象。

        Raises:
            UpstreamException: HTTP 状态码非 2xx 时抛出。
        """
        return self._request(
            "POST", url,
            json=json, data=data, params=params, headers=headers,
        )

    # ── 资源释放 ───────────────────────────────────────────────

    def close(self) -> None:
        """关闭底层 httpx 连接池。应用退出时调用。"""
        self._client.close()
