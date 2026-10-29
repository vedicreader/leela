/* static/rupaka.js */
/* rupaka core: a demo is a JSON spec of blocks over one small state. Named fns compute derived values.
   No network, no eval, no dependencies. Blocks and fns register with Rupaka.block and Rupaka.fn; boot.js mounts every [data-rupaka]. */
(() => {
  if (window.Rupaka && window.Rupaka.core) return;   // the bundle came in twice (an htmx swap): keep the first copy
  const R = window.Rupaka = {blocks: {}, fns: {}, core: true, version: '0.0.6', schema: 1};   // bundle() writes in rupaka.__version__
  const NS = 'http://www.w3.org/2000/svg', BAD = new Set(['__proto__', 'prototype', 'constructor']);

  function attrs(e, a) {
    for (const [k, v] of Object.entries(a || {})) {
      if (v == null || v === false) continue;
      if (k.startsWith('on') && typeof v === 'function') e.addEventListener(k.slice(2), v);
      else if (k === 'text') e.textContent = v;
      else e.setAttribute(k, v === true ? '' : v);
    }
  }
  const kids = ks => ks.flat(9).filter(k => k != null && k !== false);
  const el = (tag, a, ...ks) => { const e = document.createElement(tag); attrs(e, a); e.append(...kids(ks)); return e; };
  const sv = (tag, a, ...ks) => { const e = document.createElementNS(NS, tag); attrs(e, a); e.append(...kids(ks)); return e; };

  // A path such as `fused.0.id` reads into lists and objects. Only own keys, so `constructor` and `__proto__` give nothing.
  const get = (o, path) => String(path).split('.').reduce((x, k) => x == null || BAD.has(k) || !Object.hasOwn(Object(x), k) ? undefined : x[k], o);
  const show = (v, d) => v == null ? '' : typeof v === 'number' ? String(+v.toFixed(d ?? 4)).replace('-', '−') : Array.isArray(v) ? v.join(', ') : String(v);
  // `{path}` or `{path:2}` (two digits) take a value from the state. Text goes in with textContent, never as HTML.
  const fmt = (s, st) => String(s ?? '').replace(/\{([\w.]+)(?::(\d))?\}/g, (_, p, d) => show(get(st, p), d == null ? null : +d));
  const hide = (n, h) => { if (n instanceof SVGElement) n.style.display = h ? 'none' : ''; else n.hidden = h; };

  Object.assign(R, {el, sv, get, fmt, show, hide, block: (name, f) => { R.blocks[name] = f; }, fn: (name, f) => { R.fns[name] = f; }});
  R.label = (b, ...more) => b.label ? el('span', {class: 'rk-lbl', text: b.label}, ...more) : null;

  // The input keys are the keys of spec.state. `save(state)` runs after a change of one of them, with the value that Rupaka.state gives.
  const inputs = spec => Object.keys(spec.state || {});
  const snap = s => Object.fromEntries(inputs(s.spec).map(k => [k, structuredClone(s.st[k])]));

  function store(spec, save) {
    const st = structuredClone(spec.state || {}), subs = [], ins = new Set(inputs(spec));
    st.gate = {};
    const derive = () => (spec.derive || []).forEach(d => {
      const f = R.fns[d.fn];
      if (!f) throw new Error(`unknown fn "${d.fn}"`);
      st[d.out] = f(d, st, spec);
    });
    derive();
    const s = {st, spec, derive, get: p => get(st, p), on: f => { subs.push(f); },
               emit: k => subs.forEach(f => f(k)),
               set(k, v) {
                 const was = save && ins.has(k) ? JSON.stringify(st[k]) : null;
                 st[k] = v; derive(); s.emit(k);
                 if (was !== null && JSON.stringify(st[k]) !== was) {
                   try { save(snap(s)); } catch (e) { console.error('rupaka: save', e); }
                 }
               }};
    return s;
  }

  function build(b, ctx) {
    const f = R.blocks[b.type];
    if (!f) throw new Error(`unknown block "${b.type}"`);
    const node = f(b, ctx);
    node.classList.add('rk-b', `rk-${b.type}`);
    node.setAttribute('data-rk-type', b.type);
    if (b.after) node.setAttribute('data-rk-after', b.after);
    if (b.lock) node.setAttribute('data-rk-lock', b.lock);
    if (b.after) { const sync = () => hide(node, !ctx.live(b.after)); ctx.s.on(sync); sync(); }
    if (b.lock && !(node instanceof SVGElement)) {
      const note = el('div', {class: 'rk-note rk-locknote', text: 'Locked until you lock in your prediction.'});
      node.append(note);
      const sync = () => { const l = !ctx.live(b.lock); node.classList.toggle('rk-locked', l); note.hidden = !l; };
      ctx.s.on(sync); sync();
    }
    return node;
  }

  R.build = build;
  const CTX = new WeakMap();   // store -> ctx, for Rupaka.settle, Rupaka.open and Rupaka.options
  R.mount = (host, spec, opts) => {
    const save = opts?.save;
    if (!spec || typeof spec !== 'object' || Array.isArray(spec)) throw new Error('the spec is not an object');
    const v = spec.rupaka ?? R.schema;
    if (!(v === R.schema || v === R.schema - 1)) throw new Error(`schema ${v} is not supported; this runtime draws ${R.schema - 1} and ${R.schema}`);
    const s = store(spec, typeof save === 'function' ? save : null), root = el('div', {class: 'rk', 'data-rk': spec.id || ''});
    const ctx = {s, spec, root, live: g => !g || s.get(`gate.${g}`) === 'done'};
    ctx.build = b => build(b, ctx);
    ctx.put = (b, k, val) => { if (!ctx.live(b.lock)) return false; s.set(k, val); return true; };   // a locked control refuses
    if (spec.title) root.append(el('h3', {class: 'rk-title', text: spec.title}));
    if (spec.ask) root.append(el('p', {class: 'rk-ask', text: spec.ask}));
    root.append(...(spec.blocks || []).map(ctx.build));
    root.addEventListener('keydown', e => {   // ⌘↩ anywhere in the demo locks in the first open gate
      if (e.key === 'Enter' && (e.metaKey || e.ctrlKey) && ctx.commit) { e.preventDefault(); ctx.commit(); }
    });
    host.replaceChildren(root);
    s.emit('*');
    root.dataset.rkReady = host.dataset.rkReady = '1';
    host.rupaka = s;
    CTX.set(s, ctx);
    return s;
  };

  // The host API. A host mirrors a demo into a second copy with state and set, closes a gate there with settle and opens it again with open.
  // options maps a pick between an index and a value. None of them fires a gate, sends rk-predict, adds to st.log or calls save.
  const mounted = host => {
    const s = host?.rupaka;
    if (!s || !CTX.has(s)) throw new Error('no rupaka demo is mounted in this element');
    return s;
  };
  R.state = host => snap(mounted(host));
  R.set = (host, state) => {
    const s = mounted(host), ks = inputs(s.spec).filter(k => state && Object.hasOwn(state, k));
    if (!ks.length) return;
    for (const k of ks) s.st[k] = structuredClone(state[k]);
    s.derive(); s.emit('*');
  };
  const gateOf = (s, gate) => (CTX.get(s).gates || []).find(g => g.id === gate);
  R.options = (host, gate) => {
    const s = mounted(host), g = gateOf(s, gate);
    return g ? structuredClone(g.options()) : null;
  };
  // `opts.answer` draws the verdict when the spec of this copy has no answer. It is not written into the spec or the state.
  R.settle = (host, gate, pick, opts) => {
    const s = mounted(host), g = gateOf(s, gate);
    if (!g) return false;
    g.settle(pick, opts?.answer); s.emit('*');
    return true;
  };
  // Opens a closed gate again, as its Try another button does, with one draw. It does not move the focus. An open gate does not change.
  // A gate that waits for the host to save its prediction ('pending') is not opened, and the call gives false.
  R.open = (host, gate) => {
    const s = mounted(host), g = gateOf(s, gate);
    if (!g || s.get(`gate.${gate}`) === 'pending') return false;
    g.open();
    return true;
  };

  // The gate tells the page about each prediction; the event crosses a shadow root. It gives false when a listener called preventDefault.
  R.predict = (ctx, detail) => ctx.root.dispatchEvent(new CustomEvent('rk-predict', {bubbles: true, composed: true, cancelable: true, detail: {demo: ctx.spec.id, ...detail}}));

  R.boot = (scope = document) => scope.querySelectorAll('[data-rupaka]:not([data-rk-ready])').forEach(n => {
    const src = n.querySelector('script[type="application/json"]');
    try { R.mount(n, JSON.parse(src ? src.textContent : n.dataset.rupaka)); }
    catch (e) { console.error('rupaka:', e); n.dataset.rkReady = 'error'; n.replaceChildren(el('p', {class: 'rk-err', text: `This demo could not draw: ${e.message}`})); }
  });
})();

