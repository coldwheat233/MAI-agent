"""CLI entry point for `mai` command — installed via pyproject.toml [project.scripts].

Usage:
    mai                     # Interactive REPL
    mai --once "task"       # Single execution
    mai --plan              # Plan mode
"""

import asyncio
import logging
import os
import sys
import time

# Force UTF-8 on Windows before any Rich imports
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Enable readline command history if available
_HAS_READLINE = False
try:
    import readline
    _HAS_READLINE = True
    hist_file = os.path.expanduser("~/.mai_history")
    if os.path.exists(hist_file):
        readline.read_history_file(hist_file)
except ImportError:
    pass
except Exception:
    pass

import click
from dotenv import load_dotenv
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.live import Live
from rich import box

load_dotenv()

from mai_agent.config import Config, get_config
from mai_agent.core.engine import AgentEngine, EngineConfig
from mai_agent.core.loop import AgentLoopConfig
from mai_agent.tools import registry as tool_registry
from mai_agent.session import save_session, load_session, list_sessions, ensure_dirs
from mai_agent.context import build_system_prompt

console = Console(force_terminal=True, legacy_windows=False)
logger = logging.getLogger("mai-agent")


def _setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(level=level, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


def _make_progress_table(step, max_steps, tool_log, bg_tasks=0, tool_total=0, context_tokens=0, turn_tokens=0, max_context_tokens=0):
    table = Table(box=box.SIMPLE, show_header=False, padding=(0, 1))
    table.add_column("icon", width=2)
    table.add_column("detail", min_width=40)
    phase = "THINKING" if not tool_log or tool_log[-1].get("event") == "thinking" else "DOING"
    tool_count = len([t for t in tool_log if t.get("event") == "tool_result"])
    info = f"Turn {step} — {phase}"
    extras = []
    if tool_total:
        extras.append(f"tools: {tool_total}")
    if bg_tasks:
        extras.append(f"bg: {bg_tasks}")
    if context_tokens and max_context_tokens:
        extras.append(f"ctx: {context_tokens // 1000}K/{max_context_tokens // 1000}K")
    if turn_tokens:
        extras.append(f"tk: {turn_tokens}")
    if extras:
        info += "  (" + ", ".join(extras) + ")"
    table.add_row("[yellow]*[/yellow]", info)
    table.add_row("", "")
    for entry in tool_log[-8:]:
        ev = entry.get("event", "")
        name = entry.get("tool_name", "")
        args = entry.get("tool_args", "")
        result = entry.get("tool_result", "")
        error = entry.get("is_error", False)
        if ev == "thinking":
            table.add_row("[dim]...[/dim]", "[dim]thinking...[/dim]")
        elif ev == "text":
            text = entry.get("text", "")
            if text.strip():
                preview = text.replace("\n", " ")[-80:]
                table.add_row("", f"[dim]{preview}[/dim]")
        elif ev == "tool_start":
            detail = f"[bold yellow]>>[/bold yellow] [bold]{name}[/bold]"
            if args:
                detail += f" [dim]{args[:60]}[/dim]"
            table.add_row("[yellow]*[/yellow]", detail)
        elif ev == "tool_result":
            icon = "[red]X[/red]" if error else "[green]OK[/green]"
            detail = f"  [bold]{name}[/bold]"
            if result:
                detail += f" [dim]{result[:80]}[/dim]"
            table.add_row(icon, detail)
        elif ev == "converge":
            table.add_row("[cyan]OK[/cyan]", "[cyan]Done[/cyan]")
    return table


def _save_history():
    if _HAS_READLINE:
        try:
            readline.write_history_file(hist_file)
        except Exception:
            pass


def _print_help():
    console.print("""
[bold]Commands:[/bold]
  /exit, /quit, /q    Exit
  /help               Show this help
  /sessions           List saved sessions
  /mode auto|manual|plan  Switch permission mode
  /sandbox off|default|strict  Switch sandbox mode
  /brain <name>|off   Activate/deactivate a brain
                      (dev_explorer/dev_validator/knowledge_explorer/deploy_planner)
  /retry              Re-send last message
  /undo               Remove last turn from history
  /tools              List available tools
  /skills             List loaded skills
  /skills reload      Re-scan skill directory
  !cmd                Run shell command directly (no LLM)
""")


def _print_sessions(project_root):
    sessions = list_sessions(project_root)
    if not sessions:
        console.print("[dim]No saved sessions[/dim]")
        return
    for s in sessions[:10]:
        console.print(f"  {s['session_id']} — {s['message_count']} msgs — {s['updated_at']}")


def _print_tools():
    for name in sorted(tool_registry.names()):
        tool = tool_registry.get(name)
        safe = "R" if tool.is_concurrency_safe else "W"
        console.print(f"  [{safe}] [bold]{name}[/bold] — {tool.description[:80]}")


def _print_skills(project_root, cmd="/skills"):
    from mai_agent.skills.loader import get_skill_registry, reload_skills
    parts = cmd.split(maxsplit=1)
    if len(parts) > 1 and parts[1].strip() == "reload":
        reg = reload_skills(project_root)
        console.print(f"[yellow]Re-scanned. {len(reg)} skill(s) loaded.[/yellow]")
    reg = get_skill_registry(project_root)
    skills = reg.all()
    if not skills:
        console.print("[dim]No skills loaded. Add .md files to .mai/skills/[/dim]")
        return
    for s in sorted(skills, key=lambda x: x.name):
        tag = "project" if s.source == "project" else "user"
        console.print(
            f"  [{tag}] [bold]{s.name}[/bold] — {s.description[:70]}"
        )


def _print_recap(engine):
    stats = engine.stats
    elapsed = stats["duration_sec"]
    time_str = f"{elapsed:.0f}s" if elapsed < 60 else f"{elapsed / 60:.1f}m"
    tools_str = ", ".join(
        f"{k}×{v}" for k, v in stats.get("tool_breakdown", {}).items()
    ) or "none"
    console.print()
    console.print(Panel.fit(
        f"[bold]Session Recap[/bold]\n"
        f"  Duration:  {time_str}\n"
        f"  Turns:     {stats['turns']}\n"
        f"  Tools:     {stats['tool_calls']} calls ({tools_str})\n"
        f"  Messages:  {stats['messages']}\n"
        f"  Session:   {stats['session_id']}",
        title="Recap",
        border_style="dim",
    ))


async def _run_with_progress(engine, user_input, session_id, project_root, permission_mode="auto"):
    tool_log = []
    step = 1
    max_steps = engine._loop_config.max_turns
    is_tty = sys.stdout.isatty()

    if permission_mode == "manual":
        engine._loop_config.permission_mode = "manual"
        engine._run_context.permission_mode = "manual"
        async def _ask(tool_name, args):
            if is_tty:
                resp = console.input(
                    f"\n[bold yellow]Allow[/bold yellow] [bold]{tool_name}[/bold]? "
                    f"[dim](y=yes / n=no / a=always)[/dim] "
                )
                return resp.lower().startswith("y") or resp.lower().startswith("a")
            return True
        engine._loop_config.ask_permission = _ask

    async def progress_cb(p):
        nonlocal step
        step = p.step
        tool_log.append({
            "event": p.event, "tool_name": p.tool_name,
            "tool_result": p.tool_result, "is_error": p.is_error,
            "tokens_used": p.tokens_used,
            "context_tokens": p.context_tokens,
            "max_context_tokens": p.max_context_tokens,
        })
        if not is_tty:
            if p.event == "text":
                sys.stderr.write(p.text)
                sys.stderr.flush()
            elif p.event == "tool_start":
                sys.stderr.write(f"\n  [{p.step}] -> {p.tool_name}({p.tool_args[:60]})\n")
            elif p.event == "tool_result":
                icon = "x" if p.is_error else "ok"
                sys.stderr.write(f"  [{p.step}] {icon} {p.tool_name}: {p.tool_result[:80]}\n")
            elif p.event == "converge":
                tok = f" ({p.tokens_used} tk, ctx {p.context_tokens // 1000}K)" if p.tokens_used else ""
                sys.stderr.write(f"\n  [done]{tok}\n")

    if not is_tty:
        sys.stderr.write(f"[Agent] {user_input[:60]}...\n")
        answer, messages = await engine.submit(user_input, on_progress=progress_cb)
        return answer, messages

    with Live(_make_progress_table(step, max_steps, tool_log),
              console=console, refresh_per_second=4, transient=False) as live:
        async def update_progress(p):
            await progress_cb(p)
            # Extract token info from the most recent log entry
            last_entry = tool_log[-1] if tool_log else {}
            live.update(_make_progress_table(
                step, max_steps, tool_log,
                bg_tasks=engine.pending_tasks,
                tool_total=engine.total_tool_calls,
                context_tokens=last_entry.get("context_tokens", 0),
                turn_tokens=last_entry.get("tokens_used", 0),
                max_context_tokens=p.max_context_tokens or last_entry.get("max_context_tokens", 0),
            ))
        answer, messages = await engine.submit(user_input, on_progress=update_progress)
    return answer, messages


async def _run_once(config, user_input, session_id):
    ensure_dirs(config.project_root or ".")
    engine = AgentEngine(EngineConfig(
        llm_api_key=config.llm_api_key,
        llm_base_url=config.llm_base_url or "https://api.deepseek.com/v1",
        llm_model=config.llm_model,
        tools=tool_registry,
        permission_mode=config.permission_mode,
        max_turns=config.max_steps,
        cwd=config.project_root or os.getcwd(),
        sandbox_mode=config.sandbox_mode,
        sandbox_writable=config.sandbox_writable,
        brain_type=config.brain_type,
        system_prompt=build_system_prompt(AgentLoopConfig().system_prompt, project_root=config.project_root),
    ))
    engine.start()
    loaded = load_session(session_id, config.project_root or ".")
    if loaded:
        engine._messages = loaded
    answer, messages = await _run_with_progress(engine, user_input, session_id, config.project_root or ".", permission_mode=config.permission_mode)
    console.print(Panel(Markdown(answer), title="MAI-agent"))
    save_session(session_id, messages, config.project_root or ".")
    _print_recap(engine)
    await engine.stop()


async def _run_repl(config, session_id):
    ensure_dirs(config.project_root or ".")
    cwd = config.project_root or os.getcwd()
    engine = AgentEngine(EngineConfig(
        llm_api_key=config.llm_api_key,
        llm_base_url=config.llm_base_url or "https://api.deepseek.com/v1",
        llm_model=config.llm_model,
        tools=tool_registry,
        permission_mode=config.permission_mode,
        max_turns=config.max_steps,
        cwd=cwd,
        sandbox_mode=config.sandbox_mode,
        sandbox_writable=config.sandbox_writable,
        brain_type=config.brain_type,
        system_prompt=build_system_prompt(AgentLoopConfig().system_prompt, project_root=config.project_root),
    ))
    engine.start()
    loaded = load_session(session_id, config.project_root or ".")
    if loaded:
        engine._messages = loaded

    console.print(Panel.fit(
        f"[bold]MAI-agent[/bold] v0.1.0\n"
        f"Session: {session_id} | Mode: {config.permission_mode} | Model: {config.llm_model}\n"
        f"Brain: {config.brain_type or 'off'} | Sandbox: {config.sandbox_mode}\n"
        f"Type [bold]/help[/bold] for help, [bold]/exit[/bold] to quit",
        title="Launch",
    ))

    last_ctrl_c = 0.0
    last_user_input: str | None = None  # for /retry

    while True:
        try:
            user_input = console.input("\n[bold green]MAI> [/bold green]")
            last_ctrl_c = 0.0

            if not user_input.strip():
                continue

            # ── REPL 命令 ───────────────────────────────
            cmd = user_input.strip().lower()
            if cmd in ("/exit", "/quit", "/q"):
                _save_history()
                _print_recap(engine)
                await engine.stop()
                console.print("[dim]Goodbye![/dim]")
                break
            elif cmd == "/help":
                _print_help()
                continue
            elif cmd == "/sessions":
                _print_sessions(config.project_root or ".")
                continue
            elif cmd.startswith("/mode "):
                new_mode = cmd.split(" ", 1)[1].strip()
                engine.set_mode(new_mode)
                console.print(f"[yellow]Permission mode switched to: {new_mode}[/yellow]")
                continue
            elif cmd.startswith("/sandbox"):
                parts = cmd.split(maxsplit=1)
                mode = parts[1].strip() if len(parts) > 1 else "off"
                if mode not in ("off", "default", "strict"):
                    console.print("[red]Valid sandbox modes: off | default | strict[/red]")
                else:
                    config.sandbox_mode = mode
                    # Re-init session state with new sandbox
                    engine._run_context.session_state = engine._init_session_state()
                    console.print(f"[yellow]Sandbox mode: {mode}[/yellow]")
                continue
            elif cmd == "/brain" or cmd.startswith("/brain "):
                parts = cmd.split(maxsplit=1)
                brain_name = parts[1].strip() if len(parts) > 1 else ""
                if brain_name in ("off", ""):
                    engine.set_brain("")
                    console.print("[yellow]Brain deactivated.[/yellow]")
                else:
                    try:
                        engine.set_brain(brain_name)
                        console.print(f"[yellow]Brain activated: {brain_name}[/yellow]")
                    except ValueError as e:
                        console.print(f"[red]{e}[/red]")
                continue
            elif cmd == "/retry":
                if last_user_input is None:
                    console.print("[dim]Nothing to retry.[/dim]")
                    continue
                user_input = last_user_input
                console.print(f"[dim]Retrying: {user_input[:60]}...[/dim]")
            elif cmd == "/undo":
                # Find and remove the last user→assistant→tool block
                msgs = engine.messages
                # Remove from the last user message to the end
                last_user_idx = -1
                for i in range(len(msgs) - 1, -1, -1):
                    if msgs[i].role == "user":
                        last_user_idx = i
                        break
                # Also remove last assistant if it's after user
                if last_user_idx >= 0:
                    removed = len(msgs) - last_user_idx
                    del msgs[last_user_idx:]
                    console.print(f"[yellow]Removed last {removed} message(s) from history.[/yellow]")
                else:
                    console.print("[dim]Nothing to undo.[/dim]")
                continue
            elif cmd == "/tools":
                _print_tools()
                continue
            elif cmd == "/skills" or cmd.startswith("/skills "):
                _print_skills(config.project_root or os.getcwd(), cmd)
                continue

            # !cmd — bash passthrough
            if user_input.strip().startswith("!"):
                shell_cmd = user_input.strip()[1:].strip()
                if shell_cmd:
                    import types as _types
                    from mai_agent.tools.bash import BashTool
                    result = await BashTool().call(
                        _types.SimpleNamespace(command=shell_cmd, timeout=30000, description=""),
                        engine._run_context,
                    )
                    console.print(f"[dim]{result}[/dim]")
                continue

            # ── Normal LLM interaction ──────────────────
            last_user_input = user_input
            answer, messages = await _run_with_progress(
                engine, user_input, session_id, config.project_root or ".",
                permission_mode=engine._loop_config.permission_mode,
            )
            console.print()
            console.print(Panel(Markdown(answer), title="MAI-agent"))
            save_session(session_id, messages, config.project_root or ".")
            console.print(f"[dim]Session saved ({len(messages)} messages)[/dim]")

        except (KeyboardInterrupt, EOFError):
            now = time.monotonic()
            elapsed = now - last_ctrl_c
            last_ctrl_c = now
            if elapsed < 1.0:
                _save_history()
                _print_recap(engine)
                await engine.stop()
                console.print("\n[dim]Goodbye![/dim]")
                break
            else:
                console.print("\n[yellow]Press Ctrl+C again within 1 second to exit.[/yellow]")
                continue
        except Exception as exc:
            msg = str(exc) or type(exc).__name__
            if msg:
                console.print(f"[red]Error: {msg}[/red]")
            logger.debug("REPL exception", exc_info=True)


@click.command()
@click.option("--once", "-1", default=None, help="Single execution mode")
@click.option("--session", "-s", default="default", help="Session ID")
@click.option("--plan", "-p", is_flag=True, help="Plan mode (read-only)")
@click.option("--auto", "-a", "auto_mode", is_flag=True, help="Auto mode (no confirmation)")
@click.option("--sandbox", "sandbox_mode", default=None,
              type=click.Choice(["off", "default", "strict"]),
              help="Bash 沙箱模式: off | default | strict")
@click.option("--serve", is_flag=True, help="启动桌面端服务器 (http://localhost:8765)")
@click.option("--desktop", is_flag=True, help="启动 Electron 原生桌面应用")
@click.option("--port", default=8765, help="服务器端口 (默认 8765)")
@click.option("--verbose", "-v", is_flag=True, help="Verbose logging")
def main(once=None, session="default", plan=False, auto_mode=False,
         sandbox_mode=None, serve=False, desktop=False, port=8765, verbose=False):
    """MAI-agent — Personal Development Agent Platform"""
    _setup_logging(verbose)
    try:
        config = get_config()
        config.validate()
    except RuntimeError as exc:
        console.print(f"[red]Startup failed: {exc}[/red]")
        sys.exit(1)
    if plan:
        config.permission_mode = "plan"
    elif auto_mode:
        config.permission_mode = "auto"
    if sandbox_mode:
        config.sandbox_mode = sandbox_mode
    if desktop:
        _start_desktop(port)
        return
    if serve:
        _start_server(port)
        return
    if once:
        sys.exit(asyncio.run(_run_once(config, once, session)))
    else:
        sys.exit(asyncio.run(_run_repl(config, session)))


def _start_desktop(port: int = 8765):
    """启动 Electron 原生桌面应用。

    架构（ChatGPT Desktop 同款）：
      Electron (Chromium 窗口) → 加载 localhost:PORT → Python 后端提供 WebSocket

    Electron 主进程负责：窗口管理 + 系统托盘 + 启动/停止 Python 后端。
    """
    import subprocess
    import webbrowser
    from pathlib import Path

    desktop_dir = Path(__file__).parent.parent / "desktop"

    # 1. 检查 Node.js
    try:
        subprocess.run(["node", "--version"], capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        console.print("[red]需要 Node.js 来运行桌面应用。请先安装 Node.js。[/red]")
        sys.exit(1)

    # 2. 检查 Electron 是否已安装
    if not (desktop_dir / "node_modules" / "electron").exists():
        console.print("[yellow]首次运行，正在安装 Electron（约 200MB）...[/yellow]")
        result = subprocess.run(
            ["npm", "install"], cwd=str(desktop_dir),
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            console.print(f"[red]Electron 安装失败: {result.stderr}[/red]")
            sys.exit(1)
        console.print("[green]Electron 安装完成[/green]")

    console.print(Panel.fit(
        "[bold]MAI-agent Desktop[/bold]\n\n"
        "正在启动原生桌面应用...\n"
        f"Electron 窗口将自动打开。\n"
        f"关闭窗口后应用最小化到托盘。",
        title="Desktop",
        border_style="green",
    ))

    # 2.5 清理旧进程（避免端口冲突）
    if os.name == "nt":
        try:
            subprocess.run(
                f'for /f "tokens=5" %a in (\'netstat -ano ^| findstr :{port}\') do taskkill /F /PID %a',
                shell=True, capture_output=True, timeout=5,
            )
        except Exception:
            pass

    # 3. 启动 Python 后端（后台进程，强制 UTF-8）
    python_env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    python_proc = subprocess.Popen(
        [sys.executable, "-X", "utf8", "-c",
         f"import uvicorn; from mai_agent.server import app; "
         f"uvicorn.run(app, host='127.0.0.1', port={port}, log_level='error')"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        env=python_env,
    )

    # 4. 启动 Electron
    e_bin = desktop_dir / "node_modules" / ".bin"
    e_cmd = str(e_bin / "electron.cmd" if os.name == "nt" else e_bin / "electron")
    try:
        subprocess.run(
            [e_cmd, "."],
            cwd=str(desktop_dir),
            env={**os.environ, "MAI_PORT": str(port)},
        )
    except KeyboardInterrupt:
        pass
    finally:
        python_proc.terminate()
        try:
            python_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            python_proc.kill()


def _start_server(port: int = 8765):
    """启动桌面端服务器 + 自动打开浏览器。"""
    import webbrowser
    from mai_agent.server import app

    console.print(Panel.fit(
        f"[bold]MAI-agent Desktop[/bold]\n\n"
        f"服务器: [bold cyan]http://localhost:{port}[/bold cyan]\n"
        f"WebSocket: [bold cyan]ws://localhost:{port}/ws[/bold cyan]\n\n"
        f"[dim]浏览器将自动打开。按 Ctrl+C 停止。[/dim]",
        title="Desktop Server",
        border_style="green",
    ))

    # 延迟打开浏览器，留时间给服务器启动
    def _open_browser():
        import time
        time.sleep(1.0)
        webbrowser.open(f"http://localhost:{port}")

    import threading
    threading.Thread(target=_open_browser, daemon=True).start()

    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")


if __name__ == "__main__":
    main()
