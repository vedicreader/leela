// The board of the screen guide: marks drawn over the page, one step at a time, with one spoken line for each step.
// The server checked each mark (abhyasa.guide.check_line). Each mark is kept as its anchor plus an offset, and is drawn again
// when the page scrolls or changes size, so it stays on its thing. Text from the model goes in with textContent only.
// Rough.js and perfect-freehand (core/vendor, MIT) load on the first board.
//
// The look (numbers from Clicky, github.com/farzaa/clicky, MIT): a pointer flies to each mark on a quadratic arc (lift
// min(d * 0.2, 80) px, time clamp(d / 800, 0.6, 1.4) s, smoothstep) and grows to 1.3x as it lands, then settles on a spring
// (response 0.4, damping 0.6). A box is a soft glow that blooms and settles. A circle on a formula part or on words adds a
// marker under the glyphs (multiply on a light surface, screen on a dark one). Rings, underlines and sketches are
// perfect-freehand strokes with pressure, drawn on as a pen does. Arrows are one light Rough.js stroke with a filled head.
// Labels are pastel chips with a coloured bar and a thin leader line; a chip never covers its target. Marks of earlier steps
// fade to 45 %. The words of the spoken line light up as they are said. With prefers-reduced-motion, the pointer jumps, and
// marks and chips fade in for 150 ms.
//
// API (window.abhyasaBoard):
//   play(board, {labels, fast, quiet, auto, host, who, onVoice})   play a checked board; it stops the board that shows now.
//     labels  {anchorId: {label: [x0, y0, x1, y1]}}, the label boxes of a figure, 0 to 1000 of the anchor. Default {}.
//     fast    draw each step at once, with no voice and no pointer flight. Default false.
//     quiet   no voice: the words are timed by their letters. host.speak is not called. Default false.
//     auto    go to the next step 1.2 s after the line is said. Default true (false when fast).
//     who     {model, where, who}: the model that wrote the board, shown in the strip as "Claude Sonnet · hosted". Default none.
//     onVoice onVoice(on) when the learner turns the voice off or on in the strip. With it, the strip has a Voice button, and the
//             first board with a voice says once: "The guide speaks its steps. Turn the voice off here." Default none.
//     host    the hooks of the page that shows the board. Each one is optional:
//       resolve(id) -> Element|null   the element of anchor `id`. Default: document.querySelector('[data-guide-id="<id>"]').
//                                     A formula element names its parts in data-parts: JSON [[tex, elementId], ...]; the
//                                     board finds each part by its id inside the element, then in the document.
//                                     A token with no part element marks the whole formula element.
//       speak(text, onWord, done)     say `text`. Call onWord(k) when word k (from 0, split on white space) starts, and done()
//                                     at the end. It can return a function that stops the speech. The board ignores calls
//                                     after the step changes. Default: speechSynthesis, timed by letters when it has no voice.
//       demo(set)                     move the demo to `set` ({input: value}). Default: Rupaka.set on [data-guide-id="demo"],
//                                     only when each gate of the demo is done (never show the result first). A host demo
//                                     must do its own gate check.
//       assets                        the URL folder of rough.js and perfect-freehand.mjs. Default '/vendor/'.
//     A board with `streaming: true` waits for more steps: it can start with step 1 only. The strip shows no step count and
//     no end line until finish(board).
//   add(step) -> bool    add one checked step to the streaming board that shows now. When that board waits at its last step
//                        with auto on, it goes on to the new step. False when no streaming board shows.
//   finish(board) -> bool   the whole checked board for the streaming board that shows now: it adds the steps that are not
//                        there yet, takes the tier, sources and end of `board`, and stops the wait for steps. False when no
//                        streaming board shows, or when its steps are not the first steps of `board` (then play `board`).
//                        An `end` of '' shows no end line: the stream ended with no whole board.
//   stop()  note(text)  next()  back()  again()  seekVideo(t)  boxOf(at)  normTex(tex)
//   status(event)        the state line in the strip while the guide works: the `wait` text of a state event of the guide route
//                        ({wait, state, model, where, who, query, sources}), a chip "on this Mac" or "hosted · <who>", the seconds
//                        after 3 s while it asks, and Stop.
//   A board can carry `saved` ({title, url, undo}: "Saved to your vault: <title>. Undo" at the end; Undo posts to the local
//   path `undo`) and `hint` (a line for the open check, shown at the end).
//   demoAnchors(host) -> {anchors, demo: {slug, inputs, readouts, open}} | null   the anchors of the rupaka demo `host`: `demo` for
//                        the host, `in:<bind>` for each input of spec.state, `out:<n>` for each readout that shows (n from 1, in
//                        spec order). It sets data-guide-id on each one. An id of more than 40 characters is dropped, never cut.
//   state    {i, steps, tier, first, done, streaming} or null. `done` is true when each mark of the step shows in full.
//   pointer  {tip, to, flying} in window pixels, or null: where the tip of the pointer is, and the point that it flies to.
// Events on document: board:first (the first mark shows), board:stop (detail.by is 'learner' after Esc or Stop, else '').
(() => {
  if (window.abhyasaBoard) return;
  const NS = 'http://www.w3.org/2000/svg', WAIT = 1200;
  let pf = null, st = null;   // the pen module, and the board that shows now
  const script = src => new Promise((ok, no) => document.head.append(Object.assign(document.createElement('script'), {src, onload: ok, onerror: no})));
  const libs = async base => {
    if (!window.rough) await script(base + 'rough.js');
    if (!pf) pf = await import(base + 'perfect-freehand.mjs');
  };
  const normTex = s => { s = String(s || '').replace(/\s+/g, ''); for (let t; (t = s.replace(/\{(\\[A-Za-z]+|[^{}\\])\}/g, '$1')) !== s;) s = t; return s; };
  const flat = s => String(s || '').replace(/\s+/g, ' ').trim().toLowerCase();
  const seen = el => el && el.isConnected && (el.checkVisibility ? el.checkVisibility() : el.offsetParent !== null);
  const pageRect = r => ({x: r.left + scrollX, y: r.top + scrollY, w: r.width, h: r.height});
  const reduced = () => matchMedia('(prefers-reduced-motion: reduce)').matches;

  // --- motion -----------------------------------------------------------------------------------------------------------
  const clamp = (v, a = 0, b = 1) => Math.max(a, Math.min(b, v));
  const smooth = p => p * p * (3 - 2 * p);                                      // Clicky's flight
  const pen = p => p < .5 ? 4 * p * p * p : 1 - (-2 * p + 2) ** 3 / 2;          // a hand speeds up, then slows
  function spring(ms, response = .4, damping = .6) {                            // SwiftUI .spring(response:, dampingFraction:), 0 to 1
    if (ms <= 0) return 0;
    const t = ms / 1000, w = 2 * Math.PI / response, z = damping, wd = w * Math.sqrt(1 - z * z);
    return 1 - Math.exp(-z * w * t) * (Math.cos(wd * t) + z * w / wd * Math.sin(wd * t));
  }

  // --- the host: where anchors, voice, demo and pen files come from -------------------------------------------------------
  const HOST = {resolve: id => document.querySelector(`[data-guide-id="${CSS.escape(id)}"]`), speak: voice, demo: rupaka, assets: '/vendor/'};
  const hooks = () => st ? st.host : HOST;
  const anchorEl = id => { try { const e = hooks().resolve(String(id)); return e instanceof Element ? e : null; } catch (e) { return null; } };

  // The box of a run of words inside `el`, from its text nodes (not the hidden MathML of a formula).
  function textBox(el, words) {
    const nodes = [], tw = document.createTreeWalker(el, NodeFilter.SHOW_TEXT, {acceptNode: n => n.parentElement.closest('.katex-mathml, script, style') ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT});
    let all = '';
    for (let n; (n = tw.nextNode());) { nodes.push([n, all.length]); all += n.data; }
    const re = new RegExp(flat(words).split(' ').map(w => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('\\s+'));   // white space made single
    const m = re.exec(all.toLowerCase());
    if (!m) return null;
    const where = k => { let i = nodes.length - 1; while (i > 0 && nodes[i][1] > k) i--; return [nodes[i][0], k - nodes[i][1]]; };
    const r = document.createRange(), [a, ao] = where(m.index), [b, bo] = where(m.index + m[0].length);
    r.setStart(a, ao); r.setEnd(b, Math.min(bo, b.data.length));
    const rs = [...r.getClientRects()];
    return rs.length ? {...pageRect(rs[0]), el: a.parentElement, glyphs: true} : null;   // the first line only, so a mark on words that wrap stays on one line
  }

  // The box of an anchor in page pixels, or null when it is not on the page now. `el` is the element under it.
  function locate(at) {
    const a = typeof at === 'string' ? {a: at} : at || {}, el = anchorEl(a.a);
    if (!seen(el)) return null;
    const R = {...pageRect(el.getBoundingClientRect()), el};
    if (a.tex != null) {
      let parts = []; try { parts = JSON.parse(el.dataset.parts || '[]'); } catch (e) {}
      const hit = parts.find(p => normTex(p[0]) === normTex(a.tex)), pid = hit && String(hit[1]);
      const part = pid && (el.querySelector('#' + CSS.escape(pid)) || document.getElementById(pid));
      return seen(part) ? {...pageRect(part.getBoundingClientRect()), el: part, glyphs: true} : R;   // no part element: the whole formula, so the stroke stays
    }
    if (a.text != null) return textBox(el, a.text);
    const rel = b => ({x: R.x + R.w * b[0] / 1000, y: R.y + R.h * b[1] / 1000, w: R.w * (b[2] - b[0]) / 1000, h: R.h * (b[3] - b[1]) / 1000, el});
    if (a.label != null) { const b = (st && st.labels[a.a] || {})[a.label]; return b ? rel(b) : null; }
    if (a.box) return rel(a.box);
    if (a.pt) return {x: R.x + R.w * a.pt[0] / 1000, y: R.y + R.h * a.pt[1] / 1000, w: 0, h: 0, pt: true, el};
    return R;
  }
  const boxOf = at => { const b = locate(at); return b && {x: b.x, y: b.y, w: b.w, h: b.h, ...(b.pt && {pt: true})}; };

  // Is the surface under `el` dark? From the first background colour up the tree; a picture counts as light (a figure card).
  const tone = {}, probe = document.createElement('canvas').getContext('2d', {willReadFrequently: true});
  function lum(c) {
    if (c in tone) return tone[c];
    probe.clearRect(0, 0, 1, 1); probe.fillStyle = '#000'; probe.fillStyle = c; probe.fillRect(0, 0, 1, 1);
    const [r, g, b, a] = probe.getImageData(0, 0, 1, 1).data;
    return (tone[c] = a < 200 ? null : (.2126 * r + .7152 * g + .0722 * b) / 255);
  }
  function dark(el) {
    for (let e = el; e && e.nodeType === 1; e = e.parentElement) {
      if (/^(IMG|CANVAS|VIDEO|svg)$/.test(e.tagName) || e.ownerSVGElement) return false;
      const c = getComputedStyle(e).backgroundColor;
      if (c && c !== 'transparent' && !/rgba\(.*,\s*0\)$/.test(c)) { const l = lum(c); if (l != null) return l < .5; }
    }
    const l = lum(getComputedStyle(document.body).backgroundColor);
    return l != null ? l < .5 : matchMedia('(prefers-color-scheme: dark)').matches;
  }

  // --- layers -------------------------------------------------------------------------------------------------------------
  // The host is 1 px with overflow shown, so it never makes the page larger. The marker layers are outside it, at the top of
  // the page, so that their blend mode mixes with the page under them, not with the board only.
  function host() {
    let h = document.getElementById('board-host');
    if (!h) {
      h = Object.assign(document.createElement('div'), {id: 'board-host'});
      h.setAttribute('aria-hidden', 'true');
      const glows = Object.assign(document.createElement('div'), {className: 'board-glows'});
      const svg = document.createElementNS(NS, 'svg'); svg.id = 'board-layer';
      const ptr = Object.assign(document.createElement('div'), {id: 'board-pointer'});
      const tri = document.createElementNS(NS, 'svg'); tri.setAttribute('viewBox', '-8 -8 16 16');
      const p = document.createElementNS(NS, 'path'); p.setAttribute('d', 'M0 -9.24 L8 4.62 L-8 4.62 Z'); tri.append(p); ptr.append(tri);
      h.append(glows, svg, ptr);
      document.body.append(h);
      for (const blend of ['multiply', 'screen']) {
        const s = document.createElementNS(NS, 'svg'); s.classList.add('board-hl'); s.dataset.blend = blend; s.setAttribute('aria-hidden', 'true');
        document.body.append(s);
      }
    }
    return h;
  }
  const layer = () => host().querySelector('#board-layer');
  const hlLayer = blend => document.querySelector(`.board-hl[data-blend="${blend}"]`);
  const css = v => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
  const svgEl = (tag, cls) => { const e = document.createElementNS(NS, tag); if (cls) e.setAttribute('class', cls); return e; };

  // --- point lists for strokes: [x, y, pressure] ----------------------------------------------------------------------------
  function dense(path, step = 2) {   // a polyline with a point each `step` px
    const out = [path[0]];
    for (let i = 1; i < path.length; i++) {
      const [ax, ay] = path[i - 1], [bx, by] = path[i], n = Math.max(1, Math.ceil(Math.hypot(bx - ax, by - ay) / step));
      for (let k = 1; k <= n; k++) out.push([ax + (bx - ax) * k / n, ay + (by - ay) * k / n]);
    }
    return out;
  }
  const press = (pts, a = .35, m = .8, b = .3) => pts.map(([x, y], i) => { const u = i / Math.max(1, pts.length - 1); return [x, y, u < .3 ? a + (m - a) * u / .3 : m + (b - m) * (u - .3) / .7]; });
  const length = pts => pts.reduce((s, p, i) => i ? s + Math.hypot(p[0] - pts[i - 1][0], p[1] - pts[i - 1][1]) : 0, 0);
  function ring(b, pad, seed) {   // one loop with a 0.55 rad overrun and a 5 % spiral, as a hand draws it
    const cx = b.x + b.w / 2, cy = b.y + b.h / 2, rx = b.w / 2 + pad, ry = b.h / 2 + pad * .8, out = [];
    for (let i = 0; i <= 90; i++) { const u = i / 90, a = -2.3 + u * (2 * Math.PI + .55), k = 1 + .03 * Math.sin(3 * a + seed) + .05 * (u - .5); out.push([cx + rx * k * Math.cos(a), cy + ry * k * Math.sin(a)]); }
    return out;
  }
  function svgPath(o) {   // perfect-freehand's outline as a smooth closed path
    if (o.length < 3) return '';
    const d = ['M', o[0][0].toFixed(1), o[0][1].toFixed(1), 'Q'];
    for (let i = 0; i < o.length; i++) { const [x0, y0] = o[i], [x1, y1] = o[(i + 1) % o.length]; d.push(x0.toFixed(1), y0.toFixed(1), ((x0 + x1) / 2).toFixed(1), ((y0 + y1) / 2).toFixed(1)); }
    return d.join(' ') + ' Z';
  }
  // A stroke part of a mark: its points, its pen, and when it draws (from the start of the mark, in ms).
  const stroke = (el, pts, {size = 3.4, thin = .6, at = 0, dur} = {}) => ({kind: 'pen', el, pts, size, thin, at, dur: dur || clamp(length(pts) * 1.1, 420, 720)});

  // Where an arrow starts: the first of 8 places around the target that is in the window and not on text.
  function onText(x, y) {
    let n, o;
    if (document.caretRangeFromPoint) { const r = document.caretRangeFromPoint(x, y); if (!r) return false; n = r.startContainer; o = r.startOffset; }
    else if (document.caretPositionFromPoint) { const p = document.caretPositionFromPoint(x, y); if (!p) return false; n = p.offsetNode; o = p.offset; }
    if (!n || n.nodeType !== 3) return false;
    const r = document.createRange(); r.setStart(n, Math.max(0, o - 1)); r.setEnd(n, Math.min(n.data.length, o + 1));
    return [...r.getClientRects()].some(q => x >= q.left - 6 && x <= q.right + 6 && y >= q.top - 4 && y <= q.bottom + 4);
  }
  function freePlace(b) {
    const cx = b.x + b.w / 2, cy = b.y + b.h / 2, R = Math.max(64, Math.min(110, Math.max(b.w, b.h) / 2 + 52));
    const tries = [-140, -40, 180, 0, 140, 40, -90, 90].map(d => [Math.cos(d * Math.PI / 180) * (R + b.w / 4), Math.sin(d * Math.PI / 180) * (R * .8 + b.h / 4)]);
    const ok = ([dx, dy]) => { const x = cx + dx - scrollX, y = cy + dy - scrollY; return x > 8 && y > 8 && x < innerWidth - 8 && y < innerHeight - 8 && !onText(x, y); };
    return tries.find(ok) || tries[0];
  }

  // --- marks: `place` reads the page and builds the parts; `paint` sets them for one moment ------------------------------------
  const PASTEL = ['pink', 'green', 'blue', 'yellow', 'violet', 'peach'];
  function place(m) {
    const o = m.o, svg = layer(), rc = rough.svg(svg), ink = css('--board-ink') || '#b5551c';
    const b = o.at !== undefined ? locate(o.at) : null;
    if (o.at !== undefined && !b) return hide(m);
    if (!m.g && o.op !== 'label' && o.op !== 'box') { m.g = svgEl('g'); m.g.dataset.op = o.op; m.g.dataset.step = m.step; svg.append(m.g); }
    if (m.g) { m.g.replaceChildren(); m.g.style.display = ''; }
    const parts = [];
    let target = b && {x: b.x, y: b.y, w: b.w, h: b.h};
    for (const e of [m.g, m.hl, m.el, m.lead]) if (e) e.style.display = '';
    const pathIn = (g, cls) => { const p = svgEl('path', cls); g.append(p); return p; };
    const arrow = (from, to, at = 0) => {   // one light Rough.js stroke, then a filled head that springs in
      const c = [(from[0] + to[0]) / 2 + (to[1] - from[1]) * .18, (from[1] + to[1]) / 2 - (to[0] - from[0]) * .18];
      const shaft = rc.curve([from, c, to], {stroke: ink, strokeWidth: 1.8, roughness: .7, bowing: .6, disableMultiStroke: true, preserveVertices: true, seed: m.seed});
      m.g.append(shaft);
      const line = shaft.querySelector('path'), L = line ? line.getTotalLength() : 0, dur = clamp(L * 1.4, 380, 640);
      if (line) { line.setAttribute('stroke-linecap', 'round'); parts.push({kind: 'dash', el: line, L, at, dur}); }
      let tip = to, a = Math.atan2(to[1] - c[1], to[0] - c[0]);
      if (L) { const P = line.getPointAtLength(L), Q = line.getPointAtLength(Math.max(0, L - 10)); tip = [P.x, P.y]; a = Math.atan2(P.y - Q.y, P.x - Q.x); }   // the head turns with the end of the line
      parts.push({kind: 'head', el: pathIn(m.g, 'board-fill'), tip, a, at: at + dur * .92});
      return at + dur;
    };
    if (o.op === 'circle') {
      if (b.glyphs) {   // a marker through the middle of the glyphs: they stay sharp and get a tint
        const blend = dark(b.el) ? 'screen' : 'multiply', size = Math.max(8, b.h * .92);
        if (!m.hl || m.hl.ownerSVGElement !== hlLayer(blend)) { if (m.hl) m.hl.remove(); m.hl = svgEl('path', 'board-marker'); m.hl.dataset.op = 'marker'; m.hl.dataset.step = m.step; hlLayer(blend).append(m.hl); }
        const inset = Math.min(size * .42, b.w / 2 - 1);
        parts.push(stroke(m.hl, press(dense([[b.x + inset, b.y + b.h * .55], [b.x + b.w - inset, b.y + b.h * .5]]), .9, 1, .9), {size, thin: 0, dur: 420}));
      }
      parts.push(stroke(pathIn(m.g, 'board-fill'), press(ring(b, b.glyphs ? 9 : 12, m.seed)), {size: 3.3, at: b.glyphs ? 160 : 0}));
    }
    if (o.op === 'underline') parts.push(stroke(pathIn(m.g, 'board-fill'), press(dense([[b.x - 3, b.y + b.h + 5], [b.x + b.w * .5, b.y + b.h + 7], [b.x + b.w + 4, b.y + b.h + 3]])), {size: 3.5}));
    if (o.op === 'box') {   // a soft glow that blooms, then settles: no frame on the text
      if (!m.el) { m.el = Object.assign(document.createElement('div'), {className: 'board-glow'}); m.el.dataset.op = 'box'; m.el.dataset.step = m.step; host().querySelector('.board-glows').append(m.el); }
      const pad = 10; m.el.hidden = false; m.dark = dark(b.el);
      Object.assign(m.el.style, {left: b.x - pad + 'px', top: b.y - pad + 'px', width: b.w + 2 * pad + 'px', height: b.h + 2 * pad + 'px'});
      m.el.classList.toggle('on-dark', m.dark);
      parts.push({kind: 'glow', el: m.el, at: 0, dur: 1200});
    }
    if (o.op === 'point') {
      if (!m.off) m.off = freePlace(b);
      const cx = b.x + b.w / 2, cy = b.y + b.h / 2, r = Math.max(b.w, b.h) / 2 + 9, a = Math.atan2(m.off[1], m.off[0]);
      const end = arrow([cx + m.off[0], cy + m.off[1]], [cx + Math.cos(a) * r, cy + Math.sin(a) * r]);
      parts.push(stroke(pathIn(m.g, 'board-fill'), press(ring(b, 6, m.seed)), {size: 2.8, at: end - 80}));   // the ring is the last child: it is on the target
    }
    if (o.op === 'arrow') {
      const f = locate(o.from), t = locate(o.to);
      if (!f || !t) return hide(m);
      const fx = f.x + f.w / 2, fy = f.y + f.h / 2, tx = t.x + t.w / 2, ty = fy < t.y ? t.y - 5 : t.y + t.h + 5;
      arrow([fx, fy], [tx, ty]);
      target = {x: t.x, y: t.y, w: t.w, h: t.h};
    }
    if (o.op === 'sketch' && pf) {
      const W = b.pt ? 240 : b.w, H = b.pt ? 90 : b.h;
      const pts = o.pts.map(([x, y]) => [b.x + W * x / 1000, b.y + H * y / 1000]);
      if (b.pt) { const ax = pathIn(m.g, 'board-axis'); ax.setAttribute('d', `M${b.x} ${b.y - 6} V${b.y + H} H${b.x + W + 6}`); }
      parts.push(stroke(pathIn(m.g, 'board-fill'), press(dense(pts, 3), .4, .8, .45), {size: 3.6, dur: clamp(length(pts) * 1.1, 420, 900)}));
    }
    if (o.op === 'label') { if (!placeLabel(m, b)) return hide(m); parts.push({kind: 'chip', at: 0, dur: 900}); }
    m.parts = parts; m.aim = target; m.ok = true;
    m.life = parts.reduce((s, p) => Math.max(s, p.at + (p.dur || 300)), 0) + (parts.some(p => p.kind === 'head') ? 500 : 0);
    return true;
  }
  function hide(m) {
    m.ok = false;
    for (const e of [m.g, m.hl, m.el, m.lead]) if (e) e.style.display = 'none';
    return false;
  }
  function unmount(m) {
    for (const e of [m.g, m.hl, m.el, m.lead]) if (e) e.remove();
    m.g = m.hl = m.el = m.lead = null; m.parts = []; m.drawn = false; m.ok = false;
  }

  // A chip: pastel, with a coloured bar, near its target and never on it. A thin leader line ends with a dot on the part.
  function placeLabel(m, b) {
    if (!m.el) {
      m.el = Object.assign(document.createElement('div'), {className: 'board-label'}); m.el.textContent = m.o.text;
      const k = st.marks.filter(x => x.step === m.step && x.o.op === 'label').indexOf(m);
      m.el.dataset.tint = PASTEL[k % PASTEL.length]; host().append(m.el);
      m.lead = svgEl('g', 'board-lead'); m.lead.dataset.step = m.step; m.lead.append(svgEl('path'), svgEl('circle')); layer().append(m.lead);
    }
    m.el.hidden = false;
    const w = m.el.offsetWidth, h = m.el.offsetHeight, gap = 20, pad = 3;
    const sides = [m.o.side || 'above', 'above', 'below', 'right', 'left'].filter((s, i, a) => a.indexOf(s) === i);
    const others = st.marks.filter(x => x !== m && x.step === m.step && x.o.op === 'label' && x.box).map(x => x.box);
    const hits = (r, q, p = 0) => r.x < q.x + q.w + p && q.x < r.x + r.w + p && r.y < q.y + q.h + p && q.y < r.y + r.h + p;
    const maxX = Math.max(document.documentElement.scrollWidth, scrollX + innerWidth) - w - 4;
    let pick = null;
    for (const side of sides) {
      let x = b.x + b.w / 2 - w / 2, y = b.y - h - gap;
      if (side === 'below') y = b.y + b.h + gap;
      if (side === 'left') { x = b.x - w - gap; y = b.y + b.h / 2 - h / 2; }
      if (side === 'right') { x = b.x + b.w + gap; y = b.y + b.h / 2 - h / 2; }
      const r = {x: clamp(x, 4, maxX), y: Math.max(4, y), w, h, side};
      if (!hits(r, b, pad) && !others.some(q => hits(r, q, 4))) { pick = r; break; }
      pick = pick || r;
    }
    m.box = pick;
    m.el.style.left = pick.x + 'px'; m.el.style.top = pick.y + 'px';
    m.el.style.transformOrigin = {above: '50% 100%', below: '50% 0', left: '100% 50%', right: '0 50%'}[pick.side];
    // the leader: from the edge of the chip to the edge of the part that faces it
    const cx = clamp(pick.x + w / 2, b.x, b.x + b.w), cy = clamp(pick.y + h / 2, b.y, b.y + b.h);
    const p0 = pick.side === 'above' ? [cx, b.y] : pick.side === 'below' ? [cx, b.y + b.h] : pick.side === 'left' ? [b.x, cy] : [b.x + b.w, cy];
    const p1 = pick.side === 'above' ? [clamp(p0[0], pick.x + 8, pick.x + w - 8), pick.y + h] : pick.side === 'below' ? [clamp(p0[0], pick.x + 8, pick.x + w - 8), pick.y]
             : pick.side === 'left' ? [pick.x + w, clamp(p0[1], pick.y + 4, pick.y + h - 4)] : [pick.x, clamp(p0[1], pick.y + 4, pick.y + h - 4)];
    m.leadPts = [p0, p1];
    m.lead.classList.toggle('on-dark', dark(b.el));
    const dot = m.lead.children[1]; dot.setAttribute('cx', p0[0]); dot.setAttribute('cy', p0[1]); dot.setAttribute('r', '2.6');
    return true;
  }

  // Each part of a mark at time `t` (ms, performance.now).
  function paint(m, t) {
    if (!m.ok) return;
    const k = t - m.t0, still = reduced() || m.still, fade = still ? clamp(k / 150) : 1;
    const op = (k < 0 ? 0 : fade) * dim(m, t);
    for (const p of m.parts) {
      const q = k - p.at, f = still ? (k < 0 ? 0 : 1) : pen(clamp(q / p.dur));
      if (p.kind === 'pen') {
        const n = Math.max(2, Math.ceil(f * p.pts.length)), pts = f > 0 ? p.pts.slice(0, n) : [];
        const out = pts.length > 1 ? pf.getStroke(pts, {size: p.size, thinning: p.thin, smoothing: .55, streamline: .35, simulatePressure: false,
                                                        start: {taper: p.thin ? 6 : 0, cap: true}, end: {taper: f >= 1 && p.thin ? 10 : 0, cap: true}, last: f >= 1}) : [];
        p.el.setAttribute('d', svgPath(out));
      }
      if (p.kind === 'dash') { p.el.style.strokeDasharray = p.L; p.el.style.strokeDashoffset = p.L * (1 - f); p.el.style.opacity = f > 0 ? 1 : 0; }
      if (p.kind === 'head') {
        const s = still ? (k >= 0 ? 1 : 0) : spring(q, .32, .55), [ex, ey] = p.tip, a = p.a, L = 12 * s, W = 6.5 * s, c = Math.cos(a), si = Math.sin(a);
        p.el.setAttribute('d', s <= 0 ? '' : `M${ex + c * 2} ${ey + si * 2} L${ex - L * c + W * si} ${ey - L * si - W * c} Q${ex - L * .7 * c} ${ey - L * .7 * si} ${ex - L * c - W * si} ${ey - L * si + W * c} Z`);
      }
      if (p.kind === 'glow') {   // Clicky's bubble glow: strong at first, then it settles
        const settle = still ? 0 : Math.exp(-Math.max(0, q) / 380), a = still ? fade : clamp(q / 220), d = m.dark;
        Object.assign(p.el.style, {opacity: op * a, boxShadow: `0 0 0 1.5px color-mix(in srgb, var(--board-ink) ${(38 + 30 * settle).toFixed(0)}%, transparent), ` +
          `0 0 ${(14 + 22 * settle).toFixed(1)}px ${(2 + 4 * settle).toFixed(1)}px color-mix(in srgb, var(--board-ink) ${((d ? 34 : 24) + 30 * settle).toFixed(0)}%, transparent)`});
      }
      if (p.kind === 'chip') {   // it pops in on a spring; its leader draws from the chip to the part, then the dot shows
        const s = still ? 1 : spring(q), lk = still ? (k >= 0 ? 1 : 0) : smooth(clamp((q - 120) / 260));
        Object.assign(m.el.style, {opacity: op * (still ? 1 : clamp(q / 160)), transform: still ? '' : `translateY(${((1 - s) * 6).toFixed(2)}px) scale(${(.86 + .14 * s).toFixed(3)})`});
        m.el.classList.toggle('on', k >= 0);
        const [[x0, y0], [x1, y1]] = m.leadPts, [line, dot] = m.lead.children;
        line.setAttribute('d', `M${x1.toFixed(1)} ${y1.toFixed(1)} L${(x1 + (x0 - x1) * lk).toFixed(1)} ${(y1 + (y0 - y1) * lk).toFixed(1)}`);
        line.style.opacity = lk > 0 ? op : 0; dot.style.opacity = lk >= 1 ? op : 0;
      }
    }
    if (m.g) m.g.style.opacity = op;
    if (m.hl) m.hl.style.opacity = op;
  }
  // Marks of earlier steps step back to 45 %, and a glow goes. A mark of the step before fades; the others are there at once.
  function dim(m, t) {
    if (!st || m.step >= st.i) return 1;
    const low = m.o.op === 'box' ? 0 : .45;
    return m.fade ? 1 - (1 - low) * smooth(clamp((t - st.stepAt) / (low ? 350 : 300))) : low;
  }

  // --- the pointer ----------------------------------------------------------------------------------------------------------
  const home = () => { const s = document.getElementById('guide-strip'), sh = s && !s.hidden ? s.offsetHeight : 0; return [scrollX + 44, scrollY + innerHeight - sh - 36]; };
  // Where the tip rests: at the lower right of the target, so the body stays off the text; else at its right or under it, so that
  // the body (about 24 px around its centre, 6 px right and 10 px down from the tip) never sits on a chip of the step.
  function aimAt(b) {
    const chips = st ? st.marks.filter(m => m.step === st.i && m.o.op === 'label' && m.ok && m.box).map(m => m.box) : [];
    const tries = [[b.x + b.w + 6, b.y + b.h + 4], [b.x + b.w + 8, b.y + b.h / 2 - 6], [b.x + b.w + 6, b.y + 2], [b.x + b.w / 2, b.y + b.h + 4]];
    const free = ([x, y]) => !chips.some(c => x + 6 + 12 > c.x - 3 && x + 6 - 12 < c.x + c.w + 3 && y + 10 + 12 > c.y - 3 && y + 10 - 12 < c.y + c.h + 3);
    return tries.find(free) || tries[0];
  }
  function where(t) {   // the pointer at time t: its place, turn and size
    const P = st.ptr, f = P.f;
    if (!f) return {pos: P.pos || home(), rot: -35, sc: 1};
    if (f.m && f.m.ok && f.m.aim && t < f.t0 + f.dur) { const [ax, ay] = aimAt(f.m.aim); f.to = [ax + 6, ay + 10]; }   // in flight, the target can move (scroll, resize)
    const to = f.to;
    const lin = clamp((t - f.t0) / f.dur), u = smooth(lin), s = 1 - u, c = [(f.from[0] + to[0]) / 2, (f.from[1] + to[1]) / 2 - f.arc];
    const pos = [s * s * f.from[0] + 2 * s * u * c[0] + u * u * to[0], s * s * f.from[1] + 2 * s * u * c[1] + u * u * to[1]];
    if (lin < 1) {   // it turns to its path, and grows to 1.3x as it comes in
      const tx = 2 * s * (c[0] - f.from[0]) + 2 * u * (to[0] - c[0]), ty = 2 * s * (c[1] - f.from[1]) + 2 * u * (to[1] - c[1]);
      return {pos, rot: Math.atan2(ty, tx) * 180 / Math.PI + 90, sc: 1 + .3 * u, to, flying: true};
    }
    const k = t - f.t0 - f.dur, a = Math.atan2(to[1] - c[1], to[0] - c[0]) * 180 / Math.PI + 90;
    if (f.jump) return {pos, rot: -35, sc: 1, to};   // reduced motion: it is there at once
    return {pos, rot: a + (((-35 - a + 540) % 360) - 180) * smooth(clamp(k / 300)), sc: 1 + .3 * (1 - spring(k, .4, .6)), to, busy: k < 900};
  }
  function fly(m, t) {
    if (!m.aim) return t;
    const now = where(t), from = now.pos, b = m.aim, [ax, ay] = aimAt(b), to = [ax + 6, ay + 10], d = Math.hypot(to[0] - from[0], to[1] - from[1]);
    if (reduced() || st.fast) { st.ptr.f = {t0: t, dur: 0, from: to, to, arc: 0, m, jump: true}; return t; }
    const dur = clamp(d / 800, .6, 1.4) * 1000;
    st.ptr.f = {t0: t, dur, from, to, arc: Math.min(d * .2, 80), m};
    return t + dur;   // when it lands
  }
  function paintPointer(t) {
    const f = st.ptr.f;   // at rest, a target that moved or a chip that came gives a short new flight, not a jump
    if (f && f.m && f.m.ok && f.m.aim && t >= f.t0 + f.dur) { const [ax, ay] = aimAt(f.m.aim); if (Math.hypot(ax + 6 - f.to[0], ay + 10 - f.to[1]) > 2) fly(f.m, t); }
    const el = document.getElementById('board-pointer');
    if (!el) return;
    const w = where(t), breathe = reduced() ? 0 : .5 + .5 * Math.sin(t / 2500 * 2 * Math.PI), glow = 8 + (w.sc - 1) * 20 + breathe * 2;
    st.ptr.now = w;
    el.style.transform = `translate(${w.pos[0].toFixed(1)}px, ${w.pos[1].toFixed(1)}px) rotate(${w.rot.toFixed(1)}deg) scale(${w.sc.toFixed(3)})`;
    el.style.opacity = reduced() ? 1 : clamp((t - st.t0) / 400);
    el.style.setProperty('--glow', glow.toFixed(1) + 'px');
  }

  // --- one clock: each frame paints the pointer and each mark that still moves ----------------------------------------------
  let ticking = false;
  function tick() {
    if (!st) { ticking = false; return; }
    const t = performance.now();
    paintPointer(t);
    for (const m of st.marks) if (m.drawn && (m.dirty || t - m.t0 < m.life + 50 || t - st.stepAt < 400)) { paint(m, t); m.dirty = false; }
    requestAnimationFrame(tick);
  }
  const clock = () => { if (!ticking) { ticking = true; requestAnimationFrame(tick); } };

  // Each mark again from its anchor, in the next frame. A mark whose anchor is gone hides; when all are gone, the strip says so.
  let queued = false;
  function follow() {
    if (!st || queued) return;
    queued = true;
    requestAnimationFrame(() => {
      queued = false;
      if (!st || !pf) return;
      host();
      const ms = st.marks.filter(m => m.drawn), t = performance.now();
      const ok = ms.map(m => { const r = place(m); paint(m, t); return r; });
      if (ms.length && !ok.some(Boolean)) note('The page changed. Ask again.');
    });
  }

  // --- the strip ----------------------------------------------------------------------------------------------------
  const TIER = {tutor: 'tutor', vault: 'your vault', web: 'web'};
  const safeHref = u => /^(https?:\/\/|\/(?!\/))/.test(String(u || ''));
  const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
  function strip() { return document.getElementById('guide-strip') || document.body.appendChild(Object.assign(el('div', 'guide-strip'), {id: 'guide-strip'})); }
  let ticker = 0;   // the seconds of the state line
  function note(text) { clearInterval(ticker); const s = strip(); s.hidden = false; s.replaceChildren(el('p', 'board-note', text)); }
  const HERE = 'on this Mac';
  function chip(w) {   // where the text goes: "on this Mac" (quiet), or "hosted · <who>" (outlined)
    if (!w || !w.where) return null;
    const here = w.where === HERE, c = el('span', 'board-where' + (here ? '' : ' hosted'), here ? HERE : w.who ? `hosted · ${w.who}` : 'hosted');
    if (w.model) c.title = w.model;
    return c;
  }
  function button(text, cls, act) { const b = el('button', 'board-btn ' + cls, text); b.type = 'button'; b.addEventListener('click', act); return b; }
  function status(ev) {   // see the API at the top of this file
    if (!ev || typeof ev.wait !== 'string') return;
    clearInterval(ticker);
    const s = strip(), p = el('p', 'board-note board-state', null), t0 = performance.now();
    p.dataset.state = ev.state || '';
    p.append(el('span', 'board-wait', ev.wait));
    if (ev.query && !ev.wait.includes(ev.query)) p.append(' ', el('q', 'board-query', ev.query));
    const c = chip(ev); if (c) p.append(' ', c);
    if (ev.state === 'asking') {
      const n = el('span', 'board-secs', '');
      p.append(' ', n);
      ticker = setInterval(() => { const k = Math.floor((performance.now() - t0) / 1000); if (k >= 3) n.textContent = `${k} s`; if (!n.isConnected) clearInterval(ticker); }, 250);
    }
    p.append(' ', button('Stop', 'board-stop', () => stop('learner')));
    s.hidden = false; s.replaceChildren(p);
  }
  function caption() {
    clearInterval(ticker);
    const s = strip(), b = st.board, step = b.steps[st.i];
    s.hidden = false;
    const top = el('div', 'board-top'), dots = el('span', 'board-dots');
    b.steps.forEach((_, k) => dots.append(el('i', k === st.i ? 'on' : '')));
    top.append(el('span', 'pill tier-' + b.tier, TIER[b.tier] || 'tutor'), dots, el('span', 'board-n', st.streaming ? `Step ${st.i + 1}` : `Step ${st.i + 1} of ${b.steps.length}`));
    if (st.who && st.who.model) top.append(el('span', 'board-who', `${st.who.model} · ${st.who.where === HERE ? HERE : 'hosted'}`));
    const say = el('p', 'board-say');   // each word in its own span, so it can light up when it is said
    step.say.split(/\s+/).filter(Boolean).forEach((w, k) => { if (k) say.append(' '); say.append(el('span', k <= st.lit ? 'on' : '', w)); });
    const parts = [top, say];
    if (step.quote) {
      const src = b.sources[step.quote.src - 1] || {}, q = el('p', 'board-quote');
      q.append(el('q', '', step.quote.text), ' ', el('span', 'pill', src.label || 'source'), ' ', link(src));
      parts.push(q);
    }
    if (st.video) parts.push(st.video);
    if (st.i === b.steps.length - 1 && !st.streaming && b.end !== '') {   // an end of '' shows no end line
      const end = el('p', 'board-end', b.end || "In the tutor's own words. No source found.");
      (b.sources || []).filter(x => x.quoted).forEach(x => end.append(' ', link(x)));
      parts.push(end);
    }
    if (st.i === b.steps.length - 1 && !st.streaming) {
      if (b.saved && b.saved.title) {   // a thing that stays after the board: say it, with Undo
        const sv = el('p', 'board-saved', `Saved to your vault: ${b.saved.title}. `), u = String(b.saved.undo || '');
        if (/^\/(?!\/)/.test(u)) sv.append(button('Undo', 'board-undo', async () => {
          try { const r = await fetch(u, {method: 'POST'}); sv.textContent = (await r.text()).slice(0, 200); } catch (e) { sv.textContent = 'abhyasa could not undo this. Try again.'; }
          if (st) st.board.saved = null;
        }));
        parts.push(sv);
      }
      if (b.hint) parts.push(el('p', 'board-hint', b.hint));
    }
    if (st.onVoice && !st.quiet && !st.told) {   // the first board with a voice says how to turn it off, one time
      st.told = true;
      if (!localStorage.getItem('board-voice-told')) { localStorage.setItem('board-voice-told', '1'); parts.push(el('p', 'board-tell', 'The guide speaks its steps. Turn the voice off here.')); }
    }
    const keys = el('p', 'board-keys', 'A again · S back · D next · Esc stop');
    if (st.onVoice) keys.append(' ', button(st.quiet ? 'Voice on' : 'Voice off', 'board-voice', () => setVoice(st.quiet)));
    keys.append(' ', button('Stop', 'board-stop', () => stop('learner')));
    parts.push(keys);
    s.replaceChildren(...parts);
  }
  function light(k) {
    if (!st || k <= st.lit) return;
    st.lit = k;
    document.querySelectorAll('#guide-strip .board-say span').forEach((w, n) => w.classList.toggle('on', n <= k));
  }
  function link(src) {
    if (!src || !src.title) return el('span', '', '');
    if (!safeHref(src.url)) return el('span', 'board-src', src.title);
    const a = el('a', 'board-src', src.title);
    a.href = src.url;
    if (!src.url.startsWith('/')) { a.target = '_blank'; a.rel = 'noopener noreferrer'; }
    return a;
  }

  // --- steps and voice ----------------------------------------------------------------------------------------------
  function byLetters(text, onWord, done) {   // no voice: time the words by their letters
    let t = 0;
    text.split(/\s+/).forEach((w, k) => { st.timers.push(setTimeout(() => onWord(k), t)); t += 55 * (w.length + 1); });
    st.timers.push(setTimeout(done, t + 200));
  }
  function voice(text, onWord, done) {   // the default speak: speechSynthesis, else the words timed by their letters
    const words = text.split(/\s+/);
    if (!('speechSynthesis' in window) || !speechSynthesis.getVoices().length) return byLetters(text, onWord, done);
    speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(text);
    u.rate = st.rate;
    let got = false;
    u.onboundary = e => { if (e.name && e.name !== 'word') return; got = true; onWord(text.slice(0, e.charIndex).split(/\s+/).filter(Boolean).length); };
    u.onend = () => { if (!got) words.forEach((_, k) => onWord(k)); done(); };
    u.onerror = () => { if (st) byLetters(text, onWord, done); };
    st.utter = u;
    speechSynthesis.speak(u);
    st.timers.push(setTimeout(() => { if (!got) words.forEach((_, k) => onWord(k)); }, 1500));   // WebKit can send no word marks
    return () => speechSynthesis.cancel();
  }
  function talk(text, onWord, done) {   // the host's speak, with calls from an old step ignored, and done only once
    const gen = st.gen, live = f => (...a) => { if (st && st.gen === gen) f(...a); };
    let over = false;
    const w = live(k => onWord(Math.max(0, +k || 0))), d = live(() => { if (!over) { over = true; done(); } });
    if (st.quiet) return byLetters(text, w, d);
    try { const r = st.host.speak(text, w, d); if (typeof r === 'function') st.hush = r; }
    catch (e) { console.warn('board: speak', e); byLetters(text, w, d); }
  }
  function quiet() {
    if (!st) return;
    st.gen++;
    st.timers.forEach(clearTimeout); st.timers = [];
    if (st.hush) { try { st.hush(); } catch (e) {} st.hush = null; }
  }
  function setVoice(on) {   // Voice off stops the speech and says the step again with no sound; Voice on speaks from the next step
    if (!st) return;
    st.quiet = !on;
    try { st.onVoice(on); } catch (e) { console.warn('board: voice', e); }
    if (on) caption(); else show(st.i);
  }
  function show(i) {
    if (!st) return;
    quiet();
    i = Math.max(0, Math.min(st.board.steps.length - 1, i));
    const forward = i === st.i + 1, t = performance.now();
    st.i = i; st.stepAt = t; st.lit = -1; st.wait = false;
    for (const m of st.marks) unmount(m);
    st.video = null;
    const run = (m, live) => {   // a mark that starts: `clear` takes away the marks before it
      if (m.o.op === 'clear') { st.marks.filter(x => x.drawn && (m.o.n == null || x.step === m.o.n - 1)).forEach(unmount); return; }
      if (m.o.op === 'demo_set') return demo(m.o.set);
      if (m.o.op === 'video_at') return video(m.o);
      m.drawn = true; m.fade = forward && m.step === i - 1; m.still = !live;
      if (!place(m)) { m.t0 = performance.now(); return; }
      const now = performance.now(), first = st.first == null;
      m.t0 = live ? now : -1e9;
      if (live) { const land = fly(m, now); if (!first) m.t0 = Math.max(now, land - 120); }   // the mark draws from the tip of the pointer
      m.dirty = true; paint(m, now);
    };
    st.marks.filter(m => m.step < i).forEach(m => { if (m.o.op !== 'demo_set' && m.o.op !== 'video_at') run(m, false); });
    const step = st.board.steps[i], mine = st.marks.filter(m => m.step === i), started = new Set();
    caption();
    if (st.fast) { mine.forEach(m => run(m, false)); light(1e9); const a = mine.find(m => m.aim); if (a) fly(a, t); return; }
    // the first mark of a board draws at once, so the learner sees at once that the tutor answers
    const wordOf = (m, n) => i === 0 && n === 0 ? 0 : m.o.w ?? Math.round(n * step.say.split(/\s+/).length / Math.max(1, mine.length));
    const firstMark = () => { if (st.first == null) { st.first = performance.now(); document.dispatchEvent(new CustomEvent('board:first')); } };
    const at = k => { light(k); mine.forEach((m, n) => { if (!started.has(n) && wordOf(m, n) <= k) { started.add(n); run(m, true); if (m.drawn) firstMark(); } }); };
    at(0);
    talk(step.say, at, () => {
      light(1e9);
      mine.forEach((m, n) => { if (!started.has(n)) { started.add(n); run(m, true); } });
      if (st && st.auto && i < st.board.steps.length - 1) st.timers.push(setTimeout(() => show(i + 1), WAIT));
      else if (st && st.auto && st.streaming) st.wait = true;   // the last step so far is said: the next step that comes plays at once
    });
  }
  function marksOf(s, k) { return s.strokes.map((o, n) => ({o, step: k, seed: 1 + k * 10 + n, parts: []})); }
  function add(step) {   // see the API at the top of this file
    if (!st || !st.streaming || !step || typeof step.say !== 'string' || !Array.isArray(step.strokes)) return false;
    const k = st.board.steps.length;
    st.board.steps.push(step); st.marks.push(...marksOf(step, k));
    if ((st.fast || st.wait) && st.i === k - 1) show(k); else caption();
    return true;
  }
  function finish(board) {   // see the API at the top of this file
    if (!st || !st.streaming || !board || !Array.isArray(board.steps)) return false;
    const have = st.board.steps;
    if (board.steps.length < have.length || have.some((s, k) => s.say !== board.steps[k].say)) return false;
    board.steps.slice(have.length).forEach(add);
    Object.assign(st.board, board, {steps: have});
    st.streaming = false;
    caption();
    return true;
  }
  // The anchors of a rupaka demo, for a host that reads the page (guide.js, Leela). The ids are fixed, so that every host and the
  // engine agree: `demo` for the host; `in:<bind>` for each block whose bind is a key of spec.state; `out:<n>` for each readout,
  // caption, bars, pixels or plot block that shows, n from 1 in the depth-first order of the spec. The blocks are built in the
  // order of the spec, so the n-th block is the n-th [data-rk-type]. An id of more than 40 characters is dropped, never cut.
  const cut = (s, n) => String(s || '').replace(/\s+/g, ' ').trim().slice(0, n);
  function demoAnchors(host) {
    const s = host && host.rupaka, spec = s && s.spec;
    if (!spec) return null;
    const flat = [], walk = bs => (bs || []).forEach(b => { flat.push(b); walk(b.blocks); });
    walk(spec.blocks);
    const nodes = [...host.querySelectorAll('[data-rk-type]')], inputs = {}, anchors = [], readouts = [];
    const mark = (node, id, a) => { if (id.length <= 40) { node.dataset.guideId = id; anchors.push({id, ...a}); } };
    flat.forEach((b, n) => {
      const node = nodes[n];
      if (b.bind && Object.hasOwn(spec.state || {}, b.bind)) {
        inputs[b.bind] = {value: s.st[b.bind], label: b.label || b.bind, ...(b.min != null && {min: b.min}), ...(b.max != null && {max: b.max}), ...(b.step != null && {step: b.step})};
        if (node && seen(node)) mark(node, 'in:' + b.bind, {kind: 'input', text: `${b.label || b.bind} = ${JSON.stringify(s.st[b.bind])}`});
      } else if (node && seen(node) && /readout|caption|bars|pixels|plot/.test(b.type)) {
        const id = 'out:' + (readouts.length + 1);
        readouts.push(cut(node.textContent, 120));
        mark(node, id, {kind: 'readout', text: cut(node.textContent, 200) || b.label || b.type});
      }
    });
    const gates = flat.filter(b => b.type === 'gate').map(b => b.id);
    host.dataset.guideId = 'demo';
    anchors.unshift({id: 'demo', kind: 'demo', text: cut((spec.title || '') + '. ' + (spec.ask || ''), 300)});
    return {anchors, demo: {slug: spec.id || '', inputs, readouts, open: gates.every(g => s.st.gate && s.st.gate[g] === 'done')}};
  }
  function demo(set) { try { hooks().demo(set); } catch (e) { console.warn('board: demo', e); } }
  function rupaka(set) {   // the default demo: Rupaka.set, only when each gate is done
    const h = anchorEl('demo');
    if (!h || !window.Rupaka || !h.rupaka) return;
    const s = h.rupaka, gates = [];
    const walk = bs => (bs || []).forEach(b => { if (b.type === 'gate') gates.push(b.id); walk(b.blocks); });
    walk(s.spec.blocks);
    if (!gates.every(g => s.st.gate && s.st.gate[g] === 'done')) return;   // the gate is still closed: never show the result first
    Rupaka.set(h, set);
  }
  function seekVideo(t) {   // the YouTube player API by postMessage: the embed has enablejsapi=1, and no autoplay
    const f = document.querySelector('#guide-video iframe');
    if (!f || !f.contentWindow) return;
    const send = m => f.contentWindow.postMessage(JSON.stringify(m), 'https://www.youtube-nocookie.com');
    send({event: 'listening', id: 'guide-video'});
    send({event: 'command', func: 'seekTo', args: [t, true]});
  }
  const YT_LINK = /^https:\/\/www\.youtube\.com\/watch\?v=[A-Za-z0-9_-]{11}&t=\d+s$/;
  function video(o) {
    const f = document.querySelector('#guide-video iframe');
    seekVideo(o.t);
    if (f) f.closest('#guide-video').scrollIntoView({block: 'nearest'});
    const vid = (document.getElementById('guide-video') || {dataset: {}}).dataset.vid || '', p = el('p', 'board-quote');
    const mm = `${Math.floor(o.t / 60)}:${String(Math.floor(o.t % 60)).padStart(2, '0')}`;
    p.append(el('q', '', o.quote), ' ');
    const href = YT_LINK.test(o.link || '') ? o.link : /^[A-Za-z0-9_-]{11}$/.test(vid) ? `https://www.youtube.com/watch?v=${vid}&t=${Math.floor(o.t)}s` : '';   // the server's yt_link, else the same shape
    if (href) { const a = el('a', 'board-src', `The video at ${mm}`); a.href = href; a.target = '_blank'; a.rel = 'noopener noreferrer'; p.append(el('span', 'pill', 'video'), ' ', a); }
    st.video = p; caption();
  }

  // --- keys: A again, S back, D next, Esc stop, only while a board shows and never in a text box ----------------------
  function onKey(e) {
    if (!st || e.metaKey || e.ctrlKey || e.altKey || e.shiftKey || e.repeat) return;
    const t = e.target;
    if (t && t.closest && t.closest('textarea, input, select, [contenteditable]:not([contenteditable="false"]), .cm-editor')) return;
    const act = {KeyA: () => show(st.i), KeyS: () => show(st.i - 1), KeyD: () => show(st.i + 1), Escape: () => stop('learner')}[e.code];
    if (!act) return;
    e.preventDefault(); e.stopImmediatePropagation();
    if (e.code !== 'Escape') st.auto = e.code !== 'KeyS' && st.auto;
    act();
  }
  function stop(by) {
    quiet(); clearInterval(ticker);
    const back = st && st.refocus;
    st = null;
    if (back && back.isConnected && !document.activeElement.matches('textarea, input, select, [contenteditable]')) back.focus({preventScroll: true});
    for (const e of document.querySelectorAll('#board-host, .board-hl')) e.remove();
    const s = document.getElementById('guide-strip'); if (s) { s.hidden = true; s.replaceChildren(); }
    document.dispatchEvent(new CustomEvent('board:stop', {detail: {by: by === 'learner' ? 'learner' : ''}}));
  }

  // Play a checked board. See the API at the top of this file.
  async function play(board, {labels = {}, fast = false, quiet: q = false, auto = true, host: hk = {}, who = null, onVoice = null} = {}) {
    if (st) stop();
    const h = {...HOST};
    for (const k of ['resolve', 'speak', 'demo']) if (typeof (hk || {})[k] === 'function') h[k] = hk[k];
    if (hk && typeof hk.assets === 'string' && hk.assets) h.assets = hk.assets.endsWith('/') ? hk.assets : hk.assets + '/';
    await libs(h.assets);
    if (!board || !board.steps || !board.steps.length) { note(board && board.failed ? "The tutor's drawing failed. Say it again or type it." : 'The tutor did not answer. Try again.'); return; }
    if (board.streaming) board = {...board, steps: [...board.steps]};   // add() grows the steps of its own copy
    st = {board, labels, host: h, fast, quiet: q || fast, auto: auto && !fast, i: 0, gen: 0, lit: -1, timers: [], rate: +(localStorage.getItem('board-rate') || 1), first: null,
          t0: performance.now(), stepAt: 0, ptr: {pos: null, f: null}, streaming: !!board.streaming, wait: false,
          who: who && typeof who === 'object' ? who : null, onVoice: !fast && typeof onVoice === 'function' ? onVoice : null,
          marks: board.steps.flatMap(marksOf)};
    // An empty answer box with the focus (a check takes it when it loads) lets go of it, so A, S and D work. A box with your text
    // keeps it: then the keys type, and a click outside the box gives them to the board. Esc gives the focus back.
    const a = document.activeElement;
    if (a && a.matches && a.matches('textarea, input, select, [contenteditable]') && !a.value && !a.textContent) { st.refocus = a; a.blur(); }
    host();
    st.ptr.pos = home();
    show(0);
    if (fast) for (let k = 1; k < board.steps.length; k++) show(k);
    clock();
  }

  addEventListener('keydown', onKey, true);
  addEventListener('scroll', follow, {capture: true, passive: true});
  addEventListener('resize', follow);
  if (window.ResizeObserver) new ResizeObserver(follow).observe(document.documentElement);
  // A new page (an htmx swap of the body) takes the layer away: the board stops. A change inside the page moves the marks.
  const watch = () => new MutationObserver(ms => {
    if (!st) return;
    if (!document.getElementById('board-host')) return stop();
    if (ms.some(m => !(m.target.closest && m.target.closest('#board-host, #guide-strip, .board-hl, #board-trail')))) follow();
  }).observe(document.body, {childList: true, subtree: true});
  if (document.body) watch(); else addEventListener('DOMContentLoaded', watch);
  const view = p => [p[0] - scrollX, p[1] - scrollY];
  window.abhyasaBoard = {play, add, finish, stop: () => stop(), note, status, seekVideo, demoAnchors, next: () => st && show(st.i + 1), back: () => st && show(st.i - 1), again: () => st && show(st.i), boxOf, normTex,
                         get state() {
                           if (!st) return null;
                           const t = performance.now(), mine = st.marks.filter(m => m.step === st.i && !/^(clear|demo_set|video_at)$/.test(m.o.op));
                           return {i: st.i, steps: st.board.steps.length, tier: st.board.tier, first: st.first, streaming: st.streaming, done: !(st.ptr.now && (st.ptr.now.flying || st.ptr.now.busy)) && mine.every(m => m.drawn && (!m.ok || t - m.t0 >= (reduced() || m.still ? 150 : m.life)))};
                         },
                         get pointer() {
                           if (!st || !st.ptr.now) return null;
                           const w = st.ptr.now, a = w.rot * Math.PI / 180, r = 9.24 * w.sc;   // the tip is 9.24 px from the centre, turned with it
                           return {tip: view([w.pos[0] + r * Math.sin(a), w.pos[1] - r * Math.cos(a)]), to: w.to ? view([w.to[0] - 6, w.to[1] - 10]) : null, flying: !!w.flying};
                         }};
})();
