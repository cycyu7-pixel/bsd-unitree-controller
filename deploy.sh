#!/bin/bash
# ====================================================================
# bsd-unitree-controller 部署脚本（进程直跑 + systemd 开机自启）
#
# 用法：
#   ./deploy.sh install    安装：装依赖 + 注册 systemd 服务 + 启动
#   ./deploy.sh start      启动服务
#   ./deploy.sh stop       停止服务
#   ./deploy.sh restart    重启服务
#   ./deploy.sh status     查看服务状态
#   ./deploy.sh logs       查看日志（实时跟踪）
#   ./deploy.sh uninstall  卸载：停止 + 移除 systemd 服务
#
# 特性：
#   - 用 pip3 --user 安装，不污染系统环境
#   - systemd 管理，开机自启 + 崩溃自动重启
#   - 日志走 systemd journal，用 journalctl 查看
#   - 日志文件同时输出到 logs/ 目录
# ====================================================================
set -e

# ── 配置 ──────────────────────────────────────────────────────
SERVICE_NAME="bsd-controller"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_FILE="${PROJECT_DIR}/scripts/bsd-controller.service"
SYSTEMD_FILE="/etc/systemd/system/${SERVICE_NAME}.service"

# ── 颜色输出 ──────────────────────────────────────────────────
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
NC='\033[0m'

info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; }

# ── 安装：装依赖 + 注册 systemd ───────────────────────────────
install_service() {
    info "1/4 安装 Python 依赖（--user，不污染系统）..."
    cd "${PROJECT_DIR}"
    pip3 install --user -e . 2>/dev/null || pip3 install --user .
    info "依赖安装完成"

    info "2/4 修脚本换行符（Windows CRLF -> Linux LF）..."
    sed -i 's/\r$//' "${PROJECT_DIR}/scripts/ros_env.sh"
    sed -i 's/\r$//' "${PROJECT_DIR}/scripts/start.sh"
    chmod +x "${PROJECT_DIR}/scripts/ros_env.sh"
    chmod +x "${PROJECT_DIR}/scripts/start.sh"
    info "脚本权限设置完成"

    info "3/4 注册 systemd 服务..."
    sudo cp "${SERVICE_FILE}" "${SYSTEMD_FILE}"
    sudo sed -i "s|/home/unitree/bsd-unitree-controller|${PROJECT_DIR}|g" "${SYSTEMD_FILE}"
    sudo systemctl daemon-reload
    sudo systemctl enable "${SERVICE_NAME}"
    info "systemd 服务已注册并设为开机自启"

    info "4/4 启动服务..."
    sudo systemctl start "${SERVICE_NAME}"
    sleep 2
    info "部署完成！验证:"
    echo "  ./deploy.sh status   # 看状态"
    echo "  ./deploy.sh logs     # 看日志"
    echo "  curl http://127.0.0.1:18800/api/v1/test"
}

# ── 命令分发 ──────────────────────────────────────────────────
case "${1:-install}" in

    install)
        install_service
        ;;

    start)
        info "启动服务..."
        sudo systemctl start "${SERVICE_NAME}"
        info "已启动"
        ;;

    stop)
        info "停止服务..."
        sudo systemctl stop "${SERVICE_NAME}"
        info "已停止"
        ;;

    restart)
        info "重启服务..."
        sudo systemctl restart "${SERVICE_NAME}"
        info "已重启"
        ;;

    status)
        echo "=== 服务状态 ==="
        sudo systemctl status "${SERVICE_NAME}" --no-pager -l | head -20
        echo ""
        echo "=== 端口监听 ==="
        ss -tlnp | grep 18800 || echo "18800 未监听"
        ;;

    logs)
        info "查看日志（Ctrl+C 退出）..."
        echo "日志文件: ${PROJECT_DIR}/logs/app_\$(date +%Y-%m-%d).log"
        echo "---"
        journalctl -u "${SERVICE_NAME}" -f --no-pager
        ;;

    uninstall)
        info "卸载服务..."
        sudo systemctl stop "${SERVICE_NAME}" 2>/dev/null || true
        sudo systemctl disable "${SERVICE_NAME}" 2>/dev/null || true
        sudo rm -f "${SYSTEMD_FILE}"
        sudo systemctl daemon-reload
        info "已卸载 systemd 服务"
        warn "Python 依赖未卸载，如需彻底清理：pip3 uninstall bsd-unitree-controller fastapi uvicorn httpx tenacity loguru pydantic pyyaml"
        ;;

    *)
        echo "用法: $0 {install|start|stop|restart|status|logs|uninstall}"
        echo ""
        echo "命令说明:"
        echo "  install    安装依赖 + 注册 systemd 服务 + 启动（首次部署用）"
        echo "  start      启动服务"
        echo "  stop       停止服务"
        echo "  restart    重启服务"
        echo "  status     查看服务状态"
        echo "  logs       查看日志（实时跟踪）"
        echo "  uninstall  卸载 systemd 服务"
        exit 1
        ;;
esac
