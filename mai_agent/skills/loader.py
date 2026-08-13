"""Skill 加载器 — 扫描 skill 目录、解析 frontmatter、构建注册表。

对应 Claude Code 的 skills 加载逻辑，支持两种布局：
  - 目录式（Claude Code 格式）: .mai/skills/<name>/SKILL.md
  - 扁平式（旧格式，向后兼容）: .mai/skills/<name>.md

目录位置:
  - 项目级 skill: .mai/skills/
  - 用户级 skill: ~/.mai/skills/

frontmatter 字段:
  name        — skill 唯一标识（kebab-case）
  description — 一句话描述（注入 system prompt 的列表项）
  whenToUse   — 触发场景说明（注入 system prompt，帮助模型决策）
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Skill 搜索目录（相对 project_root / 用户家目录）
PROJECT_SKILL_DIR = ".mai/skills"
USER_SKILL_DIR = ".mai/skills"  # 相对 ~

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL)


@dataclass
class Skill:
    """一个已加载的 skill。

    Claude Code 对应物: Skill 元数据 + SKILL.md 正文。
    """
    name: str
    description: str
    when_to_use: str = ""
    content: str = ""  # Markdown 正文（去掉 frontmatter 后）
    source_path: str = ""
    source: str = "project"  # "project" | "user"

    def listing_line(self) -> str:
        """注入 system prompt 的一行描述。对应 available-skills 列表。"""
        line = f"- {self.name}: {self.description}"
        if self.when_to_use:
            line += f" (触发: {self.when_to_use})"
        return line


@dataclass
class SkillRegistry:
    """Skill 注册表 — 按名查找、列出可见 skill。"""
    _skills: dict[str, Skill] = field(default_factory=dict)

    def add(self, skill: Skill) -> None:
        # 项目级覆盖用户级同名 skill
        self._skills[skill.name] = skill

    def get(self, name: str) -> Optional[Skill]:
        return self._skills.get(name)

    def has(self, name: str) -> bool:
        return name in self._skills

    def all(self) -> list[Skill]:
        return list(self._skills.values())

    def __len__(self) -> int:
        return len(self._skills)

    def listing(self) -> str:
        """生成注入 system prompt 的可用 skill 列表块。"""
        if not self._skills:
            return ""
        lines = ["[可用 Skills — 按名调用 Skill 工具激活]"]
        for s in sorted(self._skills.values(), key=lambda x: x.name):
            lines.append(s.listing_line())
        lines.append("[End Skills]")
        return "\n".join(lines)


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """解析 YAML frontmatter（轻量手写解析，不引入 pyyaml 依赖）。

    支持:
      - 行内值: `name: my-skill`
      - 块标量: `description: |` 或 `description: >` 后跟缩进行（多行值）

    Returns:
        (metadata_dict, body_text)
    """
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}, text

    raw_meta, body = match.group(1), match.group(2)
    meta: dict[str, str] = {}
    lines = raw_meta.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line or line.startswith("#"):
            i += 1
            continue
        if ":" not in line:
            i += 1
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip().strip('"').strip("'")

        # 块标量（description: | 或 description: >）或空值后缩进——合并为多行值
        is_block = value in ("|", ">") or (
            not value and i + 1 < len(lines)
            and (lines[i + 1].startswith(" ") or lines[i + 1].startswith("\t"))
        )
        if is_block:
            block_lines: list[str] = []
            j = i + 1
            while j < len(lines) and (lines[j].startswith(" ") or lines[j].startswith("\t")):
                block_lines.append(lines[j].strip())
                j += 1
            value = "\n".join(block_lines) if block_lines else ""
            meta[key] = value
            i = j  # j 已指向下一条未处理行，直接 continue，不再 i += 1
            continue

        meta[key] = value
        i += 1
    return meta, body


def _load_skill_file(path: Path, source: str, fallback_name: str = "") -> Optional[Skill]:
    """从单个 .md 文件加载 skill。

    fallback_name: frontmatter 缺 name 时的兜底名（目录式 skill 用目录名）。
    """
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as exc:
        logger.warning("读取 skill 文件失败 %s: %s", path, exc)
        return None

    meta, body = _parse_frontmatter(text)
    name = meta.get("name") or fallback_name or path.stem
    description = meta.get("description", "")
    when_to_use = meta.get("whenToUse") or meta.get("when_to_use", "")

    if not description:
        description = f"(无描述) {path.name}"

    return Skill(
        name=name,
        description=description,
        when_to_use=when_to_use,
        content=body.strip(),
        source_path=str(path),
        source=source,
    )


def _scan_skill_dir(skill_dir: Path, registry: SkillRegistry, source: str) -> None:
    """扫描一个 skill 目录，两种布局都支持：

    1. 目录式（Claude Code 格式）: <dir>/<name>/SKILL.md
    2. 扁平式（旧格式，向后兼容）: <dir>/<name>.md

    同名时扁平 .md 先注册、目录式后注册会覆盖——实际以 name 去重，
    两者按 add 顺序，后扫描的覆盖先扫描的（目录式在后）。
    """
    # 1. 目录式 skill
    for child in sorted(skill_dir.iterdir()):
        if not child.is_dir():
            continue
        skill_md = child / "SKILL.md"
        if skill_md.is_file():
            skill = _load_skill_file(skill_md, source, fallback_name=child.name)
            if skill:
                registry.add(skill)

    # 2. 扁平 .md（向后兼容）
    for md in sorted(skill_dir.glob("*.md")):
        skill = _load_skill_file(md, source)
        if skill:
            registry.add(skill)


def load_skills(project_root: str = ".") -> SkillRegistry:
    """扫描项目级 + 用户级 skill 目录，构建注册表。

    项目级 skill 优先于用户级同名 skill。
    """
    registry = SkillRegistry()

    # 用户级（~/.mai/skills）
    user_dir = Path.home() / USER_SKILL_DIR
    if user_dir.is_dir():
        _scan_skill_dir(user_dir, registry, source="user")

    # 项目级（.mai/skills）— 覆盖同名用户级
    proj_dir = Path(project_root) / PROJECT_SKILL_DIR
    if proj_dir.is_dir():
        _scan_skill_dir(proj_dir, registry, source="project")

    if registry:
        logger.info("已加载 %d 个 skill: %s",
                    len(registry), [s.name for s in registry.all()])
    return registry


# ── 全局缓存 ──────────────────────────────────────────────

_cached_registry: Optional[SkillRegistry] = None
_cached_root: str = ""


def get_skill_registry(project_root: str = ".") -> SkillRegistry:
    """获取（并缓存）skill 注册表。首次调用时扫描磁盘。"""
    global _cached_registry, _cached_root
    if _cached_registry is None or _cached_root != project_root:
        _cached_registry = load_skills(project_root)
        _cached_root = project_root
    return _cached_registry


def reload_skills(project_root: str = ".") -> SkillRegistry:
    """强制重新扫描磁盘（用于运行时新增 skill 后刷新）。"""
    global _cached_registry, _cached_root
    _cached_registry = load_skills(project_root)
    _cached_root = project_root
    return _cached_registry
