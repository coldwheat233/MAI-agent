"""精确字符串替换工具 — 对应 Claude Code 的 FileEditTool。

对文件做精确的字符串替换，避免简单的 patch/line-based 编辑问题。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from pydantic import Field

from mai_agent.tools.base import Tool, ToolInput, RunContext
from mai_agent.tools.registry import registry
from mai_agent.tools.utils import resolve_path
from mai_agent.tools.snapshots import save_snapshot


class FileEditInput(ToolInput):
    file_path: str = Field(description="要修改的文件绝对路径")
    old_string: str = Field(description="要被替换的原始文本（必须与文件中完全一致，含缩进和空白）")
    new_string: str = Field(description="替换后的新文本")
    replace_all: bool = Field(default=False, description="替换所有匹配的 old_string")
    context: Optional[str] = Field(
        default=None,
        description=("可选: 定位锚点——old_string 附近的一段文本（如前后几行）。"
                     "工具会先找 context 所在位置，再在其附近找 old_string，"
                     "降低大文件中匹配错误的概率。不需要精确复述 old_string 全文。"),
    )


class FileEditTool(Tool):
    """精确字符串替换。

    对应 Claude Code 行为:
      - old_string 必须在文件中精确匹配（包括缩进和空白）
      - 如果 old_string 不唯一且 replace_all=False，返回错误
      - replace_all=True 时替换所有匹配
      - is_concurrency_safe = False (写操作)
    """
    name = "Edit"
    description = "对文件做精确字符串替换。old_string 必须与文件内容完全一致（含缩进）。"
    input_schema = FileEditInput
    is_concurrency_safe = False

    def write_targets(self, args: dict[str, Any]) -> list[str]:
        """声明写目标：file_path。多个 Edit/Write 写不同文件可并发。"""
        fp = args.get("file_path") if isinstance(args, dict) else getattr(args, "file_path", "")
        return [str(fp)] if fp else []

    async def call(self, input: FileEditInput, context: RunContext) -> str:
        path = resolve_path(input.file_path, context.cwd)

        # 沙箱写路径检查：按当前 engine 的 session_state（多工作区隔离），非全局状态
        from mai_agent.sandbox.policy import check_file_write
        reason = check_file_write(input.file_path, context.cwd,
                                  context.session_state.get("sandbox"))
        if reason:
            return f"[ERROR] {reason}"

        if not path.exists():
            return f"[ERROR] File not found: {path}"

        content = path.read_text(encoding="utf-8")

        # ── 定位 old_string ──────────────────────────────
        # 策略 1: 有 context 锚点 → 先找锚点位置，在锚点之后找第一个 old_string
        #          （"在 def bar() 里改 x = 1" = 锚点后的第一个匹配）
        # 策略 2: 无锚点 → 全局找
        search_region = content
        anchor_note = ""
        if input.context and input.context.strip():
            ctx = input.context.strip()
            idx = content.find(ctx)
            if idx == -1:
                # 锚点本身没找到 → 提示（不阻塞，退化为全局找）
                return _not_found_feedback(content, input.old_string, f"context 锚点未找到: {ctx[:80]}")
            # 锚点之后 ±100 字符内找（锚点后优先，避免匹配到锚点前的旧代码）
            start = max(0, idx)
            end = min(len(content), idx + len(ctx) + 800)
            search_region = content[start:end]
            anchor_note = f" (在 context 锚点之后定位)"

        if input.old_string not in search_region:
            # 失败反馈：给位置 + 附近内容 + 可能原因（可行动提示）
            return _not_found_feedback(content, input.old_string,
                                       f"old_string 未找到{anchor_note}")

        # 只在搜索区域内做替换——全局 count 不受锚点影响，但替换位置要落在区域内
        # 简化：无锚点时全局；有锚点时把"区域内的第一次匹配"换成全局索引
        if input.context and input.context.strip():
            region_idx = search_region.find(input.old_string)
            global_idx = start + region_idx
            count_in_region = search_region.count(input.old_string)
            if count_in_region > 1 and not input.replace_all:
                return (
                    f"[ERROR] old_string 在定位区域出现了 {count_in_region} 次，但 replace_all=False。"
                    f"请提供更多上下文使 old_string 唯一，或设置 replace_all=True。"
                )
            if input.replace_all:
                new_content = content.replace(input.old_string, input.new_string)
                replacements = content.count(input.old_string)
            else:
                new_content = content[:global_idx] + input.new_string + content[global_idx + len(input.old_string):]
                replacements = 1
        else:
            count = content.count(input.old_string)
            if count > 1 and not input.replace_all:
                return (
                    f"[ERROR] old_string 在文件中出现了 {count} 次，但 replace_all=False。"
                    f"请提供更多上下文使 old_string 唯一，或设置 replace_all=True。"
                )
            if input.replace_all:
                new_content = content.replace(input.old_string, input.new_string)
                replacements = count
            else:
                new_content = content.replace(input.old_string, input.new_string, 1)
                replacements = 1

        path.write_text(new_content, encoding="utf-8")
        diff = _compute_diff(input.old_string, input.new_string)
        snap_msg = f"\n[snapshot: {snap_id}]" if (snap_id := save_snapshot(str(path), context.cwd)) else ""
        return f"Modified: {path} ({replacements} replacement(s)){snap_msg}{anchor_note}\n{diff}"


def _not_found_feedback(content: str, old_string: str, reason: str) -> str:
    """编辑失败的"可行动反馈"：给位置、附近内容、可能原因，帮模型自我修正。

    这是工具设计的关键——失败信息决定模型下一轮能不能自己修对。
    """
    lines = content.splitlines()
    # 找最接近 old_string 首行的位置（模糊匹配首个单词）
    first_word = old_string.strip().split()[0][:30] if old_string.strip() else ""
    approx_line = 0
    if first_word:
        for i, ln in enumerate(lines, 1):
            if first_word in ln:
                approx_line = i
                break

    nearby = ""
    if approx_line:
        start = max(0, approx_line - 2)
        nearby_lines = lines[start:approx_line + 1]
        nearby = "\n".join(f"  L{start + j + 1}: {ln}" for j, ln in enumerate(nearby_lines))
    elif lines:
        nearby = "\n".join(f"  L{j + 1}: {ln}" for j, ln in enumerate(lines[:5]))

    msg = f"[ERROR] {reason}。"
    msg += f"\nold_string 首词 '{first_word}' 可能在 L{approx_line} 附近。"
    if nearby:
        msg += f"\n附近内容:\n{nearby}"
    msg += (
        "\n可能原因: ① 空白/缩进不匹配（old_string 必须与文件逐字符一致，含 \\n 和空格）；"
        "② old_string 太长容易出错——建议只给要改的那几行，必要时加 context 锚点。"
    )
    return msg


def _compute_diff(old: str, new: str) -> str:
    """Generate a simple +/- diff for display."""
    old_lines = old.splitlines() or [old]
    new_lines = new.splitlines() or [new]
    lines: list[str] = []
    for ol in old_lines:
        lines.append(f"- {ol}")
    for nl in new_lines:
        lines.append(f"+ {nl}")
    return "\n".join(lines)


registry.register(FileEditTool())
