"""应用启动入口。

类比 Spring Boot 的 main 方法：初始化配置 -> 初始化日志 -> 装配 app -> 启动 uvicorn。

支持两种启动方式：
    1. python main.py              # 走 main() 函数，uvicorn.run
    2. uvicorn main:app --reload   # 直接引用模块级 app，便于调试热重载

两种方式都会在 import 阶段完成配置加载、日志初始化、app 装配。
"""
from __future__ import annotations

import uvicorn
from loguru import logger

from bsd_unitree_controller.api.server import create_app
from bsd_unitree_controller.core.config import load_config
from bsd_unitree_controller.utils.logging import setup_logging

# ── 模块级装配：import 本模块即完成配置/日志/app 初始化 ──────────
# 这样 `uvicorn main:app` 不走 main() 也能拿到装配好的 app。
config = load_config()
setup_logging(config.log)
logger.info(
    "配置加载完成: server={}:{}, upstream timeout={}s, retry={}, ros.enabled={}",
    config.server.host, config.server.port,
    config.upstream.timeout, config.upstream.retry,
    config.ros.enabled,
)
app = create_app(config)
logger.info("FastAPI 应用装配完成")


def main() -> None:
    """以脚本方式启动应用（python main.py）。"""
    logger.info("启动 uvicorn，监听 {}:{}", config.server.host, config.server.port)
    uvicorn.run(
        app,
        host=config.server.host,
        port=config.server.port,
    )


if __name__ == "__main__":
    main()
