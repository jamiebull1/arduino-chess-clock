"""Stockfish analysis: per-move centipawn loss, cached one file per game.

Method (one engine evaluation per position, so it is cheap):
evaluate every position *before* each ply plus the final position, all from
White's point of view. The centipawn loss of the player who moved at ply *i* is
the drop in their own evaluation between position *i* and position *i+1*.
Evaluations are clamped to +/- ``eval_cap_cp`` so a single resign-worthy
position can't dominate the averages.
"""
from __future__ import annotations

import io
import json

import chess
import chess.engine
import chess.pgn

from .config import Config, resolve_stockfish
from .parse import Game

_SCHEMA = 2  # bump to invalidate cached analyses when the method changes


def _limit(engine_cfg: dict) -> chess.engine.Limit:
    if engine_cfg.get("depth"):
        return chess.engine.Limit(depth=int(engine_cfg["depth"]))
    return chess.engine.Limit(time=int(engine_cfg["movetime_ms"]) / 1000.0)


def _eval_white_cp(engine: chess.engine.SimpleEngine, board: chess.Board,
                   limit: chess.engine.Limit, cap: int) -> int:
    if board.is_game_over():
        # Terminal node: settle the score without asking the engine.
        outcome = board.outcome()
        if outcome is None or outcome.winner is None:
            return 0
        return cap if outcome.winner == chess.WHITE else -cap
    info = engine.analyse(board, limit)
    cp = info["score"].white().score(mate_score=100000)
    return max(-cap, min(cap, int(cp)))


def _phase(move_no: int, board: chess.Board, opening_moves: int) -> str:
    if move_no <= opening_moves:
        return "opening"
    non_pawn = sum(
        1 for piece in board.piece_map().values()
        if piece.piece_type not in (chess.PAWN, chess.KING)
    )
    return "endgame" if non_pawn <= 6 else "middlegame"


def analyse_game(game: Game, engine: chess.engine.SimpleEngine, cfg: Config) -> dict:
    thresholds = cfg.thresholds
    cap = int(cfg.engine["eval_cap_cp"])
    limit = _limit(cfg.engine)
    opening_moves = int(cfg.analysis["opening_moves"])
    player_white = game.color == "white"

    parsed = chess.pgn.read_game(io.StringIO(game.pgn))
    node_moves = list(parsed.mainline_moves()) if parsed else []

    board = chess.Board()
    evals_white = [_eval_white_cp(engine, board, limit, cap)]
    boards_meta: list[tuple[int, str, chess.Board]] = []  # (move_no, phase, board-before-move copy)
    for move in node_moves:
        move_no = board.fullmove_number
        phase = _phase(move_no, board, opening_moves)
        boards_meta.append((move_no, phase))
        board.push(move)
        evals_white.append(_eval_white_cp(engine, board, limit, cap))

    player_moves = []
    counts = {"blunder": 0, "mistake": 0, "inaccuracy": 0, "moves": 0}
    by_phase: dict[str, dict] = {
        p: {"moves": 0, "cpl_sum": 0, "blunder": 0} for p in ("opening", "middlegame", "endgame")
    }
    cpl_sum = 0

    replay = chess.Board()
    for idx, move in enumerate(node_moves):
        mover_white = replay.turn == chess.WHITE
        before, after = evals_white[idx], evals_white[idx + 1]
        cpl = (before - after) if mover_white else (after - before)
        cpl = max(0, cpl)
        san = replay.san(move)
        replay.push(move)

        if mover_white != player_white:
            continue  # opponent's move

        move_no, phase = boards_meta[idx]
        counts["moves"] += 1
        cpl_sum += cpl
        by_phase[phase]["moves"] += 1
        by_phase[phase]["cpl_sum"] += cpl
        if cpl >= thresholds["blunder_cp"]:
            counts["blunder"] += 1
            by_phase[phase]["blunder"] += 1
        elif cpl >= thresholds["mistake_cp"]:
            counts["mistake"] += 1
        elif cpl >= thresholds["inaccuracy_cp"]:
            counts["inaccuracy"] += 1

        eval_after_player = after if player_white else -after
        player_moves.append({
            "ply": idx + 1, "move_no": move_no, "san": san,
            "cpl": cpl, "phase": phase, "eval_after": eval_after_player,
        })

    # Player-POV evaluation trajectory, for conversion analysis.
    player_evals = [e if player_white else -e for e in evals_white]
    acpl = round(cpl_sum / counts["moves"], 1) if counts["moves"] else 0.0

    return {
        "schema": _SCHEMA,
        "uuid": game.uuid,
        "url": game.url,
        "date": game.date,
        "color": game.color,
        "outcome": game.outcome,
        "ply_count": game.ply_count,
        "acpl": acpl,
        "counts": counts,
        "by_phase": by_phase,
        "max_player_eval": max(player_evals) if player_evals else 0,
        "min_player_eval": min(player_evals) if player_evals else 0,
        "player_moves": player_moves,
    }


def analyse_all(cfg: Config, games: list[Game]) -> dict:
    """Analyse any game without an up-to-date cache file. Reuses one engine process."""
    cfg.paths.analysis.mkdir(parents=True, exist_ok=True)
    todo = []
    for game in games:
        dest = cfg.paths.analysis / f"{game.uuid}.json"
        if dest.exists():
            try:
                if json.loads(dest.read_text()).get("schema") == _SCHEMA:
                    continue
            except (json.JSONDecodeError, OSError):
                pass
        todo.append(game)

    print(f"  {len(games)} games, {len(todo)} need analysis, {len(games) - len(todo)} cached")
    if not todo:
        return {"analysed": 0, "cached": len(games)}

    sf = resolve_stockfish(cfg.engine.get("path"))
    if not sf:
        raise RuntimeError(
            "Stockfish not found. Install it (`apt-get install stockfish`) or set "
            "engine.path in config.yaml / the STOCKFISH_PATH environment variable."
        )
    print(f"  using engine: {sf}")

    engine = chess.engine.SimpleEngine.popen_uci(sf)
    try:
        engine.configure({
            "Threads": int(cfg.engine.get("threads", 1)),
            "Hash": int(cfg.engine.get("hash_mb", 128)),
        })
        for i, game in enumerate(todo, 1):
            result = analyse_game(game, engine, cfg)
            (cfg.paths.analysis / f"{game.uuid}.json").write_text(json.dumps(result))
            if i % 10 == 0 or i == len(todo):
                print(f"  analysed {i}/{len(todo)}")
    finally:
        engine.quit()

    return {"analysed": len(todo), "cached": len(games) - len(todo)}


def load_analyses(cfg: Config) -> dict[str, dict]:
    out: dict[str, dict] = {}
    if not cfg.paths.analysis.exists():
        return out
    for path in cfg.paths.analysis.glob("*.json"):
        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        out[data.get("uuid", path.stem)] = data
    return out
