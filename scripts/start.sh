#!/bin/bash
# ====================================================================
# bsd-unitree-controller 启动脚本
#
# 用法：./scripts/start.sh
# source ROS 环境 + 启动 FastAPI 服务。
# systemd 会调用这个脚本，也可以手动执行。
# ====================================================================
set -e

# 项目目录（脚本上级目录的上级）
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# source ROS 环境
source "${PROJECT_DIR}/scripts/ros_env.sh"

# 进项目目录启动
cd "${PROJECT_DIR}"
exec python3 main.py
