from __future__ import annotations

import os
from pathlib import Path


def _resolved(path) -> Path:
    try:
        return Path(path).expanduser().resolve()
    except Exception:
        return Path(path).expanduser()


def _legacy_existing_dirs(app_base: Path):
    """Discover prior extracted Lottery AI data folders without overriding explicit paths."""
    seen = set()
    roots = [app_base.parent, app_base.parent.parent]
    if os.name == "nt" and Path("D:/").exists():
        roots.insert(0, Path("D:/"))
    for root in roots:
        if not root.exists():
            continue
        try:
            candidates = list(root.glob("*Lottery_AI*/data")) + list(root.glob("*Lottery AI*/data"))
        except Exception:
            candidates = []
        for candidate in candidates:
            p = _resolved(candidate)
            key = str(p).lower()
            if key in seen:
                continue
            seen.add(key)
            if (p / "lottery.db").exists():
                yield p


def resolve_data_dir(app_base: Path) -> Path:
    """Resolve persistent data with deterministic, documented precedence.

    Priority is explicit ``LOTTERY_AI_DATA`` -> this build's local existing database
    -> stable Windows shared location -> legacy discovered databases. A larger stale
    database can no longer override an explicit or local selection.
    """
    app_base = _resolved(app_base)

    explicit = os.environ.get("LOTTERY_AI_DATA")
    if explicit:
        chosen = _resolved(explicit)
        chosen.mkdir(parents=True, exist_ok=True)
        return chosen

    local = app_base / "data"
    if (local / "lottery.db").exists():
        local.mkdir(parents=True, exist_ok=True)
        return local

    stable = Path("D:/Lottery_AI/data") if os.name == "nt" and Path("D:/").exists() else None
    if stable is not None and (stable / "lottery.db").exists():
        stable.mkdir(parents=True, exist_ok=True)
        return stable

    legacy = []
    for path in _legacy_existing_dirs(app_base):
        try:
            stat = (path / "lottery.db").stat()
            legacy.append((stat.st_mtime, stat.st_size, path))
        except OSError:
            legacy.append((0, 0, path))
    if legacy:
        # Only legacy fallback candidates compete by recency/size.
        legacy.sort(key=lambda row: (row[0], row[1]), reverse=True)
        chosen = legacy[0][2]
        chosen.mkdir(parents=True, exist_ok=True)
        return chosen

    chosen = stable if stable is not None else local
    chosen.mkdir(parents=True, exist_ok=True)
    return chosen
