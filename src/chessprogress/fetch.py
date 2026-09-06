"""Download chess.com games via the public Published-Data API.

Games are stored one file per month at ``data/games/YYYY-MM.json`` (the raw
list of game objects). Past months are immutable, so we only download a month
we don't already have plus the current (still-open) month.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone

import requests

from .config import Config

API = "https://api.chess.com/pub"
# chess.com asks for a User-Agent that identifies the app (no personal contact needed).
USER_AGENT = "chess-progress-analyzer/0.1 (+https://github.com/jamiebull1/arduino-chess-clock)"
_MAX_RETRIES = 4


def _get(url: str) -> requests.Response:
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    delay = 2.0
    for attempt in range(_MAX_RETRIES):
        resp = requests.get(url, headers=headers, timeout=30)
        if resp.status_code == 429:
            time.sleep(delay)
            delay *= 2
            continue
        resp.raise_for_status()
        return resp
    resp.raise_for_status()
    return resp


def _month_key(archive_url: str) -> str:
    """`.../games/2026/09` -> `2026-09`."""
    year, month = archive_url.rstrip("/").split("/")[-2:]
    return f"{year}-{month}"


def run(cfg: Config) -> list[str]:
    """Fetch profile, stats and missing/open archives. Returns month keys written."""
    cfg.paths.games.mkdir(parents=True, exist_ok=True)
    username = cfg.username.lower()

    # Profile + stats are small and always refreshed (they carry current ratings).
    profile = _get(f"{API}/player/{username}").json()
    stats = _get(f"{API}/player/{username}/stats").json()
    (cfg.paths.data / "profile.json").write_text(json.dumps(profile, indent=0))
    (cfg.paths.data / "stats.json").write_text(json.dumps(stats, indent=0))

    archives = _get(f"{API}/player/{username}/games/archives").json().get("archives", [])
    now = datetime.now(timezone.utc)
    current = f"{now.year:04d}-{now.month:02d}"

    written: list[str] = []
    for archive_url in archives:
        key = _month_key(archive_url)
        dest = cfg.paths.games / f"{key}.json"
        # Skip closed months we already have; always refresh the current month.
        if dest.exists() and key != current:
            continue
        games = _get(archive_url).json().get("games", [])
        dest.write_text(json.dumps(games, indent=0))
        written.append(key)
        print(f"  fetched {key}: {len(games)} games")
        time.sleep(0.5)  # be polite to the API

    if not written:
        print("  all archives already up to date")
    return written
