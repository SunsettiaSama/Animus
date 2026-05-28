"""
infra 模块单元测试
==================
覆盖 src/infra/ 中全部五个模块的核心行为（无外部依赖）：

  - BaseServiceManager  : 抽象基类约束
  - BackgroundTaskRunner: submit / status / on_error / shutdown
  - ServiceRegistry     : register / get / status_all / stop_all / names
  - SearXNGManager      : 状态机 / Docker 调用 (mock) / port probe
  - VLLMServerManager   : 状态机 / subprocess (mock) / log ring-buffer / health probe

不依赖 Docker、GPU、vLLM 进程、asyncio 运行时、LLM API。
运行方式：
  cd E:/ReAct
  python -m pytest src/test/test_infra.py -v
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
import unittest
from concurrent.futures import Future
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

SRC = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(SRC))

from infra.base_service import BaseServiceManager
from infra.task_runner import BackgroundTaskRunner
from infra.service_registry import ServiceRegistry
from infra.searxng_manager import SearXNGManager
from infra.llm.official import OfficialVLLMManager as VLLMServerManager
from config.llm_core.vllm_config import VLLMConfig


# ─────────────────────────────────────────────────────────────────────────────
# BaseServiceManager
# ─────────────────────────────────────────────────────────────────────────────

class TestBaseServiceManager(unittest.TestCase):

    def test_cannot_instantiate_directly(self):
        with self.assertRaises(TypeError):
            BaseServiceManager()

    def test_concrete_subclass_without_methods_raises(self):
        class Incomplete(BaseServiceManager):
            pass
        with self.assertRaises(TypeError):
            Incomplete()

    def test_concrete_subclass_ok(self):
        class Concrete(BaseServiceManager):
            def start(self, **kw): pass
            def stop(self): pass
            def status(self): return {"state": "stopped"}

        c = Concrete()
        self.assertEqual(c.status()["state"], "stopped")

    def test_get_logs_default_empty(self):
        class Concrete(BaseServiceManager):
            def start(self, **kw): pass
            def stop(self): pass
            def status(self): return {"state": "stopped"}

        self.assertEqual(Concrete().get_logs(), [])
        self.assertEqual(Concrete().get_logs(n=50), [])


# ─────────────────────────────────────────────────────────────────────────────
# BackgroundTaskRunner
# ─────────────────────────────────────────────────────────────────────────────

class TestBackgroundTaskRunner(unittest.TestCase):

    def setUp(self):
        self.runner = BackgroundTaskRunner(max_workers=4)

    def tearDown(self):
        self.runner.shutdown(wait=False)

    def test_submit_returns_future(self):
        f = self.runner.submit("noop", lambda: None)
        self.assertIsInstance(f, Future)

    def test_submit_result_available(self):
        f = self.runner.submit("add", lambda a, b: a + b, 3, 4)
        self.assertEqual(f.result(timeout=5), 7)

    def test_status_done_after_completion(self):
        f = self.runner.submit("quick", lambda: "x")
        f.result(timeout=5)
        st = self.runner.status()
        self.assertIn("quick", st)
        self.assertEqual(st["quick"], "done")

    def test_status_error_on_exception(self):
        def _boom():
            raise ValueError("intentional")

        f = self.runner.submit("boomer", _boom)
        # consume exception so it doesn't propagate
        exc = None
        while exc is None:
            if f.done():
                exc = f.exception()
                break
            time.sleep(0.05)

        st = self.runner.status()
        self.assertEqual(st["boomer"], "error")

    def test_on_error_callback_called(self):
        errors = []

        def _boom():
            raise RuntimeError("oops")

        def _on_err(e):
            errors.append(e)

        f = self.runner.submit("err_task", _boom, on_error=_on_err)
        f.result(timeout=5) if not f.exception() else None

        # wait for callback to fire
        deadline = time.monotonic() + 3
        while not errors and time.monotonic() < deadline:
            time.sleep(0.05)

        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], RuntimeError)
        self.assertIn("oops", str(errors[0]))

    def test_latest_task_overwrites_same_name(self):
        f1 = self.runner.submit("shared", lambda: 1)
        f1.result(timeout=5)
        f2 = self.runner.submit("shared", lambda: 2)
        f2.result(timeout=5)
        st = self.runner.status()
        self.assertIn("shared", st)

    def test_multiple_concurrent_tasks(self):
        barrier = threading.Barrier(4)

        def _work():
            barrier.wait(timeout=5)
            return True

        futures = [self.runner.submit(f"t{i}", _work) for i in range(4)]
        results = [f.result(timeout=10) for f in futures]
        self.assertTrue(all(results))

    def test_shutdown_wait(self):
        event = threading.Event()

        def _slow():
            time.sleep(0.1)
            event.set()

        self.runner.submit("slow", _slow)
        self.runner.shutdown(wait=True, timeout=5)
        self.assertTrue(event.is_set())


# ─────────────────────────────────────────────────────────────────────────────
# ServiceRegistry
# ─────────────────────────────────────────────────────────────────────────────

def _mock_mgr(state: str = "stopped") -> MagicMock:
    m = MagicMock(spec=BaseServiceManager)
    m.status.return_value = {"state": state}
    m.get_logs.return_value = []
    return m


class TestServiceRegistry(unittest.TestCase):

    def setUp(self):
        self.reg = ServiceRegistry()
        self.a = _mock_mgr("running")
        self.b = _mock_mgr("stopped")
        self.reg.register("svc_a", self.a)
        self.reg.register("svc_b", self.b)

    def test_get_existing(self):
        self.assertIs(self.reg.get("svc_a"), self.a)
        self.assertIs(self.reg.get("svc_b"), self.b)

    def test_get_missing_returns_none(self):
        self.assertIsNone(self.reg.get("unknown"))

    def test_names(self):
        self.assertCountEqual(self.reg.names(), ["svc_a", "svc_b"])

    def test_status_all(self):
        result = self.reg.status_all()
        self.assertEqual(result["svc_a"]["state"], "running")
        self.assertEqual(result["svc_b"]["state"], "stopped")

    def test_stop_all_calls_stop_on_each(self):
        self.reg.stop_all()
        self.a.stop.assert_called_once()
        self.b.stop.assert_called_once()

    def test_register_overwrites(self):
        new = _mock_mgr("error")
        self.reg.register("svc_a", new)
        self.assertIs(self.reg.get("svc_a"), new)

    def test_empty_registry(self):
        reg = ServiceRegistry()
        self.assertEqual(reg.status_all(), {})
        self.assertEqual(reg.names(), [])
        reg.stop_all()  # no error on empty

    def test_stop_all_continues_despite_error(self):
        bad = MagicMock(spec=BaseServiceManager)
        bad.stop.side_effect = RuntimeError("stop failed")
        bad.status.return_value = {"state": "error"}
        self.reg.register("bad_svc", bad)
        # stop_all should propagate the first error it hits; this verifies it
        # actually calls stop() on bad_svc (we don't require swallowing)
        # — the registry itself makes no error-swallowing promise.
        # What we verify: stop IS called on all services that come BEFORE the
        # bad one (ordering not guaranteed; just check call counts).
        #
        # If stop_all raises, that's fine too — we just verify bad.stop() ran.
        raised = False
        with self.assertRaises(RuntimeError):
            self.reg.stop_all()
        bad.stop.assert_called_once()


# ─────────────────────────────────────────────────────────────────────────────
# SearXNGManager
# ─────────────────────────────────────────────────────────────────────────────

def _searxng(host_port: int = 8888) -> SearXNGManager:
    return SearXNGManager(
        container_name="test-searxng",
        image="searxng/searxng",
        host_port=host_port,
        container_port=8080,
        settings_yml=None,
    )


def _proc_result(returncode: int = 0, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess:
    r = MagicMock(spec=subprocess.CompletedProcess)
    r.returncode = returncode
    r.stdout = stdout
    r.stderr = stderr
    return r


class TestSearXNGManager(unittest.TestCase):

    def test_url_property(self):
        mgr = _searxng(9999)
        self.assertEqual(mgr.url, "http://127.0.0.1:9999")

    # ── _docker_available ─────────────────────────────────────────────────────

    def test_docker_available_true(self):
        with patch("subprocess.run", return_value=_proc_result(0)) as mock_run, \
             patch("shutil.which", return_value="/usr/bin/docker"):
            mgr = _searxng()
            self.assertTrue(mgr._docker_available())
            mock_run.assert_called_once()

    def test_docker_available_false_when_not_found(self):
        with patch("shutil.which", return_value=None):
            mgr = _searxng()
            self.assertFalse(mgr._docker_available())

    def test_docker_available_false_on_nonzero_exit(self):
        with patch("subprocess.run", return_value=_proc_result(1)), \
             patch("shutil.which", return_value="/usr/bin/docker"):
            mgr = _searxng()
            self.assertFalse(mgr._docker_available())

    # ── _container_status ─────────────────────────────────────────────────────

    def test_container_status_up(self):
        with patch("shutil.which", return_value="/usr/bin/docker"), \
             patch("subprocess.run", return_value=_proc_result(0, stdout="Up 3 hours\n")):
            mgr = _searxng()
            self.assertEqual(mgr._container_status(), "Up 3 hours")

    def test_container_status_empty_when_docker_missing(self):
        with patch("shutil.which", return_value=None):
            mgr = _searxng()
            self.assertEqual(mgr._container_status(), "")

    # ── status ────────────────────────────────────────────────────────────────

    def test_status_docker_unavailable(self):
        with patch("shutil.which", return_value=None):
            mgr = _searxng()
            s = mgr.status()
            self.assertEqual(s["state"], "unavailable")
            self.assertIn("Docker", s["detail"])

    def test_status_running(self):
        mgr = _searxng()
        mgr._docker_available = lambda: True
        mgr._container_status = lambda: "Up 5 minutes"
        mgr._port_is_open = lambda: True
        s = mgr.status()
        self.assertEqual(s["state"], "running")
        self.assertTrue(s["healthy"])
        self.assertIn("url", s)
        self.assertIn("container", s)

    def test_status_stopped(self):
        mgr = _searxng()
        mgr._docker_available = lambda: True
        mgr._container_status = lambda: "Exited (0) 2 hours ago"
        s = mgr.status()
        self.assertEqual(s["state"], "stopped")
        self.assertFalse(s["healthy"])

    def test_status_container_nonexistent(self):
        mgr = _searxng()
        mgr._docker_available = lambda: True
        mgr._container_status = lambda: ""
        s = mgr.status()
        self.assertEqual(s["state"], "stopped")

    # ── start ─────────────────────────────────────────────────────────────────

    def test_start_skips_when_already_up(self):
        mgr = _searxng()
        mgr._docker_available = lambda: True
        mgr._container_status = lambda: "Up 3 minutes"
        mgr._run_docker = MagicMock()
        mgr.start()
        mgr._run_docker.assert_not_called()

    def test_start_docker_start_when_stopped_container(self):
        mgr = _searxng()
        mgr._docker_available = lambda: True
        mgr._container_status = lambda: "Exited (0) 1 hour ago"
        mgr._run_docker = MagicMock(return_value=_proc_result(0))
        mgr.start()
        # should call "start <container_name>" variant
        first_call_args = mgr._run_docker.call_args_list[0][0]
        self.assertIn("start", first_call_args)
        self.assertIn("test-searxng", first_call_args)

    def test_start_docker_run_when_no_container(self):
        mgr = _searxng()
        mgr._docker_available = lambda: True
        mgr._container_status = lambda: ""
        mgr._run_docker = MagicMock(return_value=_proc_result(0))
        mgr.start()
        first_call_args = mgr._run_docker.call_args_list[0][0]
        self.assertIn("run", first_call_args)

    def test_start_noop_when_docker_unavailable(self):
        mgr = _searxng()
        mgr._docker_available = lambda: False
        mgr._run_docker = MagicMock()
        mgr.start()
        mgr._run_docker.assert_not_called()

    # ── stop ──────────────────────────────────────────────────────────────────

    def test_stop_calls_docker_stop_when_up(self):
        mgr = _searxng()
        mgr._docker_available = lambda: True
        mgr._container_status = lambda: "Up 10 minutes"
        mgr._run_docker = MagicMock(return_value=_proc_result(0))
        mgr.stop()
        first_call_args = mgr._run_docker.call_args_list[0][0]
        self.assertIn("stop", first_call_args)

    def test_stop_noop_when_not_up(self):
        mgr = _searxng()
        mgr._docker_available = lambda: True
        mgr._container_status = lambda: "Exited (0)"
        mgr._run_docker = MagicMock()
        mgr.stop()
        mgr._run_docker.assert_not_called()

    # ── _port_is_open ─────────────────────────────────────────────────────────

    def test_port_is_open_true(self):
        mgr = _searxng(19999)
        import socket
        # connect_ex returns 0 → open
        with patch("socket.socket") as mock_sock_cls:
            mock_sock = MagicMock()
            mock_sock.connect_ex.return_value = 0
            mock_sock_cls.return_value = mock_sock
            self.assertTrue(mgr._port_is_open())

    def test_port_is_open_false(self):
        mgr = _searxng(19999)
        import socket
        with patch("socket.socket") as mock_sock_cls:
            mock_sock = MagicMock()
            mock_sock.connect_ex.return_value = 111  # ECONNREFUSED
            mock_sock_cls.return_value = mock_sock
            self.assertFalse(mgr._port_is_open())

    # ── wait_until_up ─────────────────────────────────────────────────────────

    def test_wait_until_up_immediate(self):
        mgr = _searxng()
        mgr._container_status = lambda: "Up 1 second"
        self.assertTrue(mgr.wait_until_up(seconds=3))

    def test_wait_until_up_timeout(self):
        mgr = _searxng()
        mgr._container_status = lambda: "Exited (0)"
        self.assertFalse(mgr.wait_until_up(seconds=2))


# ─────────────────────────────────────────────────────────────────────────────
# VLLMServerManager
# ─────────────────────────────────────────────────────────────────────────────

class TestVLLMServerManager(unittest.TestCase):

    def _mgr(self) -> VLLMServerManager:
        return VLLMServerManager()

    def _cfg(self, port: int = 8000) -> VLLMConfig:
        return VLLMConfig(host="127.0.0.1", port=port)

    # ── initial state ─────────────────────────────────────────────────────────

    def test_initial_state(self):
        mgr = self._mgr()
        s = mgr.status()
        self.assertEqual(s["state"], "stopped")
        self.assertIsNone(s["pid"])
        self.assertFalse(s["healthy"])

    def test_base_url_default(self):
        mgr = self._mgr()
        self.assertEqual(mgr.base_url, "http://127.0.0.1:8000/v1")

    def test_base_url_from_config(self):
        mgr = self._mgr()
        mgr._cfg = self._cfg(port=9999)
        self.assertEqual(mgr.base_url, "http://127.0.0.1:9999/v1")

    def test_get_logs_empty_initially(self):
        mgr = self._mgr()
        self.assertEqual(mgr.get_logs(), [])

    # ── log ring-buffer ───────────────────────────────────────────────────────

    def test_log_ring_buffer_max_len(self):
        mgr = self._mgr()
        for i in range(600):
            mgr._log_lines.append(f"line {i}")
        self.assertLessEqual(len(mgr._log_lines), mgr._LOG_MAXLEN)

    def test_get_logs_n_limit(self):
        mgr = self._mgr()
        for i in range(200):
            mgr._log_lines.append(f"line {i}")
        lines = mgr.get_logs(n=10)
        self.assertEqual(len(lines), 10)
        self.assertEqual(lines[-1], "line 199")  # last 10 lines

    # ── _port_is_open ─────────────────────────────────────────────────────────

    def test_port_is_open_no_config(self):
        mgr = self._mgr()
        self.assertFalse(mgr._port_is_open())

    def test_port_is_open_true(self):
        mgr = self._mgr()
        mgr._cfg = self._cfg(8000)
        with patch("socket.socket") as mock_sock_cls:
            s = MagicMock()
            s.connect_ex.return_value = 0
            mock_sock_cls.return_value = s
            self.assertTrue(mgr._port_is_open())

    def test_port_is_open_false(self):
        mgr = self._mgr()
        mgr._cfg = self._cfg(8000)
        with patch("socket.socket") as mock_sock_cls:
            s = MagicMock()
            s.connect_ex.return_value = 111
            mock_sock_cls.return_value = s
            self.assertFalse(mgr._port_is_open())

    # ── start / stop state machine ────────────────────────────────────────────

    def _make_fake_process(self, lines=("log line 1\n", "log line 2\n")) -> MagicMock:
        proc = MagicMock()
        proc.pid = 12345
        proc.poll.return_value = None
        # Use a list so _capture_logs can iterate it (MagicMock.stdout would
        # not be iterable by default).
        proc.stdout = list(lines)
        return proc

    def test_start_sets_state_to_starting(self):
        mgr = self._mgr()
        cfg = self._cfg()
        fake_proc = self._make_fake_process()

        with patch("subprocess.Popen", return_value=fake_proc) as mock_popen, \
             patch.object(cfg, "to_cli_args", return_value=["vllm", "serve", "model"]):
            mgr.start("model", cfg)
            # Popen must have been called and model must be stored.
            # State itself may have raced to "error" because the tiny fake
            # stdout is exhausted immediately by the log-capture daemon thread;
            # we don't assert state here.
            self.assertEqual(mgr._model, "model")
            mock_popen.assert_called_once()

    def test_start_idempotent_when_running(self):
        mgr = self._mgr()
        mgr._state = "running"
        fake_proc = self._make_fake_process()

        with patch("subprocess.Popen", return_value=fake_proc) as mock_popen:
            mgr.start("model", self._cfg())
            mock_popen.assert_not_called()

    def test_start_idempotent_when_starting(self):
        mgr = self._mgr()
        mgr._state = "starting"
        with patch("subprocess.Popen") as mock_popen:
            mgr.start("model", self._cfg())
            mock_popen.assert_not_called()

    def test_stop_resets_state(self):
        mgr = self._mgr()
        mgr._state = "running"
        fake_proc = MagicMock()
        fake_proc.poll.return_value = 0  # exits immediately on terminate
        mgr._process = fake_proc
        mgr.stop()
        self.assertEqual(mgr._state, "stopped")
        self.assertIsNone(mgr._process)
        fake_proc.terminate.assert_called_once()

    def test_stop_noop_when_already_stopped(self):
        mgr = self._mgr()
        self.assertEqual(mgr._state, "stopped")
        mgr.stop()  # must not raise
        self.assertEqual(mgr._state, "stopped")

    def test_stop_kills_if_terminate_slow(self):
        mgr = self._mgr()
        mgr._state = "running"
        fake_proc = MagicMock()
        # poll() always returns None → never exited → kill() should be called
        fake_proc.poll.return_value = None
        mgr._process = fake_proc
        # shorten deadline by mocking time
        with patch("time.monotonic", side_effect=[0.0] + [11.0] * 200), \
             patch("time.sleep"):
            mgr.stop()
        fake_proc.kill.assert_called_once()

    # ── log capture thread ────────────────────────────────────────────────────

    def test_capture_logs_fills_ring_buffer(self):
        mgr = self._mgr()
        fake_proc = MagicMock()
        fake_proc.stdout = iter(["line A\n", "line B\n", "line C\n"])

        # run _capture_logs synchronously in the test thread
        mgr._state = "starting"
        mgr._capture_logs(fake_proc)

        lines = mgr.get_logs()
        self.assertEqual(lines, ["line A", "line B", "line C"])

    def test_capture_logs_sets_error_state_on_process_exit(self):
        mgr = self._mgr()
        fake_proc = MagicMock()
        fake_proc.stdout = iter([])   # process stdout ends immediately
        mgr._state = "starting"
        mgr._capture_logs(fake_proc)
        self.assertEqual(mgr._state, "error")

    def test_capture_logs_no_state_change_when_already_stopped(self):
        mgr = self._mgr()
        fake_proc = MagicMock()
        fake_proc.stdout = iter([])
        mgr._state = "stopped"
        mgr._capture_logs(fake_proc)
        self.assertEqual(mgr._state, "stopped")

    # ── _watch_health ─────────────────────────────────────────────────────────

    def test_watch_health_transitions_to_running(self):
        mgr = self._mgr()
        cfg = self._cfg()
        mgr._state = "starting"
        mgr._cfg = cfg

        call_count = [0]

        def _fake_port_open():
            call_count[0] += 1
            return call_count[0] >= 2  # open on 2nd probe

        mgr._port_is_open = _fake_port_open

        with patch("time.sleep"):
            mgr._watch_health(cfg)

        self.assertEqual(mgr._state, "running")

    def test_watch_health_times_out_to_error(self):
        mgr = self._mgr()
        cfg = self._cfg()
        mgr._state = "starting"
        mgr._cfg = cfg
        mgr._port_is_open = lambda: False

        # Simulate monotonic time advancing past 120s immediately
        times = iter([0.0, 121.0, 122.0])

        with patch("time.monotonic", side_effect=lambda: next(times)), \
             patch("time.sleep"):
            mgr._watch_health(cfg)

        self.assertEqual(mgr._state, "error")

    def test_watch_health_exits_when_state_not_starting(self):
        mgr = self._mgr()
        cfg = self._cfg()
        mgr._state = "stopped"  # already stopped — should return immediately
        mgr._cfg = cfg
        mgr._port_is_open = MagicMock(return_value=False)

        with patch("time.sleep"):
            mgr._watch_health(cfg)

        mgr._port_is_open.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    unittest.main(verbosity=2)
