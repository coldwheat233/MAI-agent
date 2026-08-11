"""Learning Queue — tracks unknown concepts for later study & Feishu sync.

Data stored in .mai/knowledge/learning_queue.json
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class LearningItem:
    id: str
    concept: str
    context: str = ""
    priority: str = "medium"  # low | medium | high
    status: str = "pending"   # pending | learned | synced
    notes: str = ""
    created_at: str = ""
    learned_at: Optional[str] = None
    feishu_doc_token: Optional[str] = None


def _queue_path(base_dir: str = ".") -> Path:
    return Path(base_dir) / ".mai" / "knowledge" / "learning_queue.json"


def _load(base_dir: str = ".") -> list[dict]:
    p = _queue_path(base_dir)
    if not p.exists():
        return []
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save(items: list[dict], base_dir: str = "."):
    p = _queue_path(base_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def list_items(base_dir: str = ".") -> list[dict]:
    """List all learning queue items, newest first."""
    items = _load(base_dir)
    return sorted(items, key=lambda x: x.get("created_at", ""), reverse=True)


def add_item(concept: str, context: str = "", priority: str = "medium",
             base_dir: str = ".") -> dict:
    """Add a new concept to the learning queue."""
    items = _load(base_dir)
    now = datetime.now(timezone.utc).isoformat()
    item = {
        "id": uuid.uuid4().hex[:12],
        "concept": concept.strip(),
        "context": context.strip(),
        "priority": priority,
        "status": "pending",
        "notes": "",
        "created_at": now,
        "learned_at": None,
        "feishu_doc_token": None,
    }
    items.append(item)
    _save(items, base_dir)
    return item


def update_item(item_id: str, updates: dict, base_dir: str = ".") -> Optional[dict]:
    """Update a learning queue item. Set status='learned' to mark as learned."""
    items = _load(base_dir)
    for i, item in enumerate(items):
        if item.get("id") == item_id:
            if updates.get("status") == "learned" and not item.get("learned_at"):
                updates["learned_at"] = datetime.now(timezone.utc).isoformat()
            items[i] = {**item, **updates}
            _save(items, base_dir)
            return items[i]
    return None


def delete_item(item_id: str, base_dir: str = ".") -> bool:
    """Remove an item from the queue."""
    items = _load(base_dir)
    new_items = [i for i in items if i.get("id") != item_id]
    if len(new_items) == len(items):
        return False
    _save(new_items, base_dir)
    return True


def get_stats(base_dir: str = ".") -> dict:
    """Get queue statistics."""
    items = _load(base_dir)
    pending = sum(1 for i in items if i.get("status") == "pending")
    learned = sum(1 for i in items if i.get("status") == "learned")
    synced = sum(1 for i in items if i.get("status") == "synced")
    return {"total": len(items), "pending": pending, "learned": learned, "synced": synced}
