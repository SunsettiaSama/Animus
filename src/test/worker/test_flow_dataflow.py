from __future__ import annotations

from worker.flow.cluster.document import PlanDocument, PlanModule, PlanTask
from worker.flow.cluster.executor import build_task_instruction
from worker.flow.cluster.patch import HumanPatch, PatchOp, PlanDiff
from worker.tools.manager import ToolManager


def _document() -> PlanDocument:
    return PlanDocument(
        plan_id="test",
        title="Dataflow",
        objective="WRITE AN ENGLISH STORY IN ALL CAPITAL LETTERS.",
        modules=[
            PlanModule(
                name="main",
                tasks=[
                    PlanTask(
                        task_id="draft",
                        description="Draft the story.",
                        module="main",
                        result="- WAN WAN ENTERED THE PALACE.",
                    ),
                    PlanTask(
                        task_id="finalize",
                        description="Return the final story.",
                        module="main",
                        depends_on=["draft"],
                    ),
                ],
            )
        ],
    )


def test_task_instruction_contains_objective_and_dependency_results() -> None:
    doc = _document()

    instruction = build_task_instruction(doc.get_task("finalize"), doc)

    assert doc.objective in instruction
    assert "WAN WAN ENTERED THE PALACE" in instruction
    assert "Return the final story." in instruction


def test_add_task_patch_uses_top_level_task_id() -> None:
    doc = _document()
    patch = HumanPatch(
        op=PatchOp.add_task,
        task_id="repair_story",
        payload={
            "description": "Repair the story.",
            "module": "main",
            "depends_on": ["draft"],
        },
    )

    created = PlanDiff.apply(doc, [patch])

    assert created[0].task_id == "repair_story"
    assert doc.get_task("repair_story").description == "Repair the story."


def test_explicit_empty_tool_list_disables_tool_search() -> None:
    manager = ToolManager()

    descriptions = manager.primary_descriptions([])
    executor = manager.build_executor(
        allowed_actions=list(descriptions)
    )

    assert descriptions == {}
    assert executor.available_actions == []
    assert "未被当前配置允许" in executor.run(
        '{"action": "web_search", "args": {"query": "Wan Wan"}}'
    )
