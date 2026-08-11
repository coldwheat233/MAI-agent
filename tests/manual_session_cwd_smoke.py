"""Session 工作目录定位端到端验证（用户报告的 bug 场景）：

1. 服务器以 MAI-agent 启动 → 切到工作区 A → 聊一轮（产生 session S）
2. 切到工作区 B
3. POST /api/sessions/S/load → 期望引擎自动切回 A
4. WS 问模型当前工作目录 → 期望回答 A 而不是 B/MAI-agent
"""
import asyncio
import json
import shutil
import subprocess
import sys
import tempfile
import urllib.request

import websockets

PORT = 8796
HTTP = f"http://127.0.0.1:{PORT}"
WS = f"ws://127.0.0.1:{PORT}/ws"


def http_json(path, data=None, method=None):
    if data is not None:
        req = urllib.request.Request(
            HTTP + path, data=json.dumps(data).encode(),
            headers={"Content-Type": "application/json"}, method=method or "POST",
        )
    else:
        req = urllib.request.Request(HTTP + path, method=method or "GET")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


async def ws_ask(question: str) -> str:
    async with websockets.connect(WS) as ws:
        while True:
            ev = json.loads(await asyncio.wait_for(ws.recv(), 15))
            if ev["type"] == "ready":
                break
        await ws.send(json.dumps({"type": "submit", "text": question}))
        answer = ""
        while True:
            ev = json.loads(await asyncio.wait_for(ws.recv(), 120))
            if ev["type"] == "text":
                answer += ev.get("data", "")
            elif ev["type"] == "done":
                return answer
            elif ev["type"] == "error":
                raise RuntimeError(ev.get("message"))


async def main() -> int:
    tmp_a = tempfile.mkdtemp(prefix="proj_alpha_")
    tmp_b = tempfile.mkdtemp(prefix="proj_beta_")

    proc = subprocess.Popen(
        [sys.executable, "-X", "utf8", "-c",
         f"import uvicorn; from mai_agent.server import app; "
         f"uvicorn.run(app, host='127.0.0.1', port={PORT}, log_level='error')"],
        cwd=r"D:\PY_PROJ\MAI-agent",
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    session_a = None
    try:
        for _ in range(60):
            try:
                http_json("/api/tools")
                break
            except Exception:
                await asyncio.sleep(0.5)
        else:
            print("FAIL: server did not start")
            return 1

        # 1. 切到 A，聊一轮产生 session
        r = http_json("/api/workspace", {"cwd": tmp_a})
        session_a = r["session_id"]
        print("工作区 A session:", session_a)
        await ws_ask("记住数字 42。只回复 OK")

        # 2. 切到 B
        http_json("/api/workspace", {"cwd": tmp_b})
        w = http_json("/api/workspace")
        print("当前在 B:", w["cwd"] == tmp_b.replace("/", "\\") or tmp_b in w["cwd"])

        # 3. 搜索能找到 A 的 session 且 workspace 是真实路径
        results = http_json("/api/sessions/search?q=42")
        hit = [x for x in results if x["session_id"] == session_a]
        if hit:
            print("搜索命中, workspace 字段:", hit[0]["workspace"])
            real_path = "proj_alpha_" in hit[0]["workspace"]
        else:
            print("搜索未命中!"); real_path = False

        # 4. 加载 A 的 session —— 应自动切回 A
        lr = http_json(f"/api/sessions/{session_a}/load", {})
        print("load 返回 cwd:", lr.get("cwd"))
        w2 = http_json("/api/workspace")
        back_in_a = "proj_alpha_" in w2["cwd"]
        print("load 后引擎 cwd 是 A:", back_in_a)

        # 5. 问模型当前工作目录
        ans = await ws_ask("你的 system prompt 里写的当前工作目录是什么？只回答那个绝对路径")
        print("模型回答:", ans.strip()[:150])
        says_a = "proj_alpha_" in ans
        says_other = ("proj_beta_" in ans) or ("MAI-agent" in ans)
        print(f"回答 A: {says_a} | 回答其他: {says_other}")

        ok = real_path and back_in_a and says_a and not says_other
        print("RESULT:", "PASS" if ok else "FAIL")
        return 0 if ok else 1
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        shutil.rmtree(tmp_a, ignore_errors=True)
        shutil.rmtree(tmp_b, ignore_errors=True)
        # 清理全局索引里的测试条目
        try:
            from mai_agent import session as S
            idx = json.loads(S.WORKSPACE_INDEX.read_text(encoding="utf-8"))
            for slug in [S._workspace_slug(tmp_a), S._workspace_slug(tmp_b)]:
                idx.pop(slug, None)
            S.WORKSPACE_INDEX.write_text(json.dumps(idx, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
