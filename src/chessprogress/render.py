"""Render report.json into a static HTML site with Jinja2."""
from __future__ import annotations

import json
import re
import shutil

import chess
import chess.svg
from jinja2 import Environment, FileSystemLoader, select_autoescape

from .config import Config
from .engine import load_analyses

_BEST_COLOR = "#2f855a"    # green arrow = engine's best move
_PLAYED_COLOR = "#c53030"  # red arrow = move actually played


def _piece_defs() -> str:
    """The Cburnett piece <defs> block from python-chess, so the interactive
    board reuses the exact same piece set as the server-rendered diagrams."""
    svg = chess.svg.board(chess.Board(), size=360)
    m = re.search(r"<defs>.*?</defs>", svg, re.DOTALL)
    return m.group(0) if m else ""


def _markers(analysis: dict) -> list[dict]:
    """Flatten the analysis cards into per-ply markers for the eval trace.
    Card evals are player-POV (matching the site's blunder/highlight text)."""
    out: list[dict] = []

    def base(card: dict, kind: str) -> dict:
        return {
            "ply": card["ply"], "type": kind, "move_no": card["move_no"],
            "phase": card["phase"], "played_san": card["played_san"],
            "eval_before": card["eval_before"], "eval_after": card["eval_after"],
        }

    for b in analysis.get("blunders", []):
        out.append({**base(b, "blunder"), "cpl": b.get("cpl"),
                    "best_san": b.get("best_san"), "best_uci": b.get("best_uci")})
    hl = analysis.get("highlights") or {}
    for b in hl.get("brilliant", []):
        out.append({**base(b, "brilliant"), "sac_cp": b.get("sac_cp")})
    for g in hl.get("great", []):
        out.append({**base(g, "great"), "gap": g.get("gap")})

    out.sort(key=lambda m: m["ply"])
    return out


def _write_viewer_games(site, report: dict, analyses: dict, thresholds: dict) -> int:
    """One JSON per highlight game with the per-ply moves/evals/markers the
    interactive viewer replays. Metadata comes from report['viewer']['games']."""
    games_dir = site / "data" / "games"
    games_dir.mkdir(parents=True, exist_ok=True)
    written = 0
    for meta in report.get("viewer", {}).get("games", []):
        a = analyses.get(meta["uuid"])
        if not a or not a.get("moves_uci"):
            continue
        blob = {
            **meta,
            "username": report["username"],
            "start_fen": a.get("start_fen", chess.STARTING_FEN),
            "moves_uci": a["moves_uci"],
            "evals": a["evals"],
            "markers": _markers(a),
            # Centipawn-loss bands so the viewer's running commentary classifies
            # moves the same way the rest of the site does.
            "thresholds": {
                "inaccuracy": thresholds["inaccuracy_cp"],
                "mistake": thresholds["mistake_cp"],
                "blunder": thresholds["blunder_cp"],
            },
        }
        (games_dir / f"{meta['uuid']}.json").write_text(json.dumps(blob))
        written += 1
    return written


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


def _highlight_svg(item: dict) -> str:
    """Render a highlight position with a single green arrow on the played move."""
    try:
        board = chess.Board(item["fen_before"])
    except (ValueError, KeyError):
        return ""
    arrows = []
    if item.get("played_uci"):
        mv = chess.Move.from_uci(item["played_uci"])
        arrows.append(chess.svg.Arrow(mv.from_square, mv.to_square, color=_BEST_COLOR))
    orientation = chess.WHITE if item.get("side") == "white" else chess.BLACK
    return chess.svg.board(board=board, arrows=arrows, orientation=orientation,
                           size=340, coordinates=True)

_PAGES = {
    "index.html": "index",
    "openings.html": "openings",
    "tactics.html": "tactics",
    "highlights.html": "highlights",
    "games.html": "games",
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
    for item in ctx["highlights"]["brilliant"] + ctx["highlights"]["great"]:
        item["board_svg"] = _highlight_svg(item)

    # Per-game move/eval data for the interactive viewer (highlight games only).
    analyses = load_analyses(cfg)
    n_games = _write_viewer_games(site, report, analyses, cfg.thresholds)
    piece_defs = _piece_defs()

    env = _env(cfg)
    for template_name, page in _PAGES.items():
        html = env.get_template(template_name).render(
            report=ctx, page=page, data_json=data_json, title=cfg.site["title"],
            piece_defs=piece_defs,
        )
        (site / template_name).write_text(html)
    print(f"  rendered {len(_PAGES)} pages to {site} ({n_games} viewer games)")
