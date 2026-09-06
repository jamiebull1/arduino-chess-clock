"""Render report.json into a static HTML site with Jinja2."""
from __future__ import annotations

import json
import shutil

import chess
import chess.svg
from jinja2 import Environment, FileSystemLoader, select_autoescape

from .config import Config

_BEST_COLOR = "#2f855a"    # green arrow = engine's best move
_PLAYED_COLOR = "#c53030"  # red arrow = move actually played


def _board_svg(blunder: dict) -> str:
    """Render the position before a blunder, with best (green) and played (red) arrows."""
    try:
        board = chess.Board(blunder["fen_before"])
    except (ValueError, KeyError):
        return ""
    arrows = []
    for key, color in (("best_uci", _BEST_COLOR), ("played_uci", _PLAYED_COLOR)):
        uci = blunder.get(key)
        if uci:
            mv = chess.Move.from_uci(uci)
            arrows.append(chess.svg.Arrow(mv.from_square, mv.to_square, color=color))
    orientation = chess.WHITE if blunder.get("side") == "white" else chess.BLACK
    return chess.svg.board(board=board, arrows=arrows, orientation=orientation,
                           size=340, coordinates=True)

_PAGES = {
    "index.html": "index",
    "openings.html": "openings",
    "tactics.html": "tactics",
    "endgames.html": "endgames",
}


def _env(cfg: Config) -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(cfg.paths.templates)),
        autoescape=select_autoescape(["html"]),
    )
    env.filters["pct"] = lambda v: "—" if v is None else f"{v:.1f}%"
    env.filters["num"] = lambda v: "—" if v is None else f"{v:g}"
    return env


def render(cfg: Config, report: dict | None = None) -> None:
    if report is None:
        report = json.loads((cfg.paths.data / "report.json").read_text())

    site = cfg.paths.site
    site.mkdir(parents=True, exist_ok=True)

    # Static assets + a copy of the raw data.
    if cfg.paths.assets.exists():
        shutil.copytree(cfg.paths.assets, site / "assets", dirs_exist_ok=True)
    (site / "data").mkdir(exist_ok=True)
    (site / "data" / "report.json").write_text(json.dumps(report, indent=2))
    (site / ".nojekyll").write_text("")  # serve files/dirs starting with _ untouched

    # data_json (for the charts) stays free of the bulky SVG strings; the
    # template context gets a copy with a rendered board per blunder.
    data_json = json.dumps(report)
    ctx = json.loads(data_json)
    for blunder in ctx["tactics"]["worst_blunders"]:
        blunder["board_svg"] = _board_svg(blunder)

    env = _env(cfg)
    for template_name, page in _PAGES.items():
        html = env.get_template(template_name).render(
            report=ctx, page=page, data_json=data_json, title=cfg.site["title"],
        )
        (site / template_name).write_text(html)
    print(f"  rendered {len(_PAGES)} pages to {site}")
