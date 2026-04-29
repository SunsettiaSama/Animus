@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul 2>&1

:: ══════════════════════════════════════════════════════════════════
::  ReAct Agent — Docker 镜像打包脚本
::
::  用法（交互模式，直接双击）：
::    build.bat
::
::  用法（命令行参数，适合 CI/CD）：
::    build.bat [--mode api|full] [--device cpu|gpu] [--tag NAME] [--push]
::
::  --mode api    使用 requirements-light.txt（API 推理，默认）
::  --mode full   使用 requirements.txt（含本地 HuggingFace LLM 推理）
::  --device cpu  强制安装 CPU 版 torch
::  --device gpu  使用默认 PyPI torch（含 CUDA 支持，默认）
::  --tag NAME    自定义镜像名（默认 react-agent:latest）
::  --push        构建完成后推送到 registry
:: ══════════════════════════════════════════════════════════════════

:: 定位项目根目录（本脚本在 docker/ 下）
set "SCRIPT_DIR=%~dp0"
set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
for %%i in ("%SCRIPT_DIR%\..") do set "ROOT=%%~fi"

title ReAct — Docker Build

echo.
echo  ╔══════════════════════════════════════╗
echo  ║     ReAct Agent  Docker Builder      ║
echo  ╚══════════════════════════════════════╝
echo.

:: ── 解析命令行参数 ──────────────────────────────────────────────────
set "ARG_MODE="
set "ARG_DEVICE="
set "ARG_TAG="
set "ARG_PUSH=0"
set "INTERACTIVE=1"

:parse_args
if "%~1"=="" goto :done_parse
if /i "%~1"=="--mode"   ( set "ARG_MODE=%~2"   & set "INTERACTIVE=0" & shift & shift & goto :parse_args )
if /i "%~1"=="--device" ( set "ARG_DEVICE=%~2" & set "INTERACTIVE=0" & shift & shift & goto :parse_args )
if /i "%~1"=="--tag"    ( set "ARG_TAG=%~2"    & set "INTERACTIVE=0" & shift & shift & goto :parse_args )
if /i "%~1"=="--push"   ( set "ARG_PUSH=1"     & set "INTERACTIVE=0" & shift               & goto :parse_args )
shift
goto :parse_args
:done_parse

:: ── 1. 检查 Docker ──────────────────────────────────────────────────
echo  [>>] 检查 Docker 环境...
where docker >nul 2>&1
if !errorlevel! neq 0 (
    echo  [!!] 未检测到 Docker，请先安装 Docker Desktop。
    echo       https://www.docker.com/products/docker-desktop/
    pause & exit /b 1
)
docker info >nul 2>&1
if !errorlevel! neq 0 (
    echo  [!!] Docker daemon 未运行，请先启动 Docker Desktop。
    pause & exit /b 1
)
for /f "tokens=*" %%v in ('docker --version') do echo  [OK] %%v
echo.

:: ── 2. 选择构建模式 ─────────────────────────────────────────────────
if defined ARG_MODE (
    set "BUILD_MODE=!ARG_MODE!"
    goto :mode_done
)
echo  构建模式：
echo    [1] API 模式    — 轻量依赖，LLM 使用 OpenAI / 其他 API（推荐）
echo    [2] Full 模式   — 含本地 HuggingFace LLM 推理（镜像更大）
echo.
set /p "MODE_CHOICE=  请选择 [1/2，默认 1]: "
if "!MODE_CHOICE!"=="2" ( set "BUILD_MODE=full" ) else ( set "BUILD_MODE=api" )
:mode_done

:: ── 3. 选择 torch 设备 ──────────────────────────────────────────────
if defined ARG_DEVICE (
    set "BUILD_DEVICE=!ARG_DEVICE!"
    goto :device_done
)
echo.
echo  torch 版本：
echo    [1] GPU（CUDA）— 需要 NVIDIA 显卡与 CUDA 驱动（默认）
echo    [2] CPU Only   — 无 GPU 或部署到无显卡服务器时选此项
echo.
set /p "DEV_CHOICE=  请选择 [1/2，默认 1]: "
if "!DEV_CHOICE!"=="2" ( set "BUILD_DEVICE=cpu" ) else ( set "BUILD_DEVICE=gpu" )
:device_done

:: ── 4. 确定镜像标签 ─────────────────────────────────────────────────
if defined ARG_TAG (
    set "IMAGE_TAG=!ARG_TAG!"
    goto :tag_done
)

