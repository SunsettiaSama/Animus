#!/bin/bash
# =============================================================================
# ReAct Agent 健康检查脚本
# 用于 CI/CD 和监控系统
# =============================================================================

set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

echo "========================================="
echo "ReAct Agent 健康检查"
echo "========================================="

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

check_service() {
    local service=$1
    local url=$2
    local max_attempts=30
    local attempt=0
    
    echo ""
    echo "检查: $service"
    
    while [ $attempt -lt $max_attempts ]; do
        if curl -s -o /dev/null -w "%{http_code}" "$url" | grep -q "200\|301\|302"; then
            echo -e "${GREEN}✅ $service 健康${NC}"
            return 0
        fi
        attempt=$((attempt + 1))
        echo "  等待... ($attempt/$max_attempts)"
        sleep 2
    done
    
    echo -e "${RED}❌ $service 无法访问${NC}"
    return 1
}

# 检查 Docker 服务
if [ -f "docker/docker-compose.yml" ]; then
    cd docker
    
    echo ""
    echo "检查 Docker 容器..."
    
    containers=("mysql" "redis" "searxng" "react")
    
    for container in "${containers[@]}"; do
        if docker compose ps "$container" | grep -q "Up"; then
            echo -e "${GREEN}✅ $container 运行中${NC}"
        else
            echo -e "${YELLOW}⚠️ $container 未运行${NC}"
        fi
    done
fi

# 检查 HTTP 服务
check_service "ReAct Agent" "http://localhost:8080"

echo ""
echo "========================================="
echo "检查完成"
echo "========================================="
