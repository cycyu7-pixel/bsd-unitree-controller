# ====================================================================
# bsd-unitree-controller Dockerfile
#
# 部署到宇树 G1 机器人（unitree-g1-nx）使用。
#
# 关键设计：不把 ROS 装进镜像，而是运行时挂载机器人的 ROS 环境。
#   原因：rclpy / unitree_api / Cyclone DDS 都在机器人系统里，
#   装进镜像体积大且版本难对齐。挂载方式最稳。
#
# 镜像只装 Python 依赖（fastapi/httpx/tenacity 等），
# ROS 相关包（rclpy/unitree_api/std_srvs）通过 docker-compose 挂载进来。
# ====================================================================
FROM python:3.10-slim

# 装系统依赖（运行 Python 包 + DDS 通信需要）
RUN apt-get update && apt-get install -y --no-install-recommends \
        libssl3 \
        libcurl4 \
        curl \
    && rm -rf /var/lib/apt/lists/*

# 工作目录
WORKDIR /app

# 先拷依赖声明，利用 Docker 缓存层
COPY pyproject.toml ./

# 装 Python 依赖（用 --no-deps 避免解析 rclpy，PyPI 上不可用）
# rclpy / std_srvs / geometry_msgs / unitree_api 都来自挂载的 ROS 环境，不通过 pip 装
RUN pip install --no-cache-dir --no-deps -e . 2>/dev/null || \
    pip install --no-cache-dir -e . --no-build-isolation

# 拷源码
COPY . .

# 时区
ENV TZ=Asia/Shanghai
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# 暴露 FastAPI 端口
EXPOSE 18800

# 启动命令：source 挂载进来的 ROS 环境 + DDS 配置后启动
# 必须在运行时 source，因为 ROS 环境通过 volume 挂载，构建时不存在
CMD ["bash", "-c", "source /opt/ros/humble/setup.bash && source /unitree_ws/install/setup.bash && export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp && python3 main.py"]
