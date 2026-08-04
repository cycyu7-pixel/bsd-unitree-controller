#!/bin/bash
# ====================================================================
# ROS 环境变量配置
#
# 用法：source scripts/ros_env.sh
# 配置 ROS Humble + Unitree 工作空间 + Cyclone DDS，让 rclpy 可用。
# 启动脚本和验证命令都要先 source 这个文件。
#
# 注意：WiFi 策略路由（双网卡回包问题）已在系统层面永久配置，
#       不在此脚本中处理。如需重新配置，参考桌面《机器人网络与部署配置说明.md》。
# ====================================================================

# ROS Humble 基础环境（rclpy / std_srvs / geometry_msgs）
source /opt/ros/humble/setup.bash

# Unitree 工作空间（unitree_api / unitree_hg / unitree_go）
source /home/unitree/unitree_ros2_ws/install/setup.bash

# DDS 中间件，必须跟机器人其他节点一致（G1 用 Cyclone DDS）
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp

# ROS 域 ID，默认 0，跟其他节点一致才能通信
export ROS_DOMAIN_ID=0
