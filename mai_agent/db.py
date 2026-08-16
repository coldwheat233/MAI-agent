"""SQLite 持久层 — 替代旧的 JSON 文件 + 浏览器 localStorage。

设计：
  - 单文件 ~/.mai/mai.db（WAL 模式，并发读 / 单写者不冲突）
  - 公开 API：save_session / load_session / list_sessions / list_workspaces /
    register_workspace / unregister_workspace / delete_session / search_sessions /
    get_session_workspace
  - 写操作走 with conn: 事务（要么全成、要么全不成）
  - 首次启动从旧 JSON 文件做一次性迁移，不动旧文件只读取后写入 DB

Schema:
  workspaces(path PK, slug, last_used, created_at)
  sessions(id PK, workspace_path FK, updated_at, message_count, created_at)
  messages(id PK, session_id FK, position, role, content, tool_calls JSON,
           tool_call_id, name)
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional

from mai_agent.core.models import (
    AssistantMessage,
    Message,
    SystemMessage,
    ToolResultMessage,
    UserMessage,
)
from mai_agent.core.models import ToolCall, FunctionCall

logger = logging.getLogger(__name__)


# ── 路径与连接 ───────────────────────────────────────────

MAI_DIR = ".mai"
GLOBAL_MAI_DIR = Path.home() / ".mai"
DB_PATH = GLOBAL_MAI_DIR / "mai.db"

_conn_lock = threading.Lock()
# 所有连接访问（读+写）的串行化锁。save_session 走 asyncio.to_thread 线程池，
# 多个工作区并发保存时会在同一 _conn 上各自 BEGIN IMMEDIATE → 嵌套事务崩溃。
# RLock 可重入，_session_title 等在持锁函数内再访问连接也安全。
_db_lock = threading.RLock()
_conn: sqlite3.Connection | None = None


def _connect() -> sqlite3.Connection:
    """打开 DB 连接 + 应用推荐 PRAGMA。"""
    GLOBAL_MAI_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(
        str(DB_PATH),
        check_same_thread=False,    # asyncio + to_thread 共用
        isolation_level=None,       # 我们显式 BEGIN/COMMIT
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def get_conn() -> sqlite3.Connection:
    """进程内单例连接。"""
    global _conn
    if _conn is None:
        with _conn_lock:
            if _conn is None:
                _conn = _connect()
    return _conn


@contextmanager
def transaction() -> Iterator[sqlite3.Connection]:
    """with transaction(): ... — 自动 BEGIN / COMMIT / ROLLBACK（跨线程串行化）。"""
    with _db_lock:
        conn = get_conn()
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
        except Exception:
            conn.execute("ROLLBACK")
            raise
        else:
            conn.execute("COMMIT")


# ── Schema ──────────────────────────────────────────────


SCHEMA = """
CREATE TABLE IF NOT EXISTS _meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS workspaces (
    path       TEXT PRIMARY KEY,
    slug       TEXT NOT NULL,
    last_used  TEXT,
    created_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_workspaces_last_used ON workspaces(last_used DESC);

CREATE TABLE IF NOT EXISTS sessions (
    id            TEXT PRIMARY KEY,
    workspace_path TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    message_count INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT,
    FOREIGN KEY (workspace_path) REFERENCES workspaces(path) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_sessions_workspace_updated
    ON sessions(workspace_path, updated_at DESC);

CREATE TABLE IF NOT EXISTS messages (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id   TEXT NOT NULL,
    position     INTEGER NOT NULL,
    role         TEXT NOT NULL,
    content      TEXT,
    tool_calls   TEXT,
    tool_call_id TEXT,
    name         TEXT,
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_messages_session_position
    ON messages(session_id, position);
"""


def init_db() -> None:
    """建表 + 一次性 JSON 迁移。"""
    conn = get_conn()
    # executescript 自己 commit，跟显式 transaction 互斥——逐条 execute
    for stmt in SCHEMA.split(";\n"):
        stmt = stmt.strip()
        if stmt:
            conn.execute(stmt)
    migrated = conn.execute(
        "SELECT value FROM _meta WHERE key = 'migrated_from_json'"
    ).fetchone()
    if migrated is None:
        try:
            _migrate_from_json()
            conn.execute(
                "INSERT OR REPLACE INTO _meta(key, value) VALUES (?, ?)",
                ("migrated_from_json", datetime.now(timezone.utc).isoformat()),
            )
            logger.info("JSON → SQLite 迁移完成")
        except Exception as exc:
            logger.warning("JSON 迁移失败（旧数据可能需要手动处理）: %s", exc)


# ── 迁移 ────────────────────────────────────────────────


def _workspace_slug(cwd: str) -> str:
    p = str(Path(cwd).resolve())
    return re.sub(r'[<>:"|?*\\]', '_', p.replace(':', '_').replace('/', '_'))


def _scan_workspace_dirs(base_root: str) -> list[Path]:
    """扫所有已知 workspace 目录（本地 + 全局索引）。"""
    dirs: list[Path] = []
    seen: set[str] = set()

    def _add(d: Path) -> None:
        if str(d) not in seen and d.is_dir():
            seen.add(str(d))
            dirs.append(d)

    local_root = Path(base_root) / "workspaces"
    if local_root.exists():
        for d in local_root.iterdir():
            if d.is_dir():
                _add(d)

    idx = GLOBAL_MAI_DIR / "workspaces.json"
    if idx.exists():
        try:
            data = json.loads(idx.read_text(encoding="utf-8"))
            for slug, entry in data.items():
                p = entry.get("path")
                if p:
                    _add(Path(p) / "workspaces" / slug)
        except Exception:
            pass
    return dirs


def _migrate_from_json() -> None:
    """一次性把旧 JSON sessions / workspaces.json 写进 SQLite。

    数据源优先级：
      1. ~/.mai/workspaces.json（全局索引，权威列出所有 workspace 路径）
      2. 兼容旧路径：每个 path/.mai/sessions/*.json（极早期格式）
    不再依赖 cwd——DB 是用户级全局的。"""
    idx = GLOBAL_MAI_DIR / "workspaces.json"
    paths: list[tuple[str, str]] = []  # (path, slug)

    if idx.exists():
        try:
            data = json.loads(idx.read_text(encoding="utf-8"))
            for slug, entry in data.items():
                p = entry.get("path")
                if p:
                    paths.append((str(Path(p).resolve()), slug))
        except Exception as exc:
            logger.warning("解析 workspaces.json 失败: %s", exc)

    # 兜底：扫用户 home 下所有 .mai/workspaces/*（如果全局索引丢了）
    for d in (GLOBAL_MAI_DIR / "workspaces").iterdir() if (GLOBAL_MAI_DIR / "workspaces").exists() else []:
        if d.is_dir():
            meta = d / "workspace.json"
            wp = None
            if meta.exists():
                try:
                    wp = json.loads(meta.read_text(encoding="utf-8")).get("path")
                except Exception:
                    pass
            if wp:
                resolved = str(Path(wp).resolve())
                if not any(p == resolved for p, _ in paths):
                    paths.append((resolved, d.name))

    # 注册所有 workspace
    for path, slug in paths:
        try:
            with transaction() as c:
                c.execute(
                    "INSERT OR IGNORE INTO workspaces(path, slug, last_used, created_at) VALUES (?, ?, ?, ?)",
                    (path, slug, None, datetime.now(timezone.utc).isoformat()),
                )
        except Exception as exc:
            logger.warning("注册 workspace %s 失败: %s", path, exc)

    # 迁移 sessions
    for path, slug in paths:
        # 新路径：{path}/.mai/workspaces/{slug}/sessions/*.json
        new_dir = Path(path) / ".mai" / "workspaces" / slug / "sessions"
        # 旧路径：{path}/.mai/sessions/*.json
        old_dir = Path(path) / ".mai" / "sessions"
        for sessions_dir in (new_dir, old_dir):
            if not sessions_dir.exists():
                continue
            for f in sorted(sessions_dir.glob("*.json")):
                try:
                    data = json.loads(f.read_text(encoding="utf-8"))
                except Exception:
                    continue
                sid = data.get("session_id") or f.stem
                _migrate_one_session(sid, path, data)


def _migrate_one_session(sid: str, workspace_path: str, data: dict) -> None:
    try:
        with transaction() as c:
            c.execute(
                "INSERT OR IGNORE INTO sessions(id, workspace_path, updated_at, message_count, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (sid, workspace_path,
                 data.get("updated_at") or datetime.now(timezone.utc).isoformat(),
                 data.get("message_count", 0),
                 datetime.now(timezone.utc).isoformat()),
            )
            for pos, m in enumerate(data.get("messages", [])):
                c.execute(
                    "INSERT INTO messages(session_id, position, role, content, tool_calls, tool_call_id, name)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (sid, pos,
                     m.get("role", "user"),
                     m.get("content"),
                     json.dumps(m.get("tool_calls"), ensure_ascii=False) if m.get("tool_calls") else None,
                     m.get("tool_call_id"),
                     m.get("name")),
                )
    except Exception as exc:
        logger.warning("迁移 session %s 失败: %s", sid, exc)


# ── Workspaces ───────────────────────────────────────────


def register_workspace(cwd: str) -> None:
    """注册一个 workspace 路径（用户级，已存在则刷新 last_used）。"""
    resolved = str(Path(cwd).resolve())
    slug = _workspace_slug(resolved)
    now = datetime.now(timezone.utc).isoformat()
    with transaction() as c:
        c.execute(
            "INSERT INTO workspaces(path, slug, last_used, created_at) VALUES (?, ?, ?, ?)"
            " ON CONFLICT(path) DO UPDATE SET last_used = excluded.last_used, slug = excluded.slug",
            (resolved, slug, now, now),
        )


def unregister_workspace(cwd: str) -> None:
    """从全局索引移除（不会删磁盘上的项目目录）。"""
    resolved = str(Path(cwd).resolve())
    with transaction() as c:
        c.execute("DELETE FROM workspaces WHERE path = ?", (resolved,))


def list_workspaces() -> list[dict[str, Any]]:
    with _db_lock:
        conn = get_conn()
        rows = conn.execute(
            "SELECT w.path, w.slug, w.last_used, w.created_at,"
            "       (SELECT COUNT(*) FROM sessions s WHERE s.workspace_path = w.path) AS session_count"
            " FROM workspaces w"
            " ORDER BY COALESCE(w.last_used, '') DESC, w.created_at DESC"
        ).fetchall()
    result = []
    for r in rows:
        result.append({
            "path": r["path"],
            "slug": r["slug"],
            "last_used": r["last_used"] or "",
            "created_at": r["created_at"] or "",
            "session_count": r["session_count"],
            "exists": Path(r["path"]).is_dir(),
        })
    return result


def touch_workspace(cwd: str) -> None:
    """切换工作区时更新 last_used（不创建新行）。"""
    resolved = str(Path(cwd).resolve())
    with transaction() as c:
        c.execute(
            "UPDATE workspaces SET last_used = ? WHERE path = ?",
            (datetime.now(timezone.utc).isoformat(), resolved),
        )


# ── Sessions ────────────────────────────────────────────


def save_session(
    session_id: str,
    messages: list[Message],
    project_root: str = ".",
) -> None:
    """持久化一个 session 的全部 messages（事务内：upsert session row + 替换 messages）。"""
    workspace_path = str(Path(project_root).resolve())
    # 确保 workspace 存在
    register_workspace(workspace_path)
    now = datetime.now(timezone.utc).isoformat()
    serialized = [_msg_to_dict(m) for m in messages]
    with transaction() as c:
        c.execute(
            "INSERT INTO sessions(id, workspace_path, updated_at, message_count, created_at)"
            " VALUES (?, ?, ?, ?, ?)"
            " ON CONFLICT(id) DO UPDATE SET"
            "   workspace_path = excluded.workspace_path,"
            "   updated_at     = excluded.updated_at,"
            "   message_count  = excluded.message_count",
            (session_id, workspace_path, now, len(messages), now),
        )
        c.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        for pos, d in enumerate(serialized):
            c.execute(
                "INSERT INTO messages(session_id, position, role, content, tool_calls, tool_call_id, name)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (session_id, pos, d["role"], d.get("content"),
                 json.dumps(d.get("tool_calls"), ensure_ascii=False) if d.get("tool_calls") else None,
                 d.get("tool_call_id"), d.get("name")),
            )


def load_session(session_id: str, project_root: str = ".") -> Optional[list[Message]]:
    """按 id 加载 session 的 messages（不依赖 cwd——文件被 SQL 索引后全局唯一）。"""
    with _db_lock:
        conn = get_conn()
        row = conn.execute(
            "SELECT id FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        if row is None:
            return None
        rows = conn.execute(
            "SELECT role, content, tool_calls, tool_call_id, name FROM messages"
            " WHERE session_id = ? ORDER BY position ASC", (session_id,)
        ).fetchall()
    msgs = [_row_to_msg(r) for r in rows]
    # 清理半截 tool_calls
    try:
        from mai_agent.core.loop import strip_incomplete_tool_calls
        msgs = strip_incomplete_tool_calls(msgs)
    except Exception:
        pass
    return msgs


def get_session_workspace(session_id: str, project_root: str = ".") -> Optional[str]:
    with _db_lock:
        conn = get_conn()
        row = conn.execute(
            "SELECT workspace_path FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
    if row is None:
        return None
    return row["workspace_path"]


def _session_title(conn: sqlite3.Connection, session_id: str) -> str:
    """取 session 首条 user 消息压成一行短标题（截断 50 字），无则空串。"""
    row = conn.execute(
        "SELECT content FROM messages WHERE session_id = ? AND role = 'user'"
        " ORDER BY position ASC LIMIT 1",
        (session_id,),
    ).fetchone()
    if row is None or not row["content"]:
        return ""
    return " ".join(row["content"].split())[:50]


def list_sessions(project_root: str = ".") -> list[dict[str, Any]]:
    """当前 workspace 的所有 session（按 updated_at desc）。"""
    workspace_path = str(Path(project_root).resolve())
    with _db_lock:
        conn = get_conn()
        rows = conn.execute(
            "SELECT id, message_count, updated_at FROM sessions"
            " WHERE workspace_path = ? ORDER BY updated_at DESC",
            (workspace_path,),
        ).fetchall()
        return [
            {
                "session_id": r["id"],
                "message_count": r["message_count"],
                "updated_at": r["updated_at"] or "",
                "title": _session_title(conn, r["id"]),
            }
            for r in rows
        ]


def delete_session(session_id: str, project_root: str = ".") -> bool:
    with transaction() as c:
        cur = c.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        return cur.rowcount > 0


def search_sessions(keyword: str, project_root: str = ".") -> list[dict[str, Any]]:
    """跨所有 workspace 按 keyword 搜 messages.content。"""
    kw = keyword.lower()
    with _db_lock:
        conn = get_conn()
        rows = conn.execute(
            "SELECT s.id, s.message_count, s.updated_at, s.workspace_path,"
            "       m.content, m.position"
            " FROM sessions s JOIN messages m ON m.session_id = s.id"
            " WHERE LOWER(IFNULL(m.content, '')) LIKE ?"
            " ORDER BY s.updated_at DESC, m.position ASC",
            (f"%{kw}%",),
        ).fetchall()
    by_session: dict[str, dict[str, Any]] = {}
    for r in rows:
        sid = r["id"]
        if sid not in by_session:
            by_session[sid] = {
                "session_id": sid,
                "message_count": r["message_count"],
                "updated_at": r["updated_at"] or "",
                "workspace": r["workspace_path"],
                "matches": [],
            }
        if len(by_session[sid]["matches"]) < 3 and r["content"]:
            content = r["content"]
            idx = content.lower().find(kw)
            start = max(0, idx - 40)
            end = min(len(content), idx + len(kw) + 60)
            snippet = content[start:end]
            if start > 0:
                snippet = "..." + snippet
            if end < len(content):
                snippet = snippet + "..."
            by_session[sid]["matches"].append(snippet)
    # 补充标题（首条 user 消息）
    with _db_lock:
        for sid in by_session:
            by_session[sid]["title"] = _session_title(conn, sid)
    return list(by_session.values())


def get_session_message_count(session_id: str) -> int:
    with _db_lock:
        conn = get_conn()
        row = conn.execute(
            "SELECT message_count FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
    return row["message_count"] if row else 0


# ── 兼容旧 session.py 调用的钩子（保持 cli.py 可用） ───


def ensure_dirs(project_root: str) -> None:
    """保留兼容：现在只确保全局 DB 目录存在。"""
    GLOBAL_MAI_DIR.mkdir(parents=True, exist_ok=True)
    # workspace 本地 .mai 不再强需要；register_workspace 会建
    local = Path(project_root) / MAI_DIR
    if not local.exists():
        # 不强制建——SQLite DB 在 ~/.mai/，项目本地不再产生文件
        pass


# ── 消息序列化 / 反序列化 ─────────────────────────────


def _msg_to_dict(m: Message) -> dict[str, Any]:
    d: dict[str, Any] = {"role": m.role}
    if m.content is not None:
        d["content"] = m.content
    if m.tool_calls:
        d["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.function.name if tc.function else "",
                    "arguments": tc.function.arguments if tc.function else "{}",
                },
            }
            for tc in m.tool_calls
        ]
    if m.tool_call_id:
        d["tool_call_id"] = m.tool_call_id
    if m.name:
        d["name"] = m.name
    return d


def _row_to_msg(r: sqlite3.Row) -> Message:
    role = r["role"]
    content = r["content"]
    tool_call_id = r["tool_call_id"]
    name = r["name"]
    tool_calls_raw = json.loads(r["tool_calls"]) if r["tool_calls"] else None

    if role == "system":
        return SystemMessage(content=content)
    elif role == "assistant":
        tool_calls = None
        if tool_calls_raw:
            tool_calls = [
                ToolCall(
                    id=tc["id"],
                    function=FunctionCall(
                        name=tc["function"]["name"],
                        arguments=tc["function"]["arguments"],
                    ),
                )
                for tc in tool_calls_raw
            ]
        return AssistantMessage(content=content, tool_calls=tool_calls)
    elif role == "tool":
        return ToolResultMessage(content=content, tool_call_id=tool_call_id, name=name)
    else:
        return UserMessage(content=content)