/* fns/expr.js */
/* expr: a formula in a tiny safe grammar: numbers, names, + - * / ^, parentheses, and the functions
   sin cos tan exp log sqrt abs min max floor ceil round. Names are state keys; `over: {x: [min, max, n]}` gives a series of {x, y}.
   There is no eval: the text is parsed to a tree, and only own state keys can be read. */
(() => {
  const FN = {sin: Math.sin, cos: Math.cos, tan: Math.tan, exp: Math.exp, log: Math.log, sqrt: Math.sqrt, abs: Math.abs,
              min: Math.min, max: Math.max, floor: Math.floor, ceil: Math.ceil, round: Math.round};
  const K = {pi: Math.PI, e: Math.E}, OPS = {'×': '*', '÷': '/', '−': '-', '**': '^'};
  const lex = src => {
    const out = [], re = /\s*(?:(\d+\.?\d*(?:[eE][+-]?\d+)?|\.\d+)|([A-Za-z_]\w*)|(\*\*|[-+*/^(),×÷−]))/y, s = String(src);
    let i = 0;
    while (i < s.length) {
      if (!s.slice(i).trim()) break;
      re.lastIndex = i;
      const m = re.exec(s);
      if (!m) throw new Error(`expr: "${s}" has a bad character at ${i}`);
      i = re.lastIndex;
      out.push(m[1] != null ? {t: 'n', v: +m[1]} : m[2] != null ? {t: 'id', v: m[2]} : {t: 'op', v: OPS[m[3]] || m[3]});
    }
    return out;
  };
  const parse = src => {
    const ts = lex(src); let p = 0;
    const peek = () => ts[p], eat = v => { const t = ts[p]; if (!t || (v && t.v !== v)) throw new Error(`expr: "${src}" needs ${v || 'more'}`); p++; return t; };
    const binl = (next, ops) => () => { let a = next(); while (peek()?.t === 'op' && ops.includes(peek().v)) { const o = eat().v, l = a, r = next(); a = o === '+' ? e => l(e) + r(e) : o === '-' ? e => l(e) - r(e) : o === '*' ? e => l(e) * r(e) : e => l(e) / r(e); } return a; };
    const atom = () => {
      const t = eat();
      if (t.t === 'n') return () => t.v;
      if (t.t === 'op' && t.v === '(') { const a = add(); eat(')'); return a; }
      if (t.t === 'id') {
        if (t.v.startsWith('_') || ['constructor', 'prototype'].includes(t.v)) throw new Error(`expr: the name "${t.v}" is not allowed`);
        if (peek()?.v === '(') {
          if (!Object.hasOwn(FN, t.v)) throw new Error(`expr: no function "${t.v}"`);
          eat('('); const args = [add()]; while (peek()?.v === ',') { eat(','); args.push(add()); } eat(')');
          const f = FN[t.v]; return e => f(...args.map(a => a(e)));
        }
        if (Object.hasOwn(K, t.v)) return () => K[t.v];
        return e => { if (!Object.hasOwn(e, t.v)) throw new Error(`expr: no value "${t.v}"`); return +e[t.v]; };
      }
      throw new Error(`expr: "${src}" has an unexpected "${t.v}"`);
    };
    const pow = () => { const a = atom(); if (peek()?.v === '^') { eat('^'); const b = unary(); return e => a(e) ** b(e); } return a; };
    const unary = () => { if (peek()?.v === '-') { eat('-'); const a = unary(); return e => -a(e); } if (peek()?.v === '+') { eat('+'); return unary(); } return pow(); };
    const mul = binl(unary, ['*', '/']), add = binl(mul, ['+', '-']);
    const f = add();
    if (p < ts.length) throw new Error(`expr: "${src}" has extra text at "${ts[p].v}"`);
    return f;
  };
  const cache = {};
  Rupaka.expr = parse;
  Rupaka.fn('expr', (d, st) => {
    const f = cache[d.expr] ||= parse(d.expr);
    if (!d.over) return f(st);
    const [name, [lo, hi, n = 101]] = Object.entries(d.over)[0];
    return Array.from({length: n}, (_, i) => { const x = lo + (hi - lo) * i / (n - 1); return {x, y: f({...st, [name]: x})}; });
  });
})();

/* fns/helpers.js */
/* Small list helpers: ids, pick, sort, and fmt (a template into a string). */
Rupaka.fn('ids', (d, st) => (Rupaka.get(st, d.from) || []).map(x => x && typeof x === 'object' ? x.id : x));
Rupaka.fn('pick', (d, st) => (Rupaka.get(st, d.from) || []).map(x => x == null ? x : x[d.field]));
Rupaka.fn('sort', (d, st) => {
  const v = x => d.by ? (x || {})[d.by] : x;
  return [...(Rupaka.get(st, d.from) || [])].sort((a, b) => (v(a) > v(b) ? 1 : v(a) < v(b) ? -1 : 0) * (d.desc ? -1 : 1));
});
Rupaka.fn('fmt', (d, st) => Rupaka.fmt(d.text, st));

/* fns/lookup.js */
/* lookup: the row of a table for a key. A whole number picks by position; any other value picks the row whose `by` field (default id) matches. */
Rupaka.fn('lookup', (d, st, spec) => {
  const rows = (spec.tables || {})[d.table];
  if (!rows) throw new Error(`lookup: no table "${d.table}"`);
  const v = Rupaka.get(st, d.key), by = d.by || 'id';
  if (!d.by && Number.isInteger(v)) return rows[((v % rows.length) + rows.length) % rows.length];
  return rows.find(r => String(r[by]) === String(v)) ?? null;
});

