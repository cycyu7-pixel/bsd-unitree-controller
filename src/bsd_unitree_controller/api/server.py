"""FastAPI 应用装配。

类比 Spring Boot 的 @SpringBootApplication + 各种 @Configuration：
负责创建 FastAPI app、注册路由、注册异常处理器、装配 HttpClient、
启动/关闭 ROS 节点。

本模块对外暴露：
    - create_app(config): 工厂函数，测试和启动都用它
    - app: 模块级单例，供 uvicorn main:app 直接引用
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI
from loguru import logger

from bsd_unitree_controller.api import api_router
from bsd_unitree_controller.client.http_client import HttpClient
from bsd_unitree_controller.core.config import AppConfig, config as _global_config
from bsd_unitree_controller.exception.handlers import register_exception_handlers
from bsd_unitree_controller.ros.node import (
    init_ros,
    is_ros_available,
    shutdown_ros,
    spin_in_thread,
)


def _build_lifespan(config: AppConfig):
    """构造 lifespan 上下文管理器，闭包捕获 config。

    ROS 生命周期与本函数耦合，所以用工厂函数把 config 注入进来，
    避免在 lifespan 内部再读全局 config。
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        """应用生命周期钩子。

        启动时：装配 HttpClient + 初始化 ROS 节点（条件性）。
        关闭时：释放 ROS + HttpClient 资源。

        ROS 初始化条件：config.ros.enabled=true 且 rclpy 已安装。
        任一不满足则纯 HTTP 模式，不报错。
        """
        # ── 启动段 ──────────────────────────────────────────────
        # 1. HttpClient（出站 HTTP 调用封装）
        http_client = HttpClient(config)
        app.state.http_client = http_client

        # 2. ROS 节点（条件性启用）
        app.state.ros_node = None
        app.state.ros_spin_thread = None
        if config.ros.enabled and is_ros_available():
            try:
                app.state.ros_node = init_ros(config.ros.node_name)
                if app.state.ros_node is not None:
                    app.state.ros_spin_thread = spin_in_thread(app.state.ros_node)
                    logger.info("ROS 节点已启动，spin 在后台线程运行: {}",
                                config.ros.node_name)
            except Exception as exc:
                # rclpy 已装但初始化失败（如 DDS 环境问题），记录但不中断启动
                logger.error("ROS 节点初始化失败，降级为纯 HTTP 模式: {}", exc)
                app.state.ros_node = None
                app.state.ros_spin_thread = None
        elif not config.ros.enabled:
            logger.warning("ROS 已在配置中禁用（ros.enabled=false），纯 HTTP 模式")
        else:
            # config.ros.enabled=true 但 rclpy 未装
            logger.warning("rclpy 未安装，跳过 ROS 节点初始化（纯 HTTP 模式）")

        yield

        # ── 关闭段 ──────────────────────────────────────────────
        # 先关 ROS 再关 HTTP：ROS 关闭后 spin 线程自然退出
        if app.state.ros_node is not None:
            shutdown_ros(app.state.ros_node)
            logger.info("ROS 节点已关闭")
        http_client.close()

    return lifespan


def create_app(config: AppConfig) -> FastAPI:
    """创建并装配 FastAPI 应用。

    装配顺序：
        1. 构造 lifespan（含 HttpClient + ROS 生命周期）
        2. 创建 FastAPI 实例
        3. 注册路由
        4. 注册全局异常处理器

    Args:
        config: 全局配置。

    Returns:
        装配完成的 FastAPI 应用。
    """
    lifespan = _build_lifespan(config)

    # 1. 创建 FastAPI 实例
    app = FastAPI(
        title="BSD Unitree Controller",
        description="宇树机器人控制流程系统 - 对外 HTTP 接入层 + 对内 ROS 通信",
        version="0.1.0",
        lifespan=lifespan,
    )

    # 2. 注册路由
    app.include_router(api_router)

    # 3. 注册全局异常处理器
    register_exception_handlers(app)

    return app


# 模块级 app 单例：供 `uvicorn bsd_unitree_controller.api.server:app` 直接启动。
# 注意：使用此单例时日志初始化需由调用方保证（main.py 已处理）。
app = create_app(_global_config)
