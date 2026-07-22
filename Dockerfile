# ====================================================================
# bsd-unitree-controller Dockerfile
#
# 部署到宇树 G1 机器人（unitree-g1-nx，Ubuntu 22.04 + ROS Humble）。
#
# 关键设计：用 ubuntu:22.04 基础镜像（跟机器人系统一致），
# 运行时挂载机器人的 ROS 环境（rclpy + unitree_api + C 库依赖）。
# 不把 ROS 装进镜像，因为 rclpy 是 C 扩展，依赖大量系统级 .so 文件，
# 挂载方式最稳，避免 .so 版本不匹配。
#
# 镜像只装 Python 包（fastapi/httpx/tenacity 等），
# ROS 相关包通过 docker-compose 挂载进来。
# ====================================================================
FROM ubuntu:22.04

# 避免交互式安装卡住
ENV DEBIAN_FRONTEND=noninteractive

# 装系统依赖：Python 3 + 运行时 C 库 + curl
# libspdlog-dev 等 ROS 依赖通过挂载宿主机获得，不在这里装
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 \
        python3-pip \
        python3-yaml \
        curl \
        ca-certificates \
        locales \
    && rm -rf /var/lib/apt/lists/*

# 设中文 locale（避免日志中文乱码）
RUN locale-gen zh_CN.UTF-8
ENV LANG=zh_CN.UTF-8
ENV LC_ALL=zh_CN.UTF-8

# 工作目录
WORKDIR /app

# 先拷依赖声明，利用 Docker 缓存层
COPY pyproject.toml ./

# 装 Python 依赖（用 --no-deps 避免解析 rclpy，PyPI 上不可用）
# rclpy / std_srvs / geometry_msgs / unitree_api 都来自挂载的 ROS 环境
RUN pip3 install --no-cache-dir --no-deps -e .

# 拷源码
COPY . .

# 时区
ENV TZ=Asia/Shanghai
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# 暴露 FastAPI 端口
EXPOSE 18800

# 启动命令：source 挂载进来的 ROS 环境后启动
# PYTHONPATH 让容器 Python 找到挂载的 ROS Python 包
# LD_LIBRARY_PATH 让容器找到挂载的 ROS C 库（.so 文件）
CMD ["bash", "-c", \
    "source /opt/ros/humble/setup.bash && \
     source /unitree_ws/install/setup.bash && \
     export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp && \
     export PYTHONPATH=/opt/ros/humble/lib/python3.10/site-packages:/opt/ros/humble/local/lib/python3.10/dist-packages:${PYTHONPATH} && \
     export LD_LIBRARY_PATH=/opt/ros/humble/lib:/usr/lib/aarch64-linux-gnu:${LD_LIBRARY_PATH} && \
     python3 main.py"]