/* fns/rrf.js */
/* rrf: reciprocal rank fusion of the ranked lists named in `in`, with k from the key `k` (or a number). Ranks start at 1. */
Rupaka.fn('rrf', (d, st) => {
  const k = +(typeof d.k === 'number' ? d.k : st[d.k]), acc = {};
  d.in.forEach((name, j) => (st[name] || []).forEach((id, i) => { (acc[id] ||= {id, value: 0, parts: d.in.map(() => 0)}).parts[j] += 1 / (k + i + 1); }));
  return Object.values(acc).map(x => ({...x, value: x.parts.reduce((a, b) => a + b, 0)})).sort((a, b) => b.value - a.value || a.id.localeCompare(b.id));
});

/* fns/rules.js */
/* rules: the first table row whose `when` lists hold the inputs wins. `{x}` in `out` takes the state value x.
   `alts` are what the other rows give: plausible wrong answers for a gate, in a stable order. */
Rupaka.fn('rules', (d, st, spec) => {
  const rows = (spec.tables || {})[d.table];
  if (!rows) throw new Error(`rules: no table "${d.table}"`);
  const sub = t => String(t).replace(/\{(\w+)\}/g, (_, k) => st[k] ?? '');
  const hit = rows.find(r => Object.entries(r.when || {}).every(([k, vs]) => (Array.isArray(vs) ? vs : [vs]).includes(st[k]))) || {out: '?', name: 'no rule'};
  const out = sub(hit.out), alts = [out];
  for (const r of rows) { const a = sub(r.out); if (!alts.includes(a)) alts.push(a); if (alts.length >= (d.alts || 4)) break; }
  const seed = [...(d.in || []).map(k => st[k]).join('|')].reduce((h, c) => (h * 31 + c.charCodeAt(0)) | 0, 7);
  const rank = a => [...a].reduce((h, c) => (h * 33 + c.charCodeAt(0) + seed) | 0, 5) & 1023;
  alts.sort((x, y) => rank(x) - rank(y) || x.localeCompare(y));
  return {...hit, out, alts};
});

/* fns/softmax.js */
/* softmax: shares from scores, exp(x / t) / sum, with temperature t (a key or a number). A row of a grid works too. */
Rupaka.fn('softmax', (d, st) => {
  let xs = Rupaka.get(st, d.in) || [];
  if (Array.isArray(xs[0])) xs = xs[d.row || 0];
  const t = Math.max(1e-6, +(typeof d.t === 'number' ? d.t : d.t == null ? 1 : st[d.t])), mx = Math.max(...xs);
  const es = xs.map(x => Math.exp((x - mx) / t)), z = es.reduce((a, b) => a + b, 0);
  const labels = Array.isArray(d.labels) ? d.labels : d.labels ? Rupaka.get(st, d.labels) : null;
  const out = es.map((e, i) => ({id: String(labels ? labels[i] : i), value: e / z}));
  return d.sort ? out.sort((a, b) => b.value - a.value || a.id.localeCompare(b.id)) : out;
});

/* blocks/axis/axis.js */
/* axis: a number line (no y) or x/y axes with ticks. Child blocks (point, plot) draw on its shared scale. */
(() => {
  let seq = 0;
  const nice = (lo, hi, want) => { const raw = (hi - lo) / want, p = 10 ** Math.floor(Math.log10(raw)), m = raw / p;
    return (m < 1.5 ? 1 : m < 3 ? 2 : m < 7 ? 5 : 10) * p; };
  const ticks = (lo, hi, st) => { const out = []; for (let v = Math.ceil(lo / st - 1e-9) * st; v <= hi + 1e-9; v += st) out.push(+v.toFixed(10)); return out; };
  Rupaka.block('axis', (b, ctx) => {
    const {el, sv, show} = Rupaka, [x0, x1] = b.x || [-5, 5], line = !b.y, [y0, y1] = b.y || [0, 1];
    const W = 600, H = line ? 80 : (b.height || 360), L = line ? 16 : 40, Rm = 16, T = line ? 30 : 12, B = line ? 30 : 28;
    const X = v => L + (v - x0) / (x1 - x0) * (W - L - Rm), Y = v => line ? T : T + (y1 - v) / (y1 - y0) * (H - T - B);
    const plane = {X, Y, line, W, H, x: [x0, x1], y: [y0, y1], invX: px => x0 + (px - L) / (W - L - Rm) * (x1 - x0), invY: py => y1 - (py - T) / (H - T - B) * (y1 - y0)};
    const id = `rk-clip-${++seq}`;
    const svg = sv('svg', {viewBox: `0 0 ${W} ${H}`, role: 'group', 'aria-label': b.label || 'axes'});
    plane.svg = svg; plane.clip = `url(#${id})`;
    const g = sv('g', {class: 'grid'});
    const xs = ticks(x0, x1, b.xstep || nice(x0, x1, 10)), ys = line ? [] : ticks(y0, y1, b.ystep || nice(y0, y1, 8));
    const ax = line ? T : Y(Math.min(y1, Math.max(y0, 0))), ay = X(Math.min(x1, Math.max(x0, 0)));
    xs.forEach(v => { g.append(sv('line', {class: v === 0 && !line ? 'zero' : 'hair', x1: X(v), x2: X(v), y1: line ? T - 5 : T, y2: line ? T + 5 : H - B}),
      sv('text', {class: 'num', x: X(v), y: line ? T + 22 : H - B + 18, 'text-anchor': 'middle', text: show(v, 3)})); });
    ys.forEach(v => { g.append(sv('line', {class: v === 0 ? 'zero' : 'hair', x1: L, x2: W - Rm, y1: Y(v), y2: Y(v)}),
      sv('text', {class: 'num', x: L - 6, y: Y(v) + 4, 'text-anchor': 'end', text: show(v, 3)})); });
    g.append(sv('line', {class: 'main', x1: L, x2: W - Rm, y1: ax, y2: ax}));
    if (!line) g.append(sv('line', {class: 'main', x1: ay, x2: ay, y1: T, y2: H - B}));
    if (b.xlabel) g.append(sv('text', {class: 'axl', x: W - Rm, y: line ? T - 10 : ax - 8, 'text-anchor': 'end', text: b.xlabel}));
    if (b.ylabel && !line) g.append(sv('text', {class: 'axl', x: ay + 8, y: T + 12, text: b.ylabel}));
    svg.append(sv('defs', {}, sv('clipPath', {id}, sv('rect', {x: L, y: line ? 0 : T, width: W - L - Rm, height: line ? H : H - T - B}))), g);
    const c2 = Object.assign(Object.create(ctx), {plane});
    svg.append(...(b.blocks || []).map(k => Rupaka.build(k, c2)));
    return el('div', {}, Rupaka.label(b), svg);
  });
})();

