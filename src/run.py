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
import sys
from pathlib import Path

# ── sys.path：把 src/ 加入路径 ────────────────────────────────────────────────
SRC  = Path(__file__).resolve().parent
ROOT = SRC.parent
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from config import paths  # noqa: E402 — must come after sys.path setup
from config.agent.run_config import RunConfig  # noqa: E402
from infra.searxng_manager import SearXNGManager  # noqa: E402

# ── 路径常量（统一从 AppPaths 获取，不再硬编码） ──────────────────────────────
_DEFAULT_LLM_CONFIG = paths.llm_config_yaml

# 从 config/agent/run.yaml 加载运行时默认值
_run_cfg = RunConfig.load()


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
#  SearXNG 管理（委托给 SearXNGManager）
# ═════════════════════════════════════════════════════════════════════════════

def _make_searxng_manager() -> SearXNGManager:
    s = _run_cfg.searxng
    return SearXNGManager(
        container_name=s.container_name,
        image=s.image,
        host_port=s.host_port,
        container_port=s.container_port,
        settings_yml=paths.searxng_settings_yml,
    )


def ensure_searxng(skip: bool) -> None:
    _section("SearXNG")

    if skip:
        _warn("SearXNG", "已跳过（--no-searxng）")
        return

    mgr = _make_searxng_manager()

    if not mgr._docker_available():
        _warn("Docker", "daemon 不可用或未安装")
        _warn("SearXNG", "将由 SearchEngine 自动降级到 Tavily / DDG")
        return

    raw = mgr._container_status()

    if raw.startswith("Up"):
        _ok("SearXNG 容器", f"already running  →  {mgr.url}")
        return

    if raw:
        _warn("SearXNG 容器", f"状态: {raw}  →  正在重新启动…")
    else:
        _warn("SearXNG 容器", "首次创建容器，正在拉取镜像（可能需要数分钟）…")
        if paths.searxng_settings_yml.exists():
            _ok("SearXNG 配置", f"挂载 {paths.searxng_settings_yml.name}")
        else:
            _warn("SearXNG 配置", "settings.yml 不存在，使用镜像默认配置")

    mgr.start()

    _warn("SearXNG 容器", "等待服务就绪…")
    if mgr.wait_until_up():
        _ok("SearXNG 容器", f"running  →  {mgr.url}")
    else:
        _fail("SearXNG 容器", "超时：容器未能进入 Up 状态，请查看 docker logs react-searxng")


# ═════════════════════════════════════════════════════════════════════════════
#  各组件检查
# ═════════════════════════════════════════════════════════════════════════════

def check_search() -> str:
    _section("搜索后端")
    from infra.network.search.engine import SearchEngine
    engine = SearchEngine()
    name = engine.active_backend_name
    _ok("搜索后端", f"active = {name!r}")
    return name


def check_llm(config_path: Path):
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
    from config.storage import StorageConfig
    from config.agent.memory.memory_config import MemoryConfig
    from config.agent.tao_config import TaoConfig
    from infra.llm import LLM
    from agent.react.action.manager import ToolManager
    from agent.react.tao import TaoLoop

    storage = StorageConfig(root=str(paths.cache_root))
    memory = (
        MemoryConfig.from_yaml(str(paths.memory_config_yaml))
        if paths.memory_config_yaml.exists()
        else MemoryConfig()
    )
    cfg        = TaoConfig(storage=storage, memory=memory)
    llm        = LLM(llm_cfg)
    manager    = ToolManager()
    executor   = manager.build_executor()
    tool_descs = manager.primary_descriptions()
    cat_summary = manager.category_summary()
    tao        = TaoLoop(llm=llm, executor=executor, tool_descriptions=tool_descs, cfg=cfg, tool_category_summary=cat_summary)
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
    import logging
    import uvicorn

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    print(_bold("\n=== ReAct WebUI 模式 ==="))
    ensure_searxng(no_searxng)
    check_search()
    check_llm(llm_config)
    print(f"\n{_bold('启动 WebUI')}  →  http://{host}:{port}\n")
    _dist = SRC / "webui" / "static" / "dist" / "index.html"
    if not _dist.is_file():
        _warn(
            "前端未构建",
            f"未找到 {_dist.relative_to(ROOT)} — 请先执行: cd src/webui/frontend && npm ci && npm run build",
        )

    uvicorn.run("webui.app:app", host=host, port=port, reload=False, timeout_graceful_shutdown=30)


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
        help="LLM 配置文件路径（默认 config/llm_core/config.yaml）",
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
