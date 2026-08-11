"""工作区切换后 cwd 注入的端到端验证：

1. 服务器以 D:/PY_PROJ/MAI-agent 为启动 cwd
2. POST /api/workspace 切换到临时目录
3. WS submit 问模型当前工作目录
4. 断言模型回答的是临时目录，不是 MAI-agent
"""
import asyncio
import json
import subprocess
import sys
import tempfile
import urllib.request

import websockets

PORT = 8798
HTTP = f"http://127.0.0.1:{PORT}"
WS = f"ws://127.0.0.1:{PORT}/ws"


def http_get(path):
    with urllib.request.urlopen(HTTP + path, timeout=10) as r:
        return json.loads(r.read())


def http_post(path, data):
    req = urllib.request.Request(
        HTTP + path, data=json.dumps(data).encode(),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


async def main() -> int:
    tmp = tempfile.mkdtemp(prefix="ws_switch_test_")
    tmp_norm = tmp.replace("\\", "/")

    proc = subprocess.Popen(
        [sys.executable, "-X", "utf8", "-c",
         f"import uvicorn; from mai_agent.server import app; "
         f"uvicorn.run(app, host='127.0.0.1', port={PORT}, log_level='error')"],
        cwd=r"D:\PY_PROJ\MAI-agent",
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(60):
            try:
                http_get("/api/tools")
                break
            except Exception:
                await asyncio.sleep(0.5)
        else:
            print("FAIL: server did not start")
            return 1

        w0 = http_get("/api/workspace")
        print("启动时 cwd:", w0["cwd"])

        t0 = asyncio.get_event_loop().time()
        r = http_post("/api/workspace", {"cwd": tmp})
        t1 = asyncio.get_event_loop().time()
        print(f"切换到: {r.get('cwd')}  (耗时 {t1 - t0:.2f}s)")

        w1 = http_get("/api/workspace")
        print("切换后 /api/workspace cwd:", w1["cwd"])

        async with websockets.connect(WS) as ws:
            while True:
                ev = json.loads(await asyncio.wait_for(ws.recv(), 15))
                if ev["type"] == "ready":
                    break
            await ws.send(json.dumps({
                "type": "submit",
                "text": "你的 system prompt 里写的当前工作目录是什么？只回答那个绝对路径，不要别的内容",
            }))
            answer = ""
            while True:
                ev = json.loads(await asyncio.wait_for(ws.recv(), 90))
                if ev["type"] == "text":
                    answer += ev.get("data", "")
                elif ev["type"] == "done":
                    break
                elif ev["type"] == "error":
                    print("FAIL: error:", ev.get("message"))
                    return 1

        print("模型回答:", answer.strip()[:200])
        in_tmp = tmp_norm.lower() in answer.replace("\\", "/").lower()
        in_mai = "mai-agent" in answer.lower()
        print(f"包含切换后目录: {in_tmp} | 包含 MAI-agent: {in_mai}")
        ok = in_tmp and not in_mai
        print("RESULT:", "PASS" if ok else "FAIL")
        return 0 if ok else 1
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
