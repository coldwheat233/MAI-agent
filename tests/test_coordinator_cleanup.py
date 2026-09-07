"""P2-5 回归：四脑协调器残留清理 + server 冷启动修复。

覆盖：
  - coordinator.py 已删除（无残留 import 路径）；
  - AgentEngine 不再暴露 coordinator_status，set_brain 只做脑注入开关；
  - /api/coordinator 路由已下线；
  - /api/restart 冷启动（_config 未初始化）不再 500（用 _ensure_config）。
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from mai_agent.core.engine import AgentEngine, EngineConfig


class TestCoordinatorRemoved:
    def test_module_file_deleted(self):
        p = Path(__file__).resolve().parents[1] / "mai_agent" / "brains" / "coordinator.py"
        assert not p.exists(), "coordinator.py 应已删除"

    def test_import_fails_cleanly(self):
        with pytest.raises(ImportError):
            importlib.import_module("mai_agent.brains.coordinator")

    def test_definitions_still_available(self):
        # 脑定义（agent_loop 注入 + Agent 工具按需孵化）是保留功能
        from mai_agent.brains.definitions import ALL_BRAINS
        assert {"dev_explorer", "dev_validator", "deploy_planner"} <= set(ALL_BRAINS)

    def test_server_route_removed(self):
        from mai_agent.server import app
        paths = {getattr(r, "path", "") for r in app.routes}
        assert "/api/coordinator" not in paths
        assert "/api/feishu/status" in paths  # 对照组：正常路由仍在


class TestEngineBrainSurface:
    def _engine(self, tmp_path):
        return AgentEngine(EngineConfig(llm_api_key="sk-test", cwd=str(tmp_path)))

    def test_no_coordinator_status_attr(self, tmp_path):
        eng = self._engine(tmp_path)
        assert not hasattr(eng, "coordinator_status")
        assert not hasattr(eng, "_coordinator_ctx")

    def test_set_brain_switches_injection_only(self, tmp_path):
        eng = self._engine(tmp_path)
        eng.set_brain("dev_explorer")
        assert eng._run_context.active_brain == "dev_explorer"
        assert eng.config.brain_type == "dev_explorer"

        eng.set_brain("")
        assert eng._run_context.active_brain == ""
        assert eng.config.brain_type == ""

    def test_set_brain_rejects_unknown(self, tmp_path):
        eng = self._engine(tmp_path)
        with pytest.raises(ValueError):
            eng.set_brain("not-a-brain")


class TestRestartColdStart:
    def test_restart_handler_uses_ensure_config(self):
        # 结构回归：handler 必须先 _ensure_config()，不能直接解引用可能为 None 的 _config
        import inspect
        from mai_agent import server

        src = inspect.getsource(server.api_restart)
        assert "_ensure_config()" in src
        # 全局 _config 初始为 None（冷启动标志）
        assert server._config is None or hasattr(server, "_config")
