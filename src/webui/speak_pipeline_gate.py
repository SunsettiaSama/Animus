"""speak 对话 pipeline 收敛门（single-stream 需求 R3 / 开放问题 2）。

对话 pipeline 对外唯一合法值 `request_driven`。两个对话 WS
（`/ws/agent/run`、`/ws/speak/run`）共用本门：session_open 违规即断连，
会话中途违规拒绝该字段（连接保留，pipeline 维持原值）。
"""
from __future__ import annotations

LEGAL_PIPELINES = frozenset({"request_driven"})


def pipeline_reject_reason(pipeline: str) -> str:
    """合法返回空串；非法返回拒绝原因（用作 WS error 帧的 message）。"""
    value = str(pipeline).strip()
    if value in LEGAL_PIPELINES:
        return ""
    return f"unsupported pipeline: {value!r} (only request_driven)"
