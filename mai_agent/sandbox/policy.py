"""沙箱策略实现 — 命令静态审查 + 路径约束。

沙箱模式（SandboxPolicy.mode）:
  - "off"     : 不审查（默认，向后兼容）
  - "default" : 拦截高危命令 + 路径越界写
  - "strict"  : default + 仅白名单命令 + 禁网络

审查流程:
  validate_command(cmd, cwd) → SandboxDecision(allow, reason, violations)
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional


class SandboxDecision(Enum):
    ALLOW = "allow"
    DENY = "deny"
    ASK = "ask"  # 需用户确认（manual 模式）


@dataclass
class SandboxViolation:
    """一条违规记录。"""
    rule: str        # 规则名
    detail: str      # 具体描述
    severity: str    # "block" | "warn"


@dataclass
class SandboxPolicy:
    """沙箱策略配置。

    Claude Code 对应物: 命令执行前的 useCanUseTool + 沙箱约束。
    """
    mode: str = "off"  # off | default | strict

    # 黑名单：高危命令模式（正则，匹配即 deny）
    # 覆盖：递归删除根、fork 炸弹、关机、强制格式化、覆盖设备
    blacklist_patterns: list[str] = field(default_factory=lambda: [
        # rm -rf /  ~  $HOME  （flag token 含 r 或 f）
        r"\brm\s+-\w*[rfRF]\w*\s+(/|/\*|~|\\|\$HOME)(\s|$)",
        # rm -rf /usr /etc /boot ...
        r"\brm\s+-\w*[rfRF]\w*\s+/(boot|usr|etc|var|bin|lib|root|home)(\s|/|$)",
        r":\(\)\s*\{\s*:\|:\s*&\s*\}\s*;",            # fork bomb :(){ :|:& };
        r"\b(shutdown|reboot|halt|poweroff)\b",
        r"\bmkfs\.\w+\b",                             # 格式化
        r"\bdd\s+.*of=/dev/",                          # dd 写设备
        r">\s*/dev/sd[a-z]",                           # 覆盖块设备
        r"\bchmod\s+-R\s+777\s+/\s*$",                # 全盘 777
        r"\bcurl\s+.*\|\s*(ba)?sh",                    # curl | sh 远程执行
        r"\bwget\s+.*\|\s*(ba)?sh",
    ])

    # 白名单（strict 模式）：仅允许这些命令前缀
    whitelist_commands: list[str] = field(default_factory=lambda: [
        "ls", "cat", "head", "tail", "grep", "rg", "find", "echo", "pwd",
        "wc", "sort", "uniq", "diff", "git", "python", "pip", "pytest",
        "node", "npm", "cargo", "go", "make", "cd", "mkdir", "touch",
        "cp", "mv", "tree", "which", "env", "type",
    ])

    # 网络命令（default 放行，strict 禁止）
    network_commands: list[str] = field(default_factory=lambda: [
        "curl", "wget", "scp", "ssh", "rsync", "ftp", "telnet", "nc",
        "netcat",
    ])

    # 可写路径白名单（cwd 之外允许写的目录）。空 = 仅 cwd 可写
    writable_paths: list[str] = field(default_factory=list)

    # 是否约束工作目录（命令的 cwd 必须在 sandbox_root 内）
    constrain_cwd: bool = True

    @property
    def active(self) -> bool:
        return self.mode != "off"

    def _match_blacklist(self, cmd: str) -> Optional[SandboxViolation]:
        for pattern in self.blacklist_patterns:
            if re.search(pattern, cmd, re.IGNORECASE):
                return SandboxViolation(
                    rule="blacklist",
                    detail=f"命中黑名单模式: {pattern}",
                    severity="block",
                )
        return None

    def _check_whitelist(self, cmd: str) -> Optional[SandboxViolation]:
        """strict 模式下检查命令前缀是否在白名单。"""
        first = _first_command(cmd)
        if first is None:
            return None
        # 允许 env VAR=... cmd 形式
        if first in ("env", "sudo"):
            return None
        if first not in self.whitelist_commands:
            return SandboxViolation(
                rule="whitelist",
                detail=f"命令 '{first}' 不在白名单（strict 模式）",
                severity="block",
            )
        return None

    def _check_network(self, cmd: str) -> Optional[SandboxViolation]:
        if self.mode != "strict":
            return None
        first = _first_command(cmd)
        if first and first in self.network_commands:
            return SandboxViolation(
                rule="network",
                detail=f"strict 模式禁止网络命令: {first}",
                severity="block",
            )
        return None

    def _check_write_paths(self, cmd: str, cwd: str) -> Optional[SandboxViolation]:
        """检查重定向/写操作的目标路径是否越界。

        仅在 constrain_cwd 且 writable_paths 非空时做严格检查。
        检测 > file, >> file, tee file 等写目标。
        """
        if not self.constrain_cwd and not self.writable_paths:
            return None

        write_targets = _extract_write_targets(cmd)
        if not write_targets:
            return None

        allowed_roots = [Path(cwd).resolve()]
        for p in self.writable_paths:
            allowed_roots.append(Path(p).resolve())

        for target in write_targets:
            # 跳过 /dev/null 等设备
            if target in ("/dev/null", "NUL"):
                continue
            tgt = Path(target)
            if not tgt.is_absolute():
                tgt = (Path(cwd) / tgt)
            tgt = tgt.resolve()
            if not any(_is_relative_to(tgt, root) for root in allowed_roots):
                return SandboxViolation(
                    rule="path_boundary",
                    detail=f"写目标越界（不在允许路径内）: {target}",
                    severity="block",
                )
        return None

    def validate(self, cmd: str, cwd: str) -> tuple[SandboxDecision, list[SandboxViolation]]:
        """审查命令，返回 (决策, 违规列表)。"""
        if not self.active:
            return SandboxDecision.ALLOW, []

        violations: list[SandboxViolation] = []

        v = self._match_blacklist(cmd)
        if v:
            violations.append(v)

        v = self._check_whitelist(cmd)
        if v:
            violations.append(v)

        v = self._check_network(cmd)
        if v:
            violations.append(v)

        v = self._check_write_paths(cmd, cwd)
        if v:
            violations.append(v)

        if any(v.severity == "block" for v in violations):
            return SandboxDecision.DENY, violations
        return SandboxDecision.ALLOW, violations


# ── 预置策略 ──────────────────────────────────────────────


def default_policy(writable_paths: Optional[list[str]] = None) -> SandboxPolicy:
    """默认沙箱：拦截高危命令 + 路径越界写，不禁网络。"""
    return SandboxPolicy(
        mode="default",
        writable_paths=writable_paths or [],
        constrain_cwd=True,
    )


def strict_policy(writable_paths: Optional[list[str]] = None) -> SandboxPolicy:
    """严格沙箱：仅白名单命令 + 禁网络 + 路径约束。"""
    return SandboxPolicy(
        mode="strict",
        writable_paths=writable_paths or [],
        constrain_cwd=True,
    )


def validate_command(
    cmd: str, cwd: str, policy: Optional[SandboxPolicy] = None,
) -> tuple[SandboxDecision, list[SandboxViolation]]:
    """便捷入口：用给定策略审查命令。"""
    policy = policy or default_policy()
    return policy.validate(cmd, cwd)


# ── 命令解析辅助 ──────────────────────────────────────────


def _first_command(cmd: str) -> Optional[str]:
    """提取命令行的第一个命令词（处理管道/分号取第一段）。"""
    try:
        # 取第一个管道/分号/&&/|| 段
        first_segment = re.split(r"[|;&]", cmd.strip(), maxsplit=1)[0].strip()
        tokens = shlex.split(first_segment, posix=True)
        if not tokens:
            return None
        # 跳过环境变量赋值 (FOO=bar cmd)
        for t in tokens:
            if "=" in t and re.match(r"^[A-Z_][A-Z0-9_]*=", t):
                continue
            return Path(t).name  # 取 basename（git.exe → git）
        return None
    except ValueError:
        # shlex 解析失败（引号不匹配等）→ 退化处理
        tokens = cmd.strip().split()
        return tokens[0] if tokens else None


def _extract_write_targets(cmd: str) -> list[str]:
    """从命令中提取写操作的目标文件路径。

    识别: > file, >> file, tee file
    """
    targets: list[str] = []
    # > file / >> file
    for m in re.finditer(r"(?:>>|>)\s*(\S+)", cmd):
        targets.append(m.group(1))
    # tee file
    for m in re.finditer(r"\btee\s+(?!-)(\S+)", cmd):
        targets.append(m.group(1))
    return targets


def _is_relative_to(path: Path, root: Path) -> bool:
    """Path.is_relative_to 的兼容实现（<3.9 无此方法）。"""
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False
