"""MAI-agent Desktop Server — FastAPI + WebSocket 实时流式。

Architecture:
  WebSocket /ws      — real-time agent interaction (streaming text + tool calls)
  REST /api/*        — session management, settings, queries

前端: mai_agent/static/index.html

启动: mai --serve  (启动服务器 + 自动打开浏览器)
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import uuid
from pathlib import Path
from typing import Any

# ── 全链路 UTF-8 编码强制 ──────────────────────────────
# 必须在任何输出之前执行。Windows 中文系统默认 stdout=gbk，
# 中文 JSON / WebSocket 文本会被 GBK 编码器破坏。
if sys.platform == "win32":
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8")
        except Exception:
            pass

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from mai_agent.config import get_config
from mai_agent.core.engine import AgentEngine, EngineConfig
from mai_agent.core.loop import AgentLoopConfig, StepProgress
from mai_agent.tools import registry as tool_registry
from mai_agent.context import build_system_prompt
from mai_agent.session import list_sessions

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="MAI-agent Desktop", version="0.2.0")

# ── CORS ──────────────────────────────────────────────
# Renderer 在 dev 模式下由 Vite 起在 http://localhost:5173（或被占用时 5174），
# 后端在 8765——跨端口 = 跨源，没 CORS 头的话所有 fetch 都会被 Chromium 拦掉，
# 表现就是"点 workspace 没反应、session 列表永远是 loading"。
# 生产构建里 renderer 由后端同源 8765 静态服务，CORS 不影响；这里宽放本地端口。
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 按工作区隔离的引擎实例——切换工作区不杀旧任务，各自独立运行
_engines: dict[str, AgentEngine] = {}       # cwd_norm → engine
_submit_tasks: dict[str, asyncio.Task] = {}  # cwd_norm → running submit task
_save_locks: dict[str, asyncio.Lock] = {}   # cwd_norm → save serialization lock
_checkpoint_state: dict[str, int] = {}       # cwd_norm → 已 checkpoint 的累计字符数
_config: Any = None


def _norm(cwd: str) -> str:
    """规范化工作区路径为字典 key。"""
    return str(Path(cwd).resolve())


async def _get_engine(cwd: str = "") -> AgentEngine:
    """获取或懒创建指定工作区的引擎。"""
    key = _norm(cwd) if cwd else _norm(_ensure_config().project_root or ".")
    eng = _engines.get(key)
    if eng is None:
        _old_root = _ensure_config().project_root
        try:
            if cwd:
                _config.project_root = cwd
            eng = await _init_engine_async()
            _engines[key] = eng
        finally:
            if cwd:
                _config.project_root = _old_root
    return eng


async def _cancel_submit_for(cwd_norm: str, timeout: float = 3.0) -> None:
    """取消指定工作区的在途 submit（如果有）。"""
    task = _submit_tasks.pop(cwd_norm, None)
    if task is not None and not task.done():
        task.cancel()
        try:
            await asyncio.wait_for(task, timeout=timeout)
        except (asyncio.TimeoutError, BaseException):
            pass


async def _cancel_current_submit(timeout: float = 3.0) -> None:
    """取消当前工作区的在途 submit。"""
    key = _norm(_ensure_config().project_root or ".")
    await _cancel_submit_for(key, timeout=timeout)


def _get_save_lock(cwd_norm: str) -> asyncio.Lock:
    """每个工作区一把 save 锁——checkpoint / 终存 / 断连存共用，防并发写同一文件。"""
    lock = _save_locks.get(cwd_norm)
    if lock is None:
        lock = asyncio.Lock()
        _save_locks[cwd_norm] = lock
    return lock


async def _save_engine_async(engine: AgentEngine, cwd_norm: str) -> None:
    """线程池里原子写 session 文件；同一 cwd 的写串行化。"""
    from mai_agent.session import save_session
    lock = _get_save_lock(cwd_norm)
    async with lock:
        try:
            engine_cwd = str(Path(engine.config.cwd or ".").resolve())
        except Exception:
            engine_cwd = engine.config.cwd or "."
        try:
            await asyncio.to_thread(save_session, engine.session_id, engine.snapshot_messages(), engine_cwd)
        except Exception as exc:
            logger.warning("checkpoint/终存失败: session=%s err=%s", engine.session_id, exc)


async def _init_engine_async(cwd: str = "") -> AgentEngine:
    """异步初始化引擎：同步重活放线程池，MCP 回到事件循环。"""
    engine = await asyncio.to_thread(init_engine, cwd)
    await engine.start_mcp()
    key = _norm(cwd or _ensure_config().project_root or ".")
    _engines[key] = engine
    return engine


def _ensure_config() -> Any:
    """确保 _config 已初始化（engine 未创建时端点也可能要先写配置）。"""
    global _config
    if _config is None:
        _config = get_config()
    return _config


def init_engine(override_cwd: str = "") -> AgentEngine:
    """初始化引擎（不设全局——由 _init_engine_async 注册到 _engines）。"""
    global _config
    _config = get_config()
    try:
        _config.validate()
    except RuntimeError:
        pass

    # Clear context cache so new cwd takes effect
    from mai_agent.context import get_system_context, get_user_context
    get_system_context.cache_clear()
    get_user_context.cache_clear()

    cwd = override_cwd or _config.project_root or os.getcwd()
    engine = AgentEngine(EngineConfig(
        llm_api_key=_config.llm_api_key,
        llm_base_url=_config.llm_base_url or "https://api.deepseek.com/v1",
        llm_model=_config.llm_model,
        tools=tool_registry,
        permission_mode=_config.permission_mode,
        max_turns=_config.max_steps,
        cwd=cwd,
        sandbox_mode=getattr(_config, "sandbox_mode", "off"),
        sandbox_writable=getattr(_config, "sandbox_writable", ""),
        brain_type=getattr(_config, "brain_type", ""),
        system_prompt=build_system_prompt(
            AgentLoopConfig().system_prompt, project_root=cwd,
        ),
    ))
    engine.start()
    return engine


# ── Static files ────────────────────────────────────


STATIC_DIR = Path(__file__).parent / "static"

if STATIC_DIR.is_dir():
    app.mount("/assets", StaticFiles(directory=str(STATIC_DIR / "assets")), name="assets")


@app.get("/")
async def root():
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return HTMLResponse(index_path.read_text(encoding="utf-8"))
    return {"service": "MAI-agent API", "version": "0.3.0"}


# ── WebSocket ────────────────────────────────────────────


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    cwd_key = _norm(_ensure_config().project_root or ".")
    engine = await _get_engine()

    async def send_event(event: dict):
        try:
            await ws.send_text(json.dumps(event, ensure_ascii=False, default=str))
        except Exception:
            pass

    async def progress_callback(p: StepProgress):
        """将 StepProgress 转为 WebSocket 事件 + 流式 checkpoint 存盘。"""
        nonlocal cwd_key
        # 把流出的 text / tool 增量也写进 engine._streaming 并行占位——
        # 配合 snapshot_messages() 让 checkpoint / 断连 save 能拿到正在流的 assistant。
        if p.event == "thinking":
            await send_event({"type": "thinking"})
        elif p.event == "text":
            await send_event({"type": "text", "data": p.text})
            if engine._streaming is not None:
                engine._streaming.content = (engine._streaming.content or "") + (p.text or "")
            # 流式 checkpoint：累计 ~1500 字符触发一次后台存盘
            _checkpoint_state[cwd_key] = _checkpoint_state.get(cwd_key, 0) + len(p.text or "")
            if _checkpoint_state[cwd_key] >= 1500:
                _checkpoint_state[cwd_key] = 0
                try:
                    asyncio.create_task(_save_engine_async(engine, cwd_key))
                except RuntimeError:
                    pass
        elif p.event == "tool_start":
            await send_event({
                "type": "tool_start", "tool": p.tool_name, "args": p.tool_args,
            })
            if engine._streaming is not None and p.tool_name:
                from mai_agent.core.models import ToolCall, FunctionCall
                tc = ToolCall(
                    id=f"stream_{p.tool_name}_{len(engine._streaming.tool_calls or [])}",
                    function=FunctionCall(name=p.tool_name, arguments=p.tool_args or "{}"),
                )
                engine._streaming.tool_calls = (engine._streaming.tool_calls or []) + [tc]
        elif p.event == "tool_result":
            await send_event({
                "type": "tool_result", "tool": p.tool_name,
                "result": p.tool_result, "error": p.is_error,
            })
            # 工具结果是一次"明确的提交点"——立刻 checkpoint
            _checkpoint_state[cwd_key] = 0
            try:
                asyncio.create_task(_save_engine_async(engine, cwd_key))
            except RuntimeError:
                pass
        elif p.event == "converge":
            await send_event({
                "type": "converge", "answer": p.tool_result,
                "tokens": p.tokens_used, "context_tokens": p.context_tokens,
                "max_context": p.max_context_tokens,
            })
            # 模型收敛（这一轮要结束）—— 立刻 checkpoint
            try:
                asyncio.create_task(_save_engine_async(engine, cwd_key))
            except RuntimeError:
                pass

    await send_event({
        "type": "ready",
        "session_id": engine.session_id,
        "mode": engine._loop_config.permission_mode,
        "brain": engine._run_context.active_brain,
        "sandbox": getattr(_config, "sandbox_mode", "off"),
        "model": _config.llm_model,
        "tools": tool_registry.names(),
    })

    try:
        while True:
            raw = await ws.receive_text()
            msg = json.loads(raw)
            msg_type = msg.get("type", "")

            # ── 切换工作区视图 ──
            if msg_type == "switch_workspace":
                new_cwd = msg.get("cwd", "")
                if new_cwd and Path(new_cwd).is_dir():
                    _ensure_config().project_root = new_cwd
                    cwd_key = _norm(new_cwd)
                    # 登记到 SQLite 全局 workspaces 表
                    from mai_agent import db
                    try:
                        db.register_workspace(new_cwd)
                    except Exception:
                        pass
                    # 懒创建目标工作区引擎
                    new_eng = await _get_engine(new_cwd)
                    await send_event({
                        "type": "workspace_switched",
                        "cwd": str(Path(new_cwd).resolve()),
                        "session_id": new_eng.session_id,
                        "mode": new_eng._loop_config.permission_mode,
                    })
                continue

            # ── 获取当前工作区引擎 ──
            engine = await _get_engine()

            if msg_type == "submit":
                text = msg.get("text", "")
                if not text.strip():
                    continue
                # 按"engine 自身的工作区"取/取消在途 submit——避免全局指针与 engine 不一致时
                # 误取消别的 workspace 任务、或新任务落到错 key。
                submit_key = _norm(engine.config.cwd or ".")
                await _cancel_submit_for(submit_key, timeout=1.0)
                engine = await _get_engine()
                engine._run_context.abort_signal = None
                await send_event({"type": "thinking"})
                if msg.get("mode"):
                    engine.set_mode(msg["mode"])
                if msg.get("brain") is not None:
                    engine.set_brain(msg.get("brain", ""))

                _submit_tasks[submit_key] = asyncio.create_task(
                    _run_submit(engine, text, send_event, progress_callback, submit_key)
                )

            elif msg_type == "stop":
                engine = await _get_engine()
                engine._run_context.abort_signal = asyncio.Event()
                engine._run_context.abort_signal.set()
                await _cancel_current_submit(timeout=3.0)
                await send_event({"type": "status", "message": "Interrupted"})

            elif msg_type == "undo":
                await _cancel_current_submit(timeout=1.0)
                engine = await _get_engine()
                msgs = engine.messages
                last_user_idx = -1
                for i in range(len(msgs) - 1, -1, -1):
                    if msgs[i].role == "user":
                        last_user_idx = i
                        break
                if last_user_idx >= 0:
                    del msgs[last_user_idx:]
                    await send_event({
                        "type": "status",
                        "message": f"已撤销最近一轮 ({len(msgs)} 条消息)",
                    })
                else:
                    await send_event({
                        "type": "status",
                        "message": "无可撤销内容",
                    })

    except WebSocketDisconnect:
        # 窗口关闭 / 断网——把当前 engine 立刻落盘，避免丢失最近消息
        try:
            await _save_engine_async(engine, cwd_key)
        except Exception:
            pass


async def _run_submit(engine, text, send_event, progress_callback, cwd_key: str = "") -> None:
    """在独立 Task 中执行一次 submit，负责持久化和 done/error 事件。

    存盘用 engine.config.cwd（engine 自己的工作区），而不是全局 _config.project_root——
    全局指针可能在并发/历史操作中与 engine 不一致；以 engine 为准保证 session 文件
    落到它真正归属的 workspace。

    重发语义：engine.submit 返回的 messages 是"完整历史 + 本轮新 user + 本轮新 assistant"，
    save_session 整体写盘 = 线性追加新的一轮。绝不会出现"覆盖最近一条消息"——
    最近一条 assistant 永远保留在 messages 列表里，新一轮只是 list.append。

    终存策略：
      - 正常完成：先发 done（前端立刻收尾不卡），再把终存丢到后台 task。
        期间流式 checkpoint 已经把状态刷了好几轮，后台 task 只是把最后一段落定。
      - Cancel：保留 awaited 存盘——中断瞬间的 state 一定要进盘，再发 done(stopped)。"""
    # 提前解析一次 cwd，避免异常路径下再访问
    try:
        engine_cwd = str(Path(engine.config.cwd or ".").resolve())
    except Exception:
        engine_cwd = engine.config.cwd or "."
    try:
        answer, messages = await engine.submit(text, on_progress=progress_callback)
        # 清洗中断/异常残留的不完整 tool_calls——防下次加载 400
        from mai_agent.core.loop import strip_incomplete_tool_calls
        messages = strip_incomplete_tool_calls(messages)
        # 把清洗后的 messages 同步回 engine（供后续 checkpoint / 断连存用）
        engine._messages = messages
        # 先发 done——前端不再等存盘
        await send_event({
            "type": "done", "turn": engine.turn_count,
            "tools_called": engine.total_tool_calls,
            "pending_tasks": engine.pending_tasks,
        })
        # 终存丢后台：和流式 checkpoint 共用同一把锁，自然排队
        _checkpoint_state[cwd_key] = 0
        try:
            asyncio.create_task(_save_engine_async(engine, cwd_key))
        except RuntimeError:
            pass
    except asyncio.CancelledError:
        try:
            from mai_agent.session import save_session
            from mai_agent.core.loop import strip_incomplete_tool_calls
            msgs = strip_incomplete_tool_calls(engine.messages)
            # 取消时 awaited 存盘：保证中断状态进盘
            await _save_engine_async(engine, cwd_key)
        except Exception:
            pass
        await send_event({
            "type": "done", "turn": engine.turn_count,
            "tools_called": engine.total_tool_calls,
            "pending_tasks": engine.pending_tasks, "stopped": True,
        })
    except Exception as exc:
        await send_event({
            "type": "error", "message": str(exc) or type(exc).__name__,
        })
    finally:
        if cwd_key:
            _submit_tasks.pop(cwd_key, None)


# ── REST API ─────────────────────────────────────────────


@app.get("/api/stats")
async def api_stats():
    engine = await _get_engine()
    return engine.stats


@app.get("/api/sessions")
async def api_sessions(workspace: str = ""):
    # 支持查询指定工作区的 session（不切换当前引擎）
    cwd = workspace if workspace else (getattr(_config, "project_root", ".") or ".")
    return list_sessions(cwd)


@app.get("/api/sessions/search")
async def api_sessions_search(q: str = ""):
    """搜索所有 workspace 的 session 内容。"""
    if not q.strip():
        return []
    from mai_agent.session import search_sessions
    cwd = getattr(_config, "project_root", ".") or "."
    return search_sessions(q.strip(), cwd)


@app.get("/api/sessions/{session_id}")
async def api_session_detail(session_id: str):
    """获取 session 的完整消息历史。"""
    from mai_agent.session import load_session
    cwd = getattr(_config, "project_root", ".") or "."
    messages = load_session(session_id, cwd)
    if messages is None:
        return JSONResponse({"error": "Session not found"}, 404)
    return {
        "session_id": session_id,
        "message_count": len(messages),
        "messages": [
            {
                "role": m.role,
                "content": (m.content or "")[:5000],
                "tool_calls": (
                    [{
                        "name": tc.function.name if tc.function else "?",
                        "args": (tc.function.arguments if tc.function else "{}")[:500],
                    } for tc in m.tool_calls]
                ) if m.tool_calls else None,
            }
            for m in messages
        ],
    }


@app.post("/api/sessions/{session_id}/load")
async def api_session_load(session_id: str):
    """将会话加载到当前引擎的消息历史（继续之前的对话）。

    Session 驱动工作目录：若 session 记录的工作区与当前不同，
    先把引擎切换过去再加载——保证模型看到的 cwd 与会话来源一致。"""
    from mai_agent.session import load_session, get_session_workspace
    cwd = getattr(_config, "project_root", ".") or "."
    messages = load_session(session_id, cwd)
    if messages is None:
        return JSONResponse({"error": "Session not found"}, 404)

    # session 自带的工作区优先——它是模型应该看到的 cwd 的权威来源。
    ws_path = get_session_workspace(session_id, cwd)
    target_cwd: str | None = None
    if ws_path and Path(ws_path).is_dir():
        target_cwd = str(Path(ws_path).resolve())

    if target_cwd:
        # 直接按 session 的工作区取/建 engine，再把全局指针同步过去——
        # 避免依赖全局 _config.project_root 时与 engine cache 错位。
        engine = await _get_engine(target_cwd)
        _ensure_config().project_root = target_cwd
    else:
        engine = await _get_engine()

    # 确保 system prompt 反映当前工作区
    engine._refresh_system_prompt()
    # Strip system messages — engine already has correct system prompt
    non_system = [m for m in messages if getattr(m, "role", "") != "system"]
    engine._messages = non_system
    engine._session_id = session_id
    return {
        "session_id": session_id,
        "message_count": len(messages),
        "loaded": True,
        "cwd": str(Path(engine.config.cwd).resolve()),
    }


@app.get("/api/tools")
async def api_tools():
    tools = []
    for name in sorted(tool_registry.names()):
        t = tool_registry.get(name)
        tools.append({
            "name": name,
            "description": t.description,
            "safe": t.is_concurrency_safe,
        })
    return tools


@app.get("/api/skills")
async def api_skills():
    try:
        from mai_agent.skills.loader import get_skill_registry
        cwd = getattr(_config, "project_root", ".") or "."
        reg = get_skill_registry(cwd)
        return [{
            "name": s.name,
            "description": s.description,
            "whenToUse": s.when_to_use,
            "source": s.source,
        } for s in reg.all()]
    except Exception:
        return []


@app.get("/api/memories")
async def api_memories():
    try:
        from mai_agent.services.memory_tags import load_all_memories, all_tags
        cwd = getattr(_config, "project_root", ".") or "."
        memories = load_all_memories(cwd)
        return {
            "memories": [{
                "name": m.name,
                "description": m.description,
                "type": m.type,
                "tags": m.tags,
                "created_at": m.created_at,
                "wiki_links": m.wiki_links(),
            } for m in sorted(memories, key=lambda x: x.name)],
            "tags": all_tags(cwd),
        }
    except Exception:
        return {"memories": [], "tags": []}


@app.post("/api/mode")
async def api_set_mode(data: dict):
    engine = await _get_engine()
    mode = data.get("mode", "auto")
    engine.set_mode(mode)
    return {"mode": mode}


@app.post("/api/brain")
async def api_set_brain(data: dict):
    engine = await _get_engine()
    brain = data.get("brain", "")
    try:
        engine.set_brain(brain)
        return {"brain": brain}
    except ValueError as e:
        return JSONResponse({"error": str(e)}, 400)


@app.post("/api/sandbox")
async def api_set_sandbox(data: dict):
    engine = await _get_engine()
    mode = data.get("mode", "off")
    if mode not in ("off", "default", "strict"):
        return JSONResponse({"error": "无效沙箱模式"}, 400)
    _ensure_config().sandbox_mode = mode
    if engine:
        engine._run_context.session_state = engine._init_session_state()
    return {"sandbox": mode}


@app.delete("/api/sessions/{session_id}")
async def api_session_delete(session_id: str):
    """删除一个 session。"""
    from mai_agent.session import delete_session
    cwd = getattr(_config, "project_root", ".") or "."
    ok = delete_session(session_id, cwd)
    if not ok:
        return JSONResponse({"error": "Session not found"}, 404)
    return {"deleted": True, "session_id": session_id}


@app.get("/api/workspaces")
async def api_workspaces():
    """列出所有已知工作区。"""
    from mai_agent.session import list_workspaces
    cwd = getattr(_config, "project_root", ".") or "."
    return list_workspaces(cwd)


@app.get("/api/workspace")
async def api_workspace():
    """当前工作区信息。"""
    cwd = str(Path(getattr(_config, "project_root", ".") or ".").resolve())
    from mai_agent.session import list_sessions, list_workspaces
    sessions = list_sessions(cwd)
    workspaces = list_workspaces(cwd)
    return {
        "cwd": cwd,
        "name": Path(cwd).name,
        "session_count": len(sessions),
        "workspaces": workspaces,
        "sessions": sessions,
    }


@app.post("/api/workspace")
async def api_switch_workspace(data: dict):
    """切换工作目录——只改指针，旧引擎不杀。目标工作区引擎懒创建。"""
    global _config
    new_cwd = data.get("cwd", "")
    if not new_cwd or not Path(new_cwd).is_dir():
        return JSONResponse({"error": "无效目录"}, 400)
    _ensure_config().project_root = new_cwd
    # 登记到 SQLite 全局 workspaces 表（touch last_used）
    from mai_agent import db
    try:
        db.register_workspace(new_cwd)
    except Exception:
        pass
    engine = await _get_engine(new_cwd)
    return {
        "cwd": str(Path(new_cwd).resolve()),
        "session_id": engine.session_id,
    }


@app.post("/api/workspaces/register")
async def api_workspaces_register(data: dict):
    """把一个目录登记成 workspace（不切换当前引擎）。"""
    from mai_agent import db
    cwd = data.get("cwd", "")
    if not cwd or not Path(cwd).is_dir():
        return JSONResponse({"error": "无效目录"}, 400)
    db.register_workspace(cwd)
    return {"registered": True, "path": str(Path(cwd).resolve())}


@app.delete("/api/workspaces")
async def api_workspaces_unregister(data: dict):
    """从全局 workspace 列表移除（不删磁盘项目，session 行因 FK CASCADE 一起删）。"""
    from mai_agent import db
    cwd = data.get("cwd", "")
    if not cwd:
        return JSONResponse({"error": "缺少 cwd"}, 400)
    db.unregister_workspace(cwd)
    return {"unregistered": True, "path": cwd}


@app.get("/api/git")
async def api_git():
    """当前工作区的 Git 状态（异步 subprocess）。"""
    cwd = getattr(_config, "project_root", ".") or "."

    async def _run(cmd):
        try:
            p = await asyncio.create_subprocess_shell(
                f"git {cmd}", stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE, cwd=cwd,
            )
            out, _ = await asyncio.wait_for(p.communicate(), timeout=5)
            return out.decode("utf-8", errors="replace").strip(), p.returncode or 0
        except Exception:
            return "", -1

    branch, _ = await _run("branch --show-current")
    status, _ = await _run("status --short")
    log, _ = await _run("log --oneline -5")
    is_repo = (await _run("rev-parse --is-inside-work-tree"))[1] == 0

    return {
        "is_repo": is_repo,
        "branch": branch or "(detached)",
        "status": status,
        "recent_commits": log,
    }


@app.get("/api/browse")
async def api_browse(path: str = ""):
    """浏览文件系统目录（用于工作区选择器）。"""
    from pathlib import Path as _Path
    target = _Path(path) if path else _Path.home()
    if not target.exists():
        target = _Path.home()
    if not target.is_dir():
        target = target.parent

    try:
        entries = []
        for p in sorted(target.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
            if p.name.startswith(".") and p.name not in (".", ".."):
                continue
            entries.append({
                "name": p.name,
                "path": str(p.resolve()),
                "is_dir": p.is_dir(),
            })
        return {
            "path": str(target.resolve()),
            "parent": str(target.parent.resolve()) if target.parent != target else None,
            "entries": entries,
        }
    except PermissionError:
        return JSONResponse({"error": "Permission denied"}, 403)


@app.get("/api/coordinator")
async def api_coordinator():
    """获取四脑协调器当前状态。"""
    engine = await _get_engine()
    return {
        "brain": engine._run_context.active_brain,
        "status": engine.coordinator_status,
    }


@app.get("/api/feishu/status")
async def api_feishu_status():
    """检查飞书配置状态。"""
    from mai_agent.config import get_config as _gc
    cfg = _gc()
    has_config = bool(cfg.feishu_app_id and cfg.feishu_app_secret)
    return {
        "configured": has_config,
        "app_id": cfg.feishu_app_id[:8] + "..." if has_config and len(cfg.feishu_app_id) > 8 else "",
        "tools_available": has_config,
        "hint": "" if has_config else "在下方 Settings → Feishu 中配置，或手动在 .env 中设置 FEISHU_APP_ID 和 FEISHU_APP_SECRET",
    }


# ── Learning Queue ───────────────────────────────────────


@app.get("/api/learning-queue")
async def api_learning_queue():
    """列出待学习队列。"""
    try:
        from mai_agent.knowledge.learning_queue import list_items, get_stats
        return {"items": list_items(), "stats": get_stats()}
    except Exception:
        return {"items": [], "stats": {}}


@app.post("/api/learning-queue")
async def api_learning_queue_add(data: dict):
    """添加一个待学习概念。"""
    from mai_agent.knowledge.learning_queue import add_item
    concept = (data.get("concept") or "").strip()
    if not concept:
        return JSONResponse({"error": "概念名不能为空"}, 400)
    item = add_item(
        concept=concept,
        context=data.get("context", ""),
        priority=data.get("priority", "medium"),
    )
    return item


@app.put("/api/learning-queue/{item_id}")
async def api_learning_queue_update(item_id: str, data: dict):
    """更新学习队列项——标记已学、添加笔记、同步到飞书。"""
    from mai_agent.knowledge.learning_queue import update_item
    updates = {k: v for k, v in data.items() if k in ("status", "notes", "priority", "feishu_doc_token")}
    if not updates:
        return JSONResponse({"error": "无有效更新字段"}, 400)
    r = update_item(item_id, updates)
    if r is None:
        return JSONResponse({"error": "Item not found"}, 404)

    # If marking as learned + Feishu configured, try to sync
    if updates.get("status") == "learned":
        try:
            from mai_agent.config import get_config as _gc
            cfg = _gc()
            if cfg.feishu_app_id and cfg.feishu_app_secret:
                from mai_agent.services.feishu import FeishuClient
                client = FeishuClient(cfg.feishu_app_id, cfg.feishu_app_secret)
                title = f"[学习笔记] {r['concept']}"
                content = f"# {r['concept']}\n\n"
                if r.get("context"):
                    content += f"**来源上下文**: {r['context']}\n\n"
                if r.get("notes"):
                    content += f"**学习笔记**:\n{r['notes']}\n\n"
                content += f"*自动同步自 MAI-agent 学习队列*"
                doc_token = await client.create_doc(title=title, content=content)
                if doc_token:
                    update_item(item_id, {"status": "synced", "feishu_doc_token": doc_token})
                    r["status"] = "synced"
                    r["feishu_doc_token"] = doc_token
        except Exception:
            pass

    return r


@app.delete("/api/learning-queue/{item_id}")
async def api_learning_queue_delete(item_id: str):
    """从学习队列中移除一项。"""
    from mai_agent.knowledge.learning_queue import delete_item
    ok = delete_item(item_id)
    if not ok:
        return JSONResponse({"error": "Item not found"}, 404)
    return {"deleted": True}


@app.post("/api/feishu/config")
async def api_feishu_config(data: dict):
    """保存飞书配置（写入 .env）。"""
    app_id = (data.get("app_id") or "").strip()
    app_secret = (data.get("app_secret") or "").strip()

    if not app_id or not app_secret:
        return JSONResponse({"error": "app_id 和 app_secret 不能为空"}, 400)

    env_path = Path(os.getcwd()) / ".env"
    lines: list[str] = []
    has_id = False
    has_secret = False

    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines(keepends=True):
            if line.startswith("FEISHU_APP_ID="):
                lines.append(f"FEISHU_APP_ID={app_id}\n")
                has_id = True
            elif line.startswith("FEISHU_APP_SECRET="):
                lines.append(f"FEISHU_APP_SECRET={app_secret}\n")
                has_secret = True
            else:
                lines.append(line)

    if not has_id:
        lines.append(f"FEISHU_APP_ID={app_id}\n")
    if not has_secret:
        lines.append(f"FEISHU_APP_SECRET={app_secret}\n")

    env_path.write_text("".join(lines), encoding="utf-8")

    # Reload config
    global _config
    from mai_agent.config import get_config
    _config = get_config()

    return {"ok": True, "app_id": app_id[:8] + "...", "hint": "已保存到 .env。重启后端后生效。"}


@app.post("/api/model")
async def api_set_model(data: dict):
    """切换模型并重新初始化引擎。"""
    global _engine, _config
    model = data.get("model", "")
    if not model:
        return JSONResponse({"error": "模型名不能为空"}, 400)
    _ensure_config().llm_model = model
    # 重建当前工作区引擎以应用新模型
    key = _norm(_config.project_root or ".")
    await _cancel_submit_for(key, timeout=3.0)
    old = _engines.pop(key, None)
    if old:
        await old.stop()
    engine = await _init_engine_async(_config.project_root or "")
    return {"model": model, "session_id": engine.session_id}


@app.post("/api/restart")
async def api_restart():
    key = _norm(_config.project_root or ".")
    await _cancel_submit_for(key, timeout=3.0)
    old = _engines.pop(key, None)
    if old:
        # 旧引擎有消息才落盘（空会话不写垃圾文件）
        if old._messages:
            from mai_agent.session import save_session
            save_session(old.session_id, old._messages, old.config.cwd)
        await old.stop()
    engine = await _init_engine_async(_config.project_root or "")
    # 立即落盘空会话——侧边栏刷新时能看到
    from mai_agent.session import save_session
    save_session(engine.session_id, [], engine.config.cwd)
    return {"session_id": engine.session_id}


@app.on_event("shutdown")
async def shutdown():
    for eng in list(_engines.values()):
        try:
            await eng.stop()
        except Exception:
            pass
