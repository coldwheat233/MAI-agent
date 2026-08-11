"""Tool utility functions — shared across all tools."""

from pathlib import Path


def resolve_path(raw: str, cwd: str) -> Path:
    """Resolve a path string to an absolute Path, handling Windows quirks.

    On Windows, Path('/d/PY_PROJ').is_absolute() returns False because
    Windows requires 'D:\\' format. This handles Git Bash / MSYS2 style
    paths where /d/foo means D:/foo.
    """
    p = Path(raw)

    if p.is_absolute():
        return p

    # Try as POSIX absolute path on Windows (Git Bash / MSYS2 format)
    # e.g., /d/PY_PROJ/... → D:/PY_PROJ/...
    #       /c/Users/...  → C:/Users/...
    if raw.startswith("/"):
        # /x/path → X:/path (single-letter drive convention)
        import re
        m = re.match(r"^/([a-zA-Z])(/.*)", raw)
        if m:
            drive = m.group(1).upper() + ":"
            rest = m.group(2)
            candidate = Path(drive + rest)
            if candidate.exists():
                return candidate
        # Try common drive letters
        for drive in ("D:", "C:", "E:"):
            alt = Path(drive + raw)
            if alt.exists():
                return alt
        # If raw was /d/... and D:/d/... doesn't exist, try stripping /d
        if m:
            candidate2 = Path(drive + rest)
            if candidate2.exists():
                return candidate2

    # Relative path: join with cwd
    abs_path = Path(cwd) / p
    return abs_path.resolve()