/* blocks/bars/bars.js */
/* bars: horizontal bars from a derived list of {id, value, parts} or of numbers. Rows keep their element, so a new order slides. */
Rupaka.block('bars', (b, ctx) => {
  const {el, sv, show} = Rupaka, H = 30, W = 600, L = b.gutter ?? 48, names = b.items || {};
  const svg = sv('svg', {role: 'img', 'aria-label': b.label || b.bind}), keyed = {};
  const key = b.parts ? el('div', {class: 'key'}, b.parts.map((p, i) => el('span', {}, el('i', {class: `p${i ? 1 : 0}`}), p))) : null;
  const rows = () => (ctx.s.get(b.bind) || []).map((x, i) => typeof x === 'number' ? {id: String(i), value: x} : x);
  ctx.s.on(() => {
    const xs = rows(), mx = b.max ?? Math.max(...xs.map(x => x.value), 1e-9), sc = (W - L - 70) / mx;
    svg.setAttribute('viewBox', `0 0 ${W} ${H * xs.length || H}`);
    xs.forEach((x, i) => {
      let g = keyed[x.id];
      if (!g) { g = keyed[x.id] = sv('g', {class: 'bar'}, sv('text', {class: 't', x: 0, y: H / 2 + 5, text: names[x.id] || x.id}),
                  sv('rect', {class: 'p0', x: L, y: 7, height: H - 14}), sv('rect', {class: 'p1', y: 7, height: H - 14}), sv('text', {class: 'v', y: H / 2 + 5})); svg.append(g); }
      g.style.display = '';
      g.style.transform = `translate(0px, ${i * H}px)`;
      const [a, c] = x.parts || [x.value, 0], [r0, r1] = g.querySelectorAll('rect'), v = g.querySelector('text.v');
      r0.style.width = `${Math.max(0, a * sc)}px`; r1.style.x = `${L + a * sc}px`; r1.style.width = `${Math.max(0, c * sc)}px`;
      v.setAttribute('x', L + Math.max(0, (a + c) * sc) + 6); v.textContent = show(x.value, b.digits ?? 4);
    });
    Object.keys(keyed).forEach(id => { if (!xs.some(x => x.id === id)) keyed[id].style.display = 'none'; });
    svg.setAttribute('aria-label', `${b.label || b.bind}: ${xs.map(x => `${names[x.id] || x.id} ${show(x.value, b.digits ?? 4)}`).join(', ')}`);
  });
  return el('div', {}, Rupaka.label(b), svg, key);
});

/* blocks/caption/caption.js */
/* caption: the explain text. Only **bold** and {path} are special; all text goes in with textContent, so no HTML runs. */
Rupaka.block('caption', (b, ctx) => {
  const {el, fmt} = Rupaka, p = el('p');
  ctx.s.on(() => p.replaceChildren(...String(b.text ?? '').split('**').map((t, i) => i % 2 ? el('b', {text: fmt(t, ctx.s.st)}) : fmt(t, ctx.s.st))));
  return el('div', {}, Rupaka.label(b), p);
});

/* blocks/choice/choice.js */
/* choice: a row of options with one picked. ←/→ or A/D move, 1-9 pick. */
Rupaka.block('choice', (b, ctx) => {
  const {el, show} = Rupaka, s = ctx.s, os = b.options || [];
  const box = el('div', {class: 'opts', role: 'radiogroup', 'aria-label': b.label || b.bind});
  const btns = os.map((o, i) => el('button', {type: 'button', role: 'radio', onclick: () => ctx.put(b, b.bind, o)}, show(o), i < 9 ? el('kbd', {text: i + 1}) : null));
  box.append(...btns);
  box.addEventListener('keydown', e => {
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    const k = e.key.toLowerCase(), i = os.indexOf(s.get(b.bind));
    const j = ['arrowright', 'd'].includes(k) ? i + 1 : ['arrowleft', 'a'].includes(k) ? i - 1 : /^[1-9]$/.test(k) ? +k - 1 : null;
    if (j == null || j < 0 || j >= os.length) return;
    e.preventDefault();
    if (ctx.put(b, b.bind, os[j])) btns[j].focus();
  });
  s.on(() => {
    const v = s.get(b.bind), at = Math.max(0, os.indexOf(v));
    btns.forEach((x, i) => { x.setAttribute('aria-checked', String(os[i] === v)); x.tabIndex = i === at ? 0 : -1; x.disabled = !ctx.live(b.lock); });
  });
  return el('div', {}, Rupaka.label(b), box);
});

/* blocks/gate/gate.js */
/* gate: predict, then reveal. Keys 1-9 pick, ←/→ or A/D move, ⌘↩ locks in. Blocks with `after: id` wait for it.
   The verdict names the inputs it was for (`context`), because the inputs can change after the reveal.
   A host that saves the prediction calls preventDefault on rk-predict. The gate then waits ('pending') until the host calls
   detail.settle(saved, message): true reveals, false opens the gate again and shows the message as text. Only the first call counts.
   Rupaka.settle(host, id, pick, {answer}) closes the gate from the host: no rk-predict, no log. A null pick reveals with no verdict.
   `answer` draws the verdict when the spec has none (a copy for a room has its answers taken out); it is never stored.
   With no answer at all, the gate reveals with no verdict. Rupaka.options(host, id) reads the options as opts() gives them.
   Rupaka.open(host, id) opens a closed gate again with reopen(), as Try another does, but it does not move the focus. */
