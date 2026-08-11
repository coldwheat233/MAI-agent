"""File snapshots — save file state before edits for undo.

Modeled after Claude Code's fileHistory utility.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

SNAPSHOT_DIR = ".mai/snapshots"


def snapshot_dir(project_root: str = ".") -> Path:
    return Path(project_root) / SNAPSHOT_DIR


def save_snapshot(file_path: str, project_root: str = ".") -> str:
    """Save a copy of a file before editing. Returns snapshot ID."""
    src = Path(file_path)
    if not src.exists():
        return ""

    snap_dir = snapshot_dir(project_root)
    snap_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    safe_name = src.name.replace(".", "_")
    snap_id = f"{safe_name}_{ts}"
    snap_path = snap_dir / snap_id

    snap_path.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")

    # Also log to index
    index_path = snap_dir / "index.json"
    index: list[dict] = []
    if index_path.exists():
        index = json.loads(index_path.read_text(encoding="utf-8"))
    index.append({
        "id": snap_id,
        "original": str(src),
        "size": src.stat().st_size,
        "time": ts,
    })
    index_path.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8")

    return snap_id


def restore_snapshot(snap_id: str, project_root: str = ".") -> str | None:
    """Restore a file from snapshot. Returns the file path or None."""
    snap_dir = snapshot_dir(project_root)
    snap_path = snap_dir / snap_id
    if not snap_path.exists():
        return None

    # Find original path from index
    index_path = snap_dir / "index.json"
    if index_path.exists():
        index = json.loads(index_path.read_text(encoding="utf-8"))
        for entry in index:
            if entry["id"] == snap_id:
                original = entry["original"]
                Path(original).write_text(snap_path.read_text(encoding="utf-8"), encoding="utf-8")
                return original
    return None


def list_snapshots(project_root: str = ".") -> list[dict]:
    """List all snapshots."""
    index_path = snapshot_dir(project_root) / "index.json"
    if not index_path.exists():
        return []
    return json.loads(index_path.read_text(encoding="utf-8"))
