"""MAI-agent 评估器 — 自建任务集回归 + 量化报告。

用法:
    python eval_runner.py                 # 跑全部任务（默认 eval/tasks.json）
    python eval_runner.py --tasks eval/tasks.json --once 001   # 只跑单个任务
    python eval_runner.py --judge          # 开启 LLM-as-judge 质量打分
    python eval_runner.py --no-clean       # 不清理任务产生的文件（调试用）

设计:
    - 任务集: eval/tasks.json（task_id / instruction / workspace / expected_check / judge_mode）
    - expected_check 支持 5 种脚本化断言:
        file_exists   — 文件存在
        file_contains — 文件包含子串
        cmd_exit_0    — 命令退出码为 0
        output_contains — agent 最终回答包含子串
        output_length — 最终回答长度达标
    - 每个任务跑完整 agent loop（mai --once），trace 自动落盘 .mai/traces/
    - 输出 eval/summary.json: 完成率 / 平均步数 / token / 成本 / 工具失败 Top / 逐任务结果
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEFAULT_TASKS = ROOT / "eval" / "tasks.json"
OUTPUT = ROOT / "eval" / "summary.json"

# ── 断言实现 ─────────────────────────────────────────────


def check_expected(check: dict, workspace: str, final_answer: str) -> tuple[bool, str]:
    """执行 expected_check 断言，返回 (pass, 说明)。"""
    ctype = check.get("type", "")
    ws = Path(workspace).resolve()

    try:
        if ctype == "file_exists":
            p = ws / check["path"]
            return (p.exists(), f"file exists: {check['path']}")

        elif ctype == "file_contains":
            p = ws / check["path"]
            if not p.exists():
                return (False, f"file missing: {check['path']}")
            content = p.read_text(encoding="utf-8", errors="replace")
            needle = check.get("contains", "")
            return (needle in content, f"file contains '{needle}'")

        elif ctype == "cmd_exit_0":
            cmd = check.get("cmd", "")
            r = subprocess.run(cmd, cwd=str(ws), shell=True,
                               capture_output=True, text=True, timeout=30)
            ok = r.returncode == 0
            detail = (r.stdout or r.stderr or "").strip()[:120]
            return (ok, f"cmd exit={r.returncode} {detail}")

        elif ctype == "output_contains":
            needle = check.get("contains", "")
            return (needle in final_answer, f"answer contains '{needle}'")

        elif ctype == "output_length":
            min_chars = check.get("min_chars", 10)
            return (len(final_answer) >= min_chars, f"answer len={len(final_answer)}>={min_chars}")

        return (False, f"unknown check type: {ctype}")
    except Exception as exc:
        return (False, f"check error: {exc}")


# ── LLM-as-judge ─────────────────────────────────────────


def llm_judge(task: dict, final_answer: str) -> dict:
    """用 LLM 按 rubric 给任务质量打分（0-10 分，含理由）。

    只对 judge_mode=llm 的任务调用；失败时返回默认分，不阻塞评估。
    """
    rubric = (
        "你是 MAI-agent 评估裁判。根据任务要求和 agent 的最终回答，按以下维度打分：\n"
        "1. 正确性(0-5): 回答是否准确完成任务要求\n"
        "2. 完整性(0-3): 是否覆盖任务所有要点\n"
        "3. 效率(0-2): 是否用了合理数量的工具调用/步骤\n"
        "总分 0-10。只输出 JSON: {\"score\": 分数, \"reason\": 一句话理由}\n\n"
        f"任务要求: {task['instruction']}\n\n"
        f"agent 最终回答: {final_answer[:1500]}"
    )
    try:
        from mai_agent.config import get_config
        from mai_agent.llm.client import LLMClient
        cfg = get_config()
        import asyncio

        async def _judge():
            llm = LLMClient(api_key=cfg.llm_api_key, base_url=cfg.llm_base_url, model=cfg.llm_model)
            try:
                resp = await llm.chat(
                    [{"role": "user", "content": rubric}],
                    tools=None, temperature=0.0, max_tokens=200,
                )
                return resp.content or ""
            finally:
                await llm.aclose()

        content = asyncio.run(_judge())
        m = re.search(r"\{.*\}", content, re.DOTALL)
        if m:
            data = json.loads(m.group(0))
            return {"score": float(data.get("score", 0)), "reason": data.get("reason", "")[:200]}
    except Exception as exc:
        return {"score": 0.0, "reason": f"judge error: {exc}"[:200]}
    return {"score": 0.0, "reason": "no judge output"}


# ── 单任务执行 ───────────────────────────────────────────


def run_task(task: dict, root: Path, judge: bool = False, clean: bool = True) -> dict:
    """跑一个任务：独立临时工作区 + mai --once + 断言。"""
    task_id = task["task_id"]
    # 每个任务用独立临时工作区，避免任务间互相污染
    tmp = Path(tempfile.mkdtemp(prefix=f"mai_eval_{task_id}_"))
    try:
        # 复制 workspace 内容（默认是项目根，复制整个项目太慢——
        # 只复制 mai_agent 包 + .env，让 agent 能 import / 搜索）
        workspace = task.get("workspace", ".")
        src = (root / workspace).resolve()
        if src == root:
            # 复制项目核心：mai_agent 包 + .env（agent 需要 import mai_agent）
            shutil.copytree(root / "mai_agent", tmp / "mai_agent", ignore=shutil.ignore_patterns("__pycache__"))
            env = root / ".env"
            if env.exists():
                shutil.copy2(env, tmp / ".env")
        else:
            shutil.copytree(src, tmp, dirs_exist_ok=True)

        # 记录任务开始时的 trace 数（用于计算本任务新增的 span）
        tmp_traces_dir = tmp / ".mai" / "traces"
        traces_before = set(tmp_traces_dir.glob("*.jsonl")) if tmp_traces_dir.exists() else set()

        start = time.monotonic()
        # 唯一 session_id：避免同一 task_id 复用全局 SQLite 里的旧 session
        # （旧 session 的 messages 含上次运行的临时路径，agent 会跟着写错目录）
        session_id = f"eval_{task_id}_{int(time.time())}"
        r = subprocess.run(
            [sys.executable, "-m", "mai_agent.cli", "--once", task["instruction"],
             "--session", session_id],
            cwd=str(tmp),
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=180,
            env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"},
        )
        elapsed = time.monotonic() - start

        # 提取最终回答（cli 的 Panel 输出难解析——直接用 stdout 全文，
        # 断言 output_contains 在全文里匹配即可）
        final_answer = (r.stdout or "") + "\n" + (r.stderr or "")

        passed, detail = check_expected(task.get("expected_check", {}), str(tmp), final_answer)

        # 统计本任务 trace：从临时工作区读（mai --once 的 project_root 是 tmp）
        traces_after = set(tmp_traces_dir.glob("*.jsonl")) if tmp_traces_dir.exists() else set()
        new_traces = traces_after - traces_before
        if not new_traces:
            new_traces = set(tmp_traces_dir.glob("*.jsonl")) if tmp_traces_dir.exists() else set()
        span_count = 0
        llm_calls = 0
        tool_calls = 0
        total_tokens = 0
        total_cost = 0.0
        tool_errors: list[str] = []
        for tf in new_traces:
            for line in tf.read_text(encoding="utf-8").splitlines():
                try:
                    s = json.loads(line)
                except json.JSONDecodeError:
                    continue
                span_count += 1
                if s.get("type") == "llm":
                    llm_calls += 1
                    total_tokens += s.get("total_tokens", 0)
                    total_cost += s.get("cost", 0.0)
                elif s.get("type") == "tool":
                    tool_calls += 1
                    if s.get("is_error"):
                        tool_errors.append(s.get("tool", "?"))

        judge_result = llm_judge(task, final_answer) if (judge and task.get("judge_mode") == "llm") else None

        return {
            "task_id": task_id,
            "instruction": task["instruction"][:80],
            "passed": passed,
            "check": detail,
            "duration_s": round(elapsed, 1),
            "exit_code": r.returncode,
            "answer_preview": final_answer.strip().replace("\n", " ")[:200],
            "trace": {
                "spans": span_count,
                "llm_calls": llm_calls,
                "tool_calls": tool_calls,
                "total_tokens": total_tokens,
                "total_cost": round(total_cost, 6),
                "tool_errors": tool_errors,
            },
            "judge": judge_result,
        }
    except subprocess.TimeoutExpired:
        return {
            "task_id": task_id, "instruction": task["instruction"][:80],
            "passed": False, "check": "timeout (>180s)",
            "duration_s": 180.0, "exit_code": -1, "answer_preview": "",
            "trace": {"spans": 0, "llm_calls": 0, "tool_calls": 0, "total_tokens": 0, "total_cost": 0.0, "tool_errors": []},
            "judge": None,
        }
    except Exception as exc:
        return {
            "task_id": task_id, "instruction": task["instruction"][:80],
            "passed": False, "check": f"runner error: {exc}",
            "duration_s": 0.0, "exit_code": -2, "answer_preview": "",
            "trace": {"spans": 0, "llm_calls": 0, "tool_calls": 0, "total_tokens": 0, "total_cost": 0.0, "tool_errors": []},
            "judge": None,
        }
    finally:
        if clean:
            shutil.rmtree(tmp, ignore_errors=True)


# ── 主流程 ───────────────────────────────────────────────


def main():
    ap = argparse.ArgumentParser(description="MAI-agent 评估器")
    ap.add_argument("--tasks", default=str(DEFAULT_TASKS), help="任务集 JSON 路径")
    ap.add_argument("--once", default=None, help="只跑指定 task_id（逗号分隔）")
    ap.add_argument("--judge", action="store_true", help="启用 LLM-as-judge 质量打分")
    ap.add_argument("--no-clean", action="store_true", help="保留临时工作区（调试）")
    args = ap.parse_args()

    root = ROOT
    data = json.loads(Path(args.tasks).read_text(encoding="utf-8"))
    tasks = data["tasks"]
    if args.once:
        wanted = set(args.once.split(","))
        tasks = [t for t in tasks if t["task_id"] in wanted
                 or any(t["task_id"].endswith(w) for w in wanted)]

    print(f"评估开始: {len(tasks)} 个任务 (judge={'on' if args.judge else 'off'})")
    results = []
    for i, task in enumerate(tasks, 1):
        print(f"  [{i}/{len(tasks)}] {task['task_id']}: {task['instruction'][:50]}...")
        res = run_task(task, root, judge=args.judge, clean=not args.no_clean)
        status = "PASS" if res["passed"] else "FAIL"
        print(f"    → {status} ({res['check'][:80]}) [{res['duration_s']}s, {res['trace']['total_tokens']} tok, ${res['trace']['total_cost']}]")
        results.append(res)

    # 汇总
    passed = [r for r in results if r["passed"]]
    llm_calls = sum(r["trace"]["llm_calls"] for r in results)
    tool_calls = sum(r["trace"]["tool_calls"] for r in results)
    total_tokens = sum(r["trace"]["total_tokens"] for r in results)
    total_cost = sum(r["trace"]["total_cost"] for r in results)
    total_dur = sum(r["duration_s"] for r in results)

    # 工具失败 Top（从各任务 trace 的 tool_errors 聚合）
    tool_failures: dict[str, int] = {}
    for r in results:
        for name in r["trace"].get("tool_errors", []):
            tool_failures[name] = tool_failures.get(name, 0) + 1

    summary = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "total_tasks": len(tasks),
        "passed": len(passed),
        "failed": len(tasks) - len(passed),
        "pass_rate": round(len(passed) / len(tasks) * 100, 1) if tasks else 0,
        "avg_duration_s": round(total_dur / len(tasks), 1) if tasks else 0,
        "avg_steps": round(llm_calls / len(tasks), 1) if tasks else 0,
        "total_llm_calls": llm_calls,
        "total_tool_calls": tool_calls,
        "total_tokens": total_tokens,
        "total_cost_usd": round(total_cost, 4),
        "avg_cost_per_task_usd": round(total_cost / len(tasks), 4) if tasks else 0,
        "tool_failures_top": dict(sorted(tool_failures.items(), key=lambda x: -x[1])[:5]),
        "results": results,
    }

    OUTPUT.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n{'='*50}")
    print(f"完成率: {summary['passed']}/{summary['total_tasks']} ({summary['pass_rate']}%)")
    print(f"总 LLM 调用: {llm_calls} | 工具调用: {tool_calls} | 总 tokens: {total_tokens}")
    print(f"总成本: ${summary['total_cost_usd']} | 平均 ${summary['avg_cost_per_task_usd']}/任务 | 平均 {summary['avg_duration_s']}s/任务")
    if tool_failures:
        print(f"工具失败 Top: {summary['tool_failures_top']}")
    print(f"报告已写入: {OUTPUT}")


if __name__ == "__main__":
    main()
