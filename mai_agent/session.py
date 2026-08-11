"""会话持久化 — SQLite 薄壳。

历史：本模块之前写 JSON 文件到 .mai/workspaces/{slug}/sessions/*.json。
现在统一走 mai_agent.db（~/.mai/mai.db 单文件 + WAL）。

本文件只保留旧公开签名，内部全部转调 db.*；调用方（server.py / cli.py）零改动。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

from mai_agent.core.models import Message

from mai_agent import db

logger = logging.getLogger(__name__)

# 任何导入都触发一次 DB 初始化（含一次性 JSON 迁移）
db.init_db()

# ── 公开 API（保持旧 session.py 的签名，调用方无感） ─────


def save_session(
    session_id: str,
    messages: list[Message],
    project_root: str = ".",
) -> Path:
    """持久化会话消息。返回 DB 文件路径（兼容旧返回 Path 的调用方）。"""
    db.save_session(session_id, messages, project_root)
    return db.DB_PATH


def load_session(session_id: str, project_root: str = ".") -> Optional[list[Message]]:
    return db.load_session(session_id, project_root)


def get_session_workspace(session_id: str, project_root: str = ".") -> Optional[str]:
    return db.get_session_workspace(session_id, project_root)


def list_sessions(project_root: str = ".") -> list[dict[str, Any]]:
    return db.list_sessions(project_root)


def list_workspaces(base_root: str = ".") -> list[dict[str, Any]]:
    """列出所有已知 workspace。base_root 参数在 SQLite 模型下被忽略（DB 是用户级全局）。"""
    return db.list_workspaces()


def delete_session(session_id: str, project_root: str = ".") -> bool:
    return db.delete_session(session_id, project_root)


def search_sessions(keyword: str, base_root: str = ".") -> list[dict[str, Any]]:
    return db.search_sessions(keyword, base_root)


def ensure_dirs(project_root: str) -> None:
    """兼容旧 API：现在项目本地 .mai/ 不再需要，DB 在 ~/.mai/mai.db。"""
    db.ensure_dirs(project_root)
