#!/bin/bash
# =============================================================================
# ReAct Agent 开发环境一键设置
# =============================================================================

set -e

echo "========================================="
echo "ReAct Agent 开发环境设置"
echo "========================================="

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

# 检查 Docker
if ! command -v docker &> /dev/null; then
    echo "❌ Docker 未安装，请先安装 Docker"
    exit 1
fi

if ! command -v docker compose &> /dev/null && ! command -v docker-compose &> /dev/null; then
    echo "❌ Docker Compose 未安装"
    exit 1
fi

echo ""
echo "✅ Docker 环境检查通过"

# 创建必要的目录
echo ""
echo "📁 创建必要目录..."
mkdir -p .react
mkdir -p config/llm_core
mkdir -p docker/backups

# 复制示例配置
if [ ! -f docker/.env ]; then
    echo ""
    echo "📝 复制配置文件..."
    cp docker/.env.example docker/.env
fi

echo ""
echo "🚀 启动开发环境..."
cd docker
docker compose -f docker-compose.yml up -d --build

echo ""
echo "⏳ 等待服务就绪..."
sleep 10

echo ""
echo "========================================="
echo "✅ 开发环境已就绪！"
echo "========================================="
echo ""
echo "📊 访问地址："
echo "  - ReAct Agent: http://localhost:8080"
echo ""
echo "📝 常用命令："
echo "  cd docker"
echo "  docker compose logs -f    # 查看日志"
echo "  docker compose ps          # 查看状态"
echo "  docker compose down        # 停止环境"
echo ""
echo "🚀 如需监控："
echo "  cd docker"
echo "  docker compose -f docker-compose.prod.yml up -d"
echo ""
