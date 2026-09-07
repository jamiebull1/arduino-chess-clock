# chess-progress

Pulls my [chess.com](https://www.chess.com/member/rimanish) games, runs a
**Stockfish** analysis pass over every game, and publishes progress reports to
**GitHub Pages** — so I can see how I'm doing against my recurring weaknesses.

**Live site:** https://jamiebull1.github.io/arduino-chess-clock/

> The repo keeps its original `arduino-chess-clock` name/URL for now; it can be
> renamed on GitHub later (that changes the Pages URL).

## What it reports

- **Overview** — rating trend, record, and a top list of your biggest weak spots.
- **Openings** — win rate and average centipawn loss per opening, as White and
  Black; your best and worst openings are highlighted, and each name links to the
  chess.com opening page.
- **Tactics** — average centipawn loss (ACPL), blunder counts and rate, a rolling
  accuracy trend, blunder rate by game phase, and **blunder cards**: a board diagram
  of each worst mistake with the move you played (red) vs. Stockfish's better move
  (green), the run-up moves, and a review link into the game.
- **Highlights** — a build-time take on chess.com's **Brilliant (!!)** and **Great (!)**
  labels: sound sacrifices, and only-good-move finds, each on a board. Heuristic, so it
  won't match chess.com's exactly.
- **Endgames / conversion** — how often winning positions (Stockfish eval ≥ +2)
  were actually won, games thrown from winning, games saved from losing, results
  by game length, and losses on time.

## How it works

`fetch → analyse → metrics → render`

1. **fetch** — chess.com public [Published-Data API](https://www.chess.com/news/view/published-data-api)
   (no auth). Profile, stats and monthly game archives are cached under `data/games/`.
2. **analyse** — Stockfish evaluates every position; centipawn loss per move is
   the drop in the mover's own evaluation. Results are cached one file per game
   (`data/analysis/<uuid>.json`), so re-runs only analyse *new* games.
3. **metrics** — aggregates everything into `data/report.json`.
4. **render** — Jinja2 templates → a static site in `_site/` (charts via Chart.js).

Configuration (username, engine budget, thresholds) lives in [`config.yaml`](config.yaml).

## Run locally

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .
sudo apt-get install -y stockfish        # or set engine.path in config.yaml

python -m chessprogress build            # fetch + analyse + metrics + render
# then open _site/index.html
```

Sub-commands `fetch`, `analyse`, `metrics`, `render` run the stages individually.

## Automated publishing

`.github/workflows/build.yml` runs the pipeline on every push to `master` (and via
manual **Run workflow**), commits the refreshed `data/` cache, and deploys `_site/`
to GitHub Pages.

**One-time setup:** in the repo's **Settings → Pages**, set **Source = GitHub
Actions**. (This can't be done from code.) After that, the first run does the full
Stockfish backfill (~10–15 min); later runs only analyse new games and are quick.

## Refreshing the reports

The reports update themselves from a build; you don't edit anything by hand. Pick whichever
is convenient:

1. **Push anything to `master`** (the usual way). The Actions workflow runs the full
   pipeline — it fetches your latest games from the chess.com API, engine-analyses only the
   *new* ones (the per-game cache under `data/analysis/` means old games are skipped), then
   rebuilds and redeploys the site. It also commits the refreshed `data/` back to the repo
   with a `[skip ci]` message so the new games are cached for next time. Even a trivial commit
   (e.g. a README tweak) triggers a full data refresh.
2. **Run it manually, no code change:** GitHub → **Actions → "Build chess progress report"
   → Run workflow** (this is the `workflow_dispatch` trigger). Same pipeline, on demand.
3. **Locally:** `python -m chessprogress build`, then commit `data/` and push. Handy if you
   want to eyeball `_site/` before it goes live.

Because only new games are analysed, a refresh is fast (seconds to a couple of minutes) once
the initial backfill is cached. The footer of every page shows the `generated_at` timestamp
of the data it was built from.

> Want it fully hands-off? Add a `schedule:` (cron) trigger to `.github/workflows/build.yml`
> — e.g. a weekly run — and it will refresh without any push.

## Licence

Copyright © 2026 Jamie Bull.

Licensed under the **GNU General Public License v3.0 or later (GPL-3.0-or-later)** —
see [LICENSE](LICENSE). This project uses [python-chess](https://github.com/niklasf/python-chess)
(GPL-3.0-or-later) as a library, so the combined work is distributed under the GPL.
[Stockfish](https://stockfishchess.org/) (GPL-3.0) is invoked as a separate program.

This program is free software: you can redistribute it and/or modify it under the terms
of the GNU General Public License as published by the Free Software Foundation, either
version 3 of the License, or (at your option) any later version. It is distributed in the
hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied warranty
of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License
for more details.
