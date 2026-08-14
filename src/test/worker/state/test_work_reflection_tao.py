from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[3]
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from config.agent.memory.medium_term_config import MediumTermMemoryConfig
from config.agent.memory.memory_config import MemoryConfig
from config.agent.tao_config import TaoConfig
from config.agent.trace_config import TraceConfig
from config.storage import StorageConfig
from worker.tools.executor import ActionExecutor
from worker.engine.tao import FinishEvent, TaoLoop
from worker.state.service import AgentStateService


class _TaoLLM:
    def __init__(self) -> None:
        self.stream_calls = 0
        self.prompts: list[list] = []
        self.reflection_calls = 0

    def stream_generate_messages(self, messages):
        self.prompts.append(messages)
        self.stream_calls += 1
        if self.stream_calls == 1:
            text = (
                "<T>先写入可验证的临时结果</T>"
                '<A>[{"action":"note_write","args":{"key":"evidence","content":"ok"}}]</A>'
                "<O></O>"
            )
        else:
            text = (
                "<T>工具结果已经验证</T>"
                '<A>[{"action":"finish","args":{"answer":"任务完成"}}]</A>'
                "<O>任务完成</O>"
            )
        yield text

    def generate_messages(self, messages):
        self.reflection_calls += 1
        return (
            "本轮先使用草稿工具保存了中间证据，并在下一步读取到成功结果后才结束，基本形成了动作与证据闭环。"
            "仍需改进的是完成标准只存在于隐含推理中，没有在首步明确写出，因此无法严格判断“任务完成”是否覆盖全部约束。"
            "下一轮应先声明可验证完成标准，每个工具动作后检查 result_summary 的成功、部分完成或失败状态；"
            "如果证据仅覆盖局部，应继续执行而不是提前 finish，交付前还要说明测试范围与剩余风险。"
            "对于并行动作，要逐项确认 observation 与调用数量一致，不能因其中一项成功就推断整组动作成功；"
            "只有任务图中的关键路径都有明确结果，才能形成最终答复。"
        )


def test_tao_injects_sidecar_and_updates_graph_between_steps(tmp_path: Path):
    llm = _TaoLLM()
    service = AgentStateService(state_dir=tmp_path / "state", llm=llm)
    cfg = TaoConfig(
        max_steps=3,
        storage=StorageConfig(root=str(tmp_path / "cache")),
        memory=MemoryConfig(
            medium_term=MediumTermMemoryConfig(enabled=False),
        ),
        trace=TraceConfig(enabled=False),
    )
    tao = TaoLoop(
        llm=llm,
        executor=ActionExecutor(),
        tool_descriptions={},
        cfg=cfg,
        agent_state_service=service,
    )

    answer = ""
    for event in tao.stream("完成一个可验证任务"):
        if isinstance(event, FinishEvent):
            answer = event.answer
    assert answer == "任务完成"

    first_system = str(llm.prompts[0][0].content)
    first_human = str(llm.prompts[0][-1].content)
    second_system = str(llm.prompts[1][0].content)
    assert "## Worker Portrait" in first_system
    assert "## Worker Reflection Portrait" in first_system
    assert "## 当前临场任务图" in first_system
    assert "完成一个可验证任务" in first_human
    assert "action=note_write" in second_system
    assert "result_summary=success" in second_system

    tao.post_process()
    assert llm.reflection_calls == 1
    assert service.snapshot().reflection_portrait.turn_count == 1
