"""应用启动入口（ROS 节点入口）。

类比 Spring Boot 的 main 方法：初始化配置 -> 初始化日志 -> 装配 app -> 启动 uvicorn。

支持两种启动方式：
    1. ros2 run bsd_unitree_controller controller   # ROS package 标准启动
    2. python -m bsd_unitree_controller.main         # 直接 python 启动

两种模式：
    - 机器人环境（有 rclpy）：FastAPI + ROS 节点同时运行
    - 开发机环境（无 rclpy）：纯 HTTP 模式，ROS 接口返回降级响应
"""
from __future__ import annotations

import uvicorn
from loguru import logger

from bsd_unitree_controller.api.server import create_app
from bsd_unitree_controller.core.config import load_config
from bsd_unitree_controller.utils.logging import setup_logging


def main() -> None:
    """启动应用（ROS 节点入口）。

    被 setup.py 的 entry_points 注册为 console_script：
        ros2 run bsd_unitree_controller controller
    等价于：
        python -m bsd_unitree_controller.main
    """
    # 1. 加载配置
    config = load_config()
    setup_logging(config.log)
    logger.info(
        "配置加载完成: server={}:{}, upstream timeout={}s, retry={}, ros.enabled={}",
        config.server.host, config.server.port,
        config.upstream.timeout, config.upstream.retry,
        config.ros.enabled,
    )

    # 2. 装配 FastAPI 应用（lifespan 内部会条件性初始化 ROS 节点）
    app = create_app(config)
    logger.info("FastAPI 应用装配完成")

    # 3. 启动 uvicorn（主线程阻塞，ROS 在 lifespan 后台线程 spin）
    logger.info("启动 uvicorn，监听 {}:{}", config.server.host, config.server.port)
    uvicorn.run(
        app,
        host=config.server.host,
        port=config.server.port,
    )


if __name__ == "__main__":
    main()
