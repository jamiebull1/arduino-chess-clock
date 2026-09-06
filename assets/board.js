/* Minimal read-only + click-to-move SVG chess board.
 * Renders a FEN using the Cburnett piece <defs> injected into the page (the same
 * set python-chess uses for the static diagrams), so the interactive board and
 * the server-rendered cards look identical. No external assets, no drag library.
 *
 * Geometry matches python-chess: 15px coordinate margin, 45px squares, a piece
 * on square (file f, rank r) is <use transform="translate(15+f*45, 15+(7-r)*45)">.
 */
(function () {
  "use strict";
  const NS = "http://www.w3.org/2000/svg";
  const SIZE = 45, MARGIN = 15, BOARD = SIZE * 8, TOTAL = BOARD + MARGIN * 2;
  const LIGHT = "#ffce9e", DARK = "#d18b47";
  const FILES = "abcdefgh";

  function el(name, attrs) {
    const e = document.createElementNS(NS, name);
    for (const k in attrs) e.setAttribute(k, attrs[k]);
    return e;
  }

  // Board square (file 0..7, rank 0..7 where 0 = rank 1) -> top-left px,
  // honouring orientation ("white" puts rank 1 at the bottom).
  function topLeft(f, r, white) {
    const col = white ? f : 7 - f;
    const row = white ? 7 - r : r;
    return [MARGIN + col * SIZE, MARGIN + row * SIZE];
  }
  function center(sq, white) {
    const f = FILES.indexOf(sq[0]), r = parseInt(sq[1], 10) - 1;
    const [x, y] = topLeft(f, r, white);
    return [x + SIZE / 2, y + SIZE / 2];
  }

  function parseFen(fen) {
    const rows = fen.split(" ")[0].split("/");   // rank 8 first
    const map = {};                               // "e4" -> "P"/"n"/...
    for (let i = 0; i < 8; i++) {
      const rank = 8 - i;
      let file = 0;
      for (const ch of rows[i]) {
        if (/\d/.test(ch)) { file += parseInt(ch, 10); continue; }
        map[FILES[file] + rank] = ch;
        file++;
      }
    }
    return map;
  }

  const PIECE_ID = {
    p: "black-pawn", n: "black-knight", b: "black-bishop", r: "black-rook",
    q: "black-queen", k: "black-king",
    P: "white-pawn", N: "white-knight", B: "white-bishop", R: "white-rook",
    Q: "white-queen", K: "white-king",
  };

  function ChessBoard(svg, opts) {
    opts = opts || {};
    let white = (opts.orientation || "white") !== "black";
    svg.setAttribute("viewBox", `0 0 ${TOTAL} ${TOTAL}`);
    svg.setAttribute("class", "cb");

    const gSquares = el("g", {}), gCoords = el("g", { class: "cb-coords" });
    const gPieces = el("g", {}), gArrows = el("g", {}), gMarks = el("g", {});
    // Only the square rects receive clicks; overlays must not intercept them.
    for (const g of [gCoords, gPieces, gArrows, gMarks]) g.setAttribute("pointer-events", "none");
    svg.append(gSquares, gMarks, gCoords, gPieces, gArrows);

    let onSquare = null;

    function drawSquares() {
      gSquares.textContent = "";
      gCoords.textContent = "";
      for (let f = 0; f < 8; f++) {
        for (let r = 0; r < 8; r++) {
          const [x, y] = topLeft(f, r, white);
          const dark = (f + r) % 2 === 0;
          const rect = el("rect", {
            x, y, width: SIZE, height: SIZE, fill: dark ? DARK : LIGHT,
          });
          rect.dataset.sq = FILES[f] + (r + 1);
          rect.addEventListener("click", () => onSquare && onSquare(rect.dataset.sq));
          gSquares.appendChild(rect);
        }
      }
      // File letters along the bottom, rank numbers up the left.
      for (let i = 0; i < 8; i++) {
        const f = white ? i : 7 - i;
        const t = el("text", { x: MARGIN + i * SIZE + 4, y: TOTAL - 4,
          class: "cb-file" });
        t.textContent = FILES[f];
        gCoords.appendChild(t);
        const r = white ? 7 - i : i;
        const n = el("text", { x: 4, y: MARGIN + i * SIZE + 15, class: "cb-rank" });
        n.textContent = r + 1;
        gCoords.appendChild(n);
      }
    }

    function drawPieces(fen) {
      gPieces.textContent = "";
      const map = parseFen(fen);
      for (const sq in map) {
        const f = FILES.indexOf(sq[0]), r = parseInt(sq[1], 10) - 1;
        const [x, y] = topLeft(f, r, white);
        gPieces.appendChild(el("use", {
          href: "#" + PIECE_ID[map[sq]], transform: `translate(${x}, ${y})`,
        }));
      }
    }

    function drawArrows(arrows) {
      gArrows.textContent = "";
      (arrows || []).forEach((a, i) => {
        const [x1, y1] = center(a.from, white);
        const [x2, y2] = center(a.to, white);
        if ([x1, y1, x2, y2].some(Number.isNaN)) return;
        const color = a.color || "#2f855a";
        const id = "ah" + i;
        const defs = el("defs", {});
        const marker = el("marker", {
          id, markerWidth: 4, markerHeight: 4, refX: 2.2, refY: 2,
          orient: "auto", markerUnits: "strokeWidth",
        });
        marker.appendChild(el("path", { d: "M0,0 L4,2 L0,4 z", fill: color }));
        defs.appendChild(marker);
        gArrows.appendChild(defs);
        // shorten so the head sits inside the destination square
        const dx = x2 - x1, dy = y2 - y1, len = Math.hypot(dx, dy) || 1;
        const ex = x2 - (dx / len) * 14, ey = y2 - (dy / len) * 14;
        gArrows.appendChild(el("line", {
          x1, y1, x2: ex, y2: ey, stroke: color, "stroke-width": 7,
          "stroke-linecap": "round", opacity: 0.85, "marker-end": `url(#${id})`,
        }));
      });
    }

    function drawMarks(squares) {
      gMarks.textContent = "";
      (squares || []).forEach((sq) => {
        const f = FILES.indexOf(sq[0]), r = parseInt(sq[1], 10) - 1;
        const [x, y] = topLeft(f, r, white);
        gMarks.appendChild(el("rect", {
          x, y, width: SIZE, height: SIZE, fill: "#2b6cb0", opacity: 0.28,
        }));
      });
    }

    drawSquares();

    return {
      setPosition(fen, o) {
        o = o || {};
        drawPieces(fen);
        drawArrows(o.arrows);
        drawMarks(o.highlight);
      },
      setArrows(arrows) { drawArrows(arrows); },
      setOrientation(color) {
        const w = color !== "black";
        if (w === white) return;
        white = w;
        drawSquares();
      },
      set onSquareClick(fn) { onSquare = fn; },
    };
  }

  window.ChessBoard = ChessBoard;
})();
