"""Normalise raw chess.com game JSON into a flat, analysis-friendly shape."""
from __future__ import annotations

import io
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone

import chess
import chess.pgn

from .config import Config

# chess.com "result" strings that mean the game was drawn.
_DRAW_RESULTS = {
    "agreed", "repetition", "stalemate", "insufficient",
    "50move", "timevsinsufficient",
}
_CLK_RE = re.compile(r"\[%clk\s+([0-9:.]+)\]")


def _clk_to_seconds(text: str) -> float | None:
    try:
        parts = text.split(":")
        parts = [float(p) for p in parts]
        while len(parts) < 3:
            parts.insert(0, 0.0)
        h, m, s = parts[-3:]
        return h * 3600 + m * 60 + s
    except (ValueError, IndexError):
        return None


def _opening_from_url(eco_url: str | None) -> str | None:
    if not eco_url:
        return None
    slug = eco_url.rstrip("/").split("/")[-1]
    # e.g. "Italian-Game-Italian-Variation" -> "Italian Game Italian Variation"
    name = slug.replace("-", " ").strip()
    return name or None


@dataclass
class Move:
    ply: int          # 1-based
    move_no: int       # full-move number
    san: str
    by_player: bool
    clock: float | None  # seconds remaining after the move


@dataclass
class Game:
    uuid: str
    url: str
    end_time: int
    date: str          # ISO date (UTC)
    time_class: str
    time_control: str
    rated: bool
    rules: str
    color: str         # "white" | "black" (colour the player had)
    outcome: str       # "win" | "loss" | "draw"
    result_reason: str  # raw chess.com result for the player's side
    player_rating: int | None
    opponent: str
    opponent_rating: int | None
    eco: str | None
    opening: str | None
    ply_count: int
    pgn: str
    moves: list[Move] = field(default_factory=list)
    accuracy: float | None = None  # chess.com's own accuracy for the player, if present

    def as_meta(self) -> dict:
        """Lightweight dict (no move list / pgn) for report joins."""
        return {
            "uuid": self.uuid, "url": self.url, "date": self.date,
            "time_class": self.time_class, "color": self.color,
            "outcome": self.outcome, "result_reason": self.result_reason,
            "player_rating": self.player_rating, "opponent": self.opponent,
            "opponent_rating": self.opponent_rating, "eco": self.eco,
            "opening": self.opening, "ply_count": self.ply_count,
            "accuracy": self.accuracy,
        }


def _outcome(player_result: str) -> str:
    if player_result == "win":
        return "win"
    if player_result in _DRAW_RESULTS:
        return "draw"
    return "loss"


def normalise_game(raw: dict, username: str) -> Game | None:
    white = raw.get("white", {})
    black = raw.get("black", {})
    uname = username.lower()
    if white.get("username", "").lower() == uname:
        color, me, opp = "white", white, black
    elif black.get("username", "").lower() == uname:
        color, me, opp = "black", black, white
    else:
        return None  # not the target player's game

    pgn_text = raw.get("pgn", "") or ""
    game = chess.pgn.read_game(io.StringIO(pgn_text)) if pgn_text else None

    moves: list[Move] = []
    if game is not None:
        board = game.board()
        ply = 0
        for node in game.mainline():
            ply += 1
            san = board.san(node.move)
            is_white_move = board.turn == chess.WHITE
            clock = None
            m = _CLK_RE.search(node.comment or "")
            if m:
                clock = _clk_to_seconds(m.group(1))
            by_player = (color == "white") == is_white_move
            moves.append(Move(
                ply=ply, move_no=(ply + 1) // 2, san=san,
                by_player=by_player, clock=clock,
            ))
            board.push(node.move)

    end_time = raw.get("end_time", 0)
    date = datetime.fromtimestamp(end_time, tz=timezone.utc).date().isoformat() if end_time else ""

    accuracies = raw.get("accuracies") or {}
    accuracy = accuracies.get(color)

    return Game(
        uuid=raw.get("uuid", raw.get("url", "")),
        url=raw.get("url", ""),
        end_time=end_time,
        date=date,
        time_class=raw.get("time_class", ""),
        time_control=str(raw.get("time_control", "")),
        rated=bool(raw.get("rated", False)),
        rules=raw.get("rules", "chess"),
        color=color,
        outcome=_outcome(me.get("result", "")),
        result_reason=me.get("result", ""),
        player_rating=me.get("rating"),
        opponent=opp.get("username", ""),
        opponent_rating=opp.get("rating"),
        eco=(game.headers.get("ECO") if game else None),
        opening=_opening_from_url(raw.get("eco") or (game.headers.get("ECOUrl") if game else None)),
        ply_count=len(moves),
        pgn=pgn_text,
        moves=moves,
        accuracy=accuracy,
    )


def load_games(cfg: Config, standard_only: bool = True) -> list[Game]:
    """Load and normalise every stored game, sorted oldest-first by end time."""
    games: list[Game] = []
    for path in sorted(cfg.paths.games.glob("*.json")):
        raw_list = json.loads(path.read_text())
        for raw in raw_list:
            if standard_only and raw.get("rules", "chess") != "chess":
                continue  # skip variants (chess960, bughouse, etc.)
            g = normalise_game(raw, cfg.username)
            if g is not None:
                games.append(g)
    games.sort(key=lambda g: g.end_time)
    return games
