#!/usr/bin/env bash
# =============================================================================
# docker/deploy-vllm.sh
#
# WSL2 / Linux 一键部署 vLLM Docker 服务
#
# 用法（在 WSL 终端中运行）：
#   chmod +x docker/deploy-vllm.sh
#   ./docker/deploy-vllm.sh [命令] [选项]
#
# 命令：
#   up      构建并启动（默认）
#   down    停止并移除容器
#   build   仅构建镜像（不启动）
#   logs    跟踪容器日志
#   status  查看服务状态
#   shell   进入容器 bash
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
COMPOSE_FILE="${SCRIPT_DIR}/vllm/docker-compose.yml"
ENV_FILE="${SCRIPT_DIR}/vllm/.env"
ENV_EXAMPLE="${SCRIPT_DIR}/vllm/.env.example"

# ── 颜色输出 ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERR]${NC}   $*" >&2; exit 1; }

# ── 前置检查 ──────────────────────────────────────────────────────────────────
check_deps() {
    command -v docker  &>/dev/null || error "未找到 docker，请先安装 Docker Desktop 并启用 WSL2 集成"
    command -v docker compose &>/dev/null 2>&1 \
        || command -v docker-compose &>/dev/null \
        || error "未找到 docker compose，请升级 Docker Desktop 至 v2.x"
}

check_nvidia() {
    if ! docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 \
            nvidia-smi &>/dev/null 2>&1; then
        warn "未检测到 NVIDIA GPU 直通。"
        warn "请确认："
        warn "  1. 已安装 nvidia-container-toolkit"
        warn "  2. WSL2 内核已更新：  sudo apt update && sudo apt install -y linux-tools-generic"
        warn "  3. 在 WSL2 中运行:    nvidia-smi"
        echo ""
        read -r -p "是否忽略 GPU 检查继续部署？(y/N) " ans
        [[ "${ans,,}" == "y" ]] || exit 1
    else
        info "NVIDIA GPU 直通正常"
        docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi
    fi
}

ensure_env() {
    if [[ ! -f "${ENV_FILE}" ]]; then
        warn ".env 文件不存在，从 .env.example 复制..."
        cp "${ENV_EXAMPLE}" "${ENV_FILE}"
        warn "已创建 ${ENV_FILE}，请编辑后重新运行："
        warn "  nano ${ENV_FILE}"
        echo ""
        # 如果 VLLM_MODEL 未设置则提示
        if grep -q "^VLLM_MODEL=$" "${ENV_FILE}"; then
            error "VLLM_MODEL 未配置，请编辑 .env 文件"
        fi
    fi
    # 确保 VLLM_MODEL 不为空
    # shellcheck source=/dev/null
    source "${ENV_FILE}"
    [[ -n "${VLLM_MODEL:-}" ]] || error "VLLM_MODEL 未设置，请编辑 ${ENV_FILE}"
    info "模型: ${VLLM_MODEL}"
}

# ── 命令函数 ──────────────────────────────────────────────────────────────────
cmd_up() {
    check_deps
    check_nvidia
    ensure_env

    info "构建 vLLM 镜像（首次构建约需 5–15 分钟，依网速而定）..."
    docker compose \
        -f "${COMPOSE_FILE}" \
        --env-file "${ENV_FILE}" \
        --project-directory "${PROJECT_ROOT}" \
        up --build -d

    info "服务已启动，等待健康检查（约 60–120 秒）..."
    echo ""
    echo "  API 端点（Windows/WSL 访问）:"
    echo "    http://localhost:${VLLM_HOST_PORT:-8000}/v1"
    echo ""
    echo "  查看日志:"
    echo "    ./docker/deploy-vllm.sh logs"
    echo ""
    echo "  测试接口:"
    echo "    curl http://localhost:${VLLM_HOST_PORT:-8000}/v1/models"
}

cmd_down() {
    check_deps
    info "停止 vLLM 服务..."
    docker compose \
        -f "${COMPOSE_FILE}" \
        --project-directory "${PROJECT_ROOT}" \
        down
    info "已停止"
}

cmd_build() {
    check_deps
    ensure_env
    info "构建 vLLM 镜像..."
    docker compose \
        -f "${COMPOSE_FILE}" \
        --env-file "${ENV_FILE}" \
        --project-directory "${PROJECT_ROOT}" \
        build
    info "镜像构建完成"
}

cmd_logs() {
    check_deps
    docker compose \
        -f "${COMPOSE_FILE}" \
        --project-directory "${PROJECT_ROOT}" \
        logs -f vllm
}

cmd_status() {
    check_deps
    echo ""
    docker compose \
        -f "${COMPOSE_FILE}" \
        --project-directory "${PROJECT_ROOT}" \
        ps
    echo ""
    # 尝试查询 /v1/models
    PORT="${VLLM_HOST_PORT:-8000}"
    if curl -sf "http://localhost:${PORT}/v1/models" >/dev/null 2>&1; then
        info "API 可用: http://localhost:${PORT}/v1"
        curl -s "http://localhost:${PORT}/v1/models" | python3 -m json.tool 2>/dev/null || true
    else
        warn "API 暂不可用（服务可能仍在启动中）"
    fi
}

cmd_shell() {
    check_deps
    info "进入 vLLM 容器..."
    docker exec -it react-vllm bash || \
    docker run --rm -it \
        --gpus all \
        react-vllm:latest \
        bash
}

# ── 入口 ──────────────────────────────────────────────────────────────────────
CMD="${1:-up}"
case "${CMD}" in
    up)     cmd_up    ;;
    down)   cmd_down  ;;
    build)  cmd_build ;;
    logs)   cmd_logs  ;;
    status) cmd_status;;
    shell)  cmd_shell ;;
    *)
        echo "用法: $0 [up|down|build|logs|status|shell]"
        exit 1
        ;;
esac