Rupaka.block('gate', (b, ctx) => {
  const {el, fmt, show} = Rupaka, s = ctx.s, id = b.id;
  s.st.gate[id] = 'open';
  let picked = null, said = '', seen = '';
  const opts = () => Array.isArray(b.options) ? b.options : (s.get(b.options.from) || []);
  const ans = (a = b.answer) => a && typeof a === 'object' ? a.is : s.get(a);   // {is: value} or a path in the state
  const done = () => s.get(`gate.${id}`) === 'done', open = () => s.get(`gate.${id}`) === 'open';
  const q = el('p', {class: 'q', id: `rk-${ctx.spec.id || 'd'}-${id}-q`});
  const box = el('div', {class: 'opts', role: 'radiogroup', 'aria-labelledby': q.id});
  const why = b.why ? el('textarea', {rows: 1, placeholder: b.why, 'aria-label': b.why}) : null;
  const go = el('button', {class: 'go', type: 'button', disabled: true}, 'Lock in', el('kbd', {text: '⌘↩'}));
  const again = el('button', {type: 'button', hidden: true}, 'Try another');
  const verdict = el('p', {class: 'verdict', 'aria-live': 'polite', hidden: true});
  const stale = el('span', {class: 'stale', hidden: true, text: ' The demo now shows other inputs.'});
  const note = el('p', {class: 'note', 'aria-live': 'polite', hidden: true});
  const say = t => { note.textContent = t; note.hidden = !t; };
  const pick = o => { if (!open()) return; picked = o; paint(); };
  function paint() {
    const os = opts(), k = JSON.stringify(os);
    if (k !== seen) {
      seen = k;
      box.replaceChildren(...os.map((o, i) => el('button', {type: 'button', role: 'radio', onclick: () => pick(o)}, show(o), i < 9 ? el('kbd', {text: i + 1}) : null)));
    }
    [...box.children].forEach((x, i) => { x.setAttribute('aria-checked', String(os[i] === picked)); x.disabled = !open(); x.tabIndex = os[i] === picked || (picked == null && i === 0) ? 0 : -1; });
    go.disabled = picked == null || !open(); go.hidden = done(); again.hidden = !(done() && b.again); verdict.hidden = !done() || !verdict.childNodes.length;
    stale.hidden = !done() || !b.context || fmt(b.context, s.st) === said;
  }
  const tell = (c, ok, a) => {
    said = c; say('');
    verdict.replaceChildren(said ? `${said} ` : '', 'You said ', el('b', {class: ok ? 'ok' : 'no', text: show(picked)}), '. ',
      ok ? el('span', {class: 'ok', text: 'That is right.'}) : el('span', {}, 'It is ', el('b', {class: 'ok', text: show(a)}), '.'), stale);
  };
  function commit() {
    if (picked == null || !open()) return false;
    const a = ans(), ok = String(picked) === String(a), c = b.context ? fmt(b.context, s.st) : '';
    const detail = {gate: id, picked, ans: a, ok, why: why ? why.value : '', context: c};
    let settled = false;
    const settle = (saved, message = '') => {
      if (settled) return;
      settled = true;
      if (!saved) { s.st.gate[id] = 'open'; say(String(message ?? '')); paint(); return; }
      tell(c, ok, a);
      s.st.gate[id] = 'done';
      s.st.log = [...(s.st.log || []), detail];
      s.set('_', (s.st._ || 0) + 1);
    };
    s.st.gate[id] = 'pending'; say(''); paint();
    if (Rupaka.predict(ctx, {...detail, settle})) settle(true);
    else if (!settled) say('Saving your prediction.');
    return true;
  }
  go.onclick = commit;
  // Open a closed gate again: no pick, no reason, no verdict. One draw hides the blocks that wait for the gate. An open gate does not change.
  const reopen = () => {
    if (!done()) return;
    picked = null; said = ''; if (why) why.value = ''; verdict.replaceChildren();
    s.st.gate[id] = 'open'; s.set('_', (s.st._ || 0) + 1);
  };
  again.onclick = () => { reopen(); box.querySelector('button')?.focus(); };   // only the learner's button moves the focus
  // The host closes the gate. The caller (Rupaka.settle) draws once after it. The answer of the spec comes first.
  const settle = (p, answer) => {
    const w = b.answer ?? answer;
    if (p != null) picked = p;
    if (p == null || w == null) { said = ''; say(''); verdict.replaceChildren(); }
    else { const a = ans(w); tell(b.context ? fmt(b.context, s.st) : '', String(p) === String(a), a); }
    s.st.gate[id] = 'done';
  };
  (ctx.gates ||= []).push({id, commit, done, settle, open: reopen, options: opts});
  ctx.commit ||= () => { const g = ctx.gates.find(g => !g.done()); return g ? g.commit() : false; };
  const root = el('div', {}, q, box, why, verdict, note, el('div', {class: 'acts'}, go, again));
  root.addEventListener('keydown', e => {
    if (e.target.tagName === 'TEXTAREA' || !open() || e.metaKey || e.ctrlKey || e.altKey) return;
    const os = opts(), k = e.key.toLowerCase(), i = os.indexOf(picked);
    let j = /^[1-9]$/.test(k) ? +k - 1 : null;
    if (j == null && e.target.closest('.opts')) j = ['arrowright', 'arrowdown', 'd'].includes(k) ? i + 1 : ['arrowleft', 'arrowup', 'a'].includes(k) ? Math.max(0, i - 1) : null;
    if (j == null || j < 0 || j >= os.length) return;
    e.preventDefault(); pick(os[j]);
    if (e.target.closest('.opts')) box.children[j].focus();
  });
  s.on(() => {
    q.textContent = fmt(b.prompt, s.st);
    if (!Array.isArray(b.options) && open() && !opts().some(o => o === picked)) picked = null;
    paint();
  });
  return root;
});

/* blocks/grid/grid.js */
/* grid: a heatmap of a list of numbers or a list of rows. Click a cell to focus it; arrows or WASD move;
   + or E raise the cell by one step, − or Q lower it. The ramp mixes --rk-acc into the page colour. */
Rupaka.block('grid', (b, ctx) => {
  const {el, sv, show} = Rupaka, s = ctx.s, CW = b.cell || 64, CH = 40, step = b.step ?? 1;
  const mat = () => { const v = s.get(b.bind) || []; return Array.isArray(v[0]) ? v : [v]; };
  const flat = !Array.isArray((s.get(b.bind) || [])[0]);
  const m0 = mat(), nr = m0.length, nc = m0[0]?.length || 0, L = b.rows ? (b.gutter ?? 70) : 0, T = b.cols ? 24 : 0;
  const svg = sv('svg', {viewBox: `0 0 ${L + nc * CW + 2} ${T + nr * CH + 2}`, tabindex: 0, role: 'grid', 'aria-label': b.label || b.bind, style: `width: ${L + nc * CW + 2}px`});
  const say = el('div', {class: 'rk-sr', 'aria-live': 'polite'});
  let fi = 0, fj = 0;
  const cells = m0.map((row, i) => row.map((_, j) => { const g = sv('g', {class: 'cell', transform: `translate(${L + j * CW + 1} ${T + i * CH + 1})`},
    sv('rect', {width: CW - 2, height: CH - 2, rx: 2}), sv('text', {x: CW / 2 - 1, y: CH / 2 + 4, 'text-anchor': 'middle'}));
    g.addEventListener('pointerdown', () => { fi = i; fj = j; paint(); svg.focus({preventScroll: true}); }); return g; }));
  (b.cols || []).forEach((c, j) => svg.append(sv('text', {class: 'hd', x: L + j * CW + CW / 2, y: 16, 'text-anchor': 'middle', text: c})));
  (b.rows || []).forEach((r, i) => svg.append(sv('text', {class: 'hd', x: L - 8, y: T + i * CH + CH / 2 + 5, 'text-anchor': 'end', text: r})));
  const cur = sv('rect', {class: 'cur', width: CW - 2, height: CH - 2, rx: 2});
  svg.append(...cells.flat(), cur);
  const change = d => {
    if (!ctx.live(b.lock)) return;
    const m = mat().map(r => r.slice()), lo = b.min ?? -Infinity, hi = b.max ?? Infinity;
    m[fi][fj] = +Math.min(hi, Math.max(lo, m[fi][fj] + d)).toFixed(6);
    ctx.put(b, b.bind, flat ? m[0] : m);
  };
  svg.addEventListener('keydown', e => {
    const k = e.key.toLowerCase(), d = step * (e.shiftKey && !['+', '-', '_', '='].includes(k) ? 10 : 1);
    const mv = {arrowup: [-1, 0], w: [-1, 0], arrowdown: [1, 0], s: [1, 0], arrowleft: [0, -1], a: [0, -1], arrowright: [0, 1], d: [0, 1]}[k];
    if (mv) { e.preventDefault(); fi = Math.max(0, Math.min(nr - 1, fi + mv[0])); fj = Math.max(0, Math.min(nc - 1, fj + mv[1])); paint(); return; }
    if (['+', '=', 'e'].includes(k)) { e.preventDefault(); change(d); }
    else if (['-', '_', 'q', '−'].includes(k)) { e.preventDefault(); change(-d); }
  });
  function paint() {
    const m = mat(), vs = m.flat(), lo = b.lo ?? Math.min(...vs), hi = b.hi ?? Math.max(...vs);
    m.forEach((row, i) => row.forEach((v, j) => {
      const g = cells[i]?.[j]; if (!g) return;
      const pc = hi > lo ? 6 + Math.round((v - lo) / (hi - lo) * 28) : 6;
      g.firstChild.style.fill = `color-mix(in srgb, var(--rk-acc) ${pc}%, var(--rk-bg))`;
      g.lastChild.textContent = show(v, b.digits ?? 2);
    }));
    cur.setAttribute('x', L + fj * CW + 1); cur.setAttribute('y', T + fi * CH + 1);
    const lbl = [b.rows?.[fi], b.cols?.[fj]].filter(Boolean).join(', ') || `row ${fi + 1}, column ${fj + 1}`;
    svg.setAttribute('aria-valuetext', `${lbl}: ${show(m[fi][fj], b.digits ?? 2)}`); say.textContent = svg.getAttribute('aria-valuetext');
  }
  s.on(paint);
  return el('div', {}, Rupaka.label(b), svg, say, b.note ? el('div', {class: 'rk-note', text: b.note}) : null);
});

