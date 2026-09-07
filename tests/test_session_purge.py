"""L1 级联清理回归：删除会话时清掉该会话的日志/轨迹原文副本。

策略分层（详见 db.purge_session docstring + .mai/skills/mai-services）：
  L0 会话原文（SQLite）与 L1 原文副本（.mai/logs|traces/<sid>.jsonl）
  随删除清掉；L2 摘要 / L3 知识卡片属聚合产物，不随会话删除。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from mai_agent import db


def _plant_artifacts(root: Path, session_id: str) -> list[Path]:
    paths = [
        root / ".mai" / "logs" / f"{session_id}.jsonl",
        root / ".mai" / "traces" / f"{session_id}.jsonl",
    ]
    for p in paths:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text('{"event": "planted"}\n', encoding="utf-8")
    return paths


class TestPurgeSession:
    def test_purge_removes_artifacts_and_row(self, tmp_path, monkeypatch):
        sid = "sess_clean_01"
        planted = _plant_artifacts(tmp_path, sid)
        monkeypatch.setattr(db, "get_session_workspace",
                            lambda s, project_root=".": str(tmp_path))
        deleted: list[str] = []
        monkeypatch.setattr(db, "delete_session",
                            lambda s, project_root=".": (deleted.append(s) or True))

        info = asyncio.run(db.purge_session(sid, str(tmp_path)))
        assert info["deleted"] is True
        assert deleted == [sid]
        for p in planted:
            assert not p.exists(), f"{p} 应被级联删除"
        assert sorted(Path(f).name for f in info["deleted_files"]) == [
            f"{sid}.jsonl", f"{sid}.jsonl",
        ]

    def test_purge_unknown_session_no_crash(self, tmp_path, monkeypatch):
        monkeypatch.setattr(db, "get_session_workspace",
                            lambda s, project_root=".": None)
        monkeypatch.setattr(db, "delete_session",
                            lambda s, project_root=".": False)
        info = asyncio.run(db.purge_session("missing_000", str(tmp_path)))
        assert info["deleted"] is False
        assert info["deleted_files"] == []

    def test_purge_without_artifacts_still_deletes_row(self, tmp_path, monkeypatch):
        monkeypatch.setattr(db, "get_session_workspace",
                            lambda s, project_root=".": str(tmp_path))
        monkeypatch.setattr(db, "delete_session",
                            lambda s, project_root=".": True)
        info = asyncio.run(db.purge_session("sess_nofiles", str(tmp_path)))
        assert info["deleted"] is True
        assert info["deleted_files"] == []  # 没有 jsonl 不报错
