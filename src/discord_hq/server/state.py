"""Local cache of the ids `apply` manages (roles, categories, channels,
pinned messages). Ids and names only: secret-looking keys are dropped before
writing. The live server is always the source of truth; losing this file
never duplicates anything, it only makes `discord-hq access` wait for the next
`apply`."""

from __future__ import annotations

import json
from pathlib import Path

SENSITIVE_KEYS = {"token", "url", "webhook_url", "token_used"}


def _scrub(value):
    if isinstance(value, dict):
        return {k: _scrub(v) for k, v in value.items() if k not in SENSITIVE_KEYS}
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    return value


def load_state(path: Path) -> dict:
    path = Path(path)
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def save_state(path: Path, state: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_scrub(state), indent=2, sort_keys=True, ensure_ascii=False) + "\n")
