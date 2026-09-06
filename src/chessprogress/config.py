"""Configuration loading and path resolution."""
from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# repo root = .../src/chessprogress/config.py -> parents[2]
ROOT = Path(__file__).resolve().parents[2]

_DEFAULTS: dict[str, Any] = {
    "username": "rimanish",
    "engine": {
        "path": None,
        "movetime_ms": 100,
        "depth": None,
        "threads": 2,
        "hash_mb": 128,
        "eval_cap_cp": 1500,
    },
    "thresholds": {
        "inaccuracy_cp": 50,
        "mistake_cp": 100,
        "blunder_cp": 300,
        "winning_cp": 200,
    },
    "analysis": {"opening_moves": 10},
    "highlights": {
        "brilliant_max_cpl": 40,
        "brilliant_min_eval_after": 100,
        "brilliant_max_eval_before": 250,
        "sacrifice_min_cp": 200,
        "max_per_game": 2,
        "great_max_cpl": 30,
        "great_gap_cp": 250,
        "great_max_eval_before": 300,
        "great_min_eval_before": -400,
        "verify_movetime_ms": 300,
        "line_plies": 6,
    },
    "site": {
        "title": "chess.com progress",
        "recent_games": 10,
        "worst_blunders": 15,
    },
}

_STOCKFISH_FALLBACKS = ("/usr/games/stockfish", "/usr/bin/stockfish", "/usr/local/bin/stockfish")


def _deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


@dataclass
class Paths:
    root: Path
    data: Path
    games: Path
    analysis: Path
    site: Path
    templates: Path
    assets: Path


@dataclass
class Config:
    raw: dict
    paths: Paths

    @property
    def username(self) -> str:
        return self.raw["username"]

    @property
    def engine(self) -> dict:
        return self.raw["engine"]

    @property
    def thresholds(self) -> dict:
        return self.raw["thresholds"]

    @property
    def analysis(self) -> dict:
        return self.raw["analysis"]

    @property
    def highlights(self) -> dict:
        return self.raw["highlights"]

    @property
    def site(self) -> dict:
        return self.raw["site"]


def resolve_stockfish(configured: str | None) -> str | None:
    """Find a Stockfish binary. Order: config -> $STOCKFISH_PATH -> PATH -> known dirs."""
    candidates = [configured, os.environ.get("STOCKFISH_PATH")]
    for cand in candidates:
        if cand and Path(cand).exists():
            return cand
    found = shutil.which("stockfish")
    if found:
        return found
    for fallback in _STOCKFISH_FALLBACKS:
        if Path(fallback).exists():
            return fallback
    return None


def load(config_path: str | os.PathLike | None = None, root: Path | None = None) -> Config:
    root = Path(root) if root else ROOT
    path = Path(config_path) if config_path else root / "config.yaml"
    override: dict = {}
    if path.exists():
        override = yaml.safe_load(path.read_text()) or {}
    raw = _deep_merge(_DEFAULTS, override)

    data = root / "data"
    paths = Paths(
        root=root,
        data=data,
        games=data / "games",
        analysis=data / "analysis",
        site=root / "_site",
        templates=root / "templates",
        assets=root / "assets",
    )
    return Config(raw=raw, paths=paths)
