"""speak 对话 pipeline 收敛门。

合法值：`request_driven`（默认，三角色编排：导演/编剧/角色）与 `direct`
（直通旁路：帧内零前置 LLM，用户直达角色）。两个对话 WS
（`/ws/agent/run`、`/ws/speak/run`）共用本门：session_open 违规即断连，
会话中途违规拒绝该字段（连接保留，pipeline 维持原值）。
"""
from __future__ import annotations

LEGAL_PIPELINES = frozenset({"request_driven", "direct"})


def pipeline_reject_reason(pipeline: str) -> str:
    """合法返回空串；非法返回拒绝原因（用作 WS error 帧的 message）。"""
    value = str(pipeline).strip()
    if value in LEGAL_PIPELINES:
        return ""
    return f"unsupported pipeline: {value!r} (only {'/'.join(sorted(LEGAL_PIPELINES))})"
