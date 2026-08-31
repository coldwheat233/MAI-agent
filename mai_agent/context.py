"""上下文注入 — 对应 Claude Code 的 context.ts。

三层上下文模型:
  1. System context — git status, 系统信息（每会话缓存）
  2. User context — CLAUDE.md, 项目配置（memoized）
  3. Coordinator/Brain context — 当前活跃脑、任务状态（动态）
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Optional


@lru_cache(maxsize=1)
def get_system_context(project_root: Optional[str] = None) -> dict[str, str]:
    """每会话缓存的系统上下文。

    Claude Code 对应物: getSystemContext().
    包含 git status 等不常在对话中变化的信息。
    """
    cwd = project_root or os.getcwd()
    context: dict[str, str] = {
        "currentDate": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "platform": os.name,
        "cwd": str(Path(cwd).resolve()),
    }

    # Git 状态
    if project_root:
        git_status = _get_git_status_sync(project_root)
        if git_status:
            context["gitStatus"] = git_status

    return context


@lru_cache(maxsize=1)
def get_user_context(project_root: Optional[str] = None) -> dict[str, str]:
    """每会话缓存的用户/项目上下文。

    Claude Code 对应物: getUserContext().
    包含 CLAUDE.md 等项目级配置。
    """
    context: dict[str, str] = {}

    if project_root:
        root = Path(project_root)
        claude_md = _read_claude_md(root)
        if claude_md:
            context["claudeMd"] = claude_md

    return context


def get_brain_context(brain_type: str) -> dict[str, str]:
    """脑模式专用上下文注入。

    Claude Code 对应物: getCoordinatorUserContext().

    根据当前激活的脑类型，注入不同的角色指令。
    """
    contexts = {
        "dev_explorer": {
            "brainContext": (
                "你当前处于「开发探索」模式。你的职责是:\n"
                "1. 拆解用户需求为可执行子任务\n"
                "2. 生成结构化的测试清单(checklist)\n"
                "3. 识别未知概念并标记复杂度\n"
                "输出格式: Markdown 清单"
            ),
        },
        "dev_validator": {
            "brainContext": (
                "你当前处于「开发验证」模式。你的职责是:\n"
                "1. 验证所有 checklist 项是否完成\n"
                "2. 检查修改是否影响其他功能\n"
                "3. 运行测试确认无回归\n"
                "输出格式: 验证报告"
            ),
        },
        "knowledge_explorer": {
            "brainContext": (
                "你当前处于「知识探索」模式。你的职责是:\n"
                "1. 识别对话中的未知概念\n"
                "2. 搜索并预筛选概念复杂度\n"
                "3. 将知识整理为可入库格式\n"
            ),
        },
    }

    return contexts.get(brain_type, {})


def _read_claude_md(root: Path) -> Optional[str]:
    """查找并读取 CLAUDE.md 文件。"""
    for name in ["CLAUDE.md", "CLAUDE.MD", "claude.md"]:
        path = root / name
        if path.exists():
            try:
                return path.read_text(encoding="utf-8")
            except Exception:
                return None
    return None


def _get_git_status_sync(project_root: str) -> Optional[str]:
    """同步获取 git status（简化版）。"""
    import subprocess
    try:
        result = subprocess.run(
            ["git", "--no-optional-locks", "status", "--short"],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=project_root,
        )
        return result.stdout.strip() or "(clean)"
    except Exception:
        return None


def build_system_prompt(
    base_prompt: str,
    project_root: Optional[str] = None,
    brain_type: Optional[str] = None,
    budget_tokens: Optional[int] = None,
    messages_tokens: int = 0,
) -> str:
    """组装完整的 system prompt — 分层 + 可选预算管理。

    对应 Claude Code: system prompt 的组装逻辑。

    预算模式（budget_tokens 传入时）:
      用 ContextAssembler 按优先级三档降级各附加层，避免全量拼接超限。
      不传预算时保持原行为（全量拼接，向后兼容）。
    """
    # ── 提取各层内容 ─────────────────────────────────
    sys_ctx = get_system_context(project_root)
    sys_parts: list[str] = []
    if "currentDate" in sys_ctx:
        sys_parts.append(f"当前日期: {sys_ctx['currentDate']}")
    if "cwd" in sys_ctx:
        sys_parts.append(f"当前工作目录: {sys_ctx['cwd']}")
    if "gitStatus" in sys_ctx:
        sys_parts.append(f"\nGit 状态:\n{sys_ctx['gitStatus']}")
    system_context_text = "\n".join(sys_parts)

    user_ctx = get_user_context(project_root)
    claude_md_text = user_ctx.get("claudeMd", "")

    from mai_agent.services.memory import memory_context_for_prompt
    mem_ctx = memory_context_for_prompt(project_root or ".")

    tagged_ctx = ""
    try:
        from mai_agent.services.memory_tags import tagged_memory_context
        tagged_ctx = tagged_memory_context(project_root or ".")
    except Exception:
        pass

    skills_listing = ""
    try:
        from mai_agent.skills.loader import get_skill_registry
        skills_listing = get_skill_registry(project_root or ".").listing()
    except Exception:
        pass

    brain_context = ""
    if brain_type:
        brain_ctx = get_brain_context(brain_type)
        brain_context = brain_ctx.get("brainContext", "")

    # ── 预算模式：ContextAssembler 按优先级裁剪 ──────
    if budget_tokens is not None:
        from mai_agent.services.context_asm import ContextAssembler, LayerSpec, truncate_render

        asm = ContextAssembler(max_context=budget_tokens, budget_ratio=1.0)
        layers: list[LayerSpec] = []
        # P2: 会话记忆（最重要附加层）
        if mem_ctx:
            layers.append(LayerSpec(id="session_memory", priority=20,
                                    render=truncate_render(mem_ctx, 1500)))
        # P2: 标签记忆
        if tagged_ctx:
            layers.append(LayerSpec(id="tagged_memory", priority=30,
                                    render=truncate_render(tagged_ctx, 1000)))
        # P2: 项目配置
        if claude_md_text:
            layers.append(LayerSpec(id="project_config", priority=40,
                                    render=truncate_render(claude_md_text, 800)))
        # P2.5: skills
        if skills_listing:
            layers.append(LayerSpec(id="skills", priority=50,
                                    render=truncate_render(skills_listing, 800)))
        # P3: 系统上下文（git/日期）
        if system_context_text:
            layers.append(LayerSpec(id="system_context", priority=60,
                                    render=truncate_render(system_context_text, 300)))

        return asm.assemble(layers, messages_tokens,
                            base_prompt=base_prompt, brain_context=brain_context)

    # ── 原行为：全量拼接 ──────────────────────────────
    parts: list[str] = [base_prompt]
    if system_context_text:
        parts.append(system_context_text)
    if claude_md_text:
        parts.append(f"\n项目配置:\n{claude_md_text}")
    if mem_ctx:
        parts.append(mem_ctx)
    if tagged_ctx:
        parts.append(tagged_ctx)
    if skills_listing:
        parts.append(skills_listing)
    if brain_context:
        parts.append(f"\n{brain_context}")

    return "\n\n".join(parts)
