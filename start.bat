@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul 2>&1

:: ══════════════════════════════════════════════════════════════════
::  ReAct Agent — 一键启动脚本
::  用法：双击此文件即可
:: ══════════════════════════════════════════════════════════════════

set "ROOT=%~dp0"
set "ROOT=%ROOT:~0,-1%"
set "PORT=8300"
set "URL=http://127.0.0.1:%PORT%"

title ReAct Agent

echo.
echo  ╔══════════════════════════════════════╗
echo  ║        ReAct Agent  Launcher         ║
echo  ╚══════════════════════════════════════╝
echo.

:: ── 1. 定位 Python ──────────────────────────────────────────────────
set "PYTHON="

:: 优先使用项目内的 venv
if exist "%ROOT%\venv\Scripts\python.exe" (
    set "PYTHON=%ROOT%\venv\Scripts\python.exe"
    echo  [OK]  使用虚拟环境: venv\Scripts\python.exe
    goto :python_found
)
if exist "%ROOT%\.venv\Scripts\python.exe" (
    set "PYTHON=%ROOT%\.venv\Scripts\python.exe"
    echo  [OK]  使用虚拟环境: .venv\Scripts\python.exe
    goto :python_found
)

:: 其次使用指定的 Conda 环境（含项目所需全部依赖）
if exist "D:\anaconda\envs\LLMs\python.exe" (
    set "PYTHON=D:\anaconda\envs\LLMs\python.exe"
    echo  [OK]  使用 Conda 环境: D:\anaconda\envs\LLMs
    goto :python_found
)

:: 最后回退到系统 Python
where python >nul 2>&1
if !errorlevel! == 0 (
    for /f "delims=" %%i in ('where python') do (
        if not defined PYTHON set "PYTHON=%%i"
    )
    echo  [OK]  使用系统 Python: !PYTHON!
    goto :python_found
)

echo  [!!] 未找到 Python，请先安装 Python 3.10+
echo       下载地址: https://www.python.org/downloads/
pause
exit /b 1

:python_found
:: 打印版本
for /f "tokens=*" %%v in ('"%PYTHON%" --version 2^>^&1') do echo  [  ]  版本: %%v

:: ── 2. 检查依赖（requirements.txt 哈希变化时自动重装） ───────────────
set "FLAG=%ROOT%\.react\.deps_installed"
set "REQ=%ROOT%\requirements.txt"

:: 计算 requirements.txt 的 MD5 哈希（certutil 内置，无需额外工具）
set "CURRENT_HASH="
for /f "skip=1 tokens=*" %%h in ('certutil -hashfile "%REQ%" MD5 2^>nul') do (
    if not defined CURRENT_HASH set "CURRENT_HASH=%%h"
)

:: 读取上次安装时存入的哈希
set "STORED_HASH="
if exist "%FLAG%" (
    set /p STORED_HASH=<"%FLAG%"
)

:: 哈希不同（或 flag 不存在）则重新安装
set "DO_INSTALL=0"
if not "!CURRENT_HASH!"=="!STORED_HASH!" set "DO_INSTALL=1"

if !DO_INSTALL! == 1 (
    echo.
    echo  [..] 检测到依赖变更，正在安装，请稍候...
    "%PYTHON%" -m pip install -r "%REQ%" --quiet
    if !errorlevel! neq 0 (
        echo  [!!] 依赖安装失败，请检查网络或手动运行:
        echo       pip install -r requirements.txt
        pause
        exit /b 1
    )
    if not exist "%ROOT%\.react" mkdir "%ROOT%\.react"
    echo !CURRENT_HASH!> "%FLAG%"
    echo  [OK]  依赖安装完成
)

:: ── 3. 询问是否用 Docker 启动数据库（MySQL + Redis） ────────────────
echo.
echo  知识库功能依赖 MySQL 和 Redis（需要 Docker）。
echo  若不使用知识库，或已有在运行的实例，可选择跳过。
echo.
set /p "START_DB=  用 Docker 启动 MySQL + Redis？[Y/n] "
if /i "!START_DB!"=="n" (
    echo  [  ]  已跳过数据库启动。
) else (
    where docker >nul 2>&1
    if !errorlevel! neq 0 (
        echo  [!!] 未检测到 Docker，跳过数据库启动。
        echo  [  ]  若需知识库功能，请先安装 Docker Desktop。
    ) else (
        echo  [>>] 正在启动 MySQL 和 Redis 容器...
        docker compose -f "%ROOT%\docker\docker-compose-db.yml" up -d
        if !errorlevel! neq 0 (
            echo  [!!] 数据库容器启动失败，请检查 Docker 是否正常运行。
        ) else (
            echo  [OK] MySQL + Redis 容器已启动，等待就绪...
            :: 等待 MySQL 健康（最多 60 秒）
            set "DB_READY=0"
            for /l %%i in (1,1,12) do (
                if "!DB_READY!"=="0" (
                    docker exec react-mysql mysqladmin ping -h localhost -uroot -ppassword --silent >nul 2>&1
                    if !errorlevel! == 0 (
                        set "DB_READY=1"
                        echo  [OK] MySQL 已就绪。
                    ) else (
                        timeout /t 5 /nobreak >nul
                    )
                )
            )
            if "!DB_READY!"=="0" (
                echo  [!!] MySQL 未能在 60 秒内就绪，请手动检查容器状态。
            )
            :: 检查 Redis
            docker exec react-redis redis-cli ping >nul 2>&1
            if !errorlevel! == 0 (
                echo  [OK] Redis 已就绪。
            ) else (
                echo  [!!] Redis 未就绪，请手动检查容器状态。
            )
        )
    )
)

:: ── 4. 询问是否跳过 SearXNG（Docker） ───────────────────────────────
echo.
echo  SearXNG 是本地搜索引擎（需要 Docker）。
echo  若未安装 Docker 或希望跳过，输入 N；否则直接回车。
echo.
set /p "SKIP_SEARXNG=  跳过 SearXNG？[y/N] "
set "SEARXNG_FLAG="
if /i "!SKIP_SEARXNG!"=="y" (
    set "SEARXNG_FLAG=--no-searxng"
    echo  [  ]  已设置: 跳过 SearXNG，搜索引擎将自动降级。
) else (
    echo  [  ]  已设置: 尝试启动 SearXNG Docker 容器。
)

:: ── 5. 启动服务器 ────────────────────────────────────────────────────
echo.
echo  [>>] 正在启动 ReAct Agent...
echo  [  ]  访问地址: %URL%
echo  [  ]  按 Ctrl+C 可停止服务
echo  ──────────────────────────────────────────
echo.

:: 在后台轮询服务就绪后自动打开浏览器（单行，避免 ^ 续行解析错误）
start "" /b powershell -NoProfile -WindowStyle Hidden -Command "do { Start-Sleep 1 } until (try{(Invoke-WebRequest '%URL%' -UseBasicParsing -TimeoutSec 2).StatusCode -eq 200}catch{$false}); Start-Process '%URL%'"

:: 前台运行服务（stderr 合并到 stdout，日志全部显示在此窗口）
cd /d "%ROOT%"
"%PYTHON%" src\run.py %SEARXNG_FLAG% 2>&1
set "EXIT_CODE=!errorlevel!"

:: 服务退出后显示原因
echo.
if !EXIT_CODE! neq 0 (
    echo  [!!] 服务异常退出，退出码: !EXIT_CODE!
) else (
    echo  [  ] 服务已正常停止。
)
pause
endlocal