/* blocks/plot/plot.js */
/* plot: a line (or dots) through a derived series of {x, y}, on its axis. */
Rupaka.block('plot', (b, ctx) => {
  const {sv} = Rupaka, P = ctx.plane;
  if (!P) throw new Error('a plot must be inside an axis');
  const path = sv('path', {class: 'ln', 'clip-path': P.clip}), dots = sv('g', {class: 'dots', 'clip-path': P.clip});
  const g = sv('g', {role: 'img', 'aria-label': b.label || b.series}, path, dots);
  ctx.s.on(() => {
    const xs = (ctx.s.get(b.series) || []).map(p => Array.isArray(p) ? {x: p[0], y: p[1]} : p);
    let d = '', pen = false;
    for (const p of xs) {
      const ok = Number.isFinite(p.y) && Math.abs(P.Y(p.y)) < 1e5;
      if (ok) { d += `${pen ? 'L' : 'M'}${P.X(p.x).toFixed(2)} ${P.Y(p.y).toFixed(2)}`; pen = true; } else pen = false;
    }
    path.setAttribute('d', b.dots ? '' : d);
    dots.replaceChildren(...(b.dots ? xs.filter(p => Number.isFinite(p.y)).map(p => sv('circle', {cx: P.X(p.x), cy: P.Y(p.y), r: 3.5})) : []));
  });
  return g;
});

/* blocks/point/point.js */
/* point: a dot on its axis. It drags when its key is a state input; a point on a derived value only shows it.
   Arrows or WASD move one step; ⇧ moves ten. On a number line ↑/↓ move it too. */
Rupaka.block('point', (b, ctx) => {
  const {sv, show} = Rupaka, s = ctx.s, P = ctx.plane;
  if (!P) throw new Error('a point must be inside an axis');
  const kx = b.bind || b.x, ky = b.y, st = ctx.spec.state || {}, step = b.step ?? 1;
  const drag = b.drag ?? (Object.hasOwn(st, kx) && (!ky || Object.hasOwn(st, ky)));
  const dot = sv('circle', {class: 'dot', r: 7}), ring = sv('circle', {class: 'halo', r: 14}), txt = sv('text', {class: 'pl', 'text-anchor': 'middle'});
  const g = sv('g', drag ? {tabindex: 0, role: 'slider', 'aria-label': b.label || kx} : {role: 'img'}, ring, dot, txt);
  if (drag) g.classList.add('drag');
  const snap = (v, [lo, hi]) => +Math.min(hi, Math.max(lo, Math.round(v / step) * step)).toFixed(6);
  const put = (x, y) => { if (x !== s.get(kx)) ctx.put(b, kx, x); if (ky && y !== s.get(ky)) ctx.put(b, ky, y); };
  const at = e => { const pt = P.svg.createSVGPoint(); pt.x = e.clientX; pt.y = e.clientY; return pt.matrixTransform(P.svg.getScreenCTM().inverse()); };
  if (drag) {
    g.addEventListener('pointerdown', e => { if (!ctx.live(b.lock)) return; e.stopPropagation(); g.setPointerCapture(e.pointerId); g.classList.add('held'); });
    g.addEventListener('pointermove', e => { if (!g.hasPointerCapture(e.pointerId)) return; const p = at(e); put(snap(P.invX(p.x), P.x), ky ? snap(P.invY(p.y), P.y) : null); });
    g.addEventListener('pointerup', () => g.classList.remove('held'));
    g.addEventListener('keydown', e => {
      const k = e.key.toLowerCase(), d = step * (e.shiftKey ? 10 : 1);
      const dx = ['arrowright', 'd'].includes(k) ? d : ['arrowleft', 'a'].includes(k) ? -d : 0;
      const dy = ['arrowup', 'w'].includes(k) ? d : ['arrowdown', 's'].includes(k) ? -d : 0;
      if (!dx && !dy) return;
      e.preventDefault();
      if (ky) put(snap(+s.get(kx) + dx, P.x), snap(+s.get(ky) + dy, P.y));
      else put(snap(+s.get(kx) + (dx || dy), P.x));
    });
  }
  s.on(() => {
    const x = +s.get(kx), y = ky ? +s.get(ky) : null, cx = P.X(x), cy = ky ? P.Y(y) : P.Y(0);
    [dot, ring].forEach(c => { c.setAttribute('cx', cx); c.setAttribute('cy', cy); });
    txt.setAttribute('x', cx); txt.setAttribute('y', cy - 14); txt.textContent = b.label ? `${b.label}${b.show === false ? '' : ` ${show(x, 2)}${ky ? `, ${show(y, 2)}` : ''}`}` : '';
    g.style.visibility = Number.isFinite(x) && (!ky || Number.isFinite(y)) ? '' : 'hidden';
    if (drag) { g.setAttribute('aria-valuenow', x); g.setAttribute('aria-valuetext', ky ? `x ${show(x, 2)}, y ${show(y, 2)}` : show(x, 2)); }
  });
  return g;
});

