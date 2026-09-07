"""Cron 调度器 — 真正执行 .mai/cron.json 里登记的定时任务（闭环 P0-2）。

之前只有 CronCreate/Delete/List 三个登记工具，没有任何调度器读文件触发任务
（登记簿空转）。本模块补齐执行侧：
  - 5 字段 cron 表达式解析（支持 * / */n / a-b / a-b/n / a,b,c；dom 与 dow
    同时受限时按标准 cron 语义取 OR）
  - 每个 engine 工作区至多一个活跃调度器（进程内按 cwd 去重），20s 心跳
  - 到期任务用一次独立的 agent_loop 执行（复用 engine 的 LLM/工具注册表/
    系统提示词，fresh RunContext + fresh messages，不污染用户会话历史）
  - 执行结果 last_run/last_result/next_fire 写回 cron.json；
    recurring=False 的一次性任务执行后自动删除
  - durable=False 的任务在引擎重启（调度器重建）时清掉——即"不跨会话"

语义边界（诚实声明）：
  - 任务是进程内的：后端/引擎关闭期间错过的触发不做补跑，重启后从当前时间
    计算下一次触发；
  - 一次性任务若在引擎关闭期间到期，同样不补跑，重启后直接丢弃。
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

TICK_SECONDS = 20
MAX_TURNS_PER_JOB = 20
MAX_LOOKAHEAD_DAYS = 366 * 2  # 解析 next_fire 的搜索上限

_active: dict[str, asyncio.Task] = {}  # resolved cwd → scheduler task


# ── cron 表达式解析 ─────────────────────────────────────────


def _range_bounds(expr: str, lo: int, hi: int) -> tuple[int, int]:
    """把单个子字段 'n' / 'a-b' 展开为 (lo, hi) 边界。"""
    if "-" in expr:
        a, _, b = expr.partition("-")
        try:
            return int(a), int(b)
        except ValueError:
            return lo, hi
    try:
        v = int(expr)
    except ValueError:
        return lo, hi
    return v, v


def _parse_field(field: str, lo: int, hi: int) -> set[int]:
    """解析一个 cron 字段为允许值集合。支持 , 列表 / */n / a-b / a-b/n。"""
    values: set[int] = set()
    for part in str(field).split(","):
        part = part.strip()
        if not part:
            continue
        if part == "*":
            values.update(range(lo, hi + 1))
            continue
        if "/" in part:
            base, _, step_s = part.partition("/")
            try:
                step = int(step_s)
            except ValueError:
                continue
            if step <= 0:
                continue
            if base == "*":
                values.update(range(lo, hi + 1, step))
            else:
                b_lo, b_hi = _range_bounds(base, lo, hi)
                values.update(range(b_lo, min(b_hi, hi) + 1, step))
            continue
        b_lo, b_hi = _range_bounds(part, lo, hi)
        values.update(range(max(b_lo, lo), min(b_hi, hi) + 1))
    return values


def parse_cron(expr: str) -> Optional[dict[str, set[int]]]:
    """解析 5 字段 cron 表达式。

    Returns:
        含 minute/hour/dom/mon/dow 五个允许值集合的 dict；格式非法返回 None。
    """
    fields = str(expr).strip().split()
    if len(fields) != 5:
        return None
    try:
        minute = _parse_field(fields[0], 0, 59)
        hour = _parse_field(fields[1], 0, 23)
        dom = _parse_field(fields[2], 1, 31)
        mon = _parse_field(fields[3], 1, 12)
        dow = _parse_field(fields[4], 0, 7)
    except Exception:
        return None
    if not (minute and hour and mon):
        return None
    dow = {0 if v == 7 else v for v in dow}  # cron 允许 7=周日
    return {"minute": minute, "hour": hour, "dom": dom, "mon": mon, "dow": dow}


def next_fire(parsed: dict[str, set[int]], after: datetime) -> Optional[datetime]:
    """返回 parsed 在 after（不含）之后的第一个触发时刻（分钟精度）。"""
    cur = after.replace(second=0, microsecond=0) + timedelta(minutes=1)
    cap = after + timedelta(days=MAX_LOOKAHEAD_DAYS)
    dom_star = parsed["dom"] == set(range(1, 32))
    dow_star = parsed["dow"] == set(range(0, 7))

    while cur <= cap:
        if (cur.minute in parsed["minute"] and cur.hour in parsed["hour"]
                and cur.month in parsed["mon"]):
            wd = (cur.weekday() + 1) % 7  # Python Monday=0 → cron Sunday=0
            day_ok = cur.day in parsed["dom"]
            wd_ok = wd in parsed["dow"]
            if dom_star and dow_star:
                ok = True
            elif not dom_star and not dow_star:
                ok = day_ok or wd_ok  # 标准 cron：两者都受限取 OR
            elif not dom_star:
                ok = day_ok
            else:
                ok = wd_ok
            if ok:
                return cur
        cur += timedelta(minutes=1)
    return None


# ── 持久化（与 cron_tools 同一文件）────────────────────────


def _cron_path(cwd: str) -> Path:
    return Path(cwd) / ".mai" / "cron.json"


def _load_jobs(cwd: str) -> list[dict]:
    p = _cron_path(cwd)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save_jobs(cwd: str, jobs: list[dict]) -> None:
    p = _cron_path(cwd)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(jobs, ensure_ascii=False, indent=2), encoding="utf-8")


def _coerce_dt(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except Exception:
        return None


def _fmt(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


# ── 调度循环 ────────────────────────────────────────────────


def ensure_cron_scheduler(engine: Any) -> bool:
    """确保该 engine 工作区有一个活跃调度器。

    Returns:
        True = 本次由本 engine 启动（engine 关闭时负责 stop）；
        False = 已有活跃调度器或启动失败。
    """
    cwd = str((engine.config.cwd or "."))
    key = str(Path(cwd).resolve())
    task = _active.get(key)
    if task and not task.done():
        return False

    # durable=False 的任务不跨会话：新 engine 启动时清掉上一进程残留
    try:
        jobs = _load_jobs(cwd)
        survived = [j for j in jobs if j.get("durable", False)]
        if len(survived) != len(jobs):
            _save_jobs(cwd, survived)
    except Exception as exc:
        logger.warning("cron durable 清理失败: %s", exc)

    async def _loop() -> None:
        try:
            while True:
                try:
                    await _tick(engine)
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    logger.warning("cron tick error: %s", exc)
                await asyncio.sleep(TICK_SECONDS)
        except asyncio.CancelledError:
            logger.info("Cron 调度器停止: %s", key)
        finally:
            if _active.get(key) is asyncio.current_task():
                _active.pop(key, None)

    try:
        _active[key] = asyncio.create_task(_loop(), name=f"cron-{key[:24]}")
        logger.info("Cron 调度器已启动: %s", key)
        return True
    except Exception as exc:
        logger.warning("Cron 调度器启动失败: %s", exc)
        return False


def stop_cron_scheduler(cwd: str) -> None:
    """取消该工作区的调度器（由启动它的 engine 在 stop 时调用）。"""
    key = str(Path(cwd).resolve())
    task = _active.pop(key, None)
    if task and not task.done():
        task.cancel()


async def _tick(engine: Any) -> None:
    """一轮心跳：补算 next_fire、执行到期任务、回写状态。"""
    cwd = str(engine.config.cwd or ".")
    jobs = _load_jobs(cwd)
    if not jobs:
        return
    now = datetime.now(timezone.utc)

    due: list[dict] = []
    changed = False
    for job in jobs:
        parsed = parse_cron(job.get("cron", ""))
        if parsed is None:
            continue  # 非法表达式：登记时已拦截，这里跳过兜底
        nf = _coerce_dt(job.get("next_fire"))
        if nf is None:
            nf = next_fire(parsed, now)
            if nf is None:
                continue
            job["next_fire"] = _fmt(nf)
            changed = True
        if nf <= now:
            due.append(dict(job))
    if changed:
        _save_jobs(cwd, jobs)

    for snapshot in due:
        result = await _run_job(engine, snapshot)
        # 执行期间 cron.json 可能被工具改动——重读后按 id patch，避免整表覆盖
        cur = _load_jobs(cwd)
        idx = next((i for i, j in enumerate(cur)
                    if j.get("id") == snapshot.get("id")), None)
        if idx is None:
            continue  # 已被 CronDelete 删掉
        parsed = parse_cron(snapshot.get("cron", ""))
        if snapshot.get("recurring", True) and parsed is not None:
            nxt = next_fire(parsed, now)
            cur[idx]["last_run"] = _fmt(now)
            cur[idx]["last_result"] = (result or "")[:200]
            if nxt is not None:
                cur[idx]["next_fire"] = _fmt(nxt)
            else:
                cur[idx].pop("next_fire", None)
        else:
            cur.pop(idx)  # 一次性任务：执行后移除
        _save_jobs(cwd, cur)


async def _run_job(engine: Any, job: dict) -> str:
    """用一次独立的 agent_loop 执行定时任务，返回最终回答文本。"""
    try:
        from mai_agent.core.loop import agent_loop, AgentLoopConfig
        from mai_agent.tools.base import RunContext

        cfg = engine._loop_config
        ctx = RunContext(
            cwd=engine.config.cwd or ".",
            session_state=getattr(engine._run_context, "session_state", {}) or {},
            permission_mode=cfg.permission_mode,
            active_brain="",
            session_id=getattr(engine, "session_id", "") or "cron",
            trace=None,  # 定时任务不占用户 trace 会话
        )
        loop_cfg = AgentLoopConfig(
            max_turns=min(cfg.max_turns, MAX_TURNS_PER_JOB),
            permission_mode=cfg.permission_mode,
            ask_permission=None,
            max_context_tokens=cfg.max_context_tokens,
            system_prompt=cfg.system_prompt,
        )
        prompt = str(job.get("prompt") or "").strip()
        if not prompt:
            return "(empty prompt)"
        answer, _ = await agent_loop(
            user_input=prompt,
            llm=engine._llm,
            registry=engine._tools,
            context=ctx,
            config=loop_cfg,
            initial_messages=None,
            on_progress=None,
        )
        return answer or ""
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.warning("Cron 任务执行失败 %s: %s", job.get("id"), exc)
        return f"[ERROR] {type(exc).__name__}: {exc}"
