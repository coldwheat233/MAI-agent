"""MAI-agent 后端独立入口 — 供 PyInstaller 打包成 backend.exe。

开发模式仍走 `python -c "import uvicorn; ..."`；打包模式由 Electron 直接
spawn 本脚本编译出的 backend.exe（自包含 Python，无黑框、无系统依赖）。

端口通过环境变量 MAI_PORT 传入（默认 8765），与 desktop/backend.ts 对齐。
"""

from __future__ import annotations

import os

import uvicorn

from mai_agent.server import app


def main() -> None:
    port = int(os.environ.get("MAI_PORT", "8765"))
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="error")


if __name__ == "__main__":
    main()
