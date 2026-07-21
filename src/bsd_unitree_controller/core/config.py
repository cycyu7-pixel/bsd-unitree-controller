"""配置加载模块。

类比 Spring Boot 的 @ConfigurationProperties：把 config.yaml 加载成
带类型校验的 Pydantic 模型，同时支持环境变量覆盖。

环境变量覆盖规则：
    - 前缀：BSD_
    - 嵌套分隔符：__
    - 示例：BSD_SERVER__PORT=9000  ->  config.server.port = 9000
    - 示例：BSD_UPSTREAM__TIMEOUT=5  ->  config.upstream.timeout = 5
    - 字段名一律转小写匹配

加载优先级：环境变量 > yaml 文件 > Pydantic 默认值。

注意：upstream 不含 base_url，各上游 URL 在业务代码里按需硬编码
（会有多个目标地址，不适合统一配置）。
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import BaseModel, Field

# ── 环境变量覆盖规则 ────────────────────────────────────────────────
_ENV_PREFIX = "BSD_"
_ENV_DELIMITER = "__"


# ── 各配置段 ────────────────────────────────────────────────────────

class ServerConfig(BaseModel):
    """FastAPI 服务配置。"""

    host: str = "0.0.0.0"   # 监听地址
    port: int = 18800        # 监听端口


class UpstreamConfig(BaseModel):
    """出站 HTTP 调用通用配置。

    只放超时和重试这类所有上游通用的参数。
    各上游的 URL 在业务代码里按需硬编码，因为通常会有多个目标地址。
    """

    timeout: int = 10    # 出站请求超时（秒）
    retry: int = 2       # 出站请求重试次数（不含首次）


class LogConfig(BaseModel):
    """日志配置。"""

    level: str = "INFO"            # 日志级别：DEBUG / INFO / WARNING / ERROR
    dir: Optional[str] = "logs"   # 日志文件目录，为空只输出控制台


class RosConfig(BaseModel):
    """ROS 节点配置。

    enabled=false 时纯 HTTP 模式，不初始化 ROS（适合 rclpy 未装或调试时）。
    """

    enabled: bool = True              # 是否启用 ROS 节点
    node_name: str = "controller"     # ROS 节点名


# ── 顶层配置 ────────────────────────────────────────────────────────

class AppConfig(BaseModel):
    """全局配置，对应 config.yaml 顶层结构。"""

    server: ServerConfig = Field(default_factory=ServerConfig)
    upstream: UpstreamConfig = Field(default_factory=UpstreamConfig)
    log: LogConfig = Field(default_factory=LogConfig)
    ros: RosConfig = Field(default_factory=RosConfig)


# ── 加载逻辑 ────────────────────────────────────────────────────────

# 默认配置文件路径：项目根目录 / config / config.yaml
# 本文件位于 src/bsd_unitree_controller/core/config.py，向上回退三级到项目根
_DEFAULT_CONFIG_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent / "config" / "config.yaml"
)


def _apply_env_overrides(raw: dict[str, Any]) -> None:
    """把 BSD_ 前缀的环境变量写进 raw dict，覆盖 yaml 值。

    BSD_SERVER__PORT=9000        ->  raw["server"]["port"] = "9000"
    BSD_UPSTREAM__TIMEOUT=5      ->  raw["upstream"]["timeout"] = "5"

    Args:
        raw: yaml 解析后的字典，会被原地修改。
    """
    for env_key, env_val in os.environ.items():
        if not env_key.startswith(_ENV_PREFIX):
            continue
        # 去掉前缀后按分隔符切成路径，全部转小写匹配字段名
        path = env_key[len(_ENV_PREFIX):].lower().split(_ENV_DELIMITER)
        if not path or not path[0]:
            continue

        # 沿路径逐层建/进 dict，最后一层赋值
        node = raw
        for p in path[:-1]:
            existing = node.get(p)
            if not isinstance(existing, dict):
                # yaml 没有这一段或不是 dict，新建一层覆盖
                node[p] = {}
            node = node[p]
        node[path[-1]] = env_val


def load_config(config_path: Optional[Path] = None) -> AppConfig:
    """加载配置文件并构造 AppConfig。

    加载顺序：yaml 文件 -> 环境变量覆盖 -> Pydantic 校验。

    Args:
        config_path: 配置文件路径，默认为 项目根/config/config.yaml。

    Returns:
        AppConfig 实例。配置文件不存在时返回默认值，仍会应用环境变量覆盖。
    """
    path = config_path or _DEFAULT_CONFIG_PATH
    raw: dict[str, Any] = {}
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

    # 环境变量覆盖 yaml，便于不改文件就能临时调端口/上游地址
    _apply_env_overrides(raw)

    return AppConfig.model_validate(raw)


# 全局单例：业务代码直接 import 使用。
# 注意：http_client 等组件应通过依赖注入接收 config，避免直接读全局单例，
# 便于测试时传入不同配置。
config = load_config()
