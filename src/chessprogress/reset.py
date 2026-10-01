"""Clearing cached data, including automatically when the player changes."""
from __future__ import annotations

import json
import shutil

from .config import Config

MARKER = ".player"


def clear(cfg: Config) -> None:
    """Delete cached games, analysis and the report; keeps data/ itself."""
    for path in (cfg.paths.games, cfg.paths.analysis):
        shutil.rmtree(path, ignore_errors=True)
    for name in ("report.json", "profile.json", "stats.json", MARKER):
        (cfg.paths.data / name).unlink(missing_ok=True)
    print("cleared cached data.")


def _cached_player(cfg: Config) -> str | None:
    marker = cfg.paths.data / MARKER
    if marker.exists():
        return marker.read_text().strip().lower()
    report = cfg.paths.data / "report.json"  # data cached before the marker existed
    if report.exists():
        try:
            return json.loads(report.read_text()).get("username", "").lower() or None
        except ValueError:
            return None
    return None


def clear_if_player_changed(cfg: Config) -> None:
    """Wipe the cache if it belongs to a different player, then record the current one."""
    cached = _cached_player(cfg)
    if cached and cached != cfg.username.lower():
        print(f"player changed ({cached} -> {cfg.username.lower()}):")
        clear(cfg)
    cfg.paths.data.mkdir(parents=True, exist_ok=True)
    (cfg.paths.data / MARKER).write_text(cfg.username.lower() + "\n")
