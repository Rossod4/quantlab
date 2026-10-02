"""Machine-independent path strings for anything COMMITTED (report cards,
rendered reports): a path under the repository root is shown relative to it
with forward slashes; a path outside it is reduced to `<external>/<name>`
so a username or temp directory never leaks into a committed file."""

from __future__ import annotations

from pathlib import Path

# src/quantlab/core/paths.py -> repo root is three levels above this file.
REPO_ROOT = Path(__file__).resolve().parents[3]


def portable_path(path: str | Path) -> str:
    resolved = Path(path)
    try:
        resolved = resolved.resolve()
        return resolved.relative_to(REPO_ROOT).as_posix()
    except (ValueError, OSError):
        return f"<external>/{Path(path).name}"
