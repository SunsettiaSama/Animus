@echo off
REM =============================================================================
REM ReAct Agent - Windows Docker Desktop 专用脚本
REM 使用 Docker Desktop for Windows 直接启动（不需要 WSL）
REM =============================================================================

setlocal enabledelayedexpansion

cd /d "%~dp0"

set "ENV=%~1"
if "%ENV%"=="" set "ENV=staging"

set "COMPOSE_FILE=docker-compose.yml"
if "%ENV%"=="production" set "COMPOSE_FILE=docker-compose.prod.yml"
if "%ENV%"=="staging" set "COMPOSE_FILE=docker-compose.prod.yml"

echo =========================================
echo ReAct Agent 部署 (Windows Docker Desktop)
echo 环境: %ENV%
echo =========================================

REM 检查 .env 文件
if not exist ".env" (
    echo [WARN] .env 文件不存在，从 .env.example 复制中...
    copy ".env.example" ".env"
    echo.
    echo [INFO] 请编辑 .env 文件配置后重新运行
    echo.
    pause
    exit /b 1
)

REM 检查 Docker 是否运行
docker version >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] Docker 未运行！请启动 Docker Desktop.
    pause
    exit /b 1
)

REM 主逻辑
goto %ENV% 2>nul
goto :invalid

:staging
:production
echo.
echo [INFO] 拉取最新镜像...
docker compose -f "%COMPOSE_FILE%" pull

echo.
echo [INFO] 启动服务...
docker compose -f "%COMPOSE_FILE%" up -d --remove-orphans

echo.
echo [INFO] 等待服务就绪...
:wait_loop
docker compose -f "%COMPOSE_FILE%" ps react | findstr /C:"healthy" >nul 2>nul
if %errorlevel% equ 0 (
    echo [INFO] 服务就绪！
    goto show_info
)
timeout /t 5 /nobreak >nul
goto wait_loop

:show_info
echo.
echo =========================================
echo [SUCCESS] 部署完成！
echo =========================================
echo.
echo [INFO] 监控仪表板：
echo   - Grafana:    http://grafana.localhost
echo   - Prometheus: http://prometheus.localhost:9090
echo   - Traefik:    http://traefik.localhost:8080
echo   - Jaeger:     http://jaeger.localhost
echo.
echo [INFO] 应用访问：
echo   - ReAct Agent: http://app.localhost
echo.
echo [INFO] 查看日志：
echo   docker compose -f "%COMPOSE_FILE%" logs -f
goto end

:stop
echo.
echo [INFO] 停止所有服务...
docker compose -f "%COMPOSE_FILE%" down
echo [SUCCESS] 服务已停止
goto end

:backup
echo.
echo [INFO] 创建备份...
docker compose -f "%COMPOSE_FILE%" run --rm volume-backup
echo [SUCCESS] 备份完成
goto end

:restart
echo.
echo [INFO] 重启服务...
docker compose -f "%COMPOSE_FILE%" restart
echo [SUCCESS] 服务已重启
goto end

:status
echo.
echo [INFO] 服务状态：
docker compose -f "%COMPOSE_FILE%" ps
goto end

:logs
echo.
echo [INFO] 查看日志 (Ctrl+C 退出)...
docker compose -f "%COMPOSE_FILE%" logs -f
goto end

:invalid
echo.
echo [ERROR] 无效的参数！
echo.
echo [INFO] 用法:
echo   %~nx0 staging         ^| 启动开发环境
echo   %~nx0 production      ^| 启动生产环境
echo   %~nx0 stop            ^| 停止服务
echo   %~nx0 backup          ^| 备份数据
echo   %~nx0 restart         ^| 重启服务
echo   %~nx0 status          ^| 查看状态
echo   %~nx0 logs            ^| 查看日志
echo.
pause
exit /b 1

:end
endlocal
exit /b 0
