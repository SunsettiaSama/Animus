"""
src/run.py — ReAct Agent 统一启动入口

SearXNG 以 Docker 容器形式管理，而非在子进程中直接运行 Flask：
  · Docker 提供完整的生命周期管理（自动重启、幂等启停、进程隔离）
  · 若 Docker 不可用，SearchEngine 自动降级到 Tavily 或 DDG

用法：
  python src/run.py                    # WebUI 模式（默认，含自动启动 SearXNG）
  python src/run.py --mode cli         # CLI 交互模式
  python src/run.py --check            # 仅检查配置与服务状态
  python src/run.py --no-searxng       # 跳过 SearXNG Docker 容器管理
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

# ── sys.path：把 src/ 加入路径 ────────────────────────────────────────────────
SRC  = Path(__file__).resolve().parent
ROOT = SRC.parent
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from config import paths  # noqa: E402 — must come after sys.path setup
from config.react.run_config import RunConfig  # noqa: E402

# ── 路径常量（统一从 AppPaths 获取，不再硬编码） ──────────────────────────────
_DEFAULT_LLM_CONFIG   = paths.llm_config_yaml
_SEARXNG_SETTINGS_YML = paths.searxng_settings_yml

# 从 config/react/run.yaml 加载运行时默认值
_run_cfg = RunConfig.load()

_CONTAINER_NAME  = _run_cfg.searxng.container_name
_CONTAINER_IMAGE = _run_cfg.searxng.image
_HOST_PORT       = _run_cfg.searxng.host_port
_CONTAINER_PORT  = _run_cfg.searxng.container_port


# ═════════════════════════════════════════════════════════════════════════════
#  终端输出辅助
# ═════════════════════════════════════════════════════════════════════════════

def _bold(s: str)   -> str: return f"\033[1m{s}\033[0m"
def _green(s: str)  -> str: return f"\033[32m{s}\033[0m"
def _yellow(s: str) -> str: return f"\033[33m{s}\033[0m"
def _red(s: str)    -> str: return f"\033[31m{s}\033[0m"
def _cyan(s: str)   -> str: return f"\033[36m{s}\033[0m"

def _ok(label: str, detail: str = "")   -> None:
    print(f"  {_green('[OK]')}  {label}" + (f"  {detail}" if detail else ""))

def _warn(label: str, detail: str = "") -> None:
    print(f"  {_yellow('[!]')}   {label}" + (f"  {detail}" if detail else ""))

def _fail(label: str, detail: str = "") -> None:
    print(f"  {_red('[!!]')}  {label}" + (f"  {detail}" if detail else ""))

def _section(title: str) -> None:
    print(f"\n{_bold(_cyan(f'── {title}'))}")


# ═════════════════════════════════════════════════════════════════════════════
#  Docker / SearXNG 容器生命周期管理
# ═════════════════════════════════════════════════════════════════════════════

def _run_docker(*args: str, timeout: int = 10) -> subprocess.CompletedProcess | None:
    """返回 CompletedProcess；若 docker 可执行文件不存在则返回 None。"""
    try:
        return subprocess.run(
            ["docker", *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None

def _docker_available() -> bool:
    result = _run_docker("info", timeout=20)
    return result is not None and result.returncode == 0


def _container_status() -> str:
    """返回容器状态字符串（如 'Up 3 minutes'），不存在时返回空串。"""
    result = _run_docker(
        "ps", "-a",
        "--filter", f"name=^{_CONTAINER_NAME}$",
        "--format", "{{.Status}}",
    )
    return result.stdout.strip() if result else ""


def _wait_until_up(seconds: int = 12) -> bool:
    """轮询容器状态，直到 Up 或超时。"""
    for _ in range(seconds):
        time.sleep(1)
        if _container_status().startswith("Up"):
            return True
    return False


def ensure_searxng(skip: bool) -> None:
    """
    确保 SearXNG 容器处于运行状态。

    策略（按顺序）：
      1. skip=True              → 直接跳过
      2. Docker daemon 不可用   → 打印警告，搜索引擎自动降级
      3. 容器已在运行           → 什么都不做
      4. 容器存在但已停止       → docker start
      5. 容器不存在（首次）     → docker run（挂载 settings.yml）
    """
    _section("SearXNG")

    if skip:
        _warn("SearXNG", "已跳过（--no-searxng）")
        return

    if not _docker_available():
        _warn("Docker", "daemon 不可用或未安装")
        _warn("SearXNG", "将由 SearchEngine 自动降级到 Tavily / DDG")
        return

    status = _container_status()

    if status.startswith("Up"):
        _ok("SearXNG 容器", f"already running  →  http://127.0.0.1:{_HOST_PORT}")
        return

    if status:
        # 容器存在但已停止
        _warn("SearXNG 容器", f"状态: {status}  →  正在重新启动…")
        result = _run_docker("start", _CONTAINER_NAME, timeout=15)
        if result.returncode != 0:
            _fail("SearXNG 容器", f"docker start 失败: {result.stderr.strip()[:100]}")
            return
    else:
        # 首次创建
        _warn("SearXNG 容器", "首次创建容器，正在拉取镜像（可能需要数分钟）…")
        cmd = [
            "run", "-d",
            "--name",    _CONTAINER_NAME,
            "--restart", "unless-stopped",
            "-p",        f"127.0.0.1:{_HOST_PORT}:{_CONTAINER_PORT}",
        ]
        if _SEARXNG_SETTINGS_YML.exists():
            cmd += ["-v", f"{_SEARXNG_SETTINGS_YML}:/etc/searxng/settings.yml"]
            _ok("SearXNG 配置", f"挂载 {_SEARXNG_SETTINGS_YML.name}")
        else:
            _warn("SearXNG 配置", "settings.yml 不存在，使用镜像默认配置")
        cmd.append(_CONTAINER_IMAGE)

        result = _run_docker(*cmd, timeout=120)
        if result.returncode != 0:
            _fail("SearXNG 容器", f"docker run 失败: {result.stderr.strip()[:120]}")
            return

    # 等待容器内服务就绪
    _warn("SearXNG 容器", "等待服务就绪…")
    if _wait_until_up():
        _ok("SearXNG 容器", f"running  →  http://127.0.0.1:{_HOST_PORT}")
    else:
        _fail("SearXNG 容器", "超时：容器未能进入 Up 状态，请查看 docker logs react-searxng")


# ═════════════════════════════════════════════════════════════════════════════
#  各组件检查
# ═════════════════════════════════════════════════════════════════════════════

def check_search() -> str:
    """探测搜索后端并返回激活的后端名称。"""
    _section("搜索后端")
    from network.search.engine import SearchEngine
    engine = SearchEngine()
    name = engine.active_backend_name
    _ok("搜索后端", f"active = {name!r}")
    return name


def check_llm(config_path: Path):
    """加载并验证 LLM 配置，返回 LLMConfig 或 None。"""
    _section("LLM 配置")
    from config.llm_core.config import LLMConfig
    if not config_path.exists():
        _warn("LLM 配置文件", f"不存在: {config_path}")
        _warn("提示", "WebUI 启动后可在界面手动配置模型")
        return None
    cfg = LLMConfig.from_yaml(str(config_path))
    if not cfg.model:
        _warn("LLM 配置", "model 字段为空，WebUI 启动后需手动配置")
        return cfg
    _ok("LLM 配置", f"model={cfg.model!r}  base_url={cfg.base_url or '(默认)'}")
    return cfg


# ═════════════════════════════════════════════════════════════════════════════
#  TaoLoop 构建（CLI 模式使用）
# ═════════════════════════════════════════════════════════════════════════════

def _build_tao(llm_cfg) -> object:
    _section("TaoLoop 初始化")
    from cache.config import CacheConfig
    from config.react.memory.memory_config import MemoryConfig
    from config.react.tao_config import TaoConfig
    from llm_core.llm import LLM
    from react.action.manager import ToolManager
    from react.tao import TaoLoop

    cache  = CacheConfig(root=str(paths.cache_root))
    memory = (
        MemoryConfig.from_yaml(str(paths.memory_config_yaml))
        if paths.memory_config_yaml.exists()
        else MemoryConfig()
    )
    cfg        = TaoConfig(cache=cache, memory=memory)
    llm        = LLM(llm_cfg)
    manager    = ToolManager()
    executor   = manager.build_executor()
    tool_descs = manager.primary_descriptions()
    tao        = TaoLoop(llm=llm, executor=executor, tool_descriptions=tool_descs, cfg=cfg)
    _ok("TaoLoop", f"工具 {len(tool_descs)} 个  max_steps={cfg.max_steps}")
    return tao


# ═════════════════════════════════════════════════════════════════════════════
#  启动模式
# ═════════════════════════════════════════════════════════════════════════════

def run_check(llm_config: Path, no_searxng: bool) -> None:
    print(_bold("\n=== ReAct 服务检查 ==="))
    ensure_searxng(no_searxng)
    check_search()
    check_llm(llm_config)
    print(f"\n{_green('检查完成。')}\n")


def run_cli(llm_config: Path, no_searxng: bool) -> None:
    print(_bold("\n=== ReAct CLI 模式 ==="))
    ensure_searxng(no_searxng)
    check_search()
    cfg = check_llm(llm_config)

    if cfg is None or not cfg.model:
        raise RuntimeError(
            "CLI 模式需要有效的 LLM 配置（model 字段非空）。\n"
            f"请检查: {llm_config}"
        )

    tao = _build_tao(cfg)
    print(f"\n{_bold('开始对话')}  输入 exit 退出\n")

    while True:
        question = input(_cyan("> ")).strip()
        if not question:
            continue
        if question.lower() in ("exit", "quit", "q"):
            print("再见。")
            break
        answer = tao.run(question)
        print(f"\n{answer}\n")


def run_webui(host: str, port: int, llm_config: Path, no_searxng: bool) -> None:
    import uvicorn

    print(_bold("\n=== ReAct WebUI 模式 ==="))
    ensure_searxng(no_searxng)
    check_search()
    check_llm(llm_config)
    print(f"\n{_bold('启动 WebUI')}  →  http://{host}:{port}\n")

    uvicorn.run("webui.app:app", host=host, port=port, reload=False)


# ═════════════════════════════════════════════════════════════════════════════
#  CLI 参数解析 & 入口
# ═════════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="run.py",
        description="ReAct Agent 统一启动入口",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "示例：\n"
            "  python src/run.py                      # 启动 WebUI（自动管理 SearXNG）\n"
            "  python src/run.py --mode cli           # 交互式 CLI\n"
            "  python src/run.py --check              # 仅检查服务状态\n"
            "  python src/run.py --no-searxng         # 跳过 Docker/SearXNG\n"
            "  python src/run.py --mode webui --host 0.0.0.0 --port 8300\n"
        ),
    )
    parser.add_argument(
        "--mode", choices=["webui", "cli"], default="webui",
        help="启动模式（默认 webui）",
    )
    parser.add_argument("--host", default=_run_cfg.webui.host,
                        help="WebUI 监听地址（默认 127.0.0.1）")
    parser.add_argument("--port", type=int, default=_run_cfg.webui.port,
                        help="WebUI 监听端口（默认 8300）")
    parser.add_argument(
        "--llm-config", type=Path, default=_DEFAULT_LLM_CONFIG,
        dest="llm_config", metavar="PATH",
        help=f"LLM 配置文件路径（默认 config/llm_core/config.yaml）",
    )
    parser.add_argument(
        "--no-searxng", action="store_true", dest="no_searxng",
        help="跳过 SearXNG Docker 容器管理（手动管理或使用其他后端）",
    )
    parser.add_argument(
        "--check", action="store_true",
        help="仅检查配置与服务状态，不启动任何进程",
    )
    args = parser.parse_args()

    if args.check:
        run_check(args.llm_config, args.no_searxng)
    elif args.mode == "cli":
        run_cli(args.llm_config, args.no_searxng)
    else:
        run_webui(args.host, args.port, args.llm_config, args.no_searxng)


if __name__ == "__main__":
    main()
