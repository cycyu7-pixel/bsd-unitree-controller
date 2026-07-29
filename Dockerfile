# ====================================================================
# bsd-unitree-controller Dockerfile
#
# 部署到宇树 G1 机器人（unitree-g1-nx，Jetson + ROS Humble）。
#
# 关键设计：用机器人上已有的 isaac_ros_dev-aarch64 镜像做基础，
# 它自带完整的 ROS Humble + 所有 C 库依赖（rclpy 的 .so 等），
# 解决了之前 python:3.10-slim 缺 C 库导致 rclpy import 失败的问题。
#
# 镜像里没有 unitree_api（Unitree 自己编译的包），通过 docker run
# 挂载机器人的 unitree_ros2_ws 工作空间进来。
# ====================================================================
FROM isaac_ros_dev-aarch64

# 装 Python Web 依赖（rclpy/std_srvs 等来自基础镜像的 ROS，不通过 pip 装）
# 用 --no-cache-dir 减小镜像体积
RUN pip3 install --no-cache-dir \
    fastapi \
    "uvicorn[standard]" \
    httpx \
    tenacity \
    pydantic \
    pyyaml \
    loguru

# 工作目录
WORKDIR /app

# 先拷依赖声明，利用 Docker 缓存层（改代码不重装依赖）
COPY pyproject.toml ./

# 装项目本身（非 editable，ubuntu:22.04 的 pip 不支持 PEP 660）
RUN pip3 install --no-cache-dir .

# 拷源码
COPY . .

# 设 PYTHONPATH 让 Python 找到项目源码（src 布局）
ENV PYTHONPATH="/app/src:${PYTHONPATH}"

# 时区
ENV TZ=Asia/Shanghai
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# 暴露 FastAPI 端口（host 网络模式下仅文档作用）
EXPOSE 18800

# 启动命令：
# 1. source ROS Humble（让 rclpy/std_srvs 可用）
# 2. source 挂载进来的 unitree 工作空间（让 unitree_api 可用）
# 3. 设 DDS 中间件为 Cyclone DDS（跟机器人其他节点一致）
# 4. 启动服务
CMD ["bash", "-c", \
    "source /opt/ros/humble/setup.bash && \
     source /unitree_ws/install/setup.bash && \
     export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp && \
     export ROS_DOMAIN_ID=0 && \
     python3 main.py"]
