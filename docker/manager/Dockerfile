# =============================================================================
# ReAct Agent Manager Container
# 管理容器：包含所有部署脚本，负责协调项目启动
#
# 用法：
#   docker compose -f docker-compose.manager.yml run --rm manager help
#   docker compose -f docker-compose.manager.yml run --rm manager staging
# =============================================================================

FROM docker:24-dind

LABEL org.opencontainers.image.title="ReAct Agent Manager"
LABEL org.opencontainers.image.description="管理和部署 ReAct Agent 的工具容器"
LABEL org.opencontainers.image.vendor="ReAct Project"

# 设置工作目录
WORKDIR /app

# 安装基础工具（bash, curl, etc.）
RUN apk add --no-cache \
    bash \
    curl \
    git \
    tzdata \
    && ln -sf /usr/share/zoneinfo/Asia/Shanghai /etc/localtime \
    && echo "Asia/Shanghai" > /etc/timezone

# 复制入口脚本
COPY manager/entrypoint.sh /app/entrypoint.sh

# 复制 docker compose 配置
COPY docker-compose*.yml /app/

# 复制 .env.example
COPY .env.example /app/

# 复制其他配置目录
COPY prometheus/ /app/prometheus/
COPY grafana/ /app/grafana/
COPY loki/ /app/loki/
COPY redis/ /app/redis/

# 设置执行权限
RUN chmod +x /app/entrypoint.sh

# 设置入口脚本
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["help"]
