"""随机化/模糊回归 — 对冲"测试集自设计过拟合"。

- cron：随机生成 5 字段表达式，用**独立暴力实现**逐分钟扫描对照 next_fire；
- segtree：随机 插入/删除/保存/重载 操作序列，用**朴素列表模型**对照
  tag/区间查询结果，末尾校验段树不变量（verify）。

默认固定种子（可复现）；设环境变量 MAI_FUZZ_SEED 可换随机序列跑更多轮。
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import string
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from mai_agent.services.cron_scheduler import next_fire, parse_cron
from mai_agent.services.memory_segtree import MemorySegTree

UTC = timezone.utc
SEED = int(os.environ.get("MAI_FUZZ_SEED", "20260907"))


def _rng() -> random.Random:
    return random.Random(SEED)


# ── cron 模糊 ──────────────────────────────────────────────


def _pick(rng: random.Random, field: str) -> str:
    """按字段语法随机生成一个合法子字段。"""
    lo, hi = {"min": (0, 59), "hour": (0, 23), "dom": (1, 31),
              "mon": (1, 12), "dow": (0, 6)}[field]
    kind = rng.random()
    if kind < 0.3:
        return "*"
    if kind < 0.5:
        step = rng.choice([2, 5, 10, 15, 30])
        return f"*/{step}"
    if kind < 0.65:
        a = rng.randint(lo, hi - 1)
        b = rng.randint(a + 1, min(hi, a + 20))
        return f"{a}-{b}"
    if kind < 0.8:
        a = rng.randint(lo, hi - 1)
        b = rng.randint(a + 1, min(hi, a + 20))
        step = rng.choice([2, 3, 5])
        return f"{a}-{b}/{step}"
    if kind < 0.92:
        return str(rng.randint(lo, hi))
    # 列表
    a, b = rng.randint(lo, hi), rng.randint(lo, hi)
    return f"{a},{b}"


def _random_expr(rng: random.Random) -> str:
    return " ".join(_pick(rng, f) for f in ("min", "hour", "dom", "mon", "dow"))


def _brute_next(parsed: dict, after: datetime) -> datetime | None:
    """独立暴力参考实现：逐分钟扫描找第一个命中。"""
    cur = after.replace(second=0, microsecond=0) + timedelta(minutes=1)
    cap = after + timedelta(days=400)
    dom_star = parsed["dom"] == set(range(1, 32))
    dow_star = parsed["dow"] == set(range(0, 7))
    while cur <= cap:
        if (cur.minute in parsed["minute"] and cur.hour in parsed["hour"]
                and cur.month in parsed["mon"]):
            wd = (cur.weekday() + 1) % 7
            day_ok = cur.day in parsed["dom"]
            wd_ok = wd in parsed["dow"]
            if dom_star and dow_star:
                ok = True
            elif not dom_star and not dow_star:
                ok = day_ok or wd_ok
            elif not dom_star:
                ok = day_ok
            else:
                ok = wd_ok
            if ok:
                return cur
        cur += timedelta(minutes=1)
    return None


class TestCronFuzz:
    def test_random_expressions_match_brute_force(self):
        rng = _rng()
        checked = 0
        for _ in range(200):
            expr = _random_expr(rng)
            parsed = parse_cron(expr)
            if parsed is None:  # 生成器产出无效组合（如 dom/dow 永不满足仍合法）—直接跳过
                continue
            after = datetime(
                rng.randint(2025, 2027), rng.randint(1, 12), rng.randint(1, 28),
                rng.randint(0, 23), rng.randint(0, 59), tzinfo=UTC,
            )
            got = next_fire(parsed, after)
            expected = _brute_next(parsed, after)
            assert got == expected, f"expr={expr!r} after={after} got={got} expected={expected}"
            checked += 1
        assert checked >= 150, f"有效用例不足: {checked}"

    def test_invalid_garbage_never_raises(self):
        rng = _rng()
        alphabet = string.ascii_lowercase + string.digits + "*-/, "
        for _ in range(200):
            expr = "".join(rng.choice(alphabet) for _ in range(rng.randint(1, 30)))
            # 不抛异常即可（合法则行为正确性由上方用例覆盖）
            parse_cron(expr)


# ── segtree 随机操作 ───────────────────────────────────────


def _write_card(root: Path, name: str, day: date, tags: list[str]) -> None:
    d = root / ".mai" / "memory"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.md").write_text(
        "---\n"
        f"name: {name}\n"
        f"description: card {name}\n"
        "type: reference\n"
        f"tags: [{', '.join(tags)}]\n"
        f"created_at: {day.isoformat()}\n"
        "---\n"
        f"body {name}\n",
        encoding="utf-8",
    )


def _remove_card(root: Path, name: str) -> None:
    p = root / ".mai" / "memory" / f"{name}.md"
    if p.exists():
        p.unlink()


class TestSegtreeRandomOps:
    def test_random_op_sequence_vs_naive(self, tmp_path):
        rng = _rng()
        tag_pool = ["a", "b", "c", "d", "e"]
        model: list[dict] = []  # {name, date, tags}
        tree = MemorySegTree(str(tmp_path))
        existing = set()
        next_id = 0
        name_pool = [f"c{i:03d}" for i in range(400)]

        def naive_tag(tag: str) -> list[str]:
            return sorted(m["name"] for m in model if tag in m["tags"])

        def naive_range(lo: date, hi: date, tag=None) -> list[str]:
            out = []
            for m in model:
                if lo <= m["date"] <= hi and (tag is None or tag in m["tags"]):
                    out.append(m["name"])
            return sorted(out)

        for step in range(120):
            action = rng.random()
            if action < 0.45 or not model:  # insert
                name = name_pool[next_id]
                next_id += 1
                day = date(2026, rng.randint(1, 12), rng.randint(1, 28))
                tags = [t for t in tag_pool if rng.random() < 0.35] or [rng.choice(tag_pool)]
                _write_card(tmp_path, name, day, tags)
                model.append({"name": name, "date": day, "tags": tags})
                tree.insert(name, day, f"card {name}", tags)
                existing.add(name)
            elif action < 0.65 and model:  # remove
                victim = rng.choice(model)
                model.remove(victim)
                _remove_card(tmp_path, victim["name"])
                tree.remove(victim["name"])
            elif action < 0.8:  # query
                tag = rng.choice(tag_pool)
                got = sorted(tree.query_by_tag(tag, max_results=1000))
                assert got == naive_tag(tag), f"tag={tag} step={step}"
            elif action < 0.9:  # date-range query
                lo = date(2026, rng.randint(1, 12), 1)
                hi = date(2026, rng.randint(1, 12), 28)
                if lo > hi:
                    lo, hi = hi, lo
                tag = rng.choice([None, rng.choice(tag_pool)])
                got = sorted(tree.query_by_daterange(lo, hi, tag=tag, max_results=1000))
                assert got == naive_range(lo, hi, tag), f"range={lo}..{hi} step={step}"
            else:  # save + reload（模拟进程重启），树状态必须与模型一致
                tree.save()
                tree = MemorySegTree(str(tmp_path))
                assert tree.load(), f"reload 失败 step={step}"
                assert sorted(tree.cards) == sorted(m["name"] for m in model), f"step={step}"

        assert tree.cards and model, "fuzz 序列不应为空"
        assert tree.verify() == [], f"不变量被破坏: {tree.verify()}"
        # 收尾：save→load 一致性 + 模板摘要
        tree.force_summarize_all()
        tree.save()
        t2 = MemorySegTree(str(tmp_path))
        assert t2.load()
        assert sorted(t2.cards) == sorted(m["name"] for m in model)
        assert t2.root.summary, "根摘要不应为空"
