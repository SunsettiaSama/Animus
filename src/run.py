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
    print(f"\n{_bold(_cyan(f'-- {title}'))}")


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
        _warn("SearXNG", "skipped (--no-searxng)")
        return

    mgr = _make_searxng_manager()

    if not mgr._docker_available():
        _warn("Docker", "daemon is unavailable or not installed")
        _warn("SearXNG", "SearchEngine will fall back to Tavily / DDG")
        return

    raw = mgr._container_status()

    if raw.startswith("Up"):
        _ok("SearXNG container", f"already running -> {mgr.url}")
        return

    if raw:
        _warn("SearXNG container", f"status: {raw} -> restarting")
    else:
        _warn("SearXNG container", "creating container; pulling image may take several minutes")
        if paths.searxng_settings_yml.exists():
            _ok("SearXNG config", f"mounting {paths.searxng_settings_yml.name}")
        else:
            _warn("SearXNG config", "settings.yml not found; using image defaults")

    mgr.start()

    _warn("SearXNG container", "waiting for service readiness")
    if mgr.wait_until_up():
        _ok("SearXNG container", f"running -> {mgr.url}")
    else:
        _fail("SearXNG container", "timeout: container did not reach Up state; check docker logs react-searxng")


# ═════════════════════════════════════════════════════════════════════════════
#  各组件检查
# ═════════════════════════════════════════════════════════════════════════════

def check_search() -> str:
    _section("Search backend")
    from infra.network.search.engine import SearchEngine
    engine = SearchEngine()
    name = engine.active_backend_name
    _ok("Search backend", f"active = {name!r}")
    return name


def check_llm(config_path: Path):
    _section("LLM config")
    from config.llm_core.config import LLMConfig
    if not config_path.exists():
        _warn("LLM config file", f"not found: {config_path}")
        _warn("Hint", "configure the model manually in WebUI after startup")
        return None
    cfg = LLMConfig.from_yaml(str(config_path))
    if not cfg.model:
        _warn("LLM config", "model is empty; configure it manually in WebUI after startup")
        return cfg
    _ok("LLM config", f"model={cfg.model!r}  base_url={cfg.base_url or '(default)'}")
    return cfg


# ═════════════════════════════════════════════════════════════════════════════
#  TaoLoop 构建（CLI 模式使用）
# ═════════════════════════════════════════════════════════════════════════════

def _build_tao(llm_cfg) -> object:
    _section("TaoLoop init")
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
    from config.agent.persona_config import PersonaConfig
    persona = PersonaConfig()
    db_cfg = None
    if persona.enabled:
        from config.infra.db_config import DBConfig
        db_cfg = DBConfig.load_default()
    cfg        = TaoConfig(storage=storage, memory=memory, persona=persona, db=db_cfg)
    llm        = LLM(llm_cfg)
    manager    = ToolManager()
    executor   = manager.build_executor()
    tool_descs = manager.primary_descriptions()
    cat_summary = manager.category_summary()
    tao        = TaoLoop(llm=llm, executor=executor, tool_descriptions=tool_descs, cfg=cfg, tool_category_summary=cat_summary)
    _ok("TaoLoop", f"tools={len(tool_descs)}  max_steps={cfg.max_steps}")
    return tao


# ═════════════════════════════════════════════════════════════════════════════
#  启动模式
# ═════════════════════════════════════════════════════════════════════════════

def run_check(llm_config: Path, no_searxng: bool) -> None:
    print(_bold("\n=== ReAct Service Check ==="))
    ensure_searxng(no_searxng)
    check_search()
    check_llm(llm_config)
    print(f"\n{_green('Check complete.')}\n")


def run_cli(llm_config: Path, no_searxng: bool) -> None:
    print(_bold("\n=== ReAct CLI Mode ==="))
    ensure_searxng(no_searxng)
    check_search()
    cfg = check_llm(llm_config)

    if cfg is None or not cfg.model:
        raise RuntimeError(
            "CLI mode requires a valid LLM config with a non-empty model.\n"
            f"Check: {llm_config}"
        )

    tao = _build_tao(cfg)
    print(f"\n{_bold('Chat started')}  type exit to quit\n")

    while True:
        question = input(_cyan("> ")).strip()
        if not question:
            continue
        if question.lower() in ("exit", "quit", "q"):
            print("Goodbye.")
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

    print(_bold("\n=== ReAct WebUI Mode ==="))
    ensure_searxng(no_searxng)
    check_search()
    check_llm(llm_config)
    print(f"\n{_bold('Starting WebUI')} -> http://{host}:{port}\n")
    _index = SRC / "webui" / "index.html"
    _static = SRC / "webui" / "static"
    if not _index.is_file():
        _warn(
            "WebUI entry missing",
            f"not found: {_index.relative_to(ROOT)}",
        )
    if not _static.is_dir():
        _warn("WebUI static assets missing", f"not found: {_static.relative_to(ROOT)}")

    # Import the current WebUI app object in-process so CLI args can configure
    # the same AppState singleton used by app startup and routers.
    from webui import app as webui_app_module
    from state import get_state

    state = get_state()
    state.llm_config_yaml = str(llm_config)

    uvicorn.run(
        webui_app_module.app,
        host=host,
        port=port,
        reload=False,
        timeout_graceful_shutdown=30,
    )


# ═════════════════════════════════════════════════════════════════════════════
#  CLI 参数解析 & 入口
# ═════════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="run.py",
        description="ReAct Agent unified launcher",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python src/run.py                      # start WebUI and manage SearXNG\n"
            "  python src/run.py --mode cli           # interactive CLI\n"
            "  python src/run.py --check              # check service status only\n"
            "  python src/run.py --no-searxng         # skip Docker/SearXNG\n"
            "  python src/run.py --mode webui --host 127.0.0.1 --port 8300\n"
        ),
    )
    parser.add_argument(
        "--mode", choices=["webui", "cli"], default="webui",
        help="startup mode (default: webui)",
    )
    parser.add_argument("--host", default=_run_cfg.webui.host,
                        help="WebUI listen address (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=_run_cfg.webui.port,
                        help="WebUI listen port (default: 8300)")
    parser.add_argument(
        "--llm-config", type=Path, default=_DEFAULT_LLM_CONFIG,
        dest="llm_config", metavar="PATH",
        help="LLM config path (default: config/llm_core/config.yaml)",
    )
    parser.add_argument(
        "--no-searxng", action="store_true", dest="no_searxng",
        help="skip SearXNG Docker container management",
    )
    parser.add_argument(
        "--check", action="store_true",
        help="check config and service status without starting processes",
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
