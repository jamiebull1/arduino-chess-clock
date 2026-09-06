"""Aggregate parsed games + cached engine analysis into a single report.json."""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone

from .config import Config
from .engine import load_analyses
from .parse import Game, load_games

_MIN_OPENING_GAMES = 3
_LENGTH_BUCKETS = [(0, 20, "≤20 moves"), (21, 40, "21–40"), (41, 60, "41–60"), (61, 9999, "60+")]


def _score_pct(w: int, l: int, d: int) -> float:
    n = w + l + d
    return round((w + 0.5 * d) / n * 100, 1) if n else 0.0


def _read_json(path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def _overview(cfg: Config, games: list[Game]) -> dict:
    stats = _read_json(cfg.paths.data / "stats.json")
    counts = Counter(g.time_class for g in games)
    primary = counts.most_common(1)[0][0] if counts else "rapid"

    key = f"chess_{primary}"
    rec = (stats.get(key) or {}).get("record", {})
    last = (stats.get(key) or {}).get("last", {})
    best = (stats.get(key) or {}).get("best", {})

    wins = sum(1 for g in games if g.outcome == "win")
    losses = sum(1 for g in games if g.outcome == "loss")
    draws = sum(1 for g in games if g.outcome == "draw")

    trend = [
        {"date": g.date, "rating": g.player_rating}
        for g in games if g.time_class == primary and g.player_rating
    ]
    recent = [
        {
            "date": g.date, "outcome": g.outcome, "opponent": g.opponent,
            "opponent_rating": g.opponent_rating, "color": g.color,
            "url": g.url, "result_reason": g.result_reason,
        }
        for g in reversed(games)
    ][: cfg.site["recent_games"]]

    return {
        "primary_time_class": primary,
        "current_rating": last.get("rating"),
        "best_rating": best.get("rating"),
        "stats_wins": rec.get("win"), "stats_losses": rec.get("loss"), "stats_draws": rec.get("draw"),
        "total_games": len(games),
        "wins": wins, "losses": losses, "draws": draws,
        "score_pct": _score_pct(wins, losses, draws),
        "rating_trend": trend,
        "recent_form": recent,
    }


def _openings(games: list[Game], analyses: dict) -> dict:
    groups: dict[tuple[str, str], dict] = defaultdict(
        lambda: {"games": 0, "w": 0, "l": 0, "d": 0, "cpl_sum": 0.0, "cpl_n": 0, "eco": "", "eco_url": None}
    )
    for g in games:
        name = g.opening or "Unknown opening"
        grp = groups[(g.color, name)]
        grp["games"] += 1
        grp["eco"] = g.eco or grp["eco"]
        grp["eco_url"] = g.eco_url or grp["eco_url"]
        grp[{"win": "w", "loss": "l", "draw": "d"}[g.outcome]] += 1
        a = analyses.get(g.uuid)
        if a:
            grp["cpl_sum"] += a["acpl"]
            grp["cpl_n"] += 1

    def row(color: str, name: str, grp: dict) -> dict:
        return {
            "color": color, "name": name, "eco": grp["eco"], "eco_url": grp["eco_url"],
            "games": grp["games"], "w": grp["w"], "l": grp["l"], "d": grp["d"],
            "score_pct": _score_pct(grp["w"], grp["l"], grp["d"]),
            "avg_cpl": round(grp["cpl_sum"] / grp["cpl_n"], 1) if grp["cpl_n"] else None,
        }

    all_rows = [row(c, name, grp) for (c, name), grp in groups.items()]

    def by_color(color: str) -> list[dict]:
        rows = [r for r in all_rows if r["color"] == color]
        return sorted(rows, key=lambda r: (-r["games"], r["score_pct"]))

    repeated = [r for r in all_rows if r["games"] >= _MIN_OPENING_GAMES]
    weak = sorted(repeated, key=lambda r: (r["score_pct"], -r["games"]))[:8]
    strong = sorted(repeated, key=lambda r: (-r["score_pct"], -r["games"]))[:8]

    return {
        "as_white": by_color("white"),
        "as_black": by_color("black"),
        "weak_spots": weak,
        "strong_spots": strong,
    }


def _tactics(cfg: Config, games: list[Game], analyses: dict) -> dict:
    total = Counter()
    phase = {p: {"moves": 0, "cpl_sum": 0.0, "blunder": 0} for p in ("opening", "middlegame", "endgame")}
    trend, worst = [], []
    game_by_uuid = {g.uuid: g for g in games}

    for g in games:  # chronological
        a = analyses.get(g.uuid)
        if not a:
            continue
        total["moves"] += a["counts"]["moves"]
        total["blunder"] += a["counts"]["blunder"]
        total["mistake"] += a["counts"]["mistake"]
        total["inaccuracy"] += a["counts"]["inaccuracy"]
        total["cpl_sum"] += a["acpl"] * a["counts"]["moves"]
        for p, pv in a["by_phase"].items():
            phase[p]["moves"] += pv["moves"]
            phase[p]["cpl_sum"] += pv["cpl_sum"]
            phase[p]["blunder"] += pv["blunder"]
        trend.append({"date": g.date, "acpl": a["acpl"]})
        for b in a.get("blunders", []):
            worst.append({
                **b, "date": g.date, "url": g.url,
                "opponent": g.opponent, "opponent_rating": g.opponent_rating,
            })

    # rolling 10-game ACPL average
    window, rolled = [], []
    for pt in trend:
        window.append(pt["acpl"])
        window[:] = window[-10:]
        rolled.append({**pt, "rolling": round(sum(window) / len(window), 1)})

    for p in phase.values():
        p["acpl"] = round(p["cpl_sum"] / p["moves"], 1) if p["moves"] else 0.0
        p["blunder_rate"] = round(p["blunder"] / p["moves"] * 100, 1) if p["moves"] else 0.0

    analysed_games = sum(1 for g in games if g.uuid in analyses)
    worst.sort(key=lambda r: -r["cpl"])
    return {
        "acpl": round(total["cpl_sum"] / total["moves"], 1) if total["moves"] else 0.0,
        "total_moves": total["moves"],
        "blunders": total["blunder"], "mistakes": total["mistake"],
        "inaccuracies": total["inaccuracy"],
        "blunder_rate": round(total["blunder"] / analysed_games, 2) if analysed_games else 0.0,
        "analysed_games": analysed_games,
        "by_phase": phase,
        "acpl_trend": rolled,
        "worst_blunders": worst[: cfg.site["worst_blunders"]],
    }


def _endgames(cfg: Config, games: list[Game], analyses: dict) -> dict:
    win_cp = cfg.thresholds["winning_cp"]
    winning_reached = winning_converted = thrown = losing_reached = saved = 0
    buckets = {label: {"w": 0, "l": 0, "d": 0} for _, _, label in _LENGTH_BUCKETS}

    for g in games:
        for lo, hi, label in _LENGTH_BUCKETS:
            if lo <= g.ply_count // 2 <= hi:
                buckets[label][{"win": "w", "loss": "l", "draw": "d"}[g.outcome]] += 1
                break
        a = analyses.get(g.uuid)
        if not a:
            continue
        if a["max_player_eval"] >= win_cp:
            winning_reached += 1
            if g.outcome == "win":
                winning_converted += 1
            else:
                thrown += 1
        if a["min_player_eval"] <= -win_cp:
            losing_reached += 1
            if g.outcome in ("win", "draw"):
                saved += 1

    return {
        "winning_reached": winning_reached,
        "winning_converted": winning_converted,
        "thrown_from_winning": thrown,
        "conversion_pct": round(winning_converted / winning_reached * 100, 1) if winning_reached else None,
        "losing_reached": losing_reached,
        "saved_from_losing": saved,
        "save_pct": round(saved / losing_reached * 100, 1) if losing_reached else None,
        "results_by_length": [
            {"bucket": label, **buckets[label], "games": sum(buckets[label].values())}
            for _, _, label in _LENGTH_BUCKETS
        ],
    }


def _highlights(cfg: Config, games: list[Game], analyses: dict) -> dict:
    """Aggregate highlights, post-filtering and capping per game so a single
    winning endgame can't flood 'great' and already-won sacs aren't 'brilliant'."""
    max_before = cfg.highlights["brilliant_max_eval_before"]
    per_game = cfg.highlights["max_per_game"]
    brilliant, great = [], []
    for g in games:
        a = analyses.get(g.uuid)
        if not a:
            continue
        h = a.get("highlights") or {}
        meta = {"date": g.date, "url": g.url, "opponent": g.opponent,
                "opponent_rating": g.opponent_rating, "outcome": g.outcome}
        # brilliant: drop those from already-winning positions, keep the biggest sacs
        b_game = sorted((b for b in h.get("brilliant", []) if b["eval_before"] <= max_before),
                        key=lambda b: -b["sac_cp"])[:per_game]
        # great: keep the clearest only-moves (biggest gap)
        g_game = sorted(h.get("great", []), key=lambda b: -b["gap"])[:per_game]
        brilliant.extend({**b, **meta} for b in b_game)
        great.extend({**b, **meta} for b in g_game)
    brilliant.sort(key=lambda r: r["date"], reverse=True)
    great.sort(key=lambda r: r["date"], reverse=True)
    return {
        "brilliant_count": len(brilliant), "great_count": len(great),
        "brilliant": brilliant, "great": great,
    }


def _time(games: list[Game]) -> dict:
    losses = [g for g in games if g.outcome == "loss"]
    timeouts = [g for g in losses if g.result_reason == "timeout"]
    return {
        "timeout_losses": len(timeouts),
        "total_losses": len(losses),
        "timeout_rate": round(len(timeouts) / len(losses) * 100, 1) if losses else 0.0,
    }


def build_report(cfg: Config) -> dict:
    games = load_games(cfg)
    analyses = load_analyses(cfg)
    profile = _read_json(cfg.paths.data / "profile.json")

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "username": cfg.username,
        "profile": {
            "name": profile.get("name"),
            "url": profile.get("url"),
            "country": (profile.get("country") or "").rstrip("/").split("/")[-1] or None,
            "avatar": profile.get("avatar"),
            "joined": profile.get("joined"),
        },
        "overview": _overview(cfg, games),
        "openings": _openings(games, analyses),
        "tactics": _tactics(cfg, games, analyses),
        "endgames": _endgames(cfg, games, analyses),
        "highlights": _highlights(cfg, games, analyses),
        "time": _time(games),
    }

    cfg.paths.data.mkdir(parents=True, exist_ok=True)
    (cfg.paths.data / "report.json").write_text(json.dumps(report, indent=2))
    print(f"  report: {len(games)} games, {report['tactics']['analysed_games']} analysed")
    return report
