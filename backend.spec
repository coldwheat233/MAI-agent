# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置 — 把 mai_agent.server 打成自包含 backend.exe。

关键点：
  - uvicorn 的动态导入（loops/protocols/lifespan）用 collect_submodules 兜底
  - fastapi/starlette/anyio/pydantic 有官方 hook，但显式 collect 更稳
  - static 目录（SPA 前端产物）作为 datas 打进 _MEIPASS/mai_agent/static/
    server.py 里 STATIC_DIR = Path(__file__).parent / "static" 正好能解析到
"""

from PyInstaller.utils.hooks import collect_submodules

# fastapi/starlette/anyio/pydantic 有 PyInstaller 内置 hook，无需手动 collect。
# 只有 uvicorn 的 loops/protocols/lifespan 是运行时动态 import，手动兜底。
hiddenimports = collect_submodules("uvicorn")

datas = [("mai_agent/static", "mai_agent/static")]

a = Analysis(
    ["backend_entry.py"],
    pathex=["."],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="backend",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # 无黑框（GUI 子系统）
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
