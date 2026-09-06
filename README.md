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

## Licence

MIT — see [LICENSE](LICENSE).