:: 生成默认标签：react-agent:api-cpu / react-agent:full-gpu / ...
set "DEFAULT_TAG=react-agent:!BUILD_MODE!-!BUILD_DEVICE!"

echo.
set /p "TAG_INPUT=  镜像标签 [默认 !DEFAULT_TAG!]: "
if "!TAG_INPUT!"=="" ( set "IMAGE_TAG=!DEFAULT_TAG!" ) else ( set "IMAGE_TAG=!TAG_INPUT!" )
:tag_done

:: ── 5. 组装构建参数 ─────────────────────────────────────────────────
if "!BUILD_MODE!"=="full" (
    set "REQ_FILE=requirements.txt"
) else (
    set "REQ_FILE=requirements-light.txt"
)

set "TORCH_EXTRA="
if "!BUILD_DEVICE!"=="cpu" (
    set "TORCH_EXTRA=--index-url https://download.pytorch.org/whl/cpu"
)

:: ── 6. 确认并开始构建 ────────────────────────────────────────────────
echo.
echo  ──────────────────────────────────────────────────────
echo   构建配置：
echo     模式        : !BUILD_MODE!
echo     torch       : !BUILD_DEVICE!
echo     依赖文件    : !REQ_FILE!
echo     镜像标签    : !IMAGE_TAG!
if "!ARG_PUSH!"=="1" echo     构建后推送  : 是
echo  ──────────────────────────────────────────────────────
echo.

if "!INTERACTIVE!"=="1" (
    set /p "CONFIRM=  确认构建？[Y/n] "
    if /i "!CONFIRM!"=="n" (
        echo  [  ] 已取消。
        pause & exit /b 0
    )
)

echo.
echo  [>>] 开始构建镜像，请稍候（首次构建含 pip install，可能需要数分钟）...
echo.

:: 记录开始时间
set "START_TIME=%TIME%"

:: 切换到项目根目录执行 build，让 .dockerignore 生效
cd /d "%ROOT%"

if "!TORCH_EXTRA!"=="" (
    docker build ^
        --file docker/Dockerfile ^
        --tag "!IMAGE_TAG!" ^
        --tag "react-agent:latest" ^
        --build-arg REQUIREMENTS=!REQ_FILE! ^
        --progress=plain ^
        .
) else (
    docker build ^
        --file docker/Dockerfile ^
        --tag "!IMAGE_TAG!" ^
        --tag "react-agent:latest" ^
        --build-arg REQUIREMENTS=!REQ_FILE! ^
        --build-arg TORCH_EXTRA="!TORCH_EXTRA!" ^
        --progress=plain ^
        .
)

set "BUILD_CODE=!errorlevel!"
set "END_TIME=%TIME%"

echo.
if !BUILD_CODE! neq 0 (
    echo  [!!] 镜像构建失败（退出码 !BUILD_CODE!）
    echo  [  ] 请检查上方日志定位错误。
    pause & exit /b !BUILD_CODE!
)

echo  ──────────────────────────────────────────────────────
echo  [OK] 镜像构建成功！
echo       标签     : !IMAGE_TAG!  /  react-agent:latest
echo       开始时间 : !START_TIME!
echo       完成时间 : !END_TIME!
echo  ──────────────────────────────────────────────────────
echo.

:: 显示镜像大小
for /f "tokens=*" %%s in ('docker image inspect "!IMAGE_TAG!" --format "{{.Size}}" 2^>nul') do (
    set /a "SIZE_MB=%%s / 1048576"
    echo  [  ] 镜像大小: !SIZE_MB! MB
)

:: ── 7. 推送（可选） ──────────────────────────────────────────────────
if "!ARG_PUSH!"=="1" goto :do_push
if "!INTERACTIVE!"=="0" goto :push_done
echo.
set /p "PUSH_CHOICE=  是否推送到 registry？[y/N] "
if /i "!PUSH_CHOICE!"=="y" goto :do_push
goto :push_done

:do_push
echo.
echo  [>>] 推送镜像 !IMAGE_TAG!...
docker push "!IMAGE_TAG!"
if !errorlevel! neq 0 (
    echo  [!!] 推送失败，请检查 registry 登录状态（docker login）。
) else (
    echo  [OK] 推送成功。
)
:push_done

echo.
echo  [  ] 启动全栈服务：
echo       docker compose -f docker/docker-compose.yml up -d
echo.
pause
endlocal
