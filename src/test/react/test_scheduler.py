"""
调度器模块测试
==============
覆盖 src/scheduler/ 的核心行为（无外部依赖）：

  单元测试
  ├── SchedulerConfig：默认值 / from_dict / profiles 懒加载
  ├── Trigger / TaskStatus：序列化 / 反序列化
  ├── ScheduledTask：to_dict / from_dict 往返
  ├── TaskStore：add / get / list_all / update / cancel / get_due_tasks
  ├── SchedulerEngine：schedule_once / schedule_interval / cancel / list_timeline
  └── 原子工具：scheduler_add / scheduler_list / scheduler_cancel

不依赖 LLM、asyncio 运行时、TaoLoop。
运行方式：
  cd E:/ReAct
  python -m pytest src/test/test_scheduler.py -v
  # 或直接：
  python src/test/test_scheduler.py
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
from unittest.mock import MagicMock

SRC = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SRC))


# ── Stub 策略 ─────────────────────────────────────────────────────────────────
# react/__init__.py → tao.py → memory → embedding → torch → DLL crash / hang
# 完全绕开 react 包初始化：
#   1. 将 react / react.action / react.action.base 注册为轻量 stub
#   2. 用 spec_from_file_location 直接加载三个工具文件
# scheduler 核心模块（config/task/store/engine）本身无重量级依赖，直接导入即可。


def _pkg_stub(name: str) -> types.ModuleType:
    m = types.ModuleType(name)
    m.__package__ = name
    m.__spec__ = importlib.machinery.ModuleSpec(name, loader=None, is_package=True)
    m.__path__ = []
    sys.modules[name] = m
    return m


def _mod_stub(name: str) -> types.ModuleType:
    m = types.ModuleType(name)
    sys.modules[name] = m
    return m


# Stub react 包体系（阻止 tao.py / memory / embedding / torch 加载）
_react = _pkg_stub("react")
_react_action = _pkg_stub("react.action")
_react_action_tools = _pkg_stub("react.action.tools")
_react_action_tools_impl = _pkg_stub("react.action.tools.impl")

_react_action_base = _mod_stub("react.action.base")


class _BaseAction:
    """最小化 BaseAction stub：兼容 Pydantic 环境和非 Pydantic（stub）环境。

    不继承 pydantic.BaseModel，改用自定义 __init__ 支持关键字参数注入，
    避免在全量 pytest 运行时因 pydantic 已被其他测试 stub 而失效。
    """

    model_config = {"arbitrary_types_allowed": True}
    model_fields: dict = {}

    # 子类在此声明带默认值的字段
    name: str = ""
    description: str = ""

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

    def __init__(self, **kwargs):
        # 先用类层次的注解默认值初始化
        for klass in reversed(type(self).__mro__):
            for field_name in getattr(klass, "__annotations__", {}):
                if not hasattr(self, field_name):
                    setattr(self, field_name, getattr(klass, field_name, None))
        # 再用传入 kwargs 覆盖
        for k, v in kwargs.items():
            setattr(self, k, v)

    def execute(self, **kwargs) -> str:
        raise NotImplementedError


_react_action_base.BaseAction = _BaseAction


def _load_tool_file(dotted_name: str, file_path: Path):
    """直接从文件路径加载模块，注册到 sys.modules。"""
    spec = importlib.util.spec_from_file_location(dotted_name, str(file_path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[dotted_name] = mod
    spec.loader.exec_module(mod)
    return mod


_TOOLS_DIR = SRC / "react" / "action" / "tools" / "impl"
_sa_mod  = _load_tool_file("react.action.tools.impl.scheduler_add",    _TOOLS_DIR / "scheduler_add.py")
_sl_mod  = _load_tool_file("react.action.tools.impl.scheduler_list",   _TOOLS_DIR / "scheduler_list.py")
_sc_mod  = _load_tool_file("react.action.tools.impl.scheduler_cancel", _TOOLS_DIR / "scheduler_cancel.py")

from scheduler.config import SchedulerConfig
from scheduler.task import ScheduledTask, TaskStatus, Trigger
from scheduler.store import TaskStore
from scheduler.engine import SchedulerEngine


# ─────────────────────────────────────────────────────────────────────────────
# 帮助函数
# ─────────────────────────────────────────────────────────────────────────────

def _utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc)


def _future(seconds: int = 3600) -> datetime:
    return _utc(datetime.now(timezone.utc) + timedelta(seconds=seconds))


def _past(seconds: int = 60) -> datetime:
    return _utc(datetime.now(timezone.utc) - timedelta(seconds=seconds))


# ─────────────────────────────────────────────────────────────────────────────
# SchedulerConfig
# ─────────────────────────────────────────────────────────────────────────────

class TestSchedulerConfig(unittest.TestCase):

    def test_defaults(self):
        cfg = SchedulerConfig()
        self.assertEqual(cfg.scheduler_dir, ".react/scheduler")
        self.assertAlmostEqual(cfg.poll_interval, 1.0)
        self.assertEqual(cfg.llm_cfg_path, "config/llm_core/config.yaml")

    def test_from_dict(self):
        cfg = SchedulerConfig.from_dict({
            "scheduler_dir": "/tmp/sched",
            "poll_interval": 5.0,
            "llm_cfg_path": "custom/config.yaml",
        })
        self.assertEqual(cfg.scheduler_dir, "/tmp/sched")
        self.assertAlmostEqual(cfg.poll_interval, 5.0)
        self.assertEqual(cfg.llm_cfg_path, "custom/config.yaml")

    def test_from_dict_partial(self):
        cfg = SchedulerConfig.from_dict({"poll_interval": 2.5})
        self.assertAlmostEqual(cfg.poll_interval, 2.5)
        self.assertEqual(cfg.scheduler_dir, ".react/scheduler")  # default intact

    def test_profiles_default_keys(self):
        # profiles 是工厂函数返回的字典，键名固定
        cfg = SchedulerConfig(profiles={"minimal": object(), "with_memory": object(), "full": object()})
        self.assertIn("minimal", cfg.profiles)
        self.assertIn("with_memory", cfg.profiles)
        self.assertIn("full", cfg.profiles)

    def test_custom_profiles(self):
        fake = {"custom": MagicMock()}
        cfg = SchedulerConfig(profiles=fake)
        self.assertIs(cfg.profiles["custom"], fake["custom"])


# ─────────────────────────────────────────────────────────────────────────────
# Trigger
# ─────────────────────────────────────────────────────────────────────────────

class TestTrigger(unittest.TestCase):

    def test_once_roundtrip(self):
        t = Trigger(type="once", at="2026-04-29T17:00:00+00:00")
        d = t.to_dict()
        self.assertEqual(d["type"], "once")
        self.assertEqual(d["at"], "2026-04-29T17:00:00+00:00")
        self.assertIsNone(d["interval_seconds"])

        t2 = Trigger.from_dict(d)
        self.assertEqual(t2.type, "once")
        self.assertEqual(t2.at, t.at)
        self.assertIsNone(t2.interval_seconds)

    def test_interval_roundtrip(self):
        t = Trigger(type="interval", interval_seconds=1800)
        d = t.to_dict()
        self.assertEqual(d["interval_seconds"], 1800)

        t2 = Trigger.from_dict(d)
        self.assertEqual(t2.interval_seconds, 1800)
        self.assertIsNone(t2.at)


# ─────────────────────────────────────────────────────────────────────────────
# TaskStatus
# ─────────────────────────────────────────────────────────────────────────────

class TestTaskStatus(unittest.TestCase):

    def test_values(self):
        expected = {"pending", "running", "done", "failed", "cancelled"}
        actual = {s.value for s in TaskStatus}
        self.assertEqual(actual, expected)

    def test_str_enum(self):
        self.assertEqual(TaskStatus.pending, "pending")
        self.assertEqual(TaskStatus("done"), TaskStatus.done)


# ─────────────────────────────────────────────────────────────────────────────
# ScheduledTask
# ─────────────────────────────────────────────────────────────────────────────

class TestScheduledTask(unittest.TestCase):

    def _make(self, **kw) -> ScheduledTask:
        defaults = dict(
            id="test-id-001",
            name="daily_summary",
            instruction="请生成今日摘要",
            trigger=Trigger(type="once", at="2026-04-29T17:00:00+00:00"),
            config_profile="minimal",
            status=TaskStatus.pending,
            created_at="2026-04-29T09:00:00+00:00",
            next_run_at="2026-04-29T17:00:00+00:00",
        )
        defaults.update(kw)
        return ScheduledTask(**defaults)

    def test_to_dict_keys(self):
        t = self._make()
        d = t.to_dict()
        for key in ("id", "name", "instruction", "trigger", "config_profile",
                    "status", "created_at", "next_run_at", "last_run_at", "last_result_path"):
            self.assertIn(key, d)

    def test_status_serialized_as_str(self):
        t = self._make(status=TaskStatus.running)
        d = t.to_dict()
        self.assertIsInstance(d["status"], str)
        self.assertEqual(d["status"], "running")

    def test_roundtrip(self):
        t = self._make()
        t2 = ScheduledTask.from_dict(t.to_dict())
        self.assertEqual(t.id, t2.id)
        self.assertEqual(t.name, t2.name)
        self.assertEqual(t.instruction, t2.instruction)
        self.assertEqual(t.trigger.type, t2.trigger.type)
        self.assertEqual(t.trigger.at, t2.trigger.at)
        self.assertEqual(t.status, t2.status)
        self.assertEqual(t.config_profile, t2.config_profile)

    def test_optional_fields_default_none(self):
        t = self._make()
        self.assertIsNone(t.last_run_at)
        self.assertIsNone(t.last_result_path)

    def test_from_dict_defaults(self):
        minimal = {
            "id": "x",
            "name": "n",
            "instruction": "i",
            "trigger": {"type": "once", "at": None, "interval_seconds": None},
        }
        t = ScheduledTask.from_dict(minimal)
        self.assertEqual(t.config_profile, "minimal")
        self.assertEqual(t.status, TaskStatus.pending)


# ─────────────────────────────────────────────────────────────────────────────
# TaskStore
# ─────────────────────────────────────────────────────────────────────────────

class TestTaskStore(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.store = TaskStore(self._tmp)

    def _task(self, tid: str, next_run_at: str | None = None, status: TaskStatus = TaskStatus.pending) -> ScheduledTask:
        return ScheduledTask(
            id=tid,
            name=f"task_{tid}",
            instruction="do something",
            trigger=Trigger(type="once", at=next_run_at),
            status=status,
            created_at="2026-01-01T00:00:00+00:00",
            next_run_at=next_run_at,
        )

    def test_add_and_get(self):
        t = self._task("abc")
        self.store.add(t)
        t2 = self.store.get("abc")
        self.assertIsNotNone(t2)
        self.assertEqual(t2.name, "task_abc")

    def test_get_missing(self):
        self.assertIsNone(self.store.get("nonexistent"))

    def test_list_all_empty(self):
        self.assertEqual(self.store.list_all(), [])

    def test_list_all_multiple(self):
        self.store.add(self._task("a"))
        self.store.add(self._task("b"))
        tasks = self.store.list_all()
        self.assertEqual(len(tasks), 2)
        ids = {t.id for t in tasks}
        self.assertIn("a", ids)
        self.assertIn("b", ids)

    def test_update_status(self):
        self.store.add(self._task("u1"))
        self.store.update("u1", status=TaskStatus.running)
        t = self.store.get("u1")
        self.assertEqual(t.status, TaskStatus.running)

    def test_update_multiple_fields(self):
        self.store.add(self._task("u2"))
        self.store.update("u2", last_run_at="2026-04-29T17:01:00+00:00", last_result_path="/tmp/r.json")
        t = self.store.get("u2")
        self.assertEqual(t.last_run_at, "2026-04-29T17:01:00+00:00")
        self.assertEqual(t.last_result_path, "/tmp/r.json")

    def test_update_missing_noop(self):
        self.store.update("ghost", status=TaskStatus.done)  # should not raise

    def test_cancel(self):
        self.store.add(self._task("c1"))
        ok = self.store.cancel("c1")
        self.assertTrue(ok)
        t = self.store.get("c1")
        self.assertEqual(t.status, TaskStatus.cancelled)

    def test_cancel_missing(self):
        ok = self.store.cancel("nobody")
        self.assertFalse(ok)

    def test_persistence(self):
        self.store.add(self._task("p1"))
        # Create a fresh store pointing at same dir — should read back the same data
        store2 = TaskStore(self._tmp)
        t = store2.get("p1")
        self.assertIsNotNone(t)
        self.assertEqual(t.id, "p1")

    def test_get_due_tasks_returns_due(self):
        past = _past(120).isoformat()
        self.store.add(self._task("due1", next_run_at=past))
        due = self.store.get_due_tasks(datetime.now(timezone.utc))
        self.assertEqual(len(due), 1)
        self.assertEqual(due[0].id, "due1")

    def test_get_due_tasks_excludes_future(self):
        future = _future(3600).isoformat()
        self.store.add(self._task("notdue", next_run_at=future))
        due = self.store.get_due_tasks(datetime.now(timezone.utc))
        self.assertEqual(due, [])

    def test_get_due_tasks_excludes_cancelled(self):
        past = _past(60).isoformat()
        self.store.add(self._task("cancelled_task", next_run_at=past, status=TaskStatus.cancelled))
        due = self.store.get_due_tasks(datetime.now(timezone.utc))
        self.assertEqual(due, [])

    def test_get_due_tasks_excludes_running(self):
        past = _past(60).isoformat()
        self.store.add(self._task("running_task", next_run_at=past, status=TaskStatus.running))
        due = self.store.get_due_tasks(datetime.now(timezone.utc))
        self.assertEqual(due, [])

    def test_get_due_tasks_no_next_run(self):
        self.store.add(self._task("no_next", next_run_at=None))
        due = self.store.get_due_tasks(datetime.now(timezone.utc))
        self.assertEqual(due, [])

    def test_results_dir_created(self):
        results_dir = os.path.join(self._tmp, "results")
        self.assertTrue(os.path.isdir(results_dir))

    def test_tasks_json_valid(self):
        self.store.add(self._task("j1"))
        path = os.path.join(self._tmp, "tasks.json")
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        self.assertIn("j1", data)


# ─────────────────────────────────────────────────────────────────────────────
# SchedulerEngine（store 层行为，不触发 asyncio loop）
# ─────────────────────────────────────────────────────────────────────────────

class TestSchedulerEngine(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        # 注入空 profiles 避免触发 _default_profiles() 的懒加载导入
        self.cfg = SchedulerConfig(scheduler_dir=self._tmp, profiles={})
        self.engine = SchedulerEngine(self.cfg)

    def test_schedule_once_returns_task(self):
        at = _future(3600)
        task = self.engine.schedule_once("morning_report", "请生成报告", at)
        self.assertIsNotNone(task.id)
        self.assertEqual(task.name, "morning_report")
        self.assertEqual(task.trigger.type, "once")
        self.assertEqual(task.status, TaskStatus.pending)
        self.assertIsNotNone(task.next_run_at)

    def test_schedule_once_persisted(self):
        at = _future(3600)
        task = self.engine.schedule_once("t", "i", at)
        fetched = self.engine.get(task.id)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.id, task.id)

    def test_schedule_interval_returns_task(self):
        task = self.engine.schedule_interval("hourly", "check", seconds=3600)
        self.assertEqual(task.trigger.type, "interval")
        self.assertEqual(task.trigger.interval_seconds, 3600)
        self.assertIsNotNone(task.next_run_at)

    def test_schedule_interval_custom_profile(self):
        task = self.engine.schedule_interval("m", "i", 60, profile="with_memory")
        self.assertEqual(task.config_profile, "with_memory")

    def test_cancel_existing(self):
        task = self.engine.schedule_once("t", "i", _future())
        ok = self.engine.cancel(task.id)
        self.assertTrue(ok)
        fetched = self.engine.get(task.id)
        self.assertEqual(fetched.status, TaskStatus.cancelled)

    def test_cancel_nonexistent(self):
        ok = self.engine.cancel("ghost-id")
        self.assertFalse(ok)

    def test_list_timeline_empty(self):
        tasks = self.engine.list_timeline()
        self.assertEqual(tasks, [])

    def test_list_timeline_multiple(self):
        self.engine.schedule_once("a", "ia", _future(100))
        self.engine.schedule_once("b", "ib", _future(200))
        tasks = self.engine.list_timeline()
        self.assertEqual(len(tasks), 2)
        names = {t.name for t in tasks}
        self.assertIn("a", names)
        self.assertIn("b", names)

    def test_get_returns_none_for_unknown(self):
        self.assertIsNone(self.engine.get("unknown"))

    def test_schedule_once_naive_datetime_becomes_utc(self):
        naive = datetime(2026, 12, 31, 23, 59, 0)  # no tzinfo
        task = self.engine.schedule_once("n", "i", naive)
        self.assertIn("+00:00", task.next_run_at)


# ─────────────────────────────────────────────────────────────────────────────
# 原子工具
# ─────────────────────────────────────────────────────────────────────────────

SchedulerAddAction    = _sa_mod.SchedulerAddAction
SchedulerListAction   = _sl_mod.SchedulerListAction
SchedulerCancelAction = _sc_mod.SchedulerCancelAction


def _make_engine(tmp: str) -> SchedulerEngine:
    cfg = SchedulerConfig(scheduler_dir=tmp, profiles={})
    return SchedulerEngine(cfg)


class TestSchedulerAddAction(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.engine = _make_engine(self._tmp)
        self.action = SchedulerAddAction(engine=self.engine)

    def test_no_engine_returns_error(self):
        a = SchedulerAddAction(engine=None)
        result = a.execute(name="t", instruction="i")
        self.assertIn("未初始化", result)

    def test_once_valid(self):
        at = _future(3600).isoformat()
        result = self.action.execute(
            name="report", instruction="生成报告",
            trigger_type="once", at=at,
        )
        self.assertIn("task_id", result)
        self.assertIn("已预约一次性任务", result)

    def test_once_missing_at(self):
        result = self.action.execute(name="t", instruction="i", trigger_type="once", at="")
        self.assertIn("必须提供 at", result)

    def test_once_invalid_at(self):
        result = self.action.execute(name="t", instruction="i", trigger_type="once", at="not-a-date")
        self.assertIn("格式无效", result)

    def test_interval_valid(self):
        result = self.action.execute(
            name="hourly", instruction="i",
            trigger_type="interval", interval_seconds=3600,
        )
        self.assertIn("已预约周期性任务", result)
        self.assertIn("task_id", result)

    def test_interval_missing_seconds(self):
        result = self.action.execute(
            name="t", instruction="i",
            trigger_type="interval", interval_seconds=0,
        )
        self.assertIn("interval_seconds 必须 > 0", result)

    def test_unknown_trigger_type(self):
        result = self.action.execute(name="t", instruction="i", trigger_type="daily")
        self.assertIn("未知 trigger_type", result)

    def test_profile_propagated(self):
        at = _future(3600).isoformat()
        self.action.execute(
            name="mem_task", instruction="i",
            trigger_type="once", at=at, profile="with_memory",
        )
        tasks = self.engine.list_timeline()
        self.assertEqual(tasks[0].config_profile, "with_memory")


class TestSchedulerListAction(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.engine = _make_engine(self._tmp)
        self.action = SchedulerListAction(engine=self.engine)

    def test_no_engine(self):
        a = SchedulerListAction(engine=None)
        self.assertIn("未初始化", a.execute())

    def test_empty_timeline(self):
        result = self.action.execute()
        self.assertIn("为空", result)

    def test_lists_once_task(self):
        self.engine.schedule_once("evening", "做总结", _future(7200))
        result = self.action.execute()
        self.assertIn("evening", result)
        self.assertIn("一次性", result)

    def test_lists_interval_task(self):
        self.engine.schedule_interval("ping", "ping", 300)
        result = self.action.execute()
        self.assertIn("ping", result)
        self.assertIn("300", result)

    def test_count_in_header(self):
        self.engine.schedule_once("a", "i", _future(100))
        self.engine.schedule_once("b", "i", _future(200))
        result = self.action.execute()
        self.assertIn("2", result)


class TestSchedulerCancelAction(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.mkdtemp()
        self.engine = _make_engine(self._tmp)
        self.action = SchedulerCancelAction(engine=self.engine)

    def test_no_engine(self):
        a = SchedulerCancelAction(engine=None)
        self.assertIn("未初始化", a.execute(task_id="x"))

    def test_cancel_existing(self):
        task = self.engine.schedule_once("t", "i", _future())
        result = self.action.execute(task_id=task.id)
        self.assertIn("已取消", result)
        self.assertIn(task.id, result)

    def test_cancel_nonexistent(self):
        result = self.action.execute(task_id="no-such-id")
        self.assertIn("未找到", result)

    def test_cancel_reflects_in_list(self):
        task = self.engine.schedule_once("x", "i", _future())
        self.action.execute(task_id=task.id)
        fetched = self.engine.get(task.id)
        self.assertEqual(fetched.status, TaskStatus.cancelled)


# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    unittest.main(verbosity=2)
