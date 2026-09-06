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

_SCHEMA = 5  # bump to invalidate cached analyses when the method changes
_CONTEXT_PLIES = 6  # half-moves of run-up shown on a blunder / highlight card
_VALUES = {chess.PAWN: 100, chess.KNIGHT: 300, chess.BISHOP: 300, chess.ROOK: 500, chess.QUEEN: 900}


def _limit(engine_cfg: dict) -> chess.engine.Limit:
    if engine_cfg.get("depth"):
        return chess.engine.Limit(depth=int(engine_cfg["depth"]))
    return chess.engine.Limit(time=int(engine_cfg["movetime_ms"]) / 1000.0)


def _phase(move_no: int, board: chess.Board, opening_moves: int) -> str:
    if move_no <= opening_moves:
        return "opening"
    non_pawn = sum(
        1 for piece in board.piece_map().values()
        if piece.piece_type not in (chess.PAWN, chess.KING)
    )
    return "endgame" if non_pawn <= 6 else "middlegame"


def _clamp(cp: int, cap: int) -> int:
    return max(-cap, min(cap, int(cp)))


def _analyse_multi(engine: chess.engine.SimpleEngine, board: chess.Board,
                   limit: chess.engine.Limit, cap: int, multipv: int
                   ) -> tuple[int, chess.Move | None, int | None]:
    """Return (best White-POV cp, best move, second-best White-POV cp or None)."""
    if board.is_game_over():
        outcome = board.outcome()
        if outcome is None or outcome.winner is None:
            return 0, None, None
        return (cap if outcome.winner == chess.WHITE else -cap), None, None
    info = engine.analyse(board, limit, multipv=multipv)
    lines = info if isinstance(info, list) else [info]
    best = lines[0]
    best_cp = _clamp(best["score"].white().score(mate_score=100000), cap)
    best_mv = (best.get("pv") or [None])[0]
    second_cp = (_clamp(lines[1]["score"].white().score(mate_score=100000), cap)
                 if len(lines) > 1 else None)
    return best_cp, best_mv, second_cp


def _eval_pv_deep(engine: chess.engine.SimpleEngine, board: chess.Board,
                  limit: chess.engine.Limit, cap: int) -> tuple[int, list[chess.Move]]:
    """Deeper single-line analysis: (White-POV cp, principal variation)."""
    if board.is_game_over():
        outcome = board.outcome()
        term = 0 if (outcome is None or outcome.winner is None) else (cap if outcome.winner == chess.WHITE else -cap)
        return term, []
    info = engine.analyse(board, limit)
    return _clamp(info["score"].white().score(mate_score=100000), cap), list(info.get("pv") or [])


def _material(board: chess.Board, player_white: bool) -> int:
    """Signed material (player minus opponent), in centipawns."""
    total = 0
    for piece in board.piece_map().values():
        value = _VALUES.get(piece.piece_type, 0)
        total += value if (piece.color == chess.WHITE) == player_white else -value
    return total


def _captured_value(board: chess.Board, move: chess.Move) -> int:
    if board.is_en_passant(move):
        return 100
    piece = board.piece_at(move.to_square)
    return _VALUES.get(piece.piece_type, 0) if piece else 0


