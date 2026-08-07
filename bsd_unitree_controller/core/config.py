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


class AgvConfig(BaseModel):
    """AGV 调度系统配置。

    用于呼叫 AGV 小车到指定工位，并接收 AGV 到位回调。
    base_url 拆分出来便于切换环境（测试/生产），path 和 workstation 跟着场景走。
    """

    base_url: str = "https://gwwms.bsdits.cn"               # AGV 调度系统基础地址
    call_path: str = "/wcs/hikagv/callRobotComeByType"      # 呼叫 AGV 接口路径
    return_path: str = "/wcs/hikagv/hikAGVCTUInCallRobotBack"  # 返库接口路径
    workstation: str = "W03"                                # 工位号（每个机器人不同）


class EpcConfig(BaseModel):
    """EPC 条码读取服务配置。

    调 RFID 服务发起扫描，RFID 读到 EPC 后回调本系统。
    base_url 拆分出来便于切换环境（测试/生产）。
    """

    base_url: str = "http://localhost:8080"   # RFID 服务基础地址
    scan_path: str = "/api/rfid/scan"         # 发起扫描接口路径


class LogConfig(BaseModel):
    """日志配置。"""

    level: str = "INFO"            # 日志级别：DEBUG / INFO / WARNING / ERROR
    dir: Optional[str] = "logs"   # 日志文件目录，为空只输出控制台


class RosConfig(BaseModel):
    """ROS 节点配置。

    enabled=false 时纯 HTTP 模式，不初始化 ROS（适合 rclpy 未装或调试时）。
    """

    enabled: bool = True                  # 是否启用 ROS 节点
    node_name: str = "api_ctr"     # ROS 节点名


# ── 顶层配置 ────────────────────────────────────────────────────────

class AppConfig(BaseModel):
    """全局配置，对应 config.yaml 顶层结构。"""

    server: ServerConfig = Field(default_factory=ServerConfig)
    upstream: UpstreamConfig = Field(default_factory=UpstreamConfig)
    log: LogConfig = Field(default_factory=LogConfig)
    ros: RosConfig = Field(default_factory=RosConfig)
    agv: AgvConfig = Field(default_factory=AgvConfig)
    epc: EpcConfig = Field(default_factory=EpcConfig)


# ── 加载逻辑 ────────────────────────────────────────────────────────

# 配置文件查找路径（按优先级）：
# 1. 环境变量 BSD_CONFIG_PATH 指定的路径（部署时灵活指定）
# 2. 包同级目录的 config/config.yaml（开发时，项目根/config/config.yaml）
# 3. 包安装目录的 config/config.yaml（colcon install 后）
# 4. /app/config/config.yaml（Docker 容器内）
# 本文件位于 bsd_unitree_controller/core/config.py，向上回退两级到包同级目录
_PACKAGE_DIR = Path(__file__).resolve().parent.parent
_DEFAULT_CONFIG_PATHS = [
    Path(_PACKAGE_DIR) / "config" / "config.yaml",          # 开发：项目根/config/
    Path(_PACKAGE_DIR).parent / "config" / "config.yaml",   # colcon install 后上级
    Path("/app/config/config.yaml"),                        # Docker 容器
]


def _find_config_path() -> Path | None:
    """按优先级查找配置文件，返回第一个存在的路径。

    Returns:
        配置文件路径，找不到返回 None。
    """
    # 1. 环境变量优先
    env_path = os.environ.get("BSD_CONFIG_PATH")
    if env_path:
        p = Path(env_path)
        if p.exists():
            return p

    # 2. 默认路径列表
    for p in _DEFAULT_CONFIG_PATHS:
        if p.exists():
            return p
    return None


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

    配置文件查找优先级：
        1. 参数显式传入 config_path
        2. 环境变量 BSD_CONFIG_PATH
        3. 包同级目录 config/config.yaml（开发环境）
        4. 包上级目录 config/config.yaml（colcon install 后）
        5. /app/config/config.yaml（Docker 容器）
    都找不到则用 Pydantic 默认值。

    Args:
        config_path: 配置文件路径，显式传入时优先用这个。

    Returns:
        AppConfig 实例。配置文件不存在时返回默认值，仍会应用环境变量覆盖。
    """
    # 显式传入 > 环境变量 > 默认查找列表
    if config_path is None:
        config_path = _find_config_path()

    raw: dict[str, Any] = {}
    if config_path and config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

    # 环境变量覆盖 yaml，便于不改文件就能临时调端口/上游地址
    _apply_env_overrides(raw)

    return AppConfig.model_validate(raw)


# 全局单例：业务代码直接 import 使用。
# 注意：http_client 等组件应通过依赖注入接收 config，避免直接读全局单例，
# 便于测试时传入不同配置。
config = load_config()
