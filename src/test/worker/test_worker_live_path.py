"""Live Worker path wires sandbox + RiskGate."""
from __future__ import annotations

from pathlib import Path

from config.agent.risk_config import RiskConfig
from infra.sandbox import SandboxManager
from worker.tools.risk.gate import RiskGate
from worker.work.adapter import WorkerAdapter, WorkerAdapterConfig
from worker.work.service import WorkerWorkService


def test_work_service_bind_runtime_and_adapter_receive_sandbox_risk(tmp_path: Path):
    sandbox = SandboxManager()
    sandbox._cfg.workspace_root = str(tmp_path / "ws")
    sandbox.start()
    gate = RiskGate.from_config(RiskConfig())
    svc = WorkerWorkService(llm_cfg_path="config/llm_core/config.yaml")
    svc.bind_runtime(sandbox=sandbox, risk_gate=gate)
    assert svc._sandbox is sandbox
    assert svc._risk_gate is gate

    adapter = WorkerAdapter(WorkerAdapterConfig(llm_cfg_path="config/llm_core/config.yaml"))
    adapter.bind_runtime(sandbox=sandbox, risk_gate=gate)
    assert adapter._sandbox is sandbox
    assert adapter._risk_gate is gate


def test_sandbox_exec_shell_echo(tmp_path: Path):
    sandbox = SandboxManager()
    sandbox._cfg.workspace_root = str(tmp_path / "ws")
    sandbox.start()
    # Prefer powershell on Windows; fall back to cmd.
    import shutil

    if shutil.which("powershell") or shutil.which("pwsh"):
        out = sandbox.exec_shell("powershell", "Write-Output 'ok'", timeout_secs=15)
        assert "ok" in out
    elif shutil.which("cmd") or shutil.which("cmd.exe"):
        out = sandbox.exec_shell("cmd", "echo ok", timeout_secs=15)
        assert "ok" in out.lower()
    else:
        raise RuntimeError("no shell available for sandbox exec test")
