#!/bin/bash
# =============================================================================
# ReAct Agent 部署脚本
# 用法：
#   ./docker/deploy.sh staging      # 部署到 Staging
#   ./docker/deploy.sh production   # 部署到 Production
#   ./docker/deploy.sh stop         # 停止所有服务
#   ./docker/deploy.sh backup       # 手动备份数据
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$SCRIPT_DIR"

ENV="${1:-staging}"
COMPOSE_FILE="docker-compose.prod.yml"

echo "========================================="
echo "ReAct Agent 部署"
echo "环境: $ENV"
echo "========================================="

# 检查 .env 文件
if [ ! -f .env ]; then
    echo "⚠️  .env 文件不存在，从 .env.example 复制中..."
    cp .env.example .env
    echo "请编辑 .env 文件配置后重新运行"
    exit 1
fi

load_env() {
    if [ -f .env ]; then
        export $(grep -v '^#' .env | xargs)
    fi
}

load_env

case "$ENV" in
    staging|production)
        echo ""
        echo "📦 拉取最新镜像..."
        docker compose -f "$COMPOSE_FILE" pull
        
        echo ""
        echo "🚀 启动服务..."
        docker compose -f "$COMPOSE_FILE" up -d --remove-orphans
        
        echo ""
        echo "⏳ 等待服务就绪..."
        timeout 120s bash -c '
            until docker compose -f "'"$COMPOSE_FILE"'" ps react | grep -q "healthy"; do
                sleep 5
                echo "等待中..."
            done
        ' || true
        
        echo ""
        echo "✅ 部署完成！"
        echo ""
        echo "📊 监控仪表板："
        echo "  - Grafana:    http://grafana.localhost (或你的域名)"
        echo "  - Prometheus: http://prometheus.localhost"
        echo "  - Traefik:    http://traefik.localhost:8080"
        echo "  - Jaeger:     http://jaeger.localhost"
        echo ""
        echo "🎯 应用访问："
        echo "  - ReAct Agent: http://app.localhost"
        echo ""
        echo "📝 查看日志："
        echo "  docker compose -f \"$COMPOSE_FILE\" logs -f"
        ;;
    
    stop)
        echo ""
        echo "🛑 停止所有服务..."
        docker compose -f "$COMPOSE_FILE" down
        echo "✅ 服务已停止"
        ;;
    
    backup)
        echo ""
        echo "💾 创建备份..."
        docker compose -f "$COMPOSE_FILE" run --rm volume-backup
        echo "✅ 备份完成"
        ;;
    
    restart)
        echo ""
        echo "🔄 重启服务..."
        docker compose -f "$COMPOSE_FILE" restart
        echo "✅ 服务已重启"
        ;;
    
    status)
        echo ""
        echo "📊 服务状态："
        docker compose -f "$COMPOSE_FILE" ps
        ;;
    
    logs)
        echo ""
        echo "📝 查看日志 (Ctrl+C 退出)..."
        docker compose -f "$COMPOSE_FILE" logs -f
        ;;
    
    *)
        echo "用法: $0 {staging|production|stop|backup|restart|status|logs}"
        exit 1
        ;;
esac

exit 0