/* blocks/ranklist/ranklist.js */
/* ranklist: an ordered list of ids. Drag a row, or focus it (↑/↓) and move it with ⌥↑/⌥↓ or W/S. `lock` keeps it still until that gate. */
Rupaka.block('ranklist', (b, ctx) => {
  const {el, sv} = Rupaka, s = ctx.s, H = 36, W = 300, names = b.items || {};
  const order = () => s.get(b.bind) || [];
  const svg = sv('svg', {viewBox: `0 0 ${W} ${H * order().length + 4}`, role: 'list', 'aria-label': b.label || b.bind});
  const rows = Object.fromEntries(order().map(id => [id, sv('g', {class: 'row', tabindex: 0, role: 'listitem', 'data-id': id},
    sv('rect', {class: 'hit', x: 0, y: 0, width: W, height: H, rx: 3}),
    sv('text', {class: 'n', x: 8, y: H / 2 + 5}), sv('text', {class: 't', x: 34, y: H / 2 + 5, text: names[id] || id}),
    sv('text', {class: 'grip', x: W - 18, y: H / 2 + 5, text: '⋮⋮'}), sv('line', {x1: 0, x2: W, y1: H, y2: H}))]));
  svg.append(...Object.values(rows));
  const live = () => ctx.live(b.lock);
  const move = (id, j) => {
    const o = order().filter(x => x !== id);
    o.splice(Math.max(0, Math.min(o.length, j)), 0, id);
    if (o.join() !== order().join()) ctx.put(b, b.bind, o);
  };
  let drag = null;
  svg.addEventListener('pointerdown', e => { const g = e.target.closest('.row'); if (!g || !live()) return;
    e.preventDefault();   // no text selection or native drag of the row's text: either one cancels the pointer
    drag = {g, id: g.dataset.id}; svg.setPointerCapture(e.pointerId); g.classList.add('drag'); });
  svg.addEventListener('pointermove', e => { if (!drag) return; const p = svg.getBoundingClientRect(); move(drag.id, Math.floor((e.clientY - p.top) / p.width * W / H)); });
  svg.addEventListener('pointerup', () => { if (drag) drag.g.classList.remove('drag'); drag = null; });
  svg.addEventListener('keydown', e => {
    const g = e.target.closest('.row'); if (!g) return;
    const o = order(), i = o.indexOf(g.dataset.id), k = e.key.toLowerCase();
    const up = k === 'arrowup' || k === 'w', dn = k === 'arrowdown' || k === 's';
    if (!up && !dn) return;
    e.preventDefault();
    if (e.altKey || k === 'w' || k === 's') { if (live()) { move(g.dataset.id, i + (up ? -1 : 1)); g.focus(); } }
    else rows[o[Math.max(0, Math.min(o.length - 1, i + (up ? -1 : 1)))]].focus();
  });
  const note = el('div', {class: 'rk-note'});
  const wrap = el('div', {}, Rupaka.label(b), svg, note);
  s.on(() => {
    order().forEach((id, i) => { rows[id].setAttribute('transform', `translate(0 ${i * H})`); rows[id].querySelector('.n').textContent = i + 1;
      rows[id].setAttribute('aria-label', `${i + 1}: ${names[id] || id}`); });
    wrap.classList.toggle('live', live());
    note.textContent = b.hint || 'Drag a row, or focus it and press ⌥↑ ⌥↓ (or W S).';
    note.hidden = !live();
  });
  return wrap;
});

/* blocks/readout/readout.js */
/* readout: one large line from a template, for example "{a} + {b} → {join.out}". */
Rupaka.block('readout', (b, ctx) => {
  const {el, fmt} = Rupaka, d = el('div', {class: 'big', 'aria-live': 'polite'});
  ctx.s.on(() => { d.textContent = fmt(b.text, ctx.s.st); });
  return el('div', {}, Rupaka.label(b), d);
});

/* blocks/row/row.js */
/* row: child blocks side by side; they wrap on a narrow page. */
Rupaka.block('row', (b, ctx) => Rupaka.el('div', {}, (b.blocks || []).map(ctx.build)));

/* blocks/slider/slider.js */
/* slider: a number in a range. ←/→ (native) or A/D move one step; ⇧A/⇧D move ten. */
Rupaka.block('slider', (b, ctx) => {
  const {el, fmt, show} = Rupaka, s = ctx.s, step = b.step ?? 1, lo = b.min ?? 0, hi = b.max ?? 100;
  const inp = el('input', {type: 'range', min: lo, max: hi, step, 'aria-label': b.label || b.bind});
  const out = el('output');
  const set = v => { if (!ctx.put(b, b.bind, +Math.min(hi, Math.max(lo, v)).toFixed(6))) inp.value = s.get(b.bind); };
  inp.addEventListener('input', () => set(+inp.value));
  inp.addEventListener('keydown', e => {
    const k = e.key.toLowerCase();
    if (k !== 'a' && k !== 'd') return;
    e.preventDefault(); set(+s.get(b.bind) + (k === 'd' ? 1 : -1) * step * (e.shiftKey ? 10 : 1));
  });
  ctx.s.on(() => {
    const v = s.get(b.bind), t = show(v, b.digits);
    inp.value = v; out.textContent = t; inp.disabled = !ctx.live(b.lock);
    inp.setAttribute('aria-valuetext', b.valuetext ? fmt(b.valuetext, s.st) : `${b.label || b.bind} ${t}`);
  });
  return el('div', {}, el('span', {class: 'rk-lbl'}, b.label || b.bind, out), inp, b.note ? el('div', {class: 'rk-note', text: b.note}) : null);
});

/* blocks/stack/stack.js */
/* stack: child blocks one above the other, as one group (one `after` can hide them all). */
Rupaka.block('stack', (b, ctx) => Rupaka.el('div', {}, (b.blocks || []).map(ctx.build)));

/* blocks/toggle/toggle.js */
/* toggle: on or off. Space or ↩ (native button keys) flip it. */
Rupaka.block('toggle', (b, ctx) => {
  const {el} = Rupaka, s = ctx.s;
  const btn = el('button', {type: 'button', role: 'switch', class: 'sw', 'aria-label': b.label || b.bind}, el('i'), el('span'));
  btn.onclick = () => ctx.put(b, b.bind, !s.get(b.bind));
  s.on(() => {
    const v = !!s.get(b.bind);
    btn.setAttribute('aria-checked', String(v)); btn.lastChild.textContent = v ? (b.on || 'On') : (b.off || 'Off'); btn.disabled = !ctx.live(b.lock);
  });
  return el('div', {}, Rupaka.label(b), btn);
});

/* blocks/wheel/wheel.js */
/* wheel: a ring. Item mode (`bind`): pick one item; drag the hand, click an item, ←/→ or A/D, Home/End.
   Angle mode (`angle`): a hand at a number of degrees over sectors (27 nakṣatras, with 12 rāśis outside); ⇧ moves ten steps.
   In angle mode the sector under the hand lights up only when the control is live, so a locked wheel does not give the answer away. */
