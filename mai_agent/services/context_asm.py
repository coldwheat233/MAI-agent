"""Context Assembly — 预算驱动的上下文组装（长上下文管理）。

解决: build_system_prompt 全量拼接所有层，超限时才压缩消息（被动兜底）。
改为: 出发前按预算规划——各上下文层按优先级三档降级（full/summary/omit），
      在 max_context * budget_ratio 预算内组装。

层级优先级（从高到低，预算不足时低优先级先降级）:
  P1 不可裁剪: base prompt + brain 上下文（必须完整）
  P2 摘要档:   会话记忆 / 标签记忆 / 项目配置 / skills（full → summary → omit）
  P3 按需档:   git 状态 / 系统信息（full → summary → omit）

降级档位语义:
  full    — 完整注入
  summary — 压缩版（截断/取要点）
  omit    — 省略
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


@dataclass
class LayerSpec:
    """一层上下文的规格：id / 优先级 / 三档渲染器。"""
    id: str
    priority: int                      # 越小越重要
    render: Callable[[str], str]       # mode("full"/"summary"/"omit") -> 文本
    min_mode: str = "full"             # 允许的最低档（P1 用 "full" 锁死）
    est_tokens: Callable[[str], int] = lambda mode: 0  # 估算档位 token 数


class ContextAssembler:
    """预算驱动组装器。

    Usage:
        asm = ContextAssembler(max_context=100_000, budget_ratio=0.8)
        prompt = asm.assemble(layers, messages_tokens, base_prompt)
    """

    def __init__(self, max_context: int = 100_000, budget_ratio: float = 0.8,
                 approx_tokens_per_char: float = 0.25):
        self.max_context = max_context
        self.budget_ratio = budget_ratio
        self.tok_per_char = approx_tokens_per_char  # 4 char ≈ 1 token

    def _est(self, text: str) -> int:
        """估算 token：中文 ~1.2 token/字，ASCII ~0.25 token/字符。"""
        if not text:
            return 0
        cjk = sum(1 for c in text if '\u4e00' <= c <= '\u9fff' or '\u3000' <= c <= '\u303f')
        other = len(text) - cjk
        return int(cjk * 1.2 + other * 0.25)

    def assemble(
        self,
        layers: list[LayerSpec],
        messages_tokens: int,
        base_prompt: str = "",
        brain_context: str = "",
    ) -> str:
        """按预算组装 system prompt。

        Args:
            layers: 各层规格（P2/P3；P1 的 base/brain 单独传）
            messages_tokens: 当前消息占用的 token（估算）
            base_prompt: 核心 system prompt（P1，不可裁剪）
            brain_context: 脑上下文（P1，不可裁剪）

        Returns:
            组装好的 system prompt 文本
        """
        budget = int(self.max_context * self.budget_ratio)
        # P1 必须完整
        core = base_prompt
        if brain_context:
            core = f"{core}\n\n{brain_context}"
        core_tokens = self._est(core)
        if core_tokens >= budget:
            logger.warning("核心 prompt 已超预算（%d >= %d），跳过附加层", core_tokens, budget)
            return core
        available = budget - core_tokens - messages_tokens

        # 排序：优先级小的（重要）在前
        ordered = sorted(layers, key=lambda l: l.priority)
        parts: list[str] = []
        used = 0

        for layer in ordered:
            # 从 full 开始尝试，逐档降级直到 fit
            chosen: Optional[str] = None
            for mode in ("full", "summary", "omit"):
                text = layer.render(mode)
                cost = self._est(text)
                if mode == "omit" or cost <= available:
                    chosen = text
                    used_cost = 0 if mode == "omit" else cost
                    break
            if chosen:
                if chosen.strip():
                    parts.append(chosen)
                    used += used_cost
                    available -= used_cost
                logger.debug("layer=%s mode=%s cost=%d (剩余 %d)",
                             layer.id, mode, used_cost, available)

        if parts:
            return f"{core}\n\n" + "\n\n".join(parts)
        return core

    def report(self) -> dict[str, Any]:
        """组装统计（调试/面试可展示）。"""
        return {
            "max_context": self.max_context,
            "budget_ratio": self.budget_ratio,
            "budget_tokens": int(self.max_context * self.budget_ratio),
        }


# ── 通用降级渲染器工厂 ─────────────────────────────────────

def truncate_render(full_text: str, summary_chars: int = 600) -> Callable[[str], str]:
    """把一段文本包成三档渲染器: full=原文, summary=截断, omit=""。"""
    def render(mode: str) -> str:
        if mode == "full":
            return full_text
        if mode == "summary":
            if not full_text:
                return ""
            return full_text[:summary_chars] + ("…" if len(full_text) > summary_chars else "")
        return ""
    return render
