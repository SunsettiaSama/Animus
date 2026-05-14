#!/bin/bash
# =============================================================================
# ReAct Agent - 统一启动脚本 (Linux/macOS/WSL)
#
# 用法:
#   ./docker/launch.sh                    # 启动开发环境
#   ./docker/launch.sh staging           # 部署到 Staging
#   ./docker/launch.sh production        # 部署到 Production
#   ./docker/launch.sh stop              # 停止服务
#   ./docker/launch.sh backup            # 备份数据
#   ./docker/launch.sh restart           # 重启服务
#   ./docker/launch.sh status            # 查看状态
#   ./docker/launch.sh logs              # 查看日志
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$SCRIPT_DIR"

ENV="${1:-staging}"

# 根据环境选择 compose 文件
case "$ENV" in
    staging|production)
        COMPOSE_FILE="docker-compose.prod.yml"
        ;;
    stop|backup|restart|status|logs)
        # 这些命令使用生产环境 compose 文件
        COMPOSE_FILE="docker-compose.prod.yml"
        ;;
    *)
        # 开发环境使用基础 compose
        COMPOSE_FILE="docker-compose.yml"
        ;;
esac

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 输出函数
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
    echo "  ReAct Agent"
    echo "  环境: $ENV"
    echo "  Compose: $COMPOSE_FILE"
    echo "========================================="
    echo ""
}

check_docker() {
    if ! command -v docker &> /dev/null; then
        log_error "Docker 未安装或未在 PATH 中！"
        log_info "请先安装 Docker: https://docs.docker.com/get-docker/"
        return 1
    fi

    if ! command -v docker compose &> /dev/null; then
        if ! command -v docker-compose &> /dev/null; then
            log_error "Docker Compose 未安装！"
            return 1
        fi
    fi

    if ! docker version &> /dev/null; then
        log_error "Docker 未运行！请先启动 Docker。"
        return 1
    fi
}

check_env_file() {
    if [ ! -f .env ]; then
        log_warn ".env 文件不存在，从 .env.example 复制中..."
        cp .env.example .env
        log_info "已创建 .env 文件"
        log_warn "请编辑 .env 文件配置后重新运行"
        return 1
    fi
}

load_env() {
    if [ -f .env ]; then
        set -a
        # shellcheck disable=SC1091
        source <(grep -v '^#' .env | sed 's/^/export /')
        set +a
    fi
}

show_access_info() {
    echo ""
    log_success "部署完成！"
    echo ""
    log_info "监控仪表板："
    echo "  - Grafana:    http://grafana.localhost"
    echo "  - Prometheus: http://prometheus.localhost:9090"
    echo "  - Traefik:    http://traefik.localhost:8080"
    echo "  - Jaeger:     http://jaeger.localhost"
    echo ""
    log_info "应用访问："
    echo "  - ReAct Agent: http://app.localhost"
    echo ""
    log_info "常用命令："
    echo "  - 查看日志:   $0 logs"
    echo "  - 查看状态:   $0 status"
    echo "  - 停止服务:   $0 stop"
    echo "  - 重启服务:   $0 restart"
}

# 主流程
print_banner
check_docker || exit 1

case "$ENV" in
    staging|production)
        check_env_file || exit 1
        load_env

        log_info "拉取最新镜像..."
        docker compose -f "$COMPOSE_FILE" pull

        log_info "启动服务..."
        docker compose -f "$COMPOSE_FILE" up -d --remove-orphans

        log_info "等待服务就绪..."
        if timeout 120s bash -c '
            until docker compose -f "'"$COMPOSE_FILE"'" ps react | grep -q "healthy"; do
                sleep 5
                echo "  等待中..."
            done
        '; then
            log_success "服务就绪！"
        else
            log_warn "等待超时，可能需要较长时间启动"
        fi

        show_access_info
        ;;
    
    stop)
        log_info "停止所有服务..."
        docker compose -f "$COMPOSE_FILE" down
        log_success "服务已停止"
        ;;
    
    backup)
        log_info "创建备份..."
        docker compose -f "$COMPOSE_FILE" run --rm volume-backup
        log_success "备份完成"
        ;;
    
    restart)
        log_info "重启服务..."
        docker compose -f "$COMPOSE_FILE" restart
        log_success "服务已重启"
        ;;
    
    status)
        log_info "服务状态："
        docker compose -f "$COMPOSE_FILE" ps
        ;;
    
    logs)
        log_info "查看日志 (Ctrl+C 退出)..."
        docker compose -f "$COMPOSE_FILE" logs -f
        ;;
    
    *)
        echo "用法: $0 {staging|production|stop|backup|restart|status|logs}"
        exit 1
        ;;
esac

exit 0
