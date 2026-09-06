/* Interactive game review: step through a highlight game, show the balance-of-power
 * trace with brilliant/great/blunder markers, and analyse the live position with a
 * single-threaded Stockfish WASM worker. Depends on chess.js (global Chess),
 * board.js (global ChessBoard) and Chart.js (global Chart). */
(function () {
  "use strict";

  const ENGINE_URL = "assets/vendor/stockfish/stockfish.js";
  const MOVETIME_MS = 700;      // per-position budget for the single-thread engine
  const Y_CLAMP = 10;            // pawns shown on the trace y-axis

  const $ = (id) => document.getElementById(id);
  const cssVar = (n) =>
    getComputedStyle(document.documentElement).getPropertyValue(n).trim();

  // --- helpers ---------------------------------------------------------------
  const pawns = (cp) => Math.max(-Y_CLAMP, Math.min(Y_CLAMP, cp / 100));
  const winPct = (cpWhite) => 100 / (1 + Math.pow(10, -(cpWhite / 100) / 4));

  function fmtEval(cpWhite, mate) {
    if (mate != null) return (mate > 0 ? "#" : "-#") + Math.abs(mate);
    const p = cpWhite / 100;
    return (p > 0 ? "+" : "") + p.toFixed(1);
  }
  const sideToMove = (fen) => fen.split(" ")[1] || "w";
  const toWhite = (cpStm, fen) => (sideToMove(fen) === "w" ? cpStm : -cpStm);
  const uciSquares = (uci) => [uci.slice(0, 2), uci.slice(2, 4)];

  // --- state -----------------------------------------------------------------
  let board, chart, engine = null, engineReady = false;
  let blob = null, fens = [], sans = [], markersByPly = {};
  let ply = 0, orient = "white";
  let explore = null;                 // chess.js instance when in a variation
  let selected = null;                // selected square in variation mode
  let render = { fen: null, last: [], arrow: null, targets: [] };

  // --- board rendering -------------------------------------------------------
  function renderBoard() {
    const arrows = render.arrow ? [render.arrow] : [];
    board.setPosition(render.fen, {
      arrows,
      highlight: render.last.concat(render.targets),
    });
  }

  // --- game loading ----------------------------------------------------------
  function precompute() {
    fens = [blob.start_fen];
    sans = [];
    const g = new Chess(blob.start_fen);
    for (const uci of blob.moves_uci) {
      const mv = g.move({ from: uci.slice(0, 2), to: uci.slice(2, 4), promotion: uci[4] || "q" });
      sans.push(mv ? mv.san : uci);
      fens.push(g.fen());
    }
    markersByPly = {};
    for (const m of blob.markers) markersByPly[m.ply] = m;
  }

  function buildMoveList() {
    const box = $("moveList");
    box.textContent = "";
    for (let i = 0; i < sans.length; i++) {
      const p = i + 1;
      if (i % 2 === 0) {
        const num = document.createElement("span");
        num.className = "mv-num";
        num.textContent = Math.floor(i / 2) + 1 + ".";
        box.appendChild(num);
      }
      const a = document.createElement("span");
      a.className = "mv";
      const mk = markersByPly[p];
      if (mk) a.classList.add("mv-" + mk.type);
      a.textContent = sans[i] + (mk ? ({ brilliant: "!!", great: "!", blunder: "??" }[mk.type]) : "");
      a.dataset.ply = p;
      a.addEventListener("click", () => goToPly(p));
      box.appendChild(a);
    }
  }

  function buildChart() {
    const labels = fens.map((_, i) => i);
    const line = fens.map((_, i) => ({ x: i, y: pawns(blob.evals[i]) }));
    const byType = { brilliant: [], great: [], blunder: [] };
    for (const m of blob.markers) {
      (byType[m.type] || []).push({ x: m.ply, y: pawns(blob.evals[m.ply]) });
    }
    const mkSet = (data, color, style, radius) => ({
      data, type: "scatter", showLine: false, pointStyle: style,
      pointRadius: radius, pointHoverRadius: radius + 2,
      backgroundColor: color, borderColor: color, order: 0,
    });

    if (chart) chart.destroy();
    const playhead = {
      id: "playhead",
      afterDatasetsDraw(c) {
        const x = c.scales.x.getPixelForValue(ply);
        const { top, bottom } = c.chartArea;
        const ctx = c.ctx;
        ctx.save();
        ctx.strokeStyle = cssVar("--accent") || "#2b6cb0";
        ctx.lineWidth = 1.5;
        ctx.beginPath(); ctx.moveTo(x, top); ctx.lineTo(x, bottom); ctx.stroke();
        ctx.restore();
      },
    };

    chart = new Chart($("powerChart"), {
      data: {
        labels,
        datasets: [
          {
            type: "line", data: line, label: "White eval", parsing: false,
            borderColor: cssVar("--muted") || "#888", borderWidth: 1.5,
            pointRadius: 0, tension: 0.15, fill: { target: { value: 0 } },
            backgroundColor: "rgba(99,164,255,.16)", order: 1,
          },
          mkSet(byType.brilliant, "#0d9488", "star", 7),
          mkSet(byType.great, cssVar("--accent") || "#2b6cb0", "triangle", 6),
          mkSet(byType.blunder, cssVar("--bad") || "#c53030", "rectRot", 6),
        ],
      },
      options: {
        responsive: true, maintainAspectRatio: false, parsing: false,
        scales: {
          x: { type: "linear", min: 0, max: fens.length - 1,
            title: { display: true, text: "ply" }, ticks: { maxTicksLimit: 8 } },
          y: { min: -Y_CLAMP, max: Y_CLAMP, title: { display: true, text: "pawns (White +)" } },
        },
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              title: (items) => "Ply " + items[0].parsed.x,
              label: (item) => {
                const m = markersByPly[item.parsed.x];
                const base = "White " + fmtEval(blob.evals[item.parsed.x]);
                return m ? [base, m.type + ": " + m.played_san] : base;
              },
            },
          },
        },
        onClick: (e, els, c) => {
          const val = c.scales.x.getValueForPixel(e.x);
          goToPly(Math.round(val));
        },
      },
      plugins: [playhead],
    });
  }

  function loadGame(uuid) {
    fetch("data/games/" + uuid + ".json")
      .then((r) => r.json())
      .then((data) => {
        blob = data;
        orient = blob.color || "white";
        board.setOrientation(orient);
        precompute();
        buildMoveList();
        buildChart();
        $("gameMeta").innerHTML = metaHtml(blob);
        goToPly(0);
      })
      .catch((err) => {
        $("gameMeta").textContent = "Could not load game data.";
        console.error(err);
      });
  }

  function metaHtml(b) {
    const opp = b.opponent + (b.opponent_rating ? " (" + b.opponent_rating + ")" : "");
    const res = { win: "won", loss: "lost", draw: "drew" }[b.outcome] || b.outcome;
    const acc = b.accuracy != null ? " · " + b.accuracy + "% accuracy" : "";
    return `as <strong>${b.color}</strong> vs ${opp} · <span class="pill ${b.outcome}">${res}</span>` +
      ` · ${b.date}${acc}${b.opening ? " · " + b.opening : ""} · ` +
      `<a href="${b.url}" target="_blank" rel="noopener">chess.com ↗</a>`;
  }

  // --- navigation ------------------------------------------------------------
  function goToPly(k) {
    ply = Math.max(0, Math.min(fens.length - 1, k));
    explore = null; selected = null;
    $("variationBar").hidden = true;
    render.fen = fens[ply];
    render.last = ply > 0 ? uciSquares(blob.moves_uci[ply - 1]) : [];
    render.targets = [];
    render.arrow = null;
    renderBoard();
    updateReadouts();
    if (chart) chart.update("none");
    analyse(render.fen);
  }

  function updateReadouts() {
    const cpWhite = blob.evals[ply];
    $("evalWhite").style.height = winPct(cpWhite) + "%";
    $("evalNum").textContent = fmtEval(cpWhite);
    $("plyLabel").textContent = ply === 0
      ? "start" : Math.floor((ply - 1) / 2) + 1 + (ply % 2 ? "." : "…") + " " + sans[ply - 1];
    // active move in the list
    document.querySelectorAll("#moveList .mv.active").forEach((n) => n.classList.remove("active"));
    const active = document.querySelector('#moveList .mv[data-ply="' + ply + '"]');
    if (active) { active.classList.add("active"); active.scrollIntoView({ block: "nearest" }); }
    // verdict for a marked move
    const mk = markersByPly[ply];
    const v = $("moveVerdict");
    if (mk) {
      v.className = "verdict-line vl-" + mk.type;
      v.textContent = verdictText(mk);
    } else { v.className = "verdict-line"; v.textContent = ""; }
  }

  function verdictText(m) {
    const ev = (m.eval_before / 100).toFixed(1) + " → " + (m.eval_after / 100).toFixed(1) + " (your POV)";
    if (m.type === "brilliant") return `Brilliant!! ${m.played_san} — sound sacrifice (~${m.sac_cp}cp), held at ${ev}.`;
    if (m.type === "great") return `Great! ${m.played_san} — the only good move (next best ${m.gap}cp worse).`;
    return `Blunder?? ${m.played_san} dropped ${ev}${m.best_san ? "; better was " + m.best_san : ""}.`;
  }

  // --- live engine -----------------------------------------------------------
  function loadEngine() {
    try {
      engine = new Worker(ENGINE_URL);
    } catch (e) {
      $("engineState").textContent = "unavailable";
      return;
    }
    engine.onmessage = onEngineMsg;
    engine.onerror = () => { $("engineState").textContent = "unavailable"; engine = null; };
    engine.postMessage("uci");
    engine.postMessage("isready");
  }

  let curFen = null, lastInfo = null;
  function onEngineMsg(e) {
    const line = typeof e.data === "string" ? e.data : (e.data && e.data.data) || "";
    if (line === "readyok" || line.indexOf("uciok") === 0) {
      if (!engineReady) { engineReady = true; $("engineState").textContent = "ready"; if (curFen) analyse(curFen); }
      return;
    }
    if (line.indexOf("info ") === 0 && line.indexOf(" pv ") !== -1 && line.indexOf(" score ") !== -1) {
      lastInfo = parseInfo(line);
      showEngine();
      updateEngineArrow(lastInfo.pv[0]);
    } else if (line.indexOf("bestmove ") === 0) {
      updateEngineArrow(line.split(" ")[1]);
    }
  }

  // Draw the engine's current best move as a green arrow, but only while the
  // analysed position is still the one on the board (guards against stale hits).
  function updateEngineArrow(uci) {
    // ignore "(none)" from terminal positions and anything not a real move
    if (!uci || !/^[a-h][1-8][a-h][1-8]/.test(uci) || curFen !== render.fen) return;
    const next = { from: uci.slice(0, 2), to: uci.slice(2, 4), color: cssVar("--good") || "#2f855a" };
    if (render.arrow && render.arrow.from === next.from && render.arrow.to === next.to) return;
    render.arrow = next;
    board.setArrows([next]);
  }

  function parseInfo(line) {
    const t = line.split(/\s+/);
    const info = { depth: null, cp: null, mate: null, pv: [] };
    for (let i = 0; i < t.length; i++) {
      if (t[i] === "depth") info.depth = parseInt(t[i + 1], 10);
      else if (t[i] === "score") {
        if (t[i + 1] === "cp") info.cp = parseInt(t[i + 2], 10);
        else if (t[i + 1] === "mate") info.mate = parseInt(t[i + 2], 10);
      } else if (t[i] === "pv") { info.pv = t.slice(i + 1); break; }
    }
    return info;
  }

  function showEngine() {
    if (!lastInfo || !curFen) return;
    const cpWhite = lastInfo.mate != null
      ? (sideToMove(curFen) === "w" ? 1 : -1) * (lastInfo.mate > 0 ? 100000 : -100000)
      : toWhite(lastInfo.cp, curFen);
    const mateWhite = lastInfo.mate != null
      ? (sideToMove(curFen) === "w" ? lastInfo.mate : -lastInfo.mate) : null;
    $("engineEval").textContent = fmtEval(cpWhite, mateWhite) +
      (lastInfo.depth ? "  (depth " + lastInfo.depth + ")" : "");
    // render PV as SAN
    try {
      const g = new Chess(curFen);
      const line = [];
      for (const u of lastInfo.pv.slice(0, 8)) {
        const mv = g.move({ from: u.slice(0, 2), to: u.slice(2, 4), promotion: u[4] || "q" });
        if (!mv) break;
        line.push(mv.san);
      }
      $("enginePv").textContent = line.join(" ");
    } catch (_) { $("enginePv").textContent = ""; }
  }

  function analyse(fen) {
    curFen = fen; lastInfo = null;
    if (!engine || !engineReady) return;
    $("engineEval").textContent = "…";
    $("enginePv").textContent = "";
    engine.postMessage("stop");
    engine.postMessage("position fen " + fen);
    engine.postMessage("go movetime " + MOVETIME_MS);
  }

  // --- variation exploration (click to move) ---------------------------------
  function onSquareClick(sq) {
    const g = explore || new Chess(fens[ply]);
    if (!selected) {
      const piece = g.get(sq);
      if (!piece || piece.color !== g.turn()) return;
      selected = sq;
      render.targets = g.moves({ square: sq, verbose: true }).map((m) => m.to);
      renderBoard();
      return;
    }
    if (sq === selected) { selected = null; render.targets = []; renderBoard(); return; }
    const mv = g.move({ from: selected, to: sq, promotion: "q" });
    selected = null; render.targets = [];
    if (!mv) {                       // maybe re-selecting another own piece
      const piece = g.get(sq);
      if (piece && piece.color === g.turn()) { selected = sq; render.targets = g.moves({ square: sq, verbose: true }).map((m) => m.to); }
      renderBoard();
      return;
    }
    explore = g;
    render.fen = g.fen();
    render.last = [mv.from, mv.to];
    render.arrow = null;
    $("variationBar").hidden = false;
    renderBoard();
    analyse(render.fen);
  }

  // --- wiring ----------------------------------------------------------------
  function init() {
    // base.html declares `const REPORT` — a lexical global, reachable as the bare
    // identifier but not as a property of window.
    const R = (typeof REPORT !== "undefined") ? REPORT : (window.REPORT || null);
    const games = (R && R.viewer && R.viewer.games) || [];
    if (!games.length) { $("noGames").hidden = false; return; }
    $("review").hidden = false;

    board = ChessBoard($("board"), { orientation: "white" });
    board.onSquareClick = onSquareClick;

    const picker = $("gamePicker");
    for (const g of games) {
      const opt = document.createElement("option");
      const tags = [];
      if (g.counts.brilliant) tags.push(g.counts.brilliant + "×!!");
      if (g.counts.great) tags.push(g.counts.great + "×!");
      if (g.counts.blunder) tags.push(g.counts.blunder + "×??");
      opt.value = g.uuid;
      opt.textContent = `${g.date} · vs ${g.opponent} · ${g.outcome}` +
        (tags.length ? "  (" + tags.join(" ") + ")" : "");
      picker.appendChild(opt);
    }
    picker.addEventListener("change", () => loadGame(picker.value));

    $("btnFirst").addEventListener("click", () => goToPly(0));
    $("btnPrev").addEventListener("click", () => goToPly(ply - 1));
    $("btnNext").addEventListener("click", () => goToPly(ply + 1));
    $("btnLast").addEventListener("click", () => goToPly(fens.length - 1));
    $("btnFlip").addEventListener("click", () => {
      orient = orient === "white" ? "black" : "white";
      board.setOrientation(orient); renderBoard();
    });
    $("btnReset").addEventListener("click", () => goToPly(ply));
    document.addEventListener("keydown", (e) => {
      if (e.target.tagName === "SELECT") return;
      if (e.key === "ArrowLeft") { goToPly(ply - 1); e.preventDefault(); }
      else if (e.key === "ArrowRight") { goToPly(ply + 1); e.preventDefault(); }
      else if (e.key === "Home") goToPly(0);
      else if (e.key === "End") goToPly(fens.length - 1);
    });

    loadEngine();

    const params = new URLSearchParams(location.search);
    const want = params.get("g");
    if (want && games.some((g) => g.uuid === want)) picker.value = want;
    loadGame(picker.value);
  }

  // Run after the base template's DOMContentLoaded handler (which sets Chart.js
  // theme defaults). Deferred scripts execute before DOMContentLoaded fires, so
  // wait for it unless the document is already fully loaded.
  if (document.readyState === "complete") { init(); }
  else { document.addEventListener("DOMContentLoaded", init); }
})();
