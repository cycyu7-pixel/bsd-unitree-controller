# ====================================================================
# bsd-unitree-controller Dockerfile
#
# 基础镜像：ROS 2 Humble + Ubuntu 22.04（自带 rclpy + Python 3.10）
# 不能用 python:3.11，因为 rclpy 依赖 ROS 的 C 库（rcl/rmw/DDS），
# 必须用带 ROS 运行时的镜像，pip 装不了系统级 rclpy。
# ====================================================================
FROM osrf/ros:humble-ros-base

# ROS 环境变量：让 rclpy 能找到底层 C 库
ENV ROS_DISTRO=humble
# 每个 shell 启动自动 source ROS 环境
RUN echo "source /opt/ros/humble/setup.bash" >> /etc/bash.bashrc

# 装构建依赖：pip + 包管理工具
# 清理 apt 缓存减小镜像体积
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3-pip \
    && rm -rf /var/lib/apt/lists/*

# 升级 pip，避免老版本对 pydantic v2 的打包问题
RUN pip3 install --no-cache-dir --upgrade pip

# 工作目录
WORKDIR /app

# 先拷依赖声明，利用 Docker 缓存层
# 改代码时不会重装 Python 依赖，构建快
COPY pyproject.toml uv.lock ./

# 装 Python 依赖（用系统 Python 3.10，不建虚拟环境，简化部署）
# rclpy 来自基础镜像的 apt，不通过 pip 装
# --no-deps 避免 pip 试图解析 rclpy（PyPI 上不可用）
RUN pip3 install --no-cache-dir .

# 拷源码
COPY . .

# 时区设为上海，日志时间正确
ENV TZ=Asia/Shanghai
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# 暴露 FastAPI 端口（仅文档作用，host 网络模式下不生效）
EXPOSE 18800

# 启动命令：source ROS 环境后启动服务
# 必须在运行时 source，因为 CMD 不走 /etc/bash.bashrc
CMD ["bash", "-c", "source /opt/ros/humble/setup.bash && python3 main.py"]
