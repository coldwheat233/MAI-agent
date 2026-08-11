"""Deploy tools — 部署管道：Plan → Check → Run → Rollback。

每个部署步骤记录在 .mai/deploys/{id}.json，支持回滚。
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from pydantic import Field

from mai_agent.tools.base import Tool, ToolInput, RunContext
from mai_agent.tools.registry import registry

logger = logging.getLogger(__name__)

DEPLOY_DIR = ".mai/deploys"


def _deploy_path(cwd: str) -> Path:
    return Path(cwd) / DEPLOY_DIR


def _save_deploy(cwd: str, data: dict) -> str:
    """保存部署记录，返回 deploy_id。"""
    d = _deploy_path(cwd)
    d.mkdir(parents=True, exist_ok=True)
    did = data.get("deploy_id") or str(uuid.uuid4())[:8]
    data["deploy_id"] = did
    (d / f"{did}.json").write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return did


def _load_deploy(cwd: str, deploy_id: str) -> Optional[dict]:
    p = _deploy_path(cwd) / f"{deploy_id}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def _list_deploys(cwd: str) -> list[dict]:
    d = _deploy_path(cwd)
    if not d.exists():
        return []
    results = []
    for f in sorted(d.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            results.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            pass
    return results


async def _sh(cmd: str, cwd: str, timeout: float = 60) -> tuple[str, str, int]:
    """执行 shell 命令并返回 (stdout, stderr, returncode)。"""
    try:
        p = await asyncio.create_subprocess_shell(
            cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, cwd=cwd)
        out, err = await asyncio.wait_for(p.communicate(), timeout=timeout)
        return (out.decode("utf-8", errors="replace") if out else "",
                err.decode("utf-8", errors="replace") if err else "",
                p.returncode or 0)
    except asyncio.TimeoutError:
        return "", f"timeout ({timeout}s)", -1
    except Exception as exc:
        return "", str(exc), -1


# ── DeployPlan ────────────────────────────────────────────


class DeployPlanInput(ToolInput):
    target: str = Field(default="", description="部署目标描述（如 'production', 'staging', '本地测试'）")
    steps: Optional[list[str]] = Field(default=None, description="手动指定部署步骤")


class DeployPlanTool(Tool):
    """生成部署计划——分析项目并生成步骤化的部署清单。"""
    name = "DeployPlan"
    description = "Generate a step-by-step deployment plan. Analyzes the project and creates a checklist."
    input_schema = DeployPlanInput
    is_concurrency_safe = True

    async def call(self, input: DeployPlanInput, context: RunContext) -> str:
        if input.steps:
            steps = input.steps
        else:
            # Auto-detect: scan for common project signals
            cwd = Path(context.cwd)
            steps = []
            if (cwd / "pyproject.toml").exists() or (cwd / "setup.py").exists():
                steps.append("pip install -e .")
            if (cwd / "package.json").exists():
                steps.append("npm install && npm run build")
            if (cwd / "Makefile").exists():
                steps.append("make build")
            if (cwd / "tests").exists() or (cwd / "test").exists():
                steps.append("python -m pytest tests/")
            if (cwd / ".git").exists():
                steps.append("git status --short  # verify clean working tree")
            if not steps:
                steps = ["echo 'No auto-detected steps. Specify manually.'"]

        data = {
            "deploy_id": str(uuid.uuid4())[:8],
            "target": input.target or "default",
            "steps": [{"name": s, "status": "pending", "output": "", "rolled_back": False} for s in steps],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        did = _save_deploy(context.cwd, data)

        lines = [f"Deploy Plan #{did} → {input.target or 'default'}", ""]
        for i, s in enumerate(steps):
            lines.append(f"  [{i+1}] {s}  (pending)")
        lines.append("")
        lines.append(f"Use DeployCheck to verify readiness, then DeployRun to execute each step.")
        return "\n".join(lines)


registry.register(DeployPlanTool())


# ── DeployCheck ───────────────────────────────────────────


class DeployCheckInput(ToolInput):
    deploy_id: str = Field(description="部署计划 ID")


class DeployCheckTool(Tool):
    """部署前检查——测试是否通过？git 是否干净？"""
    name = "DeployCheck"
    description = "Run pre-deployment checks: tests pass? working tree clean?"
    input_schema = DeployCheckInput
    is_concurrency_safe = True

    async def call(self, input: DeployCheckInput, context: RunContext) -> str:
        deploy = _load_deploy(context.cwd, input.deploy_id)
        if not deploy:
            return f"[ERROR] 部署计划 #{input.deploy_id} 不存在"

        checks: list[tuple[str, bool, str]] = []

        # Git clean check
        out, _, code = await _sh("git status --porcelain", context.cwd)
        is_clean = code == 0 and not out.strip()
        detail = "clean" if is_clean else (f"dirty:\n{out.strip()[:200]}")
        checks.append(("Git working tree clean", is_clean, detail))

        # Tests pass
        test_out, _, test_code = await _sh("python -m pytest tests/ -q --tb=no 2>&1", context.cwd, timeout=120)
        checks.append(("Tests pass", test_code == 0, test_out.strip()[-200:]))

        # Git remote check
        remote_out, _, _ = await _sh("git remote -v", context.cwd)
        checks.append(("Git remote configured", bool(remote_out.strip()), remote_out.strip() or "no remotes"))

        lines = [f"DeployCheck #{input.deploy_id}", ""]
        all_ok = True
        for name, ok, detail in checks:
            mark = "PASS" if ok else "FAIL"
            if not ok:
                all_ok = False
            lines.append(f"  [{mark}] {name}")
            if detail:
                lines.append(f"        {detail[:100]}")

        lines.append("")
        if all_ok:
            lines.append("All checks passed. Ready to deploy with DeployRun.")
        else:
            lines.append("Some checks failed. Fix issues before deploying.")

        # Update deploy record
        deploy["checks"] = [{"name": n, "ok": o, "detail": d} for n, o, d in checks]
        deploy["checked_at"] = datetime.now(timezone.utc).isoformat()
        _save_deploy(context.cwd, deploy)

        return "\n".join(lines)


registry.register(DeployCheckTool())


# ── DeployRun ─────────────────────────────────────────────


class DeployRunInput(ToolInput):
    deploy_id: str = Field(description="部署计划 ID")
    step_index: int = Field(default=0, description="要执行的步骤序号 (1-based)。0 = 执行下一个 pending 步骤")


class DeployRunTool(Tool):
    """执行一个部署步骤。"""
    name = "DeployRun"
    description = "Execute a single deployment step. Run DeployCheck first."
    input_schema = DeployRunInput
    is_concurrency_safe = False

    async def call(self, input: DeployRunInput, context: RunContext) -> str:
        deploy = _load_deploy(context.cwd, input.deploy_id)
        if not deploy:
            return f"[ERROR] 部署计划 #{input.deploy_id} 不存在"

        steps = deploy.get("steps", [])
        if not steps:
            return "[ERROR] 部署计划中没有步骤"

        # 选择步骤
        idx = input.step_index - 1
        if idx < 0:
            # 找第一个 pending 步骤
            for i, s in enumerate(steps):
                if s["status"] == "pending":
                    idx = i
                    break
            if idx < 0:
                return "All steps completed. Nothing to run."
        elif idx >= len(steps):
            return f"[ERROR] 步骤索引超出范围 (1-{len(steps)})"

        step = steps[idx]
        if step["status"] in ("running", "completed"):
            return f"[ERROR] 步骤 {idx+1} 状态为 '{step['status']}'，不能执行"

        step["status"] = "running"
        _save_deploy(context.cwd, deploy)

        # 执行
        cmd = step["name"]
        out, err, code = await _sh(cmd, context.cwd, timeout=120)

        step["status"] = "completed" if code == 0 else "failed"
        step["output"] = (out + "\n" + err).strip()[-2000:]
        step["return_code"] = code
        _save_deploy(context.cwd, deploy)

        mark = "OK" if code == 0 else "FAIL"
        return (f"DeployRun #{input.deploy_id} Step {idx+1}/{len(steps)} [{mark}]\n"
                f"  command: {cmd}\n"
                f"  exit: {code}\n"
                f"  output: {(out + err).strip()[-500:]}")


registry.register(DeployRunTool())


# ── DeployRollback ────────────────────────────────────────


class DeployRollbackInput(ToolInput):
    deploy_id: str = Field(description="部署计划 ID")
    step_index: int = Field(default=0, description="要回滚的步骤序号 (1-based)。0 = 回滚最后完成的步骤")


class DeployRollbackTool(Tool):
    """回滚一个已完成的部署步骤。"""
    name = "DeployRollback"
    description = "Rollback the last completed deployment step. Only one step can be rolled back at a time."
    input_schema = DeployRollbackInput
    is_concurrency_safe = False

    async def call(self, input: DeployRollbackInput, context: RunContext) -> str:
        deploy = _load_deploy(context.cwd, input.deploy_id)
        if not deploy:
            return f"[ERROR] 部署计划 #{input.deploy_id} 不存在"

        steps = deploy.get("steps", [])
        idx = input.step_index - 1
        if idx < 0:
            # 找最后一个 completed 且未回滚的步骤
            for i in range(len(steps) - 1, -1, -1):
                if steps[i]["status"] == "completed" and not steps[i].get("rolled_back"):
                    idx = i
                    break
            if idx < 0:
                return "No completed steps to roll back."
        elif idx >= len(steps):
            return f"[ERROR] 步骤索引超出范围 (1-{len(steps)})"

        step = steps[idx]
        if step["status"] != "completed":
            return f"[ERROR] 步骤 {idx+1} 状态为 '{step['status']}'，不能回滚（只能回滚已完成步骤）"

        step["rolled_back"] = True
        step["rolled_back_at"] = datetime.now(timezone.utc).isoformat()
        _save_deploy(context.cwd, deploy)

        return (f"DeployRollback #{input.deploy_id} Step {idx+1}/{len(steps)} [ROLLED BACK]\n"
                f"  command: {step['name']}\n"
                f"  The step has been marked as rolled back. Manual reversal may be needed.")


registry.register(DeployRollbackTool())


# ── DeployList ────────────────────────────────────────────


class DeployListInput(ToolInput):
    """无参数——列出所有部署记录。"""


class DeployListTool(Tool):
    """列出所有部署计划及其状态。"""
    name = "DeployList"
    description = "List all deployment plans and their current status."
    input_schema = DeployListInput
    is_concurrency_safe = True

    async def call(self, input: DeployListInput, context: RunContext) -> str:
        deploys = _list_deploys(context.cwd)
        if not deploys:
            return "No deploy plans found. Use DeployPlan to create one."

        lines = [f"Deploy Plans ({len(deploys)})", ""]
        for d in deploys[:10]:
            steps = d.get("steps", [])
            done = sum(1 for s in steps if s["status"] == "completed")
            failed = sum(1 for s in steps if s["status"] == "failed")
            lines.append(f"  #{d['deploy_id']} → {d.get('target','?')} "
                        f"({done}/{len(steps)} done" + (f", {failed} failed)" if failed else "") + ")")
        return "\n".join(lines)


registry.register(DeployListTool())
