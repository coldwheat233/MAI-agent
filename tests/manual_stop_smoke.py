"""stop 按钮端到端冒烟测试：

1. 启动真实 uvicorn 服务器（测试端口）
2. WS 连接 → submit 一个会产生长回答的问题
3. 流出若干文本后发送 stop
4. 断言：stop 后快速收到 done（<8s），且之前有文本流出（答了一半被保留）
"""
import asyncio
import json
import subprocess
import sys
import time

import websockets

PORT = 8799
URL = f"ws://127.0.0.1:{PORT}/ws"


async def main() -> int:
    proc = subprocess.Popen(
        [sys.executable, "-X", "utf8", "-c",
         f"import uvicorn; from mai_agent.server import app; "
         f"uvicorn.run(app, host='127.0.0.1', port={PORT}, log_level='error')"],
        cwd=r"D:\PY_PROJ\MAI-agent",
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        # 等服务就绪
        for _ in range(60):
            try:
                async with websockets.connect(URL) as ws:
                    pass
                break
            except OSError:
                await asyncio.sleep(0.5)
        else:
            print("FAIL: server did not start")
            return 1

        async with websockets.connect(URL) as ws:
            # 等 ready
            while True:
                ev = json.loads(await asyncio.wait_for(ws.recv(), 15))
                if ev["type"] == "ready":
                    break

            # submit 一个长回答问题
            await ws.send(json.dumps({
                "type": "submit",
                "text": "用中文详细解释 TCP 三次握手和四次挥手的全过程，越详细越好，至少两千字",
            }))

            streamed = 0
            got_thinking = False
            t_submit = time.monotonic()
            stop_sent_at = None
            done_at = None
            stopped_flag = None

            while True:
                ev = json.loads(await asyncio.wait_for(ws.recv(), 60))
                t = ev["type"]
                if t == "thinking":
                    got_thinking = True
                elif t == "text":
                    streamed += len(ev.get("data", ""))
                    # 流出一定内容后立即 stop（模拟“答了一半就停”）
                    if stop_sent_at is None and streamed >= 80:
                        stop_sent_at = time.monotonic()
                        await ws.send(json.dumps({"type": "stop"}))
                elif t == "done":
                    done_at = time.monotonic()
                    stopped_flag = ev.get("stopped")
                    break
                elif t == "error":
                    print("FAIL: error event:", ev.get("message"))
                    return 1

            if stop_sent_at is None:
                print("FAIL: 回答太短，没来得及 stop（可能模型太快，重试）")
                return 1

            stop_latency = done_at - stop_sent_at
            total = done_at - t_submit
            print(f"thinking: {got_thinking}")
            print(f"streamed chars before stop: {streamed}")
            print(f"stop -> done latency: {stop_latency:.2f}s")
            print(f"total submit -> done: {total:.2f}s")
            print(f"done.stopped flag: {stopped_flag}")

            ok = got_thinking and streamed >= 80 and stop_latency < 8.0
            print("RESULT:", "PASS" if ok else "FAIL")
            return 0 if ok else 1
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
