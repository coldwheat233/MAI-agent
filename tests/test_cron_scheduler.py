"""P0-2 回归：Cron 执行器（mai_agent/services/cron_scheduler.py）。

覆盖：表达式解析、next_fire 计算、调度 tick（到期执行/回写/一次性自删）、
durable 清理、CronCreate 校验、CronList 状态展示。全离线（monkeypatch 掉
真实 agent 执行，不调 LLM/网络）。
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from mai_agent.services import cron_scheduler
from mai_agent.services.cron_scheduler import next_fire, parse_cron
from mai_agent.tools.base import RunContext
from mai_agent.tools.cron_tools import CronCreateInput, CronCreateTool, CronListTool

UTC = timezone.utc


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s).astimezone(UTC)


def _cron_path(cwd: Path) -> Path:
    return cwd / ".mai" / "cron.json"


def _write_jobs(cwd: Path, jobs: list[dict]) -> None:
    p = _cron_path(cwd)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(jobs, ensure_ascii=False), encoding="utf-8")


def _read_jobs(cwd: Path) -> list[dict]:
    return json.loads(_cron_path(cwd).read_text(encoding="utf-8"))


# ── 表达式解析 ─────────────────────────────────────────────


class TestParseCron:
    def test_valid_variants(self):
        assert parse_cron("* * * * *") is not None
        assert parse_cron("*/5 * * * *") is not None
        assert parse_cron("0 9 * * 1-5") is not None
        assert parse_cron("30 2 15 * 0") is not None  # dom 与 dow 都受限（OR）
        assert parse_cron("0,30 8-10 * * *") is not None

    def test_invalid(self):
        assert parse_cron("") is None
        assert parse_cron("bad expression here") is None
        assert parse_cron("1 2 3 4") is None  # 只有 4 字段
        assert parse_cron("61 * * * *") is None  # minute 越界→空集合

    def test_field_semantics(self):
        p = parse_cron("*/10 * * * *")
        assert p["minute"] == {0, 10, 20, 30, 40, 50}
        p = parse_cron("0 9 * * 1-5")
        assert p["hour"] == {9}
        assert p["dow"] == {1, 2, 3, 4, 5}  # 周一~周五
        # cron 的 dow=7 视作周日(0)
        p = parse_cron("0 0 * * 7")
        assert p["dow"] == {0}


class TestNextFire:
    def test_every_minute(self):
        nf = next_fire(parse_cron("* * * * *"), _dt("2026-01-01T00:00:00+00:00"))
        assert nf == _dt("2026-01-01T00:01:00+00:00")

    def test_daily_at_time(self):
        nf = next_fire(parse_cron("30 2 * * *"), _dt("2026-01-01T00:00:00+00:00"))
        assert nf == _dt("2026-01-01T02:30:00+00:00")

    def test_weekday_only(self):
        # 2026-01-01 是周四（dow=4 ∈ 1-5）→ 当天 09:00 就触发
        nf = next_fire(parse_cron("0 9 * * 1-5"), _dt("2026-01-01T00:00:00+00:00"))
        assert nf == _dt("2026-01-01T09:00:00+00:00")

    def test_weekday_only_skips_weekend(self):
        # 2026-01-03 是周六 → 下一次工作日触发是周一 01-05 09:00
        nf = next_fire(parse_cron("0 9 * * 1-5"), _dt("2026-01-03T00:00:00+00:00"))
        assert nf == _dt("2026-01-05T09:00:00+00:00")

    def test_dom_or_dow(self):
        # 每月 15 号 OR 周日；2026-01-01 之后的第一个触发是周日 01-04 00:00
        nf = next_fire(parse_cron("0 0 15 * 0"), _dt("2026-01-01T00:00:00+00:00"))
        assert nf == _dt("2026-01-04T00:00:00+00:00")


# ── 调度 tick ──────────────────────────────────────────────


def _fake_engine(cwd: Path):
    return SimpleNamespace(
        config=SimpleNamespace(cwd=str(cwd)),
        _loop_config=SimpleNamespace(
            max_turns=20, permission_mode="auto", max_context_tokens=1000,
            system_prompt="sys",
        ),
        _llm=None,
        _tools=None,
        _run_context=SimpleNamespace(session_state={}),
        session_id="cron-test",
    )


@pytest.fixture
def fake_engine(tmp_path):
    return _fake_engine(tmp_path)


@pytest.fixture
def patch_run_job(monkeypatch):
    calls: list[dict] = []

    async def _stub(engine, job):
        calls.append(job)
        return f"ran:{job.get('prompt', '')[:20]}"

    monkeypatch.setattr(cron_scheduler, "_run_job", _stub)
    return calls


class TestTick:
    def test_recurring_due_updates_and_reschedules(self, tmp_path, fake_engine, patch_run_job):
        _write_jobs(tmp_path, [{
            "id": "cron_001", "cron": "* * * * *", "prompt": "ping",
            "recurring": True, "durable": True,
            "next_fire": _dt("2026-01-01T00:00:00+00:00").isoformat(),
        }])
        asyncio.run(cron_scheduler._tick(fake_engine))
        jobs = _read_jobs(tmp_path)
        assert len(jobs) == 1
        j = jobs[0]
        assert j["last_run"], "last_run 应被回写"
        assert j["last_result"] == "ran:ping"
        # 重新排期到未来
        assert _dt(j["next_fire"]) > _dt(j["last_run"])
        assert len(patch_run_job) == 1

    def test_once_job_removed_after_run(self, tmp_path, fake_engine, patch_run_job):
        _write_jobs(tmp_path, [{
            "id": "cron_002", "cron": "* * * * *", "prompt": "do once",
            "recurring": False, "durable": True,
            "next_fire": _dt("2026-01-01T00:00:00+00:00").isoformat(),
        }])
        asyncio.run(cron_scheduler._tick(fake_engine))
        assert _read_jobs(tmp_path) == []
        assert len(patch_run_job) == 1

    def test_not_due_untouched(self, tmp_path, fake_engine, patch_run_job):
        _write_jobs(tmp_path, [{
            "id": "cron_003", "cron": "0 0 * * *", "prompt": "far",
            "recurring": True, "durable": True,
            "next_fire": _dt("2099-01-01T00:00:00+00:00").isoformat(),
        }])
        asyncio.run(cron_scheduler._tick(fake_engine))
        assert patch_run_job == []
        assert _read_jobs(tmp_path)[0]["id"] == "cron_003"

    def test_first_tick_computes_next_fire(self, tmp_path, fake_engine, patch_run_job):
        _write_jobs(tmp_path, [{
            "id": "cron_004", "cron": "0 9 * * *", "prompt": "daily",
            "recurring": True, "durable": True, "next_fire": None,
        }])
        asyncio.run(cron_scheduler._tick(fake_engine))
        j = _read_jobs(tmp_path)[0]
        assert j["next_fire"], "next_fire 应为 None → 补齐"
        assert patch_run_job == []  # 未来的触发不执行


class TestDurablePrune:
    def test_ensure_drops_non_durable(self, tmp_path):
        _write_jobs(tmp_path, [
            {"id": "a", "cron": "* * * * *", "prompt": "x",
             "recurring": True, "durable": False, "next_fire": None},
            {"id": "b", "cron": "* * * * *", "prompt": "y",
             "recurring": True, "durable": True, "next_fire": None},
        ])

        async def _main():
            started = cron_scheduler.ensure_cron_scheduler(_fake_engine(tmp_path))
            assert started is True
            cron_scheduler.stop_cron_scheduler(str(tmp_path))

        asyncio.run(_main())
        ids = [j["id"] for j in _read_jobs(tmp_path)]
        assert ids == ["b"], "durable=False 的任务在引擎(重)启动时清理"

    def test_second_ensure_is_noop(self, tmp_path):
        async def _main():
            e = _fake_engine(tmp_path)
            assert cron_scheduler.ensure_cron_scheduler(e) is True
            assert cron_scheduler.ensure_cron_scheduler(e) is False  # 已活跃
            cron_scheduler.stop_cron_scheduler(str(tmp_path))

        asyncio.run(_main())


# ── 工具层（登记/列表） ────────────────────────────────────


class TestCronTools:
    def test_create_valid_and_invalid(self, tmp_path):
        ctx = RunContext(cwd=str(tmp_path))
        ok = asyncio.run(CronCreateTool().call(
            CronCreateInput(cron="*/10 * * * *", prompt="cleanup", recurring=True, durable=True), ctx))
        assert "cron_001" in ok
        job = _read_jobs(tmp_path)[0]
        assert job["cron"] == "*/10 * * * *"
        assert job["next_fire"] is None  # 由调度器首轮补齐

        bad = asyncio.run(CronCreateTool().call(
            CronCreateInput(cron="not-a-cron", prompt="x", recurring=True, durable=True), ctx))
        assert bad.startswith("[ERROR]")
        assert len(_read_jobs(tmp_path)) == 1  # 非法的不落盘

    def test_list_shows_state(self, tmp_path):
        _write_jobs(tmp_path, [{
            "id": "cron_001", "cron": "0 9 * * *", "prompt": "morning",
            "recurring": True, "durable": True,
            "next_fire": _dt("2026-01-02T09:00:00+00:00").isoformat(),
            "last_result": "done:1",
        }])
        out = asyncio.run(CronListTool().call(CronListTool().input_schema(), RunContext(cwd=str(tmp_path))))
        assert "cron_001" in out
        assert "2026-01-02" in out
        assert "done:1" in out
