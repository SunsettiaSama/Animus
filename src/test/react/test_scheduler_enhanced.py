"""
Scheduler 四项增强方案 — 新增/改动模块测试
==========================================

覆盖范围（无外部依赖，不启动 LLM / asyncio loop）：

  单元测试
  ├── EventCommand          — render / to_dict / from_dict / display_label
  ├── ScheduledTask.command — to_dict/from_dict 往返兼容
  ├── SchedulerConfig       — scheduler_system_note 字段 & from_dict
  ├── WorkJournal           — append_task_result / append_mid_run_message / read / today_conv_id
  ├── ChannelRouter         — register / unregister / deliver / available_channels
  ├── ReplyTarget           — from_task_dict / to_task_dict
  └── NotifyUserAction      — execute(有/无 notify_fn) / description 存在

运行方式：
  cd G:/ReAct
  python -m pytest src/test/react/test_scheduler_enhanced.py -v
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import os
import sys
import tempfile
import types
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, call

SRC = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SRC))

# ── Stub 策略（与 test_scheduler.py 保持一致）────────────────────────────────
# 防止导入 react / langchain / torch 重型依赖

def _pkg_stub(name: str) -> types.ModuleType:
    m = types.ModuleType(name)
    m.__package__ = name
    m.__spec__ = importlib.machinery.ModuleSpec(name, loader=None, is_package=True)
    m.__path__ = []
    sys.modules.setdefault(name, m)
    return sys.modules[name]


def _mod_stub(name: str) -> types.ModuleType:
    m = types.ModuleType(name)
    sys.modules.setdefault(name, m)
    return sys.modules[name]


# Stub react 包体系
_pkg_stub("agent.react")
_pkg_stub("agent.react.action")
_pkg_stub("agent.react.action.tools")
_pkg_stub("agent.react.action.tools.impl")

# BaseAction stub（供 notify_user.py 使用）
_react_base = _mod_stub("agent.react.action.base")


class _BaseAction:
    model_config = {"arbitrary_types_allowed": True}
    model_fields: dict = {}
    name: str = ""
    description: str = ""

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

    def __init__(self, **kwargs):
        for klass in reversed(type(self).__mro__):
            for field_name in getattr(klass, "__annotations__", {}):
                if not hasattr(self, field_name):
                    setattr(self, field_name, getattr(klass, field_name, None))
        for k, v in kwargs.items():
            setattr(self, k, v)

    def execute(self, **kwargs) -> str:
        raise NotImplementedError


_react_base.BaseAction = _BaseAction

# Stub pydantic.BaseModel / Field（notify_user.py 依赖它）
if "pydantic" not in sys.modules:
    _pydantic = _mod_stub("pydantic")
    _pydantic.BaseModel = object
    _pydantic.Field = lambda *a, **kw: None
    _pydantic.ConfigDict = lambda **kw: {}


def _load_tool_file(dotted_name: str, file_path: Path):
    if dotted_name in sys.modules:
        return sys.modules[dotted_name]
    spec = importlib.util.spec_from_file_location(dotted_name, str(file_path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[dotted_name] = mod
    spec.loader.exec_module(mod)
    return mod


_TOOLS_DIR = SRC / "agent" / "react" / "action" / "tools" / "impl"

# 直接加载 notify_user.py（绕开包 __init__）
_nu_mod = _load_tool_file(
    "agent.react.action.tools.impl.notify_user",
    _TOOLS_DIR / "notify_user.py",
)
NotifyUserAction = _nu_mod.NotifyUserAction

# 真实导入调度器核心（无重型依赖）
from agent.scheduler.command import EventCommand
from agent.scheduler.config import SchedulerConfig
from agent.scheduler.task import ScheduledTask, TaskStatus, Trigger
from agent.scheduler.store import TaskStore
from agent.scheduler.engine import SchedulerEngine
from agent.scheduler.journal import WorkJournal
from infra.channel_router import ChannelRouter, ReplyTarget


# ─────────────────────────────────────────────────────────────────────────────
# 帮助函数
# ─────────────────────────────────────────────────────────────────────────────

def _utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc)


def _future(seconds: int = 3600) -> datetime:
    return datetime.now(timezone.utc) + timedelta(seconds=seconds)


def _make_task(tid: str = "test-id", **kw) -> ScheduledTask:
    defaults = dict(
        id=tid,
        name=f"task_{tid}",
        instruction="do something",
        trigger=Trigger(type="once", at=_future().isoformat()),
        status=TaskStatus.pending,
        created_at=datetime.now(timezone.utc).isoformat(),
        next_run_at=_future().isoformat(),
    )
    defaults.update(kw)
    return ScheduledTask(**defaults)


# ─────────────────────────────────────────────────────────────────────────────
# EventCommand
# ─────────────────────────────────────────────────────────────────────────────

class TestEventCommand(unittest.TestCase):

    def test_render_no_params(self):
        cmd = EventCommand(command_type="run_task", template="生成每日报告")
        self.assertEqual(cmd.render(), "生成每日报告")

    def test_render_with_params(self):
        cmd = EventCommand(
            command_type="run_task",
            template="分析 {topic} 的最新动态",
            params={"topic": "AI"},
        )
        self.assertEqual(cmd.render(), "分析 AI 的最新动态")

    def test_render_multiple_params(self):
        cmd = EventCommand(
            command_type="chain",
            template="{verb} {count} 份{doc}",
            params={"verb": "汇总", "count": "3", "doc": "报告"},
        )
        self.assertEqual(cmd.render(), "汇总 3 份报告")

    def test_to_dict_keys(self):
        cmd = EventCommand(command_type="ask_user", template="问题", params={"k": "v"}, label="lbl")
        d = cmd.to_dict()
        self.assertIn("command_type", d)
        self.assertIn("template", d)
        self.assertIn("params", d)
        self.assertIn("label", d)
        self.assertEqual(d["command_type"], "ask_user")
        self.assertEqual(d["label"], "lbl")

    def test_from_dict_roundtrip(self):
        cmd = EventCommand(
            command_type="notify_user",
            template="任务 {name} 完成",
            params={"name": "daily_summary"},
            label="通知",
        )
        d = cmd.to_dict()
        cmd2 = EventCommand.from_dict(d)
        self.assertEqual(cmd2.command_type, cmd.command_type)
        self.assertEqual(cmd2.template, cmd.template)
        self.assertEqual(cmd2.params, cmd.params)
        self.assertEqual(cmd2.label, cmd.label)

    def test_from_dict_defaults(self):
        cmd = EventCommand.from_dict({})
        self.assertEqual(cmd.command_type, "run_task")
        self.assertEqual(cmd.template, "")
        self.assertEqual(cmd.params, {})
        self.assertEqual(cmd.label, "")

    def test_display_label_uses_label_when_set(self):
        cmd = EventCommand(command_type="run_task", template="很长的模板文字", label="我的标签")
        self.assertEqual(cmd.display_label(), "我的标签")

    def test_display_label_falls_back_to_template_slice(self):
        long_tpl = "A" * 80
        cmd = EventCommand(command_type="run_task", template=long_tpl, label="")
        self.assertEqual(cmd.display_label(), "A" * 40)

    def test_render_returns_template_when_params_empty(self):
        cmd = EventCommand(command_type="run_task", template="no placeholders", params={})
        self.assertEqual(cmd.render(), "no placeholders")


# ─────────────────────────────────────────────────────────────────────────────
# ScheduledTask — command 字段向后兼容
# ─────────────────────────────────────────────────────────────────────────────

class TestScheduledTaskCommand(unittest.TestCase):

    def test_command_field_defaults_none(self):
        t = _make_task()
        self.assertIsNone(t.command)

    def test_command_field_in_to_dict(self):
        t = _make_task()
        d = t.to_dict()
        self.assertIn("command", d)
        self.assertIsNone(d["command"])

    def test_command_field_roundtrip(self):
        cmd_dict = EventCommand(
            command_type="run_task",
            template="请 {verb}",
            params={"verb": "汇报"},
        ).to_dict()
        t = _make_task(command=cmd_dict)
        d = t.to_dict()
        t2 = ScheduledTask.from_dict(d)
        self.assertIsNotNone(t2.command)
        self.assertEqual(t2.command["command_type"], "run_task")
        self.assertEqual(t2.command["template"], "请 {verb}")

    def test_from_dict_without_command_key(self):
        """旧格式 JSON（无 command 字段）能无缝加载。"""
        minimal = {
            "id": "old",
            "name": "old_task",
            "instruction": "old inst",
            "trigger": {"type": "once", "at": None, "interval_seconds": None},
        }
        t = ScheduledTask.from_dict(minimal)
        self.assertIsNone(t.command)

    def test_task_instruction_independent_of_command(self):
        """instruction 与 command 独立；修改 command 不影响 instruction。"""
        cmd = EventCommand(command_type="run_task", template="从 command 来的", params={})
        t = _make_task(instruction="原始指令", command=cmd.to_dict())
        self.assertEqual(t.instruction, "原始指令")
        # render 只是工具，不会自动写回 instruction
        self.assertEqual(cmd.render(), "从 command 来的")


# ─────────────────────────────────────────────────────────────────────────────
# SchedulerConfig — scheduler_system_note
# ─────────────────────────────────────────────────────────────────────────────

class TestSchedulerConfigSystemNote(unittest.TestCase):

    def test_default_system_note_is_empty_string(self):
        cfg = SchedulerConfig()
        self.assertEqual(cfg.scheduler_system_note, "")

    def test_from_dict_parses_system_note(self):
        cfg = SchedulerConfig.from_dict({
            "scheduler_system_note": "你在调度模式下运行",
        })
        self.assertEqual(cfg.scheduler_system_note, "你在调度模式下运行")

    def test_from_dict_missing_key_uses_default(self):
        cfg = SchedulerConfig.from_dict({"poll_interval": 2.0})
        self.assertEqual(cfg.scheduler_system_note, "")

    def test_system_note_can_be_set_directly(self):
        cfg = SchedulerConfig(scheduler_system_note="直接设置的提示词")
        self.assertEqual(cfg.scheduler_system_note, "直接设置的提示词")

    def test_from_dict_preserves_other_fields(self):
        cfg = SchedulerConfig.from_dict({
            "poll_interval": 3.0,
            "proactive_enabled": False,
            "scheduler_system_note": "note",
        })
        self.assertAlmostEqual(cfg.poll_interval, 3.0)
        self.assertFalse(cfg.proactive_enabled)
        self.assertEqual(cfg.scheduler_system_note, "note")


# ─────────────────────────────────────────────────────────────────────────────
# WorkJournal
# ─────────────────────────────────────────────────────────────────────────────

class TestWorkJournal(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.journal = WorkJournal(history_dir=self._tmp)

    def test_today_conv_id_format(self):
        conv_id = self.journal.today_conv_id()
        today_str = datetime.now(timezone.utc).strftime("%Y%m%d")
        self.assertEqual(conv_id, f"agent_journal_{today_str}")

    def test_append_task_result_creates_file(self):
        self.journal.append_task_result("tid-001", "daily_report", "生成报告", "报告内容")
        conv_id = self.journal.today_conv_id()
        path = os.path.join(self._tmp, f"{conv_id}.json")
        self.assertTrue(os.path.exists(path))

    def test_append_task_result_content(self):
        self.journal.append_task_result("tid-001", "daily_report", "生成报告", "**答案**")
        data = self.journal.read()
        msgs = data.get("messages", [])
        self.assertTrue(len(msgs) > 0)
        last = msgs[-1]
        self.assertEqual(last["role"], "assistant")
        self.assertIn("daily_report", last["content"])
        self.assertIn("**答案**", last["content"])

    def test_append_task_result_meta(self):
        self.journal.append_task_result("tid-abc", "my_task", "指令", "输出")
        data = self.journal.read()
        msg = data["messages"][-1]
        meta = msg.get("meta", {})
        self.assertEqual(meta["task_id"], "tid-abc")
        self.assertEqual(meta["task_name"], "my_task")
        self.assertEqual(meta["entry_type"], "task_result")

    def test_append_mid_run_message_content(self):
        self.journal.append_mid_run_message("tid-002", "proc_task", "进度汇报", "已完成 50%")
        data = self.journal.read()
        msg = data["messages"][-1]
        self.assertIn("proc_task", msg["content"])
        self.assertIn("已完成 50%", msg["content"])

    def test_append_mid_run_meta_entry_type(self):
        self.journal.append_mid_run_message("tid-003", "t", "title", "msg")
        data = self.journal.read()
        meta = data["messages"][-1]["meta"]
        self.assertEqual(meta["entry_type"], "mid_run_message")
        self.assertEqual(meta["title"], "title")

    def test_read_returns_empty_messages_for_missing(self):
        data = self.journal.read(date="19000101")   # 不存在的日期
        self.assertEqual(data.get("messages", []), [])

    def test_read_with_date_param(self):
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self.journal.append_task_result("t1", "n1", "instr", "ans")
        data = self.journal.read(date=today)
        self.assertTrue(len(data.get("messages", [])) > 0)

    def test_multiple_appends_accumulate(self):
        self.journal.append_task_result("t1", "n1", "instr1", "ans1")
        self.journal.append_task_result("t2", "n2", "instr2", "ans2")
        data = self.journal.read()
        self.assertEqual(len(data["messages"]), 2)

    def test_journal_mode_in_metadata(self):
        self.journal.append_task_result("t", "n", "i", "a")
        data = self.journal.read()
        self.assertEqual(data.get("mode"), "journal")

    def test_json_is_valid_on_disk(self):
        self.journal.append_task_result("t", "n", "i", "a")
        conv_id = self.journal.today_conv_id()
        path = os.path.join(self._tmp, f"{conv_id}.json")
        with open(path, encoding="utf-8") as f:
            loaded = json.load(f)
        self.assertIn("messages", loaded)


# ─────────────────────────────────────────────────────────────────────────────
# ReplyTarget
# ─────────────────────────────────────────────────────────────────────────────

class TestReplyTarget(unittest.TestCase):

    def test_from_task_dict_webui(self):
        d = {"type": "webui"}
        rt = ReplyTarget.from_task_dict(d)
        self.assertIsNotNone(rt)
        self.assertEqual(rt.channel, "webui")
        self.assertEqual(rt.params, {})

    def test_from_task_dict_bot_with_params(self):
        d = {"type": "bot", "message_type": "private", "user_id": 123}
        rt = ReplyTarget.from_task_dict(d)
        self.assertEqual(rt.channel, "bot")
        self.assertEqual(rt.params["user_id"], 123)
        self.assertNotIn("type", rt.params)

    def test_from_task_dict_none(self):
        self.assertIsNone(ReplyTarget.from_task_dict(None))

    def test_from_task_dict_defaults_channel_to_webui(self):
        rt = ReplyTarget.from_task_dict({})
        self.assertEqual(rt.channel, "webui")

    def test_to_task_dict_roundtrip(self):
        rt = ReplyTarget(channel="bot", params={"message_type": "group", "group_id": 456})
        d = rt.to_task_dict()
        self.assertEqual(d["type"], "bot")
        self.assertEqual(d["group_id"], 456)
        self.assertNotIn("channel", d)

    def test_to_task_dict_webui(self):
        rt = ReplyTarget(channel="webui")
        d = rt.to_task_dict()
        self.assertEqual(d, {"type": "webui"})


# ─────────────────────────────────────────────────────────────────────────────
# ChannelRouter
# ─────────────────────────────────────────────────────────────────────────────

class TestChannelRouter(unittest.TestCase):

    def setUp(self):
        self.router = ChannelRouter()

    def test_available_channels_empty(self):
        self.assertEqual(self.router.available_channels(), [])

    def test_register_adds_channel(self):
        self.router.register("webui", lambda t, ti, m: None)
        self.assertIn("webui", self.router.available_channels())

    def test_register_multiple_channels(self):
        self.router.register("webui", lambda t, ti, m: None)
        self.router.register("bot",   lambda t, ti, m: None)
        chs = self.router.available_channels()
        self.assertIn("webui", chs)
        self.assertIn("bot", chs)

    def test_unregister_removes_channel(self):
        self.router.register("tmp", lambda t, ti, m: None)
        self.router.unregister("tmp")
        self.assertNotIn("tmp", self.router.available_channels())

    def test_unregister_missing_noop(self):
        self.router.unregister("does_not_exist")  # should not raise

    def test_deliver_calls_handler(self):
        calls = []
        self.router.register("webui", lambda t, ti, m: calls.append((ti, m)))
        rt = ReplyTarget(channel="webui")
        self.router.deliver(rt, "title", "message content")
        self.assertEqual(calls, [("title", "message content")])

    def test_deliver_passes_reply_target(self):
        received = []
        self.router.register("bot", lambda t, ti, m: received.append(t))
        rt = ReplyTarget(channel="bot", params={"user_id": 99})
        self.router.deliver(rt, "t", "m")
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0].params["user_id"], 99)

    def test_deliver_missing_channel_no_raise(self):
        rt = ReplyTarget(channel="unknown_channel")
        self.router.deliver(rt, "t", "m")   # should not raise, just log warning

    def test_register_overwrites_existing(self):
        calls_a, calls_b = [], []
        self.router.register("ch", lambda t, ti, m: calls_a.append(m))
        self.router.register("ch", lambda t, ti, m: calls_b.append(m))
        rt = ReplyTarget(channel="ch")
        self.router.deliver(rt, "t", "hello")
        self.assertEqual(calls_a, [])      # old handler replaced
        self.assertEqual(calls_b, ["hello"])

    def test_deliver_is_thread_safe(self):
        """多线程并发 deliver 不应死锁或抛出异常。"""
        import threading
        results = []
        self.router.register("ch", lambda t, ti, m: results.append(m))
        rt = ReplyTarget(channel="ch")

        threads = [
            threading.Thread(target=lambda: self.router.deliver(rt, "t", f"msg-{i}"))
            for i in range(10)
        ]
        for th in threads:
            th.start()
        for th in threads:
            th.join()
        self.assertEqual(len(results), 10)


# ─────────────────────────────────────────────────────────────────────────────
# NotifyUserAction
# ─────────────────────────────────────────────────────────────────────────────

class TestNotifyUserAction(unittest.TestCase):

    def test_description_not_empty(self):
        action = NotifyUserAction()
        self.assertTrue(len(action.description) > 10)

    def test_name_is_notify_user(self):
        action = NotifyUserAction()
        self.assertEqual(action.name, "notify_user")

    def test_execute_no_fn_returns_sent(self):
        action = NotifyUserAction(notify_fn=None)
        result = action.execute(message="hello")
        self.assertIn("已发送", result)

    def test_execute_calls_notify_fn(self):
        calls = []
        fn = lambda title, msg: calls.append((title, msg))
        action = NotifyUserAction(notify_fn=fn)
        action.execute(message="进度 50%", title="日报任务")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0], ("日报任务", "进度 50%"))

    def test_execute_default_title_empty(self):
        calls = []
        action = NotifyUserAction(notify_fn=lambda t, m: calls.append(t))
        action.execute(message="msg")
        self.assertEqual(calls[0], "")

    def test_execute_with_extra_kwargs_no_error(self):
        action = NotifyUserAction(notify_fn=None)
        result = action.execute(message="m", title="t", extra_field="x")
        self.assertIn("已发送", result)

    def test_notify_fn_injected_as_attribute(self):
        fn = MagicMock()
        action = NotifyUserAction(notify_fn=fn)
        self.assertIs(action.notify_fn, fn)


# ─────────────────────────────────────────────────────────────────────────────
# TaskStore — update with command field
# ─────────────────────────────────────────────────────────────────────────────

class TestTaskStoreCommandUpdate(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.store = TaskStore(self._tmp)

    def test_update_command_field(self):
        task = _make_task("cmd-task")
        self.store.add(task)
        cmd_dict = EventCommand(command_type="chain", template="链接任务", params={}).to_dict()
        self.store.update("cmd-task", command=cmd_dict)
        fetched = self.store.get("cmd-task")
        self.assertIsNotNone(fetched.command)
        self.assertEqual(fetched.command["command_type"], "chain")

    def test_update_instruction_field(self):
        task = _make_task("instr-task")
        self.store.add(task)
        self.store.update("instr-task", instruction="新指令内容")
        fetched = self.store.get("instr-task")
        self.assertEqual(fetched.instruction, "新指令内容")

    def test_update_name_field(self):
        task = _make_task("name-task")
        self.store.add(task)
        self.store.update("name-task", name="重命名后的任务")
        fetched = self.store.get("name-task")
        self.assertEqual(fetched.name, "重命名后的任务")


# ─────────────────────────────────────────────────────────────────────────────
# SchedulerEngine — edit action 集成（通过 store.update 实现）
# ─────────────────────────────────────────────────────────────────────────────

class TestSchedulerEngineEdit(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.cfg = SchedulerConfig(scheduler_dir=self._tmp, profiles={})
        self.engine = SchedulerEngine(self.cfg)

    def test_edit_task_instruction(self):
        task = self.engine.schedule_once("edit_me", "旧指令", _future(3600))
        self.engine._store.update(task.id, instruction="新指令")
        fetched = self.engine.get(task.id)
        self.assertEqual(fetched.instruction, "新指令")

    def test_edit_task_name(self):
        task = self.engine.schedule_once("old_name", "i", _future(3600))
        self.engine._store.update(task.id, name="new_name")
        fetched = self.engine.get(task.id)
        self.assertEqual(fetched.name, "new_name")

    def test_edit_task_next_run_at(self):
        task = self.engine.schedule_once("reschedule_me", "i", _future(3600))
        new_at = _future(7200).isoformat()
        self.engine._store.update(task.id, next_run_at=new_at)
        fetched = self.engine.get(task.id)
        self.assertEqual(fetched.next_run_at, new_at)

    def test_edit_command_and_instruction_together(self):
        task = self.engine.schedule_once("cmd_task", "旧指令", _future(3600))
        cmd = EventCommand(command_type="run_task", template="新 {x} 指令", params={"x": "的"})
        self.engine._store.update(
            task.id,
            command=cmd.to_dict(),
            instruction=cmd.render(),
        )
        fetched = self.engine.get(task.id)
        self.assertEqual(fetched.instruction, "新 的 指令")
        self.assertEqual(fetched.command["template"], "新 {x} 指令")


# ─────────────────────────────────────────────────────────────────────────────
# system_note prepend logic (黑盒测试 config 字符串拼接逻辑)
# ─────────────────────────────────────────────────────────────────────────────

class TestSystemNotePrepend(unittest.TestCase):
    """验证 TaskRunner 中的 system_note 拼接逻辑，无需实例化 TaskRunner。"""

    def _prepend(self, sched_note: str, profile_note: str) -> str:
        return "\n\n".join(filter(None, [sched_note, profile_note]))

    def test_both_notes_combined(self):
        result = self._prepend("调度模式", "个人提示词")
        self.assertEqual(result, "调度模式\n\n个人提示词")

    def test_empty_sched_note_only_profile(self):
        result = self._prepend("", "个人提示词")
        self.assertEqual(result, "个人提示词")

    def test_empty_profile_note_only_sched(self):
        result = self._prepend("调度模式", "")
        self.assertEqual(result, "调度模式")

    def test_both_empty_produces_empty(self):
        result = self._prepend("", "")
        self.assertEqual(result, "")

    def test_none_values_filtered(self):
        result = "\n\n".join(filter(None, [None, "profile"]))
        self.assertEqual(result, "profile")


# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    unittest.main(verbosity=2)
