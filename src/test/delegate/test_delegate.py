"""Tests for agent.profile and agent.runner: SubAgentConfig, SubAgentProfile, SubAgentResult."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

SRC = Path(__file__).resolve().parent.parent.parent
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import pytest
from agent.profile import SubAgentConfig, SubAgentProfile
from agent.result import SubAgentResult


class TestSubAgentProfile:
    def test_default_profile(self):
        p = SubAgentProfile()
        assert p.max_steps == 10
        assert p.tools is None
        assert p.system_note == ""

    def test_custom_profile(self):
        p = SubAgentProfile(max_steps=20, tools=["web_search"], system_note="你好")
        assert p.max_steps == 20
        assert p.tools == ["web_search"]
        assert p.system_note == "你好"


class TestSubAgentConfig:
    def test_default_profiles_exist(self):
        cfg = SubAgentConfig(llm_cfg_path="fake.yaml")
        assert "minimal" in cfg.profiles
        assert "executor" in cfg.profiles
        assert "researcher" in cfg.profiles
        assert "researcher_with_memory" in cfg.profiles
        assert "analyst" in cfg.profiles

    def test_minimal_profile_has_no_tools(self):
        cfg = SubAgentConfig(llm_cfg_path="fake.yaml")
        assert cfg.profiles["minimal"].tools is None

    def test_researcher_profile_has_tools(self):
        cfg = SubAgentConfig(llm_cfg_path="fake.yaml")
        researcher = cfg.profiles["researcher"]
        assert "web_search" in researcher.tools
        assert "web_fetch" in researcher.tools

    def test_analyst_profile_has_tools(self):
        cfg = SubAgentConfig(llm_cfg_path="fake.yaml")
        analyst = cfg.profiles["analyst"]
        assert "calculator" in analyst.tools

    def test_profile_lookup_returns_none_for_missing(self):
        cfg = SubAgentConfig(llm_cfg_path="fake.yaml")
        assert cfg.profiles.get("nonexistent") is None

    def test_custom_profiles(self):
        custom = SubAgentProfile(max_steps=5, system_note="custom")
        cfg = SubAgentConfig(llm_cfg_path="fake.yaml", profiles={"custom": custom})
        assert cfg.profiles["custom"].max_steps == 5


class TestSubAgentResult:
    def test_default_status(self):
        r = SubAgentResult(agent_id="abc")
        assert r.status == "running"
        assert r.answer == ""
        assert r.error == ""

    def test_done_result(self):
        r = SubAgentResult(agent_id="xyz", status="done", answer="hello")
        assert r.status == "done"
        assert r.answer == "hello"

    def test_failed_result(self):
        r = SubAgentResult(agent_id="xyz", status="failed", error="oops")
        assert r.status == "failed"
        assert r.error == "oops"


class TestSubAgentRunnerMocked:
    def test_run_sync_returns_dict_with_expected_keys(self):
        import sys
        from agent.runner import SubAgentRunner
        runner = SubAgentRunner()
        profile = SubAgentProfile(max_steps=5)

        mock_tao_instance = MagicMock()
        mock_tao_instance.stream.return_value = []

        mock_tao_mod = MagicMock()
        mock_tao_mod.TaoLoop.return_value = mock_tao_instance
        mock_tao_mod.FinishEvent = type("FinishEvent", (), {})
        mock_tao_mod.StepEvent = type("StepEvent", (), {})

        fake_modules = {
            "config.llm_core.config": MagicMock(),
            "config.agent.tao_config": MagicMock(),
            "config.agent.prompt_config": MagicMock(),
            "llm_core.llm": MagicMock(),
            "agent.react.action.manager": MagicMock(),
            "agent.react.tao": mock_tao_mod,
        }
        with patch.dict(sys.modules, fake_modules):
            result = runner.run_sync("do something", profile, "fake.yaml")

        assert isinstance(result, dict)
        assert "answer" in result
        assert "step_count" in result
        assert "steps_log" in result
        assert result["answer"] == ""
        assert result["step_count"] == 0
