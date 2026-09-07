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
  const isUci = (u) => !!u && /^[a-h][1-8][a-h][1-8]/.test(u);
  const arrowFromUci = (uci, color) =>
    isUci(uci) ? { from: uci.slice(0, 2), to: uci.slice(2, 4), color } : null;

  const PIECE_NAME = { p: "pawn", n: "knight", b: "bishop", r: "rook", q: "queen", k: "king" };
  const PIECE_VALUE = { p: 1, n: 3, b: 3, r: 5, q: 9 };
  const sumVals = (list) => list.reduce((s, t) => s + (PIECE_VALUE[t] || 0), 0);
  const esc = (s) => String(s).replace(/[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  // SAN of a uci move played from `fen` (null if illegal / chess.js missing).
  function sanOf(uci, fen) {
    if (!isUci(uci)) return null;
    try {
      const g = new Chess(fen);
      const mv = g.move({ from: uci.slice(0, 2), to: uci.slice(2, 4), promotion: uci[4] || "q" });
      return mv ? mv.san : null;
    } catch (_) { return null; }
  }

  // A short plain-English note on what a move does (check, capture, …), from
  // the position `fen`. Kept to a single, directly-observable clause.
  function moveNote(uci, fen) {
    try {
      const g = new Chess(fen);
      const mv = g.move({ from: uci.slice(0, 2), to: uci.slice(2, 4), promotion: uci[4] || "q" });
      if (!mv) return "";
      if (mv.san.indexOf("#") !== -1) return " (delivering mate)";
      if (mv.san.indexOf("+") !== -1) return " (with check)";
      if ((mv.flags || "").indexOf("p") !== -1) return " (queening)";
      if (mv.captured) return " (takes the " + (PIECE_NAME[mv.captured] || "piece") + ")";
    } catch (_) {}
    return "";
  }

  // --- state -----------------------------------------------------------------
  let board, chart, engine = null, engineReady = false;
  let blob = null, fens = [], sans = [], markersByPly = {}, caps = [];
  let ply = 0, orient = "white";
  let explore = null;                 // chess.js instance when in a variation
  let selected = null;                // selected square in variation mode
  let bestNow = null;                 // {uci, san} engine's best for the shown position
  let render = { fen: null, last: [], targets: [], playedArrow: null, bestArrow: null };

  const GREEN = () => cssVar("--good") || "#2f855a";   // move actually played
  const BLUE = () => cssVar("--accent") || "#2b6cb0";  // engine's best move

  // --- board rendering -------------------------------------------------------
  function renderBoard() {
    const arrows = [render.playedArrow, render.bestArrow].filter(Boolean);
    board.setPosition(render.fen, {
      arrows,
      highlight: render.last.concat(render.targets),
    });
  }

  // --- captured material -----------------------------------------------------
  // Pieces each side has captured up to the shown position (main line or a
  // variation), newest exploration captures folded onto the main-line total.
  function capturedNow() {
    const base = caps[ply] || { w: [], b: [] };
    if (!explore) return { w: base.w, b: base.b };
    const w = base.w.slice(), b = base.b.slice();
    for (const mv of explore.history({ verbose: true })) {
      if (mv.captured) (mv.color === "w" ? w : b).push(mv.captured);
    }
    return { w, b };
  }

  // One side's tray: overlapped mini-icons of the (opponent-coloured) pieces it
  // captured, that side's captured points, and a +N badge if it's ahead.
  function trayHtml(capturer, cap, net) {
    const list = cap[capturer];
    const oppColor = capturer === "w" ? "black" : "white";
    const counts = {};
    for (const t of list) counts[t] = (counts[t] || 0) + 1;
    let icons = '<span class="cap-pcs">';
    for (const t of ["q", "r", "b", "n", "p"]) {
      if (!counts[t]) continue;
      icons += '<span class="cap-grp">';
      for (let i = 0; i < counts[t]; i++) {
        icons += '<svg class="cap-pc" viewBox="0 0 45 45" aria-hidden="true">'
          + '<use href="#' + oppColor + "-" + PIECE_NAME[t] + '"/></svg>';
      }
      icons += "</span>";
    }
    icons += "</span>";
    const pts = sumVals(list);
    const ptsHtml = pts ? '<span class="cap-pts">' + pts + " pts</span>" : "";
    const ahead = (net > 0 && capturer === "w") || (net < 0 && capturer === "b");
    const advHtml = ahead ? '<span class="cap-adv">+' + Math.abs(net) + "</span>" : "";
    return icons + ptsHtml + advHtml;
  }

  function renderCaptured() {
    if (!caps.length) return;
    const cap = capturedNow();
    const net = sumVals(cap.w) - sumVals(cap.b);   // white minus black
    const bottom = orient === "white" ? "w" : "b"; // side shown at the board foot
    const top = bottom === "w" ? "b" : "w";
    $("capTop").innerHTML = trayHtml(top, cap, net);
    $("capBottom").innerHTML = trayHtml(bottom, cap, net);
  }

  // --- game loading ----------------------------------------------------------
  function precompute() {
    fens = [blob.start_fen];
    sans = [];
    caps = [{ w: [], b: [] }];   // cumulative pieces captured by each side, per ply
    const g = new Chess(blob.start_fen);
    for (const uci of blob.moves_uci) {
      const mv = g.move({ from: uci.slice(0, 2), to: uci.slice(2, 4), promotion: uci[4] || "q" });
      sans.push(mv ? mv.san : uci);
      fens.push(g.fen());
      const prev = caps[caps.length - 1];
      const cur = { w: prev.w.slice(), b: prev.b.slice() };
      if (mv && mv.captured) cur[mv.color].push(mv.captured);   // mv.color = the capturer
      caps.push(cur);
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
      // Land on the position *before* this move so the commentary previews it
      // (green = the move played, blue = the engine's best here).
      a.addEventListener("click", () => goToPly(p - 1));
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
    bestNow = null;
    $("variationBar").hidden = true;
    render.fen = fens[ply];
    render.last = ply > 0 ? uciSquares(blob.moves_uci[ply - 1]) : [];
    render.targets = [];
    // Green arrow: the move actually played next from this position.
    render.playedArrow = ply < blob.moves_uci.length
      ? arrowFromUci(blob.moves_uci[ply], GREEN()) : null;
    render.bestArrow = null;
    renderBoard();
    renderCaptured();
    applyBest(null, null);   // draws the best-move arrow + commentary (marker best, if any)
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
    // Highlight the move the commentary is discussing (the one about to be played).
    document.querySelectorAll("#moveList .mv.active").forEach((n) => n.classList.remove("active"));
    const active = document.querySelector('#moveList .mv[data-ply="' + (ply + 1) + '"]');
    if (active) { active.classList.add("active"); active.scrollIntoView({ block: "nearest" }); }
  }

  // --- running commentary ----------------------------------------------------
  // Record the engine's (or a marker's) best move for the shown position, redraw
  // the best-move arrow, and refresh the commentary. Called once per position
  // (marker best) and again when the live engine reports (non-marker positions).
  function applyBest(uci, san) {
    if (uci && bestNow && bestNow.uci === uci) return;   // unchanged — avoid redraw churn
    bestNow = uci ? { uci: uci, san: san } : null;

    // On the main line a blunder marker carries the authoritative best move
    // (consistent with the eval trace); otherwise trust the live engine.
    let showUci = uci, showSan = san;
    if (!explore) {
      const um = markersByPly[ply + 1];
      if (um && um.best_uci) { showUci = um.best_uci; showSan = um.best_san; }
    }
    const played = explore ? null : blob.moves_uci[ply];
    render.bestArrow = (isUci(showUci) && showUci !== played)
      ? arrowFromUci(showUci, BLUE()) : null;
    board.setArrows([render.playedArrow, render.bestArrow].filter(Boolean));
    renderCommentary();
  }

  function renderCommentary() {
    const box = $("commentary");
    const n = blob.moves_uci.length;

    if (explore) {
      box.className = "commentary";
      box.innerHTML = '<div class="cm-detail">Exploring your own line — the '
        + '<span class="cm-best">blue arrow</span> is the engine\'s best move here. '
        + 'Use “Back to game” to return to the running commentary.</div>';
      return;
    }
    if (ply >= n) {   // final position, nothing to play next
      box.className = "commentary";
      const res = { win: "You won", loss: "You lost", draw: "Drawn" }[blob.outcome] || "Game over";
      box.innerHTML = '<div><span class="cm-move">End of game.</span></div>'
        + '<div class="cm-detail">' + res + '. Final evaluation ' + fmtEval(blob.evals[ply])
        + ' (White +). Step back through the moves to review the play.</div>';
      return;
    }

    const k = ply;
    const whiteToMove = (k % 2 === 0);
    const mover = whiteToMove ? "White" : "Black";
    const playedSan = sans[k];
    const playedUci = blob.moves_uci[k];
    const evalBefore = blob.evals[k];        // White POV, best play at this point
    const evalAfter = blob.evals[k + 1];     // White POV after the played move
    const lossMover = Math.max(0, whiteToMove ? evalBefore - evalAfter : evalAfter - evalBefore);
    const moveNo = (Math.floor(k / 2) + 1) + (whiteToMove ? "." : "…");
    const th = blob.thresholds || { inaccuracy: 50, mistake: 100, blunder: 300 };
    const um = markersByPly[k + 1];

    // Classify: positive highlights win, then centipawn-loss bands.
    let cls, tag;
    if (um && um.type === "brilliant") { cls = "brilliant"; tag = "Brilliant !!"; }
    else if (um && um.type === "great") { cls = "great"; tag = "Great !"; }
    else if (lossMover >= th.blunder) { cls = "blunder"; tag = "Blunder"; }
    else if (lossMover >= th.mistake) { cls = "mistake"; tag = "Mistake"; }
    else if (lossMover >= th.inaccuracy) { cls = "inaccuracy"; tag = "Inaccuracy"; }
    else { cls = "good"; tag = "Best move"; }

    const bestUci = (um && um.best_uci) || (bestNow && bestNow.uci) || null;
    const bestSan = (um && um.best_san) || (bestNow && bestNow.san) || null;
    const isBest = !bestUci || bestUci === playedUci;
    if (cls === "good" && !isBest) tag = "Solid";   // fine, but not the engine's pick

    let detail;
    if (cls === "brilliant") {
      detail = "A sound sacrifice — the engine agrees it keeps the advantage.";
    } else if (cls === "great") {
      detail = "The only move that holds here; the alternatives are clearly worse.";
    } else if (isBest) {
      detail = (bestUci ? mover + " plays the engine's top choice." : mover + " plays a strong move.")
        + " Evaluation " + fmtEval(evalAfter) + " (White +).";
    } else if (cls === "good") {
      // A fine move that just isn't the engine's first pick — no real loss.
      detail = "A solid choice." + (bestSan
        ? ' The engine narrowly preferred <span class="cm-best">' + esc(bestSan) + "</span>"
          + moveNote(bestUci, fens[k]) + ", worth about the same (" + fmtEval(evalAfter) + ", White +)."
        : " Evaluation " + fmtEval(evalAfter) + " (White +).");
    } else {
      detail = mover + "’s move loses " + (lossMover / 100).toFixed(1) + ".";
      if (bestSan) {
        detail += ' Stronger was <span class="cm-best">' + esc(bestSan) + "</span>"
          + moveNote(bestUci, fens[k]) + ", holding the eval near " + fmtEval(evalBefore)
          + " instead of " + fmtEval(evalAfter) + " (White +).";
      } else {
        detail += " The engine prefers another move (eval " + fmtEval(evalBefore)
          + " → " + fmtEval(evalAfter) + ", White +).";
      }
    }

    box.className = "commentary cm-" + cls;
    box.innerHTML = '<div><span class="cm-move">' + moveNo + " " + esc(playedSan)
      + '</span><span class="cm-tag">' + tag + '</span></div>'
      + '<div class="cm-detail">' + detail + "</div>";
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
      engineBest(lastInfo.pv[0]);
    } else if (line.indexOf("bestmove ") === 0) {
      engineBest(line.split(" ")[1]);
    }
  }

  // Feed the engine's current best move into the board + commentary, but only
  // while the analysed position is still the one on the board (guards against
  // stale hits). A blunder marker's best move takes precedence (see applyBest).
  function engineBest(uci) {
    if (!isUci(uci) || curFen !== render.fen) return;   // ignore "(none)" / stale
    applyBest(uci, sanOf(uci, render.fen));
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
    bestNow = null;
    render.fen = g.fen();
    render.last = [mv.from, mv.to];
    render.playedArrow = null;   // no "played" move off the main line
    render.bestArrow = null;     // the live engine fills this in for the new position
    $("variationBar").hidden = false;
    renderBoard();
    renderCaptured();
    renderCommentary();
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
      board.setOrientation(orient); renderBoard(); renderCaptured();
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
