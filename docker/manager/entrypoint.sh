#!/bin/bash
# =============================================================================
# ReAct Agent Manager - Entrypoint
# 管理容器的入口脚本，统一处理所有命令
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="/app/workspace"
DOCKER_DIR="$PROJECT_ROOT/docker"

cd "$DOCKER_DIR"

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

print_banner() {
    echo ""
    echo "========================================="
    echo "  ReAct Agent Manager"
    echo "========================================="
}

show_help() {
    print_banner
    echo ""
    log_info "可用命令："
    echo "  init               - 初始化项目（首次运行）"
    echo "  staging            - 启动开发/测试环境"
    echo "  production         - 启动生产环境"
    echo "  stop               - 停止所有服务"
    echo "  restart            - 重启所有服务"
    echo "  status             - 查看服务状态"
    echo "  logs [service]     - 查看日志（可选指定服务）"
    echo "  backup             - 备份数据"
    echo "  clean              - 清理镜像和容器（谨慎使用）"
    echo "  help               - 显示此帮助"
    echo ""
    log_info "示例："
    echo "  docker compose -f docker-compose.manager.yml run --rm manager init"
    echo "  docker compose -f docker-compose.manager.yml run --rm manager staging"
    echo "  docker compose -f docker-compose.manager.yml run --rm manager logs"
}

check_docker_access() {
    if ! docker version > /dev/null 2>&1; then
        log_error "无法访问 Docker！请确保容器正确挂载了 /var/run/docker.sock"
        exit 1
    fi
}

init_project() {
    log_info "正在初始化 ReAct Agent 项目..."
    
    # 检查 .env 文件
    if [ ! -f "$DOCKER_DIR/.env" ]; then
        log_warn ".env 文件不存在，正在创建..."
        if [ -f "$DOCKER_DIR/.env.example" ]; then
            cp "$DOCKER_DIR/.env.example" "$DOCKER_DIR/.env"
            log_success "已从 .env.example 创建 .env 文件"
        else
            log_error "找不到 .env.example 文件！"
            exit 1
        fi
    fi
    
    # 创建必要目录
    mkdir -p "$PROJECT_ROOT/.react"
    log_success "项目初始化完成！"
    echo ""
    log_info "请先编辑 $DOCKER_DIR/.env 文件配置参数，然后运行："
    echo "  docker compose -f docker-compose.manager.yml run --rm manager staging"
}

# 主命令处理
CMD="${1:-help}"

case "$CMD" in
    help)
        show_help
        ;;
    
    init)
        print_banner
        check_docker_access
        init_project
        ;;
    
    staging)
        print_banner
        check_docker_access
        log_info "启动 Staging 环境..."
        docker compose -f docker-compose.prod.yml up -d --remove-orphans
        log_success "Staging 环境已启动！"
        log_info "访问 http://app.localhost"
        ;;
    
    production)
        print_banner
        check_docker_access
        log_warn "正在启动生产环境..."
        docker compose -f docker-compose.prod.yml up -d --remove-orphans
        log_success "生产环境已启动！"
        ;;
    
    stop)
        print_banner
        check_docker_access
        log_info "正在停止所有服务..."
        docker compose -f docker-compose.prod.yml down
        log_success "服务已停止"
        ;;
    
    restart)
        print_banner
        check_docker_access
        log_info "正在重启服务..."
        docker compose -f docker-compose.prod.yml restart
        log_success "服务已重启"
        ;;
    
    status)
        print_banner
        check_docker_access
        log_info "服务状态："
        docker compose -f docker-compose.prod.yml ps
        ;;
    
    logs)
        SERVICE="$2"
        print_banner
        check_docker_access
        if [ -z "$SERVICE" ]; then
            docker compose -f docker-compose.prod.yml logs -f
        else
            docker compose -f docker-compose.prod.yml logs -f "$SERVICE"
        fi
        ;;
    
    backup)
        print_banner
        check_docker_access
        log_info "正在创建备份..."
        docker compose -f docker-compose.prod.yml run --rm volume-backup
        log_success "备份完成"
        ;;
    
    clean)
        print_banner
        check_docker_access
        log_warn "正在清理..."
        docker compose -f docker-compose.prod.yml down -v --rmi local
        log_success "清理完成"
        ;;
    
    *)
        log_error "未知命令: $CMD"
        show_help
        exit 1
        ;;
esac
