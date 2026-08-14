# syntax=docker/dockerfile:1
# =============================================================================
# Dockerfile — ReAct Agent（API 推理模式）
#
# 构建上下文为项目根目录，从 docker/ 目录内指定此文件：
#   docker build -f docker/Dockerfile -t react-agent .
#
# 前端为 FastAPI 托管的 static ES modules（src/webui/static），无独立 Vite 构建。
# =============================================================================

FROM python:3.11-slim AS base

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        gcc \
        libgomp1 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

ARG REQUIREMENTS=requirements-light.txt
ARG TORCH_EXTRA=""

COPY ${REQUIREMENTS} ./requirements-active.txt
RUN pip install --no-cache-dir ${TORCH_EXTRA} -r requirements-active.txt

COPY src/ ./src/
COPY config/ ./config/

RUN mkdir -p /app/.react/traces /app/.react/persona

ENV PYTHONPATH=/app/src
ENV PYTHONUNBUFFERED=1
ENV SEARXNG_URL=http://searxng:8080

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c \
      "import urllib.request; urllib.request.urlopen('http://localhost:8080/')" \
      || exit 1

CMD ["python", "src/run.py", "--mode", "webui", \
     "--host", "0.0.0.0", "--port", "8080", "--no-searxng"]
