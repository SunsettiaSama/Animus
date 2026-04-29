#!/usr/bin/env bash
# =============================================================================
# docker/build.sh — ReAct Agent 镜像打包脚本（Linux / macOS）
#
# 用法（交互模式）：
#   bash docker/build.sh
#
# 用法（命令行参数，适合 CI/CD）：
#   bash docker/build.sh [--mode api|full] [--device cpu|gpu] [--tag NAME] [--push]
#
# --mode api    使用 requirements-light.txt（API 推理，默认）
# --mode full   使用 requirements.txt（含本地 HuggingFace LLM 推理）
# --device cpu  强制安装 CPU 版 torch
# --device gpu  使用默认 PyPI torch（含 CUDA 支持，默认）
# --tag NAME    自定义镜像名（默认 react-agent:<mode>-<device>）
# --push        构建完成后推送到 registry
# =============================================================================

set -euo pipefail

# ── 颜色 ──────────────────────────────────────────────────────────────────────
RED='\033[31m'; GREEN='\033[32m'; YELLOW='\033[33m'
CYAN='\033[36m'; BOLD='\033[1m'; RESET='\033[0m'

ok()   { echo -e "  ${GREEN}[OK]${RESET}  $*"; }
warn() { echo -e "  ${YELLOW}[!]${RESET}   $*"; }
fail() { echo -e "  ${RED}[!!]${RESET}  $*"; }
info() { echo -e "  ${CYAN}[  ]${RESET}  $*"; }
section() { echo -e "\n${BOLD}${CYAN}── $* ${RESET}"; }

# ── 定位项目根目录 ────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo
echo -e "${BOLD}  ╔══════════════════════════════════════╗${RESET}"
echo -e "${BOLD}  ║     ReAct Agent  Docker Builder      ║${RESET}"
echo -e "${BOLD}  ╚══════════════════════════════════════╝${RESET}"
echo

# ── 解析参数 ─────────────────────────────────────────────────────────────────
ARG_MODE=""
ARG_DEVICE=""
ARG_TAG=""
ARG_PUSH=0
INTERACTIVE=1

while [[ $# -gt 0 ]]; do
    case "$1" in
        --mode)   ARG_MODE="$2";   INTERACTIVE=0; shift 2 ;;
        --device) ARG_DEVICE="$2"; INTERACTIVE=0; shift 2 ;;
        --tag)    ARG_TAG="$2";    INTERACTIVE=0; shift 2 ;;
        --push)   ARG_PUSH=1;      INTERACTIVE=0; shift   ;;
        *) shift ;;
    esac
done

# ── 1. 检查 Docker ────────────────────────────────────────────────────────────
section "检查 Docker 环境"
if ! command -v docker &>/dev/null; then
    fail "未检测到 Docker，请先安装 Docker。"
    fail "  Linux: https://docs.docker.com/engine/install/"
    fail "  macOS: https://www.docker.com/products/docker-desktop/"
    exit 1
fi
if ! docker info &>/dev/null; then
    fail "Docker daemon 未运行，请先启动 Docker 服务。"
    exit 1
fi
ok "$(docker --version)"

# ── 2. 选择构建模式 ───────────────────────────────────────────────────────────
if [[ -n "$ARG_MODE" ]]; then
    BUILD_MODE="$ARG_MODE"
else
    echo
    echo "  构建模式："
    echo "    [1] API 模式    — 轻量依赖，LLM 使用 OpenAI / 其他 API（推荐）"
    echo "    [2] Full 模式   — 含本地 HuggingFace LLM 推理（镜像更大）"
    echo
    read -rp "  请选择 [1/2，默认 1]: " MODE_CHOICE
    [[ "$MODE_CHOICE" == "2" ]] && BUILD_MODE="full" || BUILD_MODE="api"
fi

# ── 3. 选择 torch 设备 ───────────────────────────────────────────────────────
if [[ -n "$ARG_DEVICE" ]]; then
    BUILD_DEVICE="$ARG_DEVICE"
else
    echo
    echo "  torch 版本："
    echo "    [1] GPU（CUDA）— 需要 NVIDIA 显卡与 CUDA 驱动（默认）"
    echo "    [2] CPU Only   — 无 GPU 或部署到无显卡服务器时选此项"
    echo
    read -rp "  请选择 [1/2，默认 1]: " DEV_CHOICE
    [[ "$DEV_CHOICE" == "2" ]] && BUILD_DEVICE="cpu" || BUILD_DEVICE="gpu"
