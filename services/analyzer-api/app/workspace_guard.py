"""Restrict analyzer workspaces to an explicit allowlist of trusted roots.

The analyzer accepts a workspace path from its local caller. When
``TERRAMIND_ALLOWED_ROOTS`` is configured, every workspace must resolve to one
of those trusted roots. Paths are resolved before they are compared so a
symlink or junction cannot be used to escape an allowed root.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import HTTPException

_ALLOWED_ROOTS_ENV = "TERRAMIND_ALLOWED_ROOTS"


def allowed_roots() -> list[Path]:
    """Return the existing directories named by ``TERRAMIND_ALLOWED_ROOTS``.

    The variable is split on ``os.pathsep``; blank entries are ignored and
    ``~`` is expanded. An unset or empty variable returns ``[]``, which means
    "no allowlist is configured".
    """
    configured = os.environ.get(_ALLOWED_ROOTS_ENV, "")
    roots: list[Path] = []
    for entry in configured.split(os.pathsep):
        entry = entry.strip()
        if not entry:
            continue
        root = Path(entry).expanduser().resolve()
        if root.is_dir():
            roots.append(root)
    return roots


def resolve_workspace(workspace_path: str, *, require_allowed_root: bool = False) -> Path:
    """Resolve a caller-supplied workspace path and enforce the allowlist.

    The path must resolve to an existing directory (otherwise ``400``). When an
    allowlist is configured, the resolved path must equal or live inside one of
    the allowed roots (otherwise ``403``). Set ``require_allowed_root`` to reject
    requests when no allowlist is configured at all.
    """
    workspace = Path(workspace_path).expanduser().resolve()
    if not workspace.is_dir():
        raise HTTPException(status_code=400, detail="workspace_path must be an existing directory")

    roots = allowed_roots()
    if not roots:
        if require_allowed_root:
            raise HTTPException(
                status_code=403,
                detail=(
                    "workspace_path cannot be authorized because "
                    "TERRAMIND_ALLOWED_ROOTS is not configured"
                ),
            )
        return workspace

    for root in roots:
        if workspace == root or workspace.is_relative_to(root):
            return workspace

    raise HTTPException(
        status_code=403,
        detail="workspace_path is outside the configured TERRAMIND_ALLOWED_ROOTS allowlist",
    )