def analyse_game(game: Game, engine: chess.engine.SimpleEngine, cfg: Config) -> dict:
    thresholds = cfg.thresholds
    cap = int(cfg.engine["eval_cap_cp"])
    limit = _limit(cfg.engine)
    opening_moves = int(cfg.analysis["opening_moves"])
    player_white = game.color == "white"

    hl = cfg.highlights
    vlimit = chess.engine.Limit(time=int(hl["verify_movetime_ms"]) / 1000.0)

    def to_player(cp_white: int) -> int:
        return cp_white if player_white else -cp_white

    parsed = chess.pgn.read_game(io.StringIO(game.pgn))
    node_moves = list(parsed.mainline_moves()) if parsed else []

    # Forward pass: evaluate every position once. Player-to-move positions get
    # multipv=2 so we also learn the second-best eval (for "only good move").
    board = chess.Board()
    evals_white: list[int] = []
    best_moves: list[chess.Move | None] = []
    second_white: list[int | None] = []
    boards_meta: list[tuple[int, str]] = []  # (move_no, phase) before each ply
    n = len(node_moves)
    for i in range(n + 1):
        is_player = ((i % 2 == 0) == player_white)
        cp, best, second = _analyse_multi(engine, board, limit, cap, 2 if (is_player and i < n) else 1)
        evals_white.append(cp)
        best_moves.append(best)
        second_white.append(second)
        if i < n:
            boards_meta.append((board.fullmove_number, _phase(board.fullmove_number, board, opening_moves)))
            board.push(node_moves[i])

    counts = {"blunder": 0, "mistake": 0, "inaccuracy": 0, "moves": 0}
    by_phase: dict[str, dict] = {
        p: {"moves": 0, "cpl_sum": 0, "blunder": 0} for p in ("opening", "middlegame", "endgame")
    }
    cpl_sum = 0
    blunders: list[dict] = []
    brilliant: list[dict] = []
    great: list[dict] = []

    replay = chess.Board()
    sans: list[str] = []
    for idx, move in enumerate(node_moves):
        mover_white = replay.turn == chess.WHITE
        before, after = evals_white[idx], evals_white[idx + 1]
        cpl = max(0, (before - after) if mover_white else (after - before))
        san = replay.san(move)
        fen_before = replay.fen()
        move_no, phase = boards_meta[idx]

        if mover_white != player_white:
            replay.push(move)
            sans.append(san)
            continue  # opponent's move

        counts["moves"] += 1
        cpl_sum += cpl
        by_phase[phase]["moves"] += 1
        by_phase[phase]["cpl_sum"] += cpl

        def card(extra: dict) -> dict:
            return {
                "ply": idx + 1, "move_no": move_no, "phase": phase, "side": game.color,
                "cpl": cpl, "eval_before": to_player(before), "eval_after": to_player(after),
                "fen_before": fen_before, "played_san": san, "played_uci": move.uci(),
                "context": sans[-_CONTEXT_PLIES:], **extra,
            }

        if cpl >= thresholds["blunder_cp"]:
            counts["blunder"] += 1
            by_phase[phase]["blunder"] += 1
            best_mv = best_moves[idx]
            blunders.append(card({
                "best_san": replay.san(best_mv) if best_mv else None,
                "best_uci": best_mv.uci() if best_mv else None,
            }))
        elif cpl >= thresholds["mistake_cp"]:
            counts["mistake"] += 1
        elif cpl >= thresholds["inaccuracy_cp"]:
            counts["inaccuracy"] += 1

        # Highlights (a near-best move can't also be a blunder). Brilliant wins ties.
        if cpl <= hl["brilliant_max_cpl"] and to_player(before) <= hl["brilliant_max_eval_before"]:
            after_board = replay.copy(stack=False)
            after_board.push(move)
            offers = any(after_board.is_capture(mv) and _captured_value(after_board, mv) >= 300
                         for mv in after_board.legal_moves)
            if offers:
                cp_after_deep, pv = _eval_pv_deep(engine, after_board, vlimit, cap)
                if to_player(cp_after_deep) >= hl["brilliant_min_eval_after"]:
                    mat_before = _material(replay, player_white)
                    min_mat = _material(after_board, player_white)
                    walk = after_board.copy(stack=False)
                    for pm in pv[: hl["line_plies"]]:
                        walk.push(pm)
                        min_mat = min(min_mat, _material(walk, player_white))
                    sac_cp = mat_before - min_mat
                    if sac_cp >= hl["sacrifice_min_cp"]:
                        brilliant.append(card({"sac_cp": sac_cp, "eval_after": to_player(cp_after_deep)}))
                        replay.push(move)
                        sans.append(san)
                        continue

        recapture = (replay.is_capture(move) and idx > 0
                     and node_moves[idx - 1].to_square == move.to_square)
        if (cpl <= hl["great_max_cpl"] and phase != "opening" and not recapture
                and hl["great_min_eval_before"] <= to_player(before) <= hl["great_max_eval_before"]
                and replay.legal_moves.count() > 1 and second_white[idx] is not None
                and to_player(before) - to_player(second_white[idx]) >= hl["great_gap_cp"]):
            best_d, _, second_d = _analyse_multi(engine, replay, vlimit, cap, 2)
            if second_d is not None and to_player(best_d) - to_player(second_d) >= hl["great_gap_cp"]:
                great.append(card({"gap": to_player(best_d) - to_player(second_d)}))

        replay.push(move)
        sans.append(san)

    # Player-POV evaluation trajectory, for conversion analysis.
    player_evals = [e if player_white else -e for e in evals_white]
    acpl = round(cpl_sum / counts["moves"], 1) if counts["moves"] else 0.0

    # Per-ply data for the interactive game viewer. ``evals`` is White-POV
    # (length n+1, one per position incl. the final one); ``moves_uci`` is the
    # move list (length n); ``start_fen`` handles any non-standard setup.
    start_fen = parsed.board().fen() if parsed else chess.STARTING_FEN

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
        "blunders": blunders,
        "highlights": {"brilliant": brilliant, "great": great},
        "start_fen": start_fen,
        "moves_uci": [m.uci() for m in node_moves],
        "evals": evals_white,
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
