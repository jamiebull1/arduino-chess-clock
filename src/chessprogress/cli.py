"""Command-line entry point: fetch / analyse / metrics / render / build."""
from __future__ import annotations

import argparse

from . import config as config_mod
from . import engine, fetch, metrics, render
from .parse import load_games


def _load(args) -> config_mod.Config:
    return config_mod.load(config_path=args.config)


def cmd_fetch(args) -> int:
    fetch.run(_load(args))
    return 0


def cmd_analyse(args) -> int:
    cfg = _load(args)
    engine.analyse_all(cfg, load_games(cfg))
    return 0


def cmd_metrics(args) -> int:
    metrics.build_report(_load(args))
    return 0


def cmd_render(args) -> int:
    render.render(_load(args))
    return 0


def cmd_build(args) -> int:
    cfg = _load(args)
    print("fetch:")
    fetch.run(cfg)
    print("analyse:")
    engine.analyse_all(cfg, load_games(cfg))
    print("metrics:")
    report = metrics.build_report(cfg)
    print("render:")
    render.render(cfg, report)
    print("done.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="chess-progress", description=__doc__)
    parser.add_argument("--config", default=None, help="path to config.yaml")
    sub = parser.add_subparsers(dest="command", required=True)

    for name, handler, help_text in [
        ("fetch", cmd_fetch, "download profile, stats and game archives"),
        ("analyse", cmd_analyse, "run Stockfish over any un-analysed games"),
        ("metrics", cmd_metrics, "aggregate into data/report.json"),
        ("render", cmd_render, "render the static site into _site/"),
        ("build", cmd_build, "fetch + analyse + metrics + render"),
    ]:
        p = sub.add_parser(name, help=help_text)
        p.set_defaults(func=handler)

    args = parser.parse_args(argv)
    return args.func(args)