Rupaka.block('wheel', (b, ctx) => {
  const {el, sv, show} = Rupaka, s = ctx.s, items = b.items || [], n = items.length, ang = b.angle != null;
  const key = ang ? b.angle : b.bind, W = ang ? 420 : 240, C = W / 2, r = ang ? 165 : 92, step = b.step ?? 1;
  const pol = (deg, rr) => { const t = deg * Math.PI / 180; return [C + rr * Math.sin(t), C - rr * Math.cos(t)]; };
  const svg = sv('svg', {viewBox: `0 0 ${W} ${W}`, tabindex: 0, role: 'slider', 'aria-label': b.label || key});
  const hand = sv('line', {class: 'hand'}), val = sv('text', {class: 'val', x: C, y: C + 10, 'text-anchor': 'middle'});
  const arc = (a0, a1, r0, r1) => { const [x0, y0] = pol(a0, r1), [x1, y1] = pol(a1, r1), [x2, y2] = pol(a1, r0), [x3, y3] = pol(a0, r0), big = a1 - a0 > 180 ? 1 : 0;
    return `M${x0} ${y0}A${r1} ${r1} 0 ${big} 1 ${x1} ${y1}L${x2} ${y2}A${r0} ${r0} 0 ${big} 0 ${x3} ${y3}Z`; };
  let ticks, wedge, marks;
  if (!ang) {
    ticks = items.map((it, i) => { const [x, y] = pol(360 * i / n, r);
      return sv('g', {class: 'tick', onclick: () => ctx.put(b, key, it)}, sv('circle', {class: 'dot', cx: x, cy: y, r: 15}), sv('text', {x, y: y + 5, 'text-anchor': 'middle', text: it})); });
    svg.append(sv('circle', {class: 'ring', cx: C, cy: C, r}), hand, ...ticks, val);
  } else {
    const sec = 360 / n, r0 = 80;
    wedge = sv('path', {class: 'wedge'});
    const lines = items.map((_, i) => { const [x0, y0] = pol(i * sec, r0), [x1, y1] = pol(i * sec, r); return sv('line', {class: 'sep', x1: x0, y1: y0, x2: x1, y2: y1}); });
    ticks = items.map((it, i) => { const a = (i + .5) * sec, [x, y] = pol(a, (r0 + r) / 2 + 2), rot = a <= 180 ? a - 90 : a + 90;
      return sv('text', {class: 'tick', x, y, 'text-anchor': 'middle', 'dominant-baseline': 'middle', transform: `rotate(${rot} ${x} ${y})`, text: it}); });
    marks = sv('g', {class: 'marks'}, Array.from({length: n * (b.marks || 1)}, (_, i) => { const [x0, y0] = pol(i * sec / (b.marks || 1), r - 6), [x1, y1] = pol(i * sec / (b.marks || 1), r);
      return sv('line', {x1: x0, y1: y0, x2: x1, y2: y1}); }));
    const out = b.outer || [], os = 360 / (out.length || 1), ro = 196;
    const outer = out.length ? sv('g', {class: 'outer'}, sv('circle', {class: 'ring', cx: C, cy: C, r: ro + 12}),
      out.map((t, i) => { const [x0, y0] = pol(i * os, r), [x1, y1] = pol(i * os, ro + 12), a = (i + .5) * os, [x, y] = pol(a, ro), rot = a > 90 && a < 270 ? a + 180 : a;
        return [sv('line', {class: 'sep', x1: x0, y1: y0, x2: x1, y2: y1}), sv('text', {x, y, 'text-anchor': 'middle', 'dominant-baseline': 'middle', transform: `rotate(${rot} ${x} ${y})`, text: t})]; })) : null;
    svg.append(wedge, sv('circle', {class: 'ring', cx: C, cy: C, r}), sv('circle', {class: 'ring', cx: C, cy: C, r: r0}), ...lines, marks, outer, ...ticks, hand, val);
  }
  const set = v => { if (v !== s.get(key)) ctx.put(b, key, v); };
  const norm = d => +(((Math.round(d / step) * step) % 360 + 360) % 360).toFixed(6);
  const pick = e => {
    const p = svg.getBoundingClientRect(), x = (e.clientX - p.left) / p.width * W - C, y = (e.clientY - p.top) / p.height * W - C;
    if (Math.hypot(x, y) < (ang ? 30 : 24)) return;
    const deg = (Math.atan2(x, -y) * 180 / Math.PI + 360) % 360;
    set(ang ? norm(deg) : items[Math.round(deg / 360 * n) % n]);
  };
  svg.addEventListener('pointerdown', e => { if (!ctx.live(b.lock)) return; svg.setPointerCapture(e.pointerId); svg.classList.add('drag'); pick(e); });
  svg.addEventListener('pointermove', e => { if (svg.hasPointerCapture(e.pointerId)) pick(e); });
  svg.addEventListener('pointerup', () => svg.classList.remove('drag'));
  svg.addEventListener('keydown', e => {
    const k = e.key.toLowerCase(), up = ['arrowright', 'arrowup', 'd'].includes(k), dn = ['arrowleft', 'arrowdown', 'a'].includes(k);
    if (!up && !dn && k !== 'home' && k !== 'end') return;
    e.preventDefault();
    if (ang) { const v = +s.get(key), d = step * (e.shiftKey ? 10 : 1); set(norm(k === 'home' ? 0 : k === 'end' ? 360 - step : v + (up ? d : -d))); return; }
    const i = items.indexOf(s.get(key)), j = k === 'home' ? 0 : k === 'end' ? n - 1 : i + (up ? 1 : -1);
    set(items[(j + n) % n]);
  });
  s.on(() => {
    const v = s.get(key), live = ctx.live(b.lock);
    if (ang) {
      const sec = 360 / n, i = Math.floor((+v % 360) / sec) % n, [x1, y1] = pol(+v, 30), [x2, y2] = pol(+v, r + 4);
      Object.entries({x1, y1, x2, y2}).forEach(([a, z]) => hand.setAttribute(a, z));
      val.textContent = `${show(+v, 2)}°`;
      wedge.setAttribute('d', arc(i * sec, (i + 1) * sec, 80, r)); wedge.style.display = live ? '' : 'none';
      ticks.forEach((t, j) => t.classList.toggle('on', live && j === i));
      marks.style.display = b.marks && (!b.marks_on || s.get(b.marks_on)) ? '' : 'none';
      svg.setAttribute('aria-valuenow', v); svg.setAttribute('aria-valuemin', 0); svg.setAttribute('aria-valuemax', 360);
      svg.setAttribute('aria-valuetext', `${show(+v, 2)} degrees${live ? `, ${items[i]}` : ''}`);
    } else {
      const i = items.indexOf(v), [x, y] = pol(360 * i / n, r), k = Math.hypot(x - C, y - C) || 1;
      hand.setAttribute('x1', C + (x - C) * 30 / k); hand.setAttribute('y1', C + (y - C) * 30 / k);
      hand.setAttribute('x2', C + (x - C) * (k - 16) / k); hand.setAttribute('y2', C + (y - C) * (k - 16) / k);
      val.textContent = show(v);
      ticks.forEach((t, j) => t.classList.toggle('on', j === i));
      svg.setAttribute('aria-valuenow', i); svg.setAttribute('aria-valuemin', 0); svg.setAttribute('aria-valuemax', n - 1); svg.setAttribute('aria-valuetext', show(v));
    }
  });
  const wrap = el('div', {}, Rupaka.label(b), svg);
  if (ang) wrap.classList.add('ang');
  return wrap;
});

/* static/boot.js */
/* rupaka boot: the last part of the bundle. Mount each [data-rupaka] on load and after each htmx swap, one time each. */
(() => {
  const R = window.Rupaka, go = () => R.boot();
  if (R.booted) return;
  R.booted = true;
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', go); else go();
  document.addEventListener('htmx:afterSwap', go);
  document.addEventListener('htmx:afterSettle', go);
})();
