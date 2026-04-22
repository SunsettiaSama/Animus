# syntax=docker/dockerfile:1
# =============================================================================
# Dockerfile — ReAct Agent（API 推理模式）
#
# 构建上下文为项目根目录，从 docker/ 目录内指定此文件：
#   docker build -f docker/Dockerfile -t react-agent .
#
# 若需本地 HuggingFace 推理（含 torch CPU / faiss），改用：
#   docker build -f docker/Dockerfile \
#     --build-arg REQUIREMENTS=requirements.txt \
#     --build-arg TORCH_EXTRA="--index-url https://download.pytorch.org/whl/cpu" \
#     -t react-agent .
# =============================================================================

# ── 基础镜像 ──────────────────────────────────────────────────────────────────
FROM python:3.11-slim AS base

# ── 系统依赖 ──────────────────────────────────────────────────────────────────
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        gcc \
        libgomp1 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ── 构建参数 ──────────────────────────────────────────────────────────────────
ARG REQUIREMENTS=requirements-light.txt
# 本地推理时设为 "--index-url https://download.pytorch.org/whl/cpu"
ARG TORCH_EXTRA=""

# ── Python 依赖（独立层，代码变动不重建此层）─────────────────────────────────
COPY ${REQUIREMENTS} ./requirements-active.txt
RUN pip install --no-cache-dir ${TORCH_EXTRA} -r requirements-active.txt

# ── 应用代码（路径均相对于构建上下文，即项目根目录）─────────────────────────
COPY src/    ./src/
COPY config/ ./config/

# ── 运行时数据目录（由 volume 覆盖，此处仅创建空占位） ─────────────────────
RUN mkdir -p /app/.react/traces /app/.react/persona

# ── 环境变量 ──────────────────────────────────────────────────────────────────
ENV PYTHONPATH=/app/src
ENV PYTHONUNBUFFERED=1
# 容器内通过 compose 服务名访问 SearXNG
ENV SEARXNG_URL=http://searxng:8080

# ── 端口 & 健康检查 ────────────────────────────────────────────────────────────
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c \
      "import urllib.request; urllib.request.urlopen('http://localhost:8080/')" \
      || exit 1

# ── 启动命令 ──────────────────────────────────────────────────────────────────
# --no-searxng：容器内不再用 Docker CLI 管理 SearXNG，由 compose 负责编排
CMD ["python", "src/run.py", "--mode", "webui", \
     "--host", "0.0.0.0", "--port", "8080", "--no-searxng"]
