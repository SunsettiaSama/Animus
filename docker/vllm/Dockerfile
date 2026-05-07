# syntax=docker/dockerfile:1
# =============================================================================
# docker/vllm/Dockerfile — vLLM 推理服务
#
# 基础镜像: nvidia/cuda (Ubuntu 22.04)
# 包管理:  uv  (比 pip 快 10–100×，锁文件可复现)
#
# 构建 (在项目根目录执行):
#   docker build -f docker/vllm/Dockerfile -t react-vllm .
#
# 多阶段构建:
#   builder  — 安装 uv + 所有 Python 依赖
#   runtime  — 仅拷贝 venv，保持镜像体积最小
# =============================================================================

# ── Stage 1: builder ──────────────────────────────────────────────────────────
FROM nvidia/cuda:12.4.1-cudnn-devel-ubuntu22.04 AS builder

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3.11 \
        python3.11-dev \
        python3-pip \
        curl \
        git \
    && rm -rf /var/lib/apt/lists/*

# uv 安装器写入 ~/.local/bin；对 root 用户需要显式加 PATH
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.local/bin:${PATH}"

# 独立 venv — 后续 stage 直接拷贝整个目录
RUN uv venv /opt/vllm-env --python 3.11
ENV VIRTUAL_ENV=/opt/vllm-env
ENV PATH="/opt/vllm-env/bin:${PATH}"

# vllm 本身会拉 torch + CUDA kernel；使用 uv pip 加速解析
# --index-strategy unsafe-best-match 允许从多个 index 混合安装
RUN uv pip install \
        --index-url https://pypi.org/simple \
        --extra-index-url https://download.pytorch.org/whl/cu124 \
        vllm


# ── Stage 2: runtime ──────────────────────────────────────────────────────────
FROM nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04 AS runtime

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
        python3.11 \
        python3.11-dev \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# 从 builder 拷贝完整 venv
COPY --from=builder /opt/vllm-env /opt/vllm-env

ENV VIRTUAL_ENV=/opt/vllm-env
ENV PATH="/opt/vllm-env/bin:${PATH}"

# HuggingFace / vllm 缓存目录（由 volume 挂载）
ENV HF_HOME=/cache/huggingface
ENV VLLM_CACHE_ROOT=/cache/vllm
RUN mkdir -p /cache/huggingface /cache/vllm

WORKDIR /workspace

# entrypoint 脚本：根据环境变量动态生成 vllm serve 参数
COPY docker/vllm/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# OpenAI-compatible API port
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=5 \
  CMD python3.11 -c \
      "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" \
      || exit 1

ENTRYPOINT ["/entrypoint.sh"]
