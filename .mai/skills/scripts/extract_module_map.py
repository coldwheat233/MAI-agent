#!/usr/bin/env python
"""extract_module_map.py — 扫描 mai_agent/ 生成模块摘要索引（Skill 体系脚本扫包）。

对齐 AI-Meeting 的 extract_api_index.py 思路：生成类文档由脚本自动扫描源码产出，
人力只维护规则/约束类文档（SKILL.md 的 invariants / gotchas）。

输出: skills/mai-repo-map/references/generated-module-map.md

扫描内容（每个 Python 模块）:
  - 模块路径 + 一行摘要（docstring 首行）
  - 关键类/函数（类名 + 首行 docstring）
  - 依赖（import 自 mai_agent 的其他模块）
  - 行数
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent.parent  # .mai/skills/scripts → MAI-agent/
PKG = ROOT / "mai_agent"
OUT = ROOT / ".mai" / "skills" / "mai-repo-map" / "references" / "generated-module-map.md"

# 忽略的模块（测试、缓存、egg-info）
IGNORE_PARTS = {"__pycache__", "test", "egg-info"}


def _first_docstring(node: ast.AST) -> str:
    """取 AST 节点 docstring 首行。"""
    try:
        doc = ast.get_docstring(node)
        if doc:
            return doc.strip().splitlines()[0][:120]
    except Exception:
        pass
    return ""


def scan_module(path: Path) -> dict:
    """扫描单个 .py 模块。"""
    try:
        src = path.read_text(encoding="utf-8")
        tree = ast.parse(src)
    except Exception as exc:
        return {"path": str(path.relative_to(PKG)), "error": str(exc)[:80], "lines": 0}

    classes = []
    funcs = []
    deps = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            classes.append((node.name, _first_docstring(node)))
        elif isinstance(node, ast.FunctionDef) and not node.name.startswith("_"):
            funcs.append((node.name, _first_docstring(node)))
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module.startswith("mai_agent") or node.module.startswith("."):
                deps.append(node.module)
        elif isinstance(node, ast.Import):
            for a in node.names:
                if a.name.startswith("mai_agent"):
                    deps.append(a.name)

    return {
        "path": str(path.relative_to(PKG)),
        "doc": _first_docstring(tree),
        "classes": classes,
        "funcs": funcs,
        "deps": sorted(set(deps)),
        "lines": len(src.splitlines()),
    }


def main() -> None:
    modules = []
    for py in sorted(PKG.rglob("*.py")):
        if any(p in IGNORE_PARTS for p in py.parts):
            continue
        modules.append(scan_module(py))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Generated Module Map（自动生成，勿手改 — 运行 extract_module_map.py 重新生成）",
        "",
        f"扫描时间: {__import__('datetime').datetime.now().isoformat(timespec='seconds')}",
        f"模块总数: {len(modules)} | 总行数: {sum(m['lines'] for m in modules)}",
        "",
        "## 模块摘要",
        "",
    ]
    for m in modules:
        rel = m["path"].replace("\\", "/")
        lines.append(f"### {rel}" + ("（解析失败: " + m["error"] + "）" if m.get("error") else ""))
        if m.get("doc"):
            lines.append(f"`{m['doc']}`")
        if m.get("classes"):
            lines.append("")
            lines.append("类:")
            for name, doc in m["classes"][:8]:
                lines.append(f"- `{name}` — {doc or '(无文档)'}")
        if m.get("funcs"):
            lines.append("")
            lines.append("函数:")
            for name, doc in m["funcs"][:6]:
                lines.append(f"- `{name}()` — {doc or '(无文档)'}")
        if m.get("deps"):
            lines.append("")
            lines.append(f"依赖: `{'`, `'.join(m['deps'][:10])}`")
        lines.append("")
        lines.append(f"行数: {m['lines']}")
        lines.append("")
        lines.append("---")
        lines.append("")

    OUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"[ok] 生成 {OUT.relative_to(ROOT)}（{len(modules)} 个模块）")


if __name__ == "__main__":
    main()
