#!/bin/bash
# ====================================================================
# bsd-unitree-controller Docker 部署脚本
#
# 用法：
#   ./deploy.sh build     构建镜像
#   ./deploy.sh up        启动容器（开机自启）
#   ./deploy.sh stop      停止容器
#   ./deploy.sh restart   重启容器
#   ./deploy.sh status    查看容器状态
#   ./deploy.sh logs      查看日志（实时跟踪）
#   ./deploy.sh uninstall 停止并删除容器+镜像
#
# 特性：
#   - 基于 isaac_ros_dev-aarch64 镜像（自带 ROS Humble + C 库）
#   - 挂载 unitree_ros2_ws（unitree_api 包）
#   - host 网络（ROS DDS 必须）
#   - --restart unless-stopped 开机自启 + 崩溃重启
#   - 配置和日志外挂，改配置不用重打镜像
# ====================================================================
set -e

# ── 配置 ──────────────────────────────────────────────────────
IMAGE_NAME="bsd-controller"
IMAGE_TAG="0.2.0"
CONTAINER_NAME="bsd-controller"

# 项目目录
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="${PROJECT_DIR}/logs"
mkdir -p "${LOG_DIR}"

# ── 颜色输出 ──────────────────────────────────────────────────
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; }

# ── 启动容器的核心函数 ────────────────────────────────────────
start_container() {
    info "启动容器 ${CONTAINER_NAME}..."

    docker run -d \
        --name "${CONTAINER_NAME}" \
        --network host \
        --restart unless-stopped \
        -v /opt/ros/humble:/opt/ros/humble:ro \
        -v /home/unitree/unitree_ros2_ws:/unitree_ws:ro \
        -v "${PROJECT_DIR}/config/config.yaml:/app/config/config.yaml:ro" \
        -v "${LOG_DIR}:/app/logs" \
        -e ROS_DOMAIN_ID=0 \
        -e RMW_IMPLEMENTATION=rmw_cyclonedds_cpp \
        -e TZ=Asia/Shanghai \
        "${IMAGE_NAME}:${IMAGE_TAG}"

    info "容器已启动，日志挂载到宿主机: ${LOG_DIR}"
    info "查看日志: ./deploy.sh logs"
}

# ── 停止并删除旧容器 ──────────────────────────────────────────
remove_container() {
    if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
        info "停止并删除旧容器..."
        docker stop "${CONTAINER_NAME}" 2>/dev/null || true
        docker rm "${CONTAINER_NAME}" 2>/dev/null || true
    fi
}

# ── 构建镜像 ──────────────────────────────────────────────────
build_image() {
    info "构建镜像 ${IMAGE_NAME}:${IMAGE_TAG}..."
    cd "${PROJECT_DIR}"
    docker build -t "${IMAGE_NAME}:${IMAGE_TAG}" .
    info "镜像构建完成"
}

# ── 命令分发 ──────────────────────────────────────────────────
case "${1:-up}" in

    build)
        build_image
        ;;

    up)
        # 默认：构建 + 启动
        build_image
        remove_container
        start_container
        info "部署完成！验证:"
        echo "  ./deploy.sh status   # 看状态"
        echo "  ./deploy.sh logs     # 看日志"
        echo "  curl http://127.0.0.1:18800/api/v1/test"
        ;;

    stop)
        info "停止容器..."
        docker stop "${CONTAINER_NAME}"
        info "已停止（容器保留，可用 ./deploy.sh start 重启）"
        ;;

    start)
        info "启动已存在的容器..."
        docker start "${CONTAINER_NAME}"
        info "已启动"
        ;;

    restart)
        info "重启容器..."
        docker restart "${CONTAINER_NAME}"
        info "已重启"
        ;;

    status)
        echo "=== 容器状态 ==="
        docker ps -a --filter "name=${CONTAINER_NAME}" \
            --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
        echo ""
        echo "=== 端口监听 ==="
        ss -tlnp | grep 18800 || echo "18800 未监听"
        echo ""
        echo "=== 镜像 ==="
        docker images "${IMAGE_NAME}" --format "table {{.Repository}}:{{.Tag}}\t{{.Size}}"
        ;;

    logs)
        info "查看日志（Ctrl+C 退出）..."
        docker logs -f "${CONTAINER_NAME}"
        ;;

    uninstall)
        remove_container
        info "删除镜像..."
        docker rmi "${IMAGE_NAME}:${IMAGE_TAG}" 2>/dev/null || warn "镜像不存在"
        info "清理完成"
        ;;

    *)
        echo "用法: $0 {build|up|stop|start|restart|status|logs|uninstall}"
        echo ""
        echo "命令说明:"
        echo "  build     构建镜像"
        echo "  up        构建镜像 + 启动容器（默认，首次部署用）"
        echo "  stop      停止容器"
        echo "  start     启动已存在的容器"
        echo "  restart   重启容器"
        echo "  status    查看容器状态 + 端口"
        echo "  logs      查看日志（实时跟踪）"
        echo "  uninstall 停止容器并删除容器+镜像"
        exit 1
        ;;
esac
