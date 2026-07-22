#!/bin/bash
# ====================================================================
# bsd-unitree-controller 一键部署脚本
#
# 用法：
#   ./deploy.sh          构建镜像并启动容器
#   ./deploy.sh logs     查看日志（实时跟踪）
#   ./deploy.sh stop     停止容器
#   ./deploy.sh restart  重启容器（不重新构建）
#   ./deploy.sh status   查看容器状态
#   ./deploy.sh rebuild  强制重新构建镜像并启动
#
# 特性：
#   - 日志挂载到宿主机 ~/bsd-unitree-controller/logs，可直接查看
#   - --restart unless-stopped 保证开机自启（机器人重启后自动恢复）
#   - 挂载机器人 ROS 环境（rclpy + unitree_api），不在镜像里装 ROS
#   - host 网络，ROS DDS 自动发现其他节点
# ====================================================================
set -e

# ── 配置 ──────────────────────────────────────────────────────
IMAGE_NAME="bsd-controller"
IMAGE_TAG="0.1.0"
CONTAINER_NAME="bsd-controller"

# 项目目录（脚本所在目录）
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 宿主机日志目录
LOG_DIR="${PROJECT_DIR}/logs"
mkdir -p "${LOG_DIR}"

# ── 颜色输出 ──────────────────────────────────────────────────
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; }

# ── 启动容器的核心函数 ────────────────────────────────────────
start_container() {
    info "启动容器 ${CONTAINER_NAME}..."

    # 清掉代理，避免容器内 pip 访问网络时 SOCKS 报错
    unset HTTP_PROXY HTTPS_PROXY ALL_PROXY

    docker run -d \
        --name "${CONTAINER_NAME}" \
        --network host \
        --restart unless-stopped \
        -v /opt/ros/humble:/opt/ros/humble:ro \
        -v /home/unitree/unitree_ros2_ws:/unitree_ws:ro \
        -v /usr/lib/aarch64-linux-gnu:/usr/lib/aarch64-linux-gnu:ro \
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
        info "停止并删除旧容器 ${CONTAINER_NAME}..."
        docker stop "${CONTAINER_NAME}" 2>/dev/null || true
        docker rm "${CONTAINER_NAME}" 2>/dev/null || true
    fi
}

# ── 构建镜像 ──────────────────────────────────────────────────
build_image() {
    info "构建镜像 ${IMAGE_NAME}:${IMAGE_TAG}..."
    cd "${PROJECT_DIR}"
    unset HTTP_PROXY HTTPS_PROXY ALL_PROXY
    docker build -t "${IMAGE_NAME}:${IMAGE_TAG}" .
    info "镜像构建完成"
}

# ── 命令分发 ──────────────────────────────────────────────────
case "${1:-up}" in

    up|deploy)
        # 默认操作：构建 + 启动
        build_image
        remove_container
        start_container
        info "部署完成！验证:"
        echo "  ./deploy.sh logs      # 看日志"
        echo "  ./deploy.sh status    # 看状态"
        echo "  curl http://127.0.0.1:18800/api/v1/test"
        ;;

    rebuild)
        # 强制重新构建（无缓存）+ 启动
        info "强制重新构建（无缓存）..."
        cd "${PROJECT_DIR}"
        unset HTTP_PROXY HTTPS_PROXY ALL_PROXY
        docker build --no-cache -t "${IMAGE_NAME}:${IMAGE_TAG}" .
        remove_container
        start_container
        ;;

    logs)
        info "查看日志（Ctrl+C 退出）..."
        echo "日志文件位置: ${LOG_DIR}/app_\$(date +%Y-%m-%d).log"
        echo "---"
        docker logs -f "${CONTAINER_NAME}"
        ;;

    stop)
        info "停止容器 ${CONTAINER_NAME}..."
        docker stop "${CONTAINER_NAME}"
        info "已停止（容器仍保留，可用 ./deploy.sh start 重新启动）"
        ;;

    start)
        info "启动已存在的容器..."
        docker start "${CONTAINER_NAME}"
        info "已启动，查看日志: ./deploy.sh logs"
        ;;

    restart)
        info "重启容器..."
        docker restart "${CONTAINER_NAME}"
        info "已重启，查看日志: ./deploy.sh logs"
        ;;

    status)
        echo "=== 容器状态 ==="
        docker ps -a --filter "name=${CONTAINER_NAME}" \
            --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
        echo ""
        echo "=== 镜像 ==="
        docker images "${IMAGE_NAME}" --format "table {{.Repository}}:{{.Tag}}\t{{.Size}}\t{{.CreatedAt}}"
        echo ""
        echo "=== 日志目录 ==="
        ls -lh "${LOG_DIR}" 2>/dev/null | tail -5
        ;;

    clean)
        # 停止 + 删除容器 + 删除镜像
        remove_container
        info "删除镜像..."
        docker rmi "${IMAGE_NAME}:${IMAGE_TAG}" 2>/dev/null || warn "镜像不存在"
        info "清理完成"
        ;;

    *)
        echo "用法: $0 {up|rebuild|logs|stop|start|restart|status|clean}"
        echo ""
        echo "命令说明:"
        echo "  up        构建镜像并启动容器（默认）"
        echo "  rebuild   强制重新构建（无缓存）并启动"
        echo "  logs      查看日志（实时跟踪）"
        echo "  stop      停止容器"
        echo "  start     启动已存在的容器"
        echo "  restart   重启容器"
        echo "  status    查看容器和镜像状态"
        echo "  clean     停止容器并删除容器+镜像"
        exit 1
        ;;
esac