fi

# ── 4. 确定镜像标签 ───────────────────────────────────────────────────────────
DEFAULT_TAG="react-agent:${BUILD_MODE}-${BUILD_DEVICE}"
if [[ -n "$ARG_TAG" ]]; then
    IMAGE_TAG="$ARG_TAG"
else
    echo
    read -rp "  镜像标签 [默认 ${DEFAULT_TAG}]: " TAG_INPUT
    IMAGE_TAG="${TAG_INPUT:-$DEFAULT_TAG}"
fi

# ── 5. 组装构建参数 ───────────────────────────────────────────────────────────
[[ "$BUILD_MODE" == "full" ]] && REQ_FILE="requirements.txt" || REQ_FILE="requirements-light.txt"

TORCH_EXTRA=""
[[ "$BUILD_DEVICE" == "cpu" ]] && TORCH_EXTRA="--index-url https://download.pytorch.org/whl/cpu"

# ── 6. 确认并构建 ─────────────────────────────────────────────────────────────
echo
echo "  ──────────────────────────────────────────────────────"
echo "   构建配置："
echo "     模式        : $BUILD_MODE"
echo "     torch       : $BUILD_DEVICE"
echo "     依赖文件    : $REQ_FILE"
echo "     镜像标签    : $IMAGE_TAG"
[[ "$ARG_PUSH" -eq 1 ]] && echo "     构建后推送  : 是"
echo "  ──────────────────────────────────────────────────────"
echo

if [[ "$INTERACTIVE" -eq 1 ]]; then
    read -rp "  确认构建？[Y/n] " CONFIRM
    [[ "${CONFIRM,,}" == "n" ]] && { info "已取消。"; exit 0; }
fi

echo
info "开始构建镜像，请稍候（首次构建含 pip install，可能需要数分钟）..."
echo

START_TS="$(date +%s)"
cd "$ROOT"

BUILD_ARGS=(
    --file docker/Dockerfile
    --tag "$IMAGE_TAG"
    --tag "react-agent:latest"
    --build-arg "REQUIREMENTS=$REQ_FILE"
    --progress=plain
)
[[ -n "$TORCH_EXTRA" ]] && BUILD_ARGS+=(--build-arg "TORCH_EXTRA=$TORCH_EXTRA")

if docker build "${BUILD_ARGS[@]}" .; then
    END_TS="$(date +%s)"
    ELAPSED=$(( END_TS - START_TS ))

    echo
    echo "  ──────────────────────────────────────────────────────"
    ok "镜像构建成功！"
    info "  标签     : $IMAGE_TAG  /  react-agent:latest"
    info "  耗时     : ${ELAPSED}s"

    # 显示镜像大小
    SIZE_BYTES=$(docker image inspect "$IMAGE_TAG" --format '{{.Size}}' 2>/dev/null || echo 0)
    SIZE_MB=$(( SIZE_BYTES / 1048576 ))
    info "  镜像大小 : ${SIZE_MB} MB"
    echo "  ──────────────────────────────────────────────────────"
else
    BUILD_CODE=$?
    echo
    fail "镜像构建失败（退出码 $BUILD_CODE）"
    fail "请检查上方日志定位错误。"
    exit $BUILD_CODE
fi

# ── 7. 推送（可选） ───────────────────────────────────────────────────────────
DO_PUSH=$ARG_PUSH
if [[ "$DO_PUSH" -eq 0 && "$INTERACTIVE" -eq 1 ]]; then
    echo
    read -rp "  是否推送到 registry？[y/N] " PUSH_CHOICE
    [[ "${PUSH_CHOICE,,}" == "y" ]] && DO_PUSH=1
fi

if [[ "$DO_PUSH" -eq 1 ]]; then
    echo
    info "推送镜像 $IMAGE_TAG ..."
    if docker push "$IMAGE_TAG"; then
        ok "推送成功。"
    else
        fail "推送失败，请检查 registry 登录状态（docker login）。"
    fi
fi

echo
info "启动全栈服务："
info "  docker compose -f docker/docker-compose.yml up -d"
echo
