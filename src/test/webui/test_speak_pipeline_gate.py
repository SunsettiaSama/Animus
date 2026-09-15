from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

# routers 以 `from state import get_state` 顶层导入 webui/state——与
# webui/app.py 启动序一致，需先把 src/webui 加进 sys.path。
WEBUI_DIR = Path(__file__).resolve().parents[2] / "webui"
if str(WEBUI_DIR) not in sys.path:
    sys.path.insert(0, str(WEBUI_DIR))

from webui.routers import agent as agent_router  # noqa: E402
from webui.routers import speak as speak_router  # noqa: E402
from webui.speak_pipeline_gate import pipeline_reject_reason  # noqa: E402


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(agent_router.router)
    app.include_router(speak_router.router)
    return app


def _session_open(pipeline: str) -> dict:
    return {
        "type": "session_open",
        "session_id": "live:test",
        "channel_id": "live:test",
        "gen_id": "g1",
        "pipeline": pipeline,
    }


def test_gate_helper_accepts_only_request_driven():
    assert pipeline_reject_reason("request_driven") == ""
    assert "request_driven" in pipeline_reject_reason("react")
    assert "request_driven" in pipeline_reject_reason("")


def test_agent_run_rejects_illegal_pipeline_before_soul():
    # 收敛门在 soul 解析之前：无 soul 的测试环境也应先收到 pipeline 拒绝。
    client = TestClient(_app())
    with client.websocket_connect("/ws/agent/run") as ws:
        ws.send_json(_session_open("react"))
        msg = ws.receive_json()
        assert msg["type"] == "error"
        assert "unsupported pipeline" in msg["message"]
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()


def test_agent_run_legal_pipeline_passes_gate():
    # 合法 pipeline 越过收敛门，到达下一道必然的 Soul 检查——证明门未误伤。
    client = TestClient(_app())
    with client.websocket_connect("/ws/agent/run") as ws:
        ws.send_json(_session_open("request_driven"))
        msg = ws.receive_json()
        assert msg["type"] == "error"
        assert "unsupported pipeline" not in msg["message"]


def test_speak_run_rejects_illegal_pipeline():
    client = TestClient(_app())
    with client.websocket_connect("/ws/speak/run") as ws:
        ws.send_json(_session_open("chat"))
        msg = ws.receive_json()
        assert msg["type"] == "error"
        assert "unsupported pipeline" in msg["message"]
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()
