/* static/rupaka.js */
/* rupaka core: a demo is a JSON spec of blocks over one small state. Named fns compute derived values.
   No network, no eval, no dependencies. Blocks and fns register with Rupaka.block and Rupaka.fn; boot.js mounts every [data-rupaka]. */
(() => {
  if (window.Rupaka && window.Rupaka.core) return;   // the bundle came in twice (an htmx swap): keep the first copy
  const R = window.Rupaka = {blocks: {}, fns: {}, core: true, version: '0.0.12', schema: 1};   // bundle() writes in rupaka.__version__
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

  // The [r, g, b] (0 to 255) of a CSS colour or a --rk-* var, as it is in effect on `node`. A 1 x 1 canvas reads any colour syntax.
  let probe;
  R.rgb = (node, c) => {
    node.style.color = c.startsWith('--') ? `var(${c})` : c;
    const v = getComputedStyle(node).color;
    node.style.color = '';
    probe ??= el('canvas', {width: 1, height: 1}).getContext('2d', {willReadFrequently: true});
    probe.clearRect(0, 0, 1, 1); probe.fillStyle = v; probe.fillRect(0, 0, 1, 1);
    return [...probe.getImageData(0, 0, 1, 1).data.slice(0, 3)];
  };

  // A vendored library that only some blocks need (three.js for a scene). page() puts it in the page when a spec needs it.
  // Else it loads one time from `R.base` (the folder of rupaka.js, or a path that the host sets), never from another site.
  const SRC = document.currentScript?.src || '', LIBS = {three: 'RupakaTHREE'}, loading = {};
  R.base = SRC ? SRC.replace(/[?#].*$/, '').replace(/[^/]*$/, '') : '';
  const query = SRC.match(/\?[^#]*/)?.[0] || '';
  R.need = name => {
    const g = LIBS[name];
    if (!g) return Promise.reject(new Error(`unknown library "${name}"`));
    if (window[g]) return Promise.resolve(window[g]);
    return loading[name] ??= new Promise((ok, no) => {
      if (!R.base) { delete loading[name]; return no(new Error(`${name}.js is not on this page`)); }
      const s = el('script', {src: `${R.base}${name}.js${query}`});
      s.onload = () => window[g] ? ok(window[g]) : no(new Error(`${name}.js did not load`));
      s.onerror = () => { delete loading[name]; no(new Error(`${name}.js did not load`)); };
      document.head.append(s);
    });
  };

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

  // In an explainer, a block with `step` shows from that step of the state key `step`. These blocks use `step` for their own meaning.
  // A Python test keeps this list equal to the manifests that have a `step` prop.
  R.ownStep = new Set(['body', 'force', 'grid', 'label3d', 'point', 'shot', 'slider', 'wheel']);
  function build(b, ctx) {
    const f = R.blocks[b.type];
    if (!f) throw new Error(`unknown block "${b.type}"`);
    const node = f(b, ctx), from = ctx.learn && b.step != null && !R.ownStep.has(b.type) ? +b.step : null;
    node.classList.add('rk-b', `rk-${b.type}`);
    node.setAttribute('data-rk-type', b.type);
    if (b.after) node.setAttribute('data-rk-after', b.after);
    if (b.lock) node.setAttribute('data-rk-lock', b.lock);
    if (from != null) node.setAttribute('data-rk-step', from);
    if (ctx.ids?.has(b)) node.setAttribute('data-rk-id', ctx.id(b));
    if (b.after || from != null) { const sync = () => hide(node, !ctx.live(b.after) || (from != null && ctx.step() < from)); ctx.s.on(sync); sync(); }
    if (b.lock && !(node instanceof SVGElement)) {
      const note = el('div', {class: 'rk-note rk-locknote', text: 'Locked until you lock in your prediction.'});
      node.append(note);
      const sync = () => { const l = !ctx.live(b.lock); node.classList.toggle('rk-locked', l); note.hidden = !l; };
      ctx.s.on(sync); sync();
    }
    ctx.nodes?.set(b, node);
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
    const ctx = {s, spec, root, nodes: new WeakMap(), ids: new WeakMap(), live: g => !g || s.get(`gate.${g}`) === 'done', learn: spec.mode === 'learn',
                 step: () => s.st.step == null ? Infinity : +s.st.step};   // with no step key, each part shows
    ctx.build = b => build(b, ctx);
    // Each block has a stable id: its path in the spec, such as 'blocks.2' or 'blocks.0.blocks.1'. A part adds its own path: 'blocks.2.cells.0'.
    ctx.tag = (b, p) => { if (b && typeof b === 'object') { ctx.ids.set(b, p); (b.blocks || []).forEach((k, i) => ctx.tag(k, `${p}.blocks.${i}`)); } };
    ctx.id = (b, part) => { const p = ctx.ids.get(b); return p == null ? null : part == null ? p : `${p}.${part}`; };
    (spec.blocks || []).forEach((b, i) => ctx.tag(b, `blocks.${i}`));
    ctx.put = (b, k, val) => { if (!ctx.live(b.lock)) return false; s.set(k, val); return true; };   // a locked control refuses
    if (spec.mode === 'learn') { root.dataset.rkMode = 'learn'; root.append(el('p', {class: 'rk-mode', text: 'Explainer'})); }   // no gate, so no prediction step
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
  // Add one block to a mounted demo with no rebuild, so a stream can grow a panel. The block goes at the end, or at the end of the
  // stack or row at the path `opts.into` (for example 'blocks.0'). The parts that show stay as they are. It gives the path of the new block.
  // The host checks the block first (rupaka.spec.append in Python): the runtime only refuses an unknown type or a bad place.
  const GROUPS = new Set(['stack', 'row']);
  R.append = (host, block, opts) => {
    const s = mounted(host), ctx = CTX.get(s), into = opts?.into;
    const box = into ? get(s.spec, into) : s.spec, at = into ? ctx.nodes.get(box) : ctx.root;
    if (!box || (into && !GROUPS.has(box.type)) || !at) throw new Error(`${into} is not a stack or a row of this demo`);
    const b = structuredClone(block), list = box.blocks ||= [], path = `${into ? into + '.' : ''}blocks.${list.length}`;
    ctx.tag(b, path);
    const node = ctx.build(b);
    list.push(b); at.append(node); s.emit('*');
    return path;
  };
  // The element of a block or of a part at `path` (its data-rk-id), or null. A host draws a curve from a mark on its page to this element.
  // The element can be hidden, for example a part of a later step: check it before you draw.
  R.anchor = (host, path) => CTX.get(mounted(host)).root.querySelector(`[data-rk-id="${CSS.escape(String(path))}"]`);
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
   There is no eval: the text is parsed to a tree, and only own state keys can be read.
   `Rupaka.expr(src, fns)` also allows the functions in `fns`, by name; `field` adds noise this way. */
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
  const parse = (src, fns) => {
    const ts = lex(src), fs = fns ? {...FN, ...fns} : FN; let p = 0;
    const peek = () => ts[p], eat = v => { const t = ts[p]; if (!t || (v && t.v !== v)) throw new Error(`expr: "${src}" needs ${v || 'more'}`); p++; return t; };
    const binl = (next, ops) => () => { let a = next(); while (peek()?.t === 'op' && ops.includes(peek().v)) { const o = eat().v, l = a, r = next(); a = o === '+' ? e => l(e) + r(e) : o === '-' ? e => l(e) - r(e) : o === '*' ? e => l(e) * r(e) : e => l(e) / r(e); } return a; };
    const atom = () => {
      const t = eat();
      if (t.t === 'n') return () => t.v;
      if (t.t === 'op' && t.v === '(') { const a = add(); eat(')'); return a; }
      if (t.t === 'id') {
        if (t.v.startsWith('_') || ['constructor', 'prototype'].includes(t.v)) throw new Error(`expr: the name "${t.v}" is not allowed`);
        if (peek()?.v === '(') {
          if (!Object.hasOwn(fs, t.v)) throw new Error(`expr: no function "${t.v}"`);
          eat('('); const args = [add()]; while (peek()?.v === ',') { eat(','); args.push(add()); } eat(')');
          const f = fs[t.v]; return e => f(...args.map(a => a(e)));
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

/* fns/field.js */
/* field: an expr formula on each cell of an n x n grid, as a list of n rows. Row i and column j go from 0 to n - 1.
   The formula can call noise(i, j): a value with mean 0 and variance 1, the same for the same seed, i and j.
   noise is a sum of four uniform hashes (murmur3 fmix32), so Python gives the same bits. */
(() => {
  const mix = h => { h ^= h >>> 16; h = Math.imul(h, 0x85ebca6b); h ^= h >>> 13; h = Math.imul(h, 0xc2b2ae35); return (h ^ h >>> 16) >>> 0; };
  const step = (h, x) => mix(((h ^ x) + 0x9e3779b9) >>> 0);
  const noise = (seed, i, j) => {
    const h = step(step(seed >>> 0, i >>> 0), j >>> 0);
    return ((step(h, 0) + step(h, 1) + step(h, 2) + step(h, 3)) / 4294967296 - 2) * Math.sqrt(3);
  };
  const cache = {};
  Rupaka.fn('field', (d, st) => {
    const n = d.n ?? 16, seed = d.seed ?? 0;
    if (!(Number.isInteger(n) && n >= 1 && n <= 64)) throw new Error('field: n must be an int from 1 to 64');
    const f = cache[`${seed}|${d.expr}`] ||= Rupaka.expr(d.expr, {noise: (i, j) => noise(seed, i, j)});
    return Array.from({length: n}, (_, i) => Array.from({length: n}, (_, j) => f({...st, i, j})));
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

/* blocks/body/body.js */
/* body: one part of a scene. A primitive shape, or a group that holds other bodies. `in` puts it inside another body, so it
   moves and turns with that body. `at` is in the frame of its parent. `rot` (degrees about x, y and z) turns it about `pivot`.
   An item of `rot` can be a state key, so a slider turns the part; the turn eases, or cuts with prefers-reduced-motion. */
(() => {
  const SIZE = {box: [1, 1, 1], cylinder: [.5, 1], cone: [.5, 1], sphere: [.5], capsule: [.25, 1], torus: [.5, .15], group: []};
  const rad = d => d * Math.PI / 180;

  // A box with round edges: a rounded square, pushed out with a bevel. The normals are smooth, so the bands of light curve.
  function rounded(T, [x, y, z], r) {
    const s = new T.Shape(), e = 1e-5, w = x - 2 * r, h = y - 2 * r;
    s.absarc(e, e, e, -Math.PI / 2, -Math.PI, true);
    s.absarc(e, h, e, Math.PI, Math.PI / 2, true);
    s.absarc(w, h, e, Math.PI / 2, 0, true);
    s.absarc(w, e, e, 0, -Math.PI / 2, true);
    const g = new T.ExtrudeGeometry(s, {depth: Math.max(e, z - 2 * r), bevelEnabled: true, bevelSegments: 4, steps: 1,
                                        bevelSize: r - e, bevelThickness: r, curveSegments: 4});
    g.center();
    return smooth(T, g);
  }
  // Join the corners that share a place, then find the normals again.
  function smooth(T, g) {
    const p = g.attributes.position, seen = new Map(), pos = [], idx = [];
    for (let i = 0; i < p.count; i++) {
      const k = `${p.getX(i).toFixed(4)},${p.getY(i).toFixed(4)},${p.getZ(i).toFixed(4)}`;
      let j = seen.get(k);
      if (j === undefined) { j = pos.length / 3; seen.set(k, j); pos.push(p.getX(i), p.getY(i), p.getZ(i)); }
      idx.push(j);
    }
    const out = new T.BufferGeometry();
    out.setAttribute('position', new T.Float32BufferAttribute(pos, 3)); out.setIndex(idx); out.computeVertexNormals();
    return out;
  }
  function shape(T, b) {
    const z = Object.assign([...SIZE[b.kind]], b.size || []);
    switch (b.kind) {
      case 'box': {
        const r = Math.min(...z) * Math.min(.5, b.round ?? .14);
        return r > 1e-3 ? rounded(T, z, r) : new T.BoxGeometry(...z);
      }
      case 'cylinder': return z.length > 2 ? new T.CylinderGeometry(z[0], z[1], z[2], 40) : new T.CylinderGeometry(z[0], z[0], z[1], 40);
      case 'cone': return new T.ConeGeometry(z[0], z[1], 40);
      case 'sphere': return new T.SphereGeometry(z[0], 40, 24);
      case 'capsule': return new T.CapsuleGeometry(z[0], z[1], 8, 32);
      case 'torus': return new T.TorusGeometry(z[0], z[1], 20, 56);
    }
  }

  Rupaka.block('body', (b, ctx) => {
    const S = ctx.scene;
    if (!S) throw new Error('a body must be inside a scene');
    if (!Object.hasOwn(SIZE, b.kind)) throw new Error(`"${b.kind}" is not a body kind; use one of: ${Object.keys(SIZE).join(', ')}`);
    if (b.in && !S.ids.has(b.in)) throw new Error(`the body "${b.id}" is in "${b.in}", which is not a body`);
    return S.part(b, {
      make(T, P) {
        const outer = new T.Group(), frame = new T.Group(), at = S.vec(b.at), pv = b.pivot ? S.vec(b.pivot) : at;
        outer.position.set(...pv); frame.position.set(at[0] - pv[0], at[1] - pv[1], at[2] - pv[2]);
        outer.add(frame);
        if (b.kind !== 'group') frame.add(new T.Mesh(shape(T, b), S.mat(b.color || 'body')));
        (b.in ? S.bodies[b.in].frame : S.world).add(outer);
        S.bodies[b.id] = {outer, frame, b, P};
        P.rot = S.vec(b.rot).map(rad); outer.rotation.set(...P.rot);
        P.outer = outer;
        return outer;
      },
      sync(P, live) {
        S.show(P, P.outer, live);
        const to = S.vec(b.rot).map(rad), o = P.outer;
        if (to.every((x, i) => x === P.rot[i])) return;
        const from = [o.rotation.x, o.rotation.y, o.rotation.z];
        P.rot = to;
        S.anim(P, b.turn ?? 700, k => o.rotation.set(...from.map((x, i) => x + (to[i] - x) * k)));
      },
    }, Rupaka.el('li', {text: `${b.id}: a ${b.kind}`}));
  });
})();

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

/* blocks/flow/flow.js */
/* flow: a few nodes and the arrows between them, left to right (row) or as a loop (cycle), for example guess → compare → adjust. */
Rupaka.block('flow', (b, ctx) => {
  const {el, sv} = Rupaka, ns = b.nodes || [], n = ns.length, cyc = b.layout === 'cycle', W = 600, LH = 19;
  const at = Object.fromEntries(ns.map((x, i) => [x.id, i]));
  const es = b.edges ?? ns.slice(cyc ? 0 : 1).map((x, i) => ({from: ns[i].id, to: ns[(i + 1) % n].id}));   // no edges: each node points to the next
  // The words of a node in at most two lines that fit `w`, at about 8 px a letter.
  const wrap = (t, w) => { const per = Math.max(4, Math.floor((w - 20) / 8)), out = [''];
    for (const wd of String(t).split(/\s+/)) { const l = out.length - 1; if (out[l] && (out[l] + ' ' + wd).length > per && out.length < 2) out.push(wd); else out[l] = out[l] ? `${out[l]} ${wd}` : wd; }
    return out; };
  const slot = cyc ? 170 : W / Math.max(n, 1), boxes = ns.map(x => { const ls = wrap(x.text, slot - 28);
    return {ls, w: Math.min(slot - 28, Math.max(64, 8 * Math.max(...ls.map(l => l.length)) + 26)), h: LH * ls.length + 16}; });
  const hmax = Math.max(...boxes.map(x => x.h), 0), arcs = es.map(e => at[e.to] - at[e.from]);
  const up = !cyc && arcs.some(d => d > 1) ? 56 : 8, down = !cyc && arcs.some(d => d < 0) ? 56 : 8;
  const H = cyc ? 300 : up + hmax + down, ry = (H - hmax) / 2 - 14, rx = W / 2 - 90;
  const ctr = i => cyc ? [W / 2 + rx * Math.cos(-Math.PI / 2 + 2 * Math.PI * i / n), H / 2 + ry * Math.sin(-Math.PI / 2 + 2 * Math.PI * i / n)] : [slot * (i + .5), up + hmax / 2];
  // The point where the line from the centre of box i toward [x, y] leaves the box, 5 px out.
  const edge = (i, [x, y]) => { const [cx, cy] = ctr(i), dx = x - cx, dy = y - cy, bx = boxes[i];
    const t = Math.min(Math.abs((bx.w / 2 + 5) / (dx || 1e-9)), Math.abs((bx.h / 2 + 5) / (dy || 1e-9))); return [cx + dx * t, cy + dy * t]; };
  const f = v => +v.toFixed(1), q = (a, c, z) => `M${f(a[0])} ${f(a[1])}Q${f(c[0])} ${f(c[1])} ${f(z[0])} ${f(z[1])}`;
  const head = (c, z) => { const a = Math.atan2(z[1] - c[1], z[0] - c[0]), p = s => [z[0] - 9 * Math.cos(a + s), z[1] - 9 * Math.sin(a + s)];
    const [l, r] = [p(.45), p(-.45)]; return `M${f(l[0])} ${f(l[1])}L${f(z[0])} ${f(z[1])}L${f(r[0])} ${f(r[1])}`; };
  const svg = sv('svg', {viewBox: `0 0 ${W} ${H}`, role: 'img', 'aria-label': [b.label, ...es.map(e => `${ns[at[e.from]].text} to ${ns[at[e.to]].text}`)].filter(Boolean).join('; ')});
  es.forEach((e, j) => {
    const i = at[e.from], k = at[e.to], A = ctr(i), Z = ctr(k), d = k - i;
    let c, out = [0, d < 0 ? 1 : -1];   // the side of the line that the words go on
    if (cyc) { const m = [(A[0] + Z[0]) / 2, (A[1] + Z[1]) / 2], ox = m[0] - W / 2, oy = m[1] - H / 2, l = Math.hypot(ox, oy) || 1;
      out = [ox / l, oy / l]; c = [m[0] + 30 * out[0], m[1] + 30 * out[1]]; }   // bend out from the middle, so the arrows make a loop
    else if (d === 1) c = [(A[0] + Z[0]) / 2, A[1]];
    else c = [(A[0] + Z[0]) / 2, d > 0 ? up - 48 : up + hmax + 48 - 8];   // a skip goes over the row, a step back goes under it
    const a = edge(i, d === 1 && !cyc ? Z : c), z = edge(k, d === 1 && !cyc ? A : c), mid = [(a[0] + 2 * c[0] + z[0]) / 4, (a[1] + 2 * c[1] + z[1]) / 4];
    const jog = [c[0] + 2, c[1] - 2.5];
    svg.append(sv('g', {class: 'edge', style: `--i: ${n + j}`, 'data-rk-id': ctx.id(b, `edges.${j}`)},
      sv('path', {class: 'ln', d: q(a, c, z) + head(c, z), pathLength: 1}),
      sv('path', {class: 'sk', d: q([a[0] + 1, a[1] + 1.5], jog, [z[0] - 1, z[1] + 1]), pathLength: 1}),
      e.text ? sv('text', {class: 'et', x: f(mid[0] + 10 * out[0]), y: f(mid[1] + 12 * out[1] + 4), text: e.text,
                           'text-anchor': out[0] > .3 ? 'start' : out[0] < -.3 ? 'end' : 'middle'}) : null));
  });
  ns.forEach((x, i) => { const [cx, cy] = ctr(i), bx = boxes[i], x0 = cx - bx.w / 2, y0 = cy - bx.h / 2;
    svg.append(sv('g', {class: 'node', style: `--i: ${i}`, 'data-rk-id': ctx.id(b, `nodes.${i}`)},
      sv('rect', {x: f(x0), y: f(y0), width: f(bx.w), height: f(bx.h), rx: 6}),
      sv('rect', {class: 'sk', x: f(x0 + 1.5), y: f(y0 - 1), width: f(bx.w - 2), height: f(bx.h + 1.5), rx: 8}),
      bx.ls.map((l, r) => sv('text', {x: f(cx), y: f(cy + (r - (bx.ls.length - 1) / 2) * LH + 5), 'text-anchor': 'middle', text: l})))); });
  return el('div', {}, Rupaka.label(b), svg);
});

/* blocks/force/force.js */
/* force: an arrow in a scene. Its length is |mag| times the scene scale, so arrows in one scene compare. `at` is a point in the
   frame of the body `on` (or in the world), so the arrow moves with the body. `dir` is in the world. With `tip`, the arrow ends at
   the point (a push); else it starts there (a pull). The arrow grows when it shows or when its mag changes. */
(() => {
  const tone = d => d[1] > .5 ? 'up' : d[1] < -.5 ? 'down' : 'side';
  Rupaka.block('force', (b, ctx) => {
    const S = ctx.scene;
    if (!S) throw new Error('a force must be inside a scene');
    if (b.on && !S.ids.has(b.on)) throw new Error(`the force is on "${b.on}", which is not a body`);
    const name = b.tone || tone(S.vec(b.dir, [0, 1, 0]));
    const node = b.label ? S.chip(b, b.label, name) : Rupaka.el('li');
    if (!b.label) ctx.s.on(() => { node.textContent = `A force, ${Rupaka.show(S.num(b.mag), 2)}`; });
    let T;
    const len = P => Math.abs(S.num(b.mag)) * S.scale || 0;
    const way = P => {   // the unit direction; a negative mag turns it round
      const d = P.dir.set(...S.vec(b.dir, [0, 1, 0]));
      if (d.lengthSq() < 1e-9) d.set(0, 1, 0);
      return S.num(b.mag) < 0 ? d.normalize().negate() : d.normalize();
    };
    return S.part(b, {
      make(lib, P) {
        T = lib;
        const g = new T.Group(), mat = S.mat(name);
        const shaft = new T.Mesh(new T.CylinderGeometry(1, 1, 1, 24).translate(0, .5, 0), mat);
        const head = new T.Mesh(new T.ConeGeometry(1, 1, 32).translate(0, .5, 0), mat);
        g.add(shaft, head); S.world.add(g);
        Object.assign(P, {g, shaft, head, len: len(P), dir: new T.Vector3(0, 1, 0), base: new T.Vector3()});
        return g;
      },
      sync(P, live) {
        S.show(P, P.g, live);
        const to = len(P), from = P.len;
        if (to !== P.to) { P.to = to; S.anim(P, 600, k => { P.len = from + (to - from) * k; }); }
      },
      // Each frame: put the arrow at its point, along its direction, at its length now.
      frame(P) {
        const d = way(P), L = Math.max(P.len, 1e-3), r = S.unit * .55, hr = r * 2.6, hl = Math.min(hr * 2.4, L * .45);
        P.base.copy(S.point(b.on, b.at)); if (b.tip) P.base.addScaledVector(d, -L);
        P.g.position.copy(P.base);
        P.g.quaternion.setFromUnitVectors(new T.Vector3(0, 1, 0), d);
        P.shaft.scale.set(r, Math.max(1e-3, L - hl), r);
        P.head.scale.set(hr, hl, hr); P.head.position.y = L - hl;
      },
      // The chip goes on the arrow, at its full length.
      anchor(P) {
        if (!P.g) return null;
        const L = P.to ?? P.len;
        return S.point(b.on, b.at).addScaledVector(way(P), b.tip ? -L * .6 : L * .6);
      },
    }, node);
  });
})();

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

/* blocks/label3d/label3d.js */
/* label3d: a chip pinned to a point of a scene, with a thin leader line that ends in a dot at the point. `at` is in the frame of
   the body `on` (or in the world). The text fills {path} from the state, as a readout does. The scene places the chips so that
   they never overlap: a chip that has no free place does not show. */
Rupaka.block('label3d', (b, ctx) => {
  const S = ctx.scene;
  if (!S) throw new Error('a label3d must be inside a scene');
  if (b.on && !S.ids.has(b.on)) throw new Error(`the label is on "${b.on}", which is not a body`);
  return S.part(b, {anchor: () => S.T ? S.point(b.on, b.at) : null}, S.chip(b, b.text));
});

/* blocks/pair/pair.js */
/* pair: input cells, an arrow and the answer, as one row of a worked example: [18] → 47. The parts come in one by one. */
Rupaka.block('pair', (b, ctx) => {
  const {el, fmt} = Rupaka, cells = b.cells || [];
  const part = (cls, i, id) => el('span', {class: cls, style: `--i: ${i}`, 'data-rk-id': ctx.id(b, id)});
  const cs = cells.map((_, i) => part('cell', i, `cells.${i}`)), to = part('to', cells.length + 1, 'to');
  ctx.s.on(() => { cs.forEach((c, i) => { c.textContent = fmt(cells[i], ctx.s.st); }); to.textContent = fmt(b.to, ctx.s.st); });
  const heads = b.heads ? el('div', {class: 'heads'}, el('span', {text: b.heads[0]}), el('span', {text: b.heads[1]})) : null;
  return el('div', {}, heads, el('div', {class: 'line'}, b.n ? el('span', {class: 'n', text: b.n}) : null,
    el('span', {class: 'cells'}, cs), el('span', {class: 'arrow', style: `--i: ${cells.length}`, role: 'img', 'aria-label': 'gives'}), to));
});

/* blocks/pixels/pixels.js */
/* pixels: a grey image of a list of rows of numbers, one square per cell. Read-only.
   The ramp goes from --rk-bg at lo to --rk-fg at hi, so it follows the theme. The label fills {path} from the state;
   it is the aria-label of the canvas and shows above it. */
Rupaka.block('pixels', (b, ctx) => {
  const {el, fmt} = Rupaka, s = ctx.s;
  const cv = el('canvas', {role: 'img', width: 0, height: 0, style: `width: ${b.size ?? 256}px`});
  const lbl = b.label ? el('span', {class: 'rk-lbl', 'aria-hidden': 'true'}) : null;
  const rgb = v => Rupaka.rgb(cv, v);
  s.on(() => {
    const text = fmt(b.label || b.bind, s.st), v = s.get(b.bind) || [], m = Array.isArray(v[0]) ? v : [v];
    cv.setAttribute('aria-label', text); if (lbl) lbl.textContent = text;
    const nr = m.length, nc = m[0]?.length || 0, vs = m.flat();
    if (cv.width !== nc || cv.height !== nr) { cv.width = nc; cv.height = nr; }
    if (!nr || !nc) return;
    const lo = b.lo ?? Math.min(...vs), hi = b.hi ?? Math.max(...vs), bg = rgb('--rk-bg'), fg = rgb('--rk-fg');
    const img = new ImageData(nc, nr), px = img.data;
    vs.forEach((x, k) => {
      const t = hi > lo ? Math.min(1, Math.max(0, (x - lo) / (hi - lo))) : 0;
      for (let c = 0; c < 3; c++) px[4 * k + c] = bg[c] + (fg[c] - bg[c]) * t;
      px[4 * k + 3] = 255;
    });
    cv.getContext('2d').putImageData(img, 0, 0);
  });
  return el('div', {}, lbl, cv);
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

/* blocks/scene/scene.js */
/* scene: a 3D view in a toon style, drawn with three.js. Its child blocks (body, force, label3d, shot) are its parts.
   three.js loads only for a spec that has a scene (Rupaka.need). The look: flat colour in three soft bands, ink outlines from
   one edge pass on depth and normals, a soft floor with contact shadows, and label chips in screen space that never overlap.
   Colours come from the --rk-* vars. The camera moves between named shots with easing; with prefers-reduced-motion it cuts.
   `bind` is the step: a part with `step: n` shows from step n. Keys on the view: A/D back and next, 1-9 a step, Q/E turn, W/S tilt. */
(() => {
  const R = Rupaka, {el, sv, fmt} = R;
  const SHOTS = {wide: {az: 30, el: 18, fov: 30}, side: {az: 0, el: 4, fov: 12}, front: {az: 90, el: 4, fov: 12},
                 top: {az: 0, el: 89, fov: 12}, close: {az: 30, el: 18, fov: 28}};
  const clamp = (x, a, b) => Math.min(b, Math.max(a, x));
  const inout = t => (t = clamp(t, 0, 1)) < .5 ? 4 * t ** 3 : 1 - (2 - 2 * t) ** 3 / 2;
  const settle = t => { t = clamp(t, 0, 1) - 1; return 1 + 2.4 * t ** 3 + 1.4 * t ** 2; };   // a small overshoot, then rest
  const still = () => matchMedia('(prefers-reduced-motion: reduce)').matches;
  const rad = d => d * Math.PI / 180;
  const lum = c => .2126 * c[0] + .7152 * c[1] + .0722 * c[2];
  const mix = (a, b, t) => a.map((x, i) => x + (b[i] - x) * t);
  const scenes = new WeakMap();   // store -> its scenes, for Rupaka.cam
  // One watch on the theme for all scenes: a change of the OS scheme, or of a class, data-theme or style on <html>.
  // Each scene in `themed` gives false when its view has left the page; then it frees its WebGL context and drops out.
  const themed = new Set();
  let watch = null;
  const retheme = () => themed.forEach(f => { if (!f()) themed.delete(f); });
  const onTheme = f => {
    themed.add(f);
    if (watch) return;
    watch = new MutationObserver(retheme);
    watch.observe(document.documentElement, {attributes: true, attributeFilter: ['class', 'data-theme', 'style']});
    matchMedia('(prefers-color-scheme: dark)').addEventListener('change', retheme);
  };
  R.SHOTS = Object.keys(SHOTS).filter(k => k !== 'close');

  // A shot name: wide, side, front, top, or close:<body id>.
  const isShot = (v, ids) => typeof v === 'string' && (R.SHOTS.includes(v) || (v.startsWith('close:') && ids.has(v.slice(6))));

  // The board's `cam` operation: set the key that a shot block binds. It gives false for a bad name or a scene with no such key.
  R.cam = (host, shot) => {
    const s = host?.rupaka;
    if (!s) throw new Error('no rupaka demo is mounted in this element');
    for (const S of scenes.get(s) || []) {
      const k = S.shotKey();
      if (k && isShot(shot, S.ids)) { R.set(host, {[k]: shot}); return true; }
    }
    return false;
  };

  const TOON_V = `varying vec3 vN;
    void main() { vN = normalize(normalMatrix * normal); gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.); }`;
  // Three bands of light with soft edges, so a flat colour stays true in the light band and a round part still reads as round.
  const TOON_F = `uniform vec3 color; uniform vec3 light; varying vec3 vN;
    void main() {
      vec3 n = normalize(vN); if (!gl_FrontFacing) n = -n;
      float d = dot(n, light), a = fwidth(d) + .11;
      float band = .66 + .16 * smoothstep(-.3 - a, -.3 + a, d) + .18 * smoothstep(.3 - a, .3 + a, d);
      gl_FragColor = vec4(color * band, 1.);
      #include <colorspace_fragment>
    }`;
  const FLAT_V = `varying vec2 vUv; void main() { vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.); }`;
  // The floor fades into the page at its rim. A contact shadow is dark at its middle and soft at its edge.
  const FLOOR_F = `uniform vec3 color; varying vec2 vUv;
    void main() { float r = length(vUv - .5) * 2., a = 1. - smoothstep(0., 1., r); gl_FragColor = vec4(color, a * a); }`;
  // The contact shadow: the scene seen from under the floor, dark where a part is near the floor, then blurred.
  const DARK_V = `varying float vY; void main() { vec4 p = modelMatrix * vec4(position, 1.); vY = p.y; gl_Position = projectionMatrix * viewMatrix * p; }`;
  const DARK_F = `uniform float floor, fade; varying float vY;
    void main() { float a = 1. - clamp((vY - floor) / fade, 0., 1.); gl_FragColor = vec4(0., 0., 0., a * a); }`;
  const BLUR_F = `uniform sampler2D map; uniform vec2 step; varying vec2 vUv;
    void main() {
      float w[5]; w[0] = .227; w[1] = .194; w[2] = .121; w[3] = .054; w[4] = .016;
      float a = texture2D(map, vUv).a * w[0];
      for (int i = 1; i < 5; i++) a += (texture2D(map, vUv + step * float(i)).a + texture2D(map, vUv - step * float(i)).a) * w[i];
      gl_FragColor = vec4(0., 0., 0., a);
    }`;
  const SHADOW_F = `uniform vec3 color; uniform float alpha; uniform sampler2D map; varying vec2 vUv;
    void main() { float r = length(vUv - .5) * 2.; gl_FragColor = vec4(color, alpha * texture2D(map, vec2(vUv.x, 1. - vUv.y)).a * (1. - smoothstep(.7, 1., r))); }`;
  const POST_V = `varying vec2 vUv; void main() { vUv = uv; gl_Position = vec4(position.xy, 0., 1.); }`;
  // The ink: a line where the depth steps toward the viewer (the outline) or where the normal turns fast (a crease).
  // Where no part draws, the floor and its shadow fade into the page near the edges of the view, so the ground has no edge.
  const POST_F = `uniform sampler2D tC; uniform sampler2D tN; uniform sampler2D tD; uniform vec2 texel; uniform float w, near, far; uniform vec3 ink, bg;
    varying vec2 vUv;
    float lin(float d) { float z = d * 2. - 1.; return 2. * near * far / (far + near - z * (far - near)); }
    void main() {
      vec3 col = texture2D(tC, vUv).rgb;
      float d0 = texture2D(tD, vUv).x, l0 = lin(d0), de = 0., ne = 0.;
      vec3 n0 = texture2D(tN, vUv).xyz * 2. - 1.;
      for (int i = 0; i < 8; i++) {
        float a = float(i) * .7853982;
        vec2 uv = vUv + vec2(cos(a), sin(a)) * texel * w;
        float d = texture2D(tD, uv).x;
        de += min(lin(d) - l0, l0);
        if (d0 < 1. && d < 1.) ne = max(ne, 1. - dot(n0, texture2D(tN, uv).xyz * 2. - 1.));
      }
      vec2 q = abs(vUv - .5) * 2.;
      if (d0 >= 1.) col = mix(col, bg, smoothstep(.55, 1., max(q.x, q.y)));
      float e = d0 < 1. ? max(smoothstep(.05, .16, de / l0), smoothstep(.3, .6, ne)) : 0.;
      gl_FragColor = vec4(mix(col, ink, e * .92), 1.);
      #include <colorspace_fragment>
    }`;

  Rupaka.block('scene', (b, ctx) => {
    const s = ctx.s, parts = [], specs = Object.fromEntries((b.blocks || []).filter(k => k.type === 'body').map(k => [k.id, k]));
    const ids = new Set(Object.keys(specs)), S = {b, s, ids, bodies: {}, anims: new Map()};
    S.part = (pb, impl, node) => { parts.push({b: pb, impl, node}); return node; };
    S.num = v => typeof v === 'number' ? v : +s.get(v);
    S.vec = (v, d = [0, 0, 0]) => Array.isArray(v) ? v.map((x, i) => { const n = S.num(x); return Number.isFinite(n) ? n : d[i]; }) : d;
    S.step = () => b.bind ? (+s.get(b.bind) || 1) : Infinity;
    const own = pb => ctx.live(pb.after) && (pb.step == null || S.step() >= pb.step) && (pb.show == null || !!s.get(pb.show));
    S.seen = id => !!specs[id] && own(specs[id]) && (!specs[id].in || S.seen(specs[id].in));   // a body and each body that holds it
    S.live = pb => own(pb) && (pb.on == null || S.seen(pb.on));
    S.shotKey = () => parts.find(p => p.b.type === 'shot' && p.b.bind)?.b.bind;
    // A chip: a label in screen space with a leader line to its point. Its text fills {path} from the state.
    S.chip = (pb, tpl, tone) => {
      const t = el('span', {class: 'txt'}), n = el('div', {class: 'rk-chip off', 'data-tone': pb.tone || tone || 'ink'}, t);
      s.on(() => { t.textContent = fmt(tpl, s.st); });
      return n;
    };
    // An animation of one thing (`key`). A new one for the same key takes its place. f(k) gets k from 0 to 1.
    S.anim = (key, ms, f, ease = inout) => {
      if (still() || !ms || !S.T) { S.anims.delete(key); f(1); return; }
      S.anims.set(key, {t0: performance.now(), ms, f, ease, k: 0}); f(0); kick();
    };
    // Show or hide an object: it grows in with a small overshoot, or shrinks out.
    S.show = (P, o, live) => {
      if (P.on === live) return;
      const first = P.on === undefined; P.on = live;
      if (first || !S.T) { o.visible = live; o.scale.setScalar(1); return; }
      o.visible = true;
      if (live) S.anim(o, 420, k => { o.scale.setScalar(Math.max(1e-3, k)); }, settle);
      else S.anim(o, 220, k => { o.scale.setScalar(Math.max(1e-3, 1 - k)); if (k >= 1) o.visible = false; });
    };
    S.point = (on, at) => {
      const v = new S.T.Vector3(...S.vec(at));
      return on ? S.bodies[on].frame.localToWorld(v) : v;
    };

    const c2 = Object.assign(Object.create(ctx), {scene: S});
    const nodes = (b.blocks || []).map(k => R.build(k, c2));
    const cv = el('canvas', {class: 'gl'}), leads = sv('svg', {class: 'leads', 'aria-hidden': 'true'}), chips = el('div', {class: 'chips'});
    const msg = el('p', {class: 'rk-note msg', hidden: true});
    const stage = el('div', {class: 'stage', tabindex: 0, role: 'group', 'aria-roledescription': '3D scene',
                             'aria-label': b.label || 'A 3D scene', style: `height: ${b.height ?? 380}px`}, cv, leads, chips, msg);
    const sr = el('ul', {class: 'rk-sr'});
    nodes.forEach(n => (n.classList.contains('rk-chip') ? chips : sr).append(n));

    const N = b.steps?.length || Math.max(1, ...(b.blocks || []).map(k => k.step || 1));
    const say = el('p', {class: 'say', 'aria-live': 'polite'}), count = el('span', {class: 'count'});
    const go = d => { if (b.bind) { const v = clamp(S.step() + d, 1, N); if (v !== S.step()) ctx.put(b, b.bind, v); } };
    const prev = el('button', {type: 'button', onclick: () => go(-1)}, 'Back', el('kbd', {text: 'A'}));
    const next = el('button', {type: 'button', onclick: () => go(1)}, 'Next', el('kbd', {text: 'D'}));
    const bar = b.bind ? el('div', {class: 'bar'}, prev, count, next) : null;

    const user = {az: 0, el: 0};
    const turn = (daz, del, now) => { user.az += daz; user.el = clamp(user.el + del, -20, 60); if (S.T) aim(frameOf(S.shot), now ? 0 : 260); };
    stage.addEventListener('keydown', e => {
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const k = e.key.toLowerCase();
      if (k === 'a' || k === 'arrowleft') go(-1);
      else if (k === 'd' || k === 'arrowright') go(1);
      else if (k === 'q') turn(-20, 0); else if (k === 'e') turn(20, 0);
      else if (k === 'w') turn(0, 10); else if (k === 's') turn(0, -10);
      else if (/^[1-9]$/.test(k) && b.bind && +k <= N) ctx.put(b, b.bind, +k);
      else return;
      e.preventDefault();
    });
    let held = null;
    stage.addEventListener('pointerdown', e => { held = [e.clientX, e.clientY]; stage.setPointerCapture(e.pointerId); });
    stage.addEventListener('pointermove', e => {
      if (!held) return;
      turn((e.clientX - held[0]) * .4, (e.clientY - held[1]) * .3, true); held = [e.clientX, e.clientY];
    });
    stage.addEventListener('pointerup', () => { held = null; });

    // three.js parts, made when the library is there.
    let rtM, mask, MW = 96, MH = 48;
    let T, gl, world, cam, post, postCam, rtC, rtN, floor, W = 0, H = 0, raf = 0, sig = '', pal;
    const view = {az: 35, el: 22, fov: 32, dist: 10, tx: 0, ty: 0, tz: 0};
    let tw = null;
    const kick = () => { if (!raf && gl) raf = requestAnimationFrame(frame); };

    function palette() {
      const g = v => R.rgb(stage, v).map(x => x / 255);
      const bg = g('--rk-bg'), fg = g('--rk-fg'), acc = g('--rk-acc'), ok = g('--rk-ok'), no = g('--rk-no');
      // On a dark page the parts take a dimmed paper, so a light part does not glare.
      const night = lum(bg) < lum(fg), paper = night ? mix(fg, bg, .25) : bg, ink = night ? bg : fg;
      const tint = c => mix(c, paper, night ? .35 : .62), deep = c => mix(c, paper, night ? .12 : .3);
      return {night, bg, floor: mix(bg, fg, night ? .07 : .05), shade: mix(ink, [0, 0, 0], .5), line: mix(ink, [0, 0, 0], night ? .7 : .3),
              body: mix(paper, ink, night ? .2 : .12), light: night ? mix(paper, fg, .3) : mix(paper, [1, 1, 1], .35), dark: mix(paper, ink, .4),
              glass: mix(mix(paper, ink, .45), acc, .12), acc: tint(acc), ok: tint(ok), no: tint(no), up: deep(ok), down: deep(no), side: deep(acc)};
    }
    const mats = {};
    const col = c => new T.Color().setRGB(c[0], c[1], c[2], T.SRGBColorSpace);
    const LIGHT = {value: null};
    S.mat = name => mats[name] ??= new T.ShaderMaterial({uniforms: {color: {value: col(pal[name] || pal.body)}, light: LIGHT},
                                                         vertexShader: TOON_V, fragmentShader: TOON_F});
    function recolor() {
      if (!T) return;
      pal = palette();
      for (const [k, m] of Object.entries(mats)) m.uniforms.color.value = col(pal[k] || pal.body);
      floor.material.uniforms.color.value = col(pal.floor);
      shadow.material.uniforms.color.value = col(pal.shade);
      post.material.uniforms.ink.value = col(pal.line); post.material.uniforms.bg.value = col(pal.bg);
      kick();
    }

    // The box of what shows: each visible mesh at its end state (animations at k = 1), without the floor and the shadows.
    const tmp = () => new T.Box3();
    function boxes(o, out = []) {
      o.updateWorldMatrix(true, true);
      o.traverseVisible(m => {
        if (!m.isMesh || m.userData.flat) return;
        m.geometry.boundingBox ?? m.geometry.computeBoundingBox();
        out.push(tmp().copy(m.geometry.boundingBox).applyMatrix4(m.matrixWorld));
      });
      return out;
    }
    const boxOf = o => boxes(o).reduce((a, x) => a.union(x), tmp());
    const corners = bx => [...Array(8)].map((_, i) => new T.Vector3(i & 1 ? bx.max.x : bx.min.x, i & 2 ? bx.max.y : bx.min.y, i & 4 ? bx.max.z : bx.min.z));
    function atEnd(f) {
      const as = [...S.anims.values()];
      as.forEach(a => a.f(1)); const r = f(); as.forEach(a => a.f(a.k));
      return r;
    }
    // The camera for a shot: its angles, and the distance at which what shows fits the view, with a margin for the chips.
    // It fits the corners of the box of each mesh (not one box of all), so a long, thin shape fills the view.
    function frameOf(name) {
      const close = name.startsWith('close:'), p = SHOTS[close ? 'close' : name] || SHOTS.wide;
      const pts = atEnd(() => {
        let bs = close && S.bodies[name.slice(6)] ? boxes(S.bodies[name.slice(6)].outer) : [];
        if (bs.length) bs = [bs.reduce((a, x) => a.union(x), tmp()).expandByScalar(S.size * .1)];   // a close shot keeps some room
        if (!bs.length) bs = boxes(world);
        const out = bs.flatMap(corners);
        if (!close) for (const q of parts) { const a = q.impl.anchor?.(q); if (a && S.live(q.b)) out.push(a); }
        return out;
      });
      if (!pts.length) pts.push(new T.Vector3(-1, -1, -1), new T.Vector3(1, 1, 1));
      const az = p.az + user.az, elv = clamp(p.el + user.el, -10, 89), a = rad(az), e = rad(elv);
      const c = pts.reduce((m, x) => m.add(x), new T.Vector3()).divideScalar(pts.length);
      const dir = new T.Vector3(Math.cos(e) * Math.sin(a), Math.sin(e), Math.cos(e) * Math.cos(a));
      const right = new T.Vector3().crossVectors(new T.Vector3(0, 1, 0), dir).normalize(), up = new T.Vector3().crossVectors(dir, right);
      const tv = Math.tan(rad(p.fov) / 2) * .8, th = tv * (W / H || 1);
      const fit = () => pts.reduce((D, x) => {
        const v = x.clone().sub(c), z = v.dot(dir);
        return Math.max(D, z + Math.abs(v.dot(right)) / th, z + Math.abs(v.dot(up)) / tv);
      }, .1);
      for (let i = 0; i < 2; i++) {   // move the centre to the middle of what shows, then fit again
        const D = fit(), xs = pts.map(x => { const v = x.clone().sub(c), z = D - v.dot(dir); return [v.dot(right) / z, v.dot(up) / z]; });
        const mid = k => (Math.min(...xs.map(q => q[k])) + Math.max(...xs.map(q => q[k]))) / 2;
        c.addScaledVector(right, mid(0) * D).addScaledVector(up, mid(1) * D);
      }
      return {az, el: elv, fov: p.fov, dist: fit(), tx: c.x, ty: c.y, tz: c.z};
    }
    function aim(to, ms) {
      if (still() || !ms || !W) { Object.assign(view, to); tw = null; }
      else tw = {from: {...view}, to, t0: performance.now(), ms};
      kick();
    }
    function place() {
      const a = rad(view.az), e = rad(view.el), size = view.dist;
      cam.fov = view.fov; cam.aspect = W / H || 1;
      cam.position.set(view.tx + size * Math.cos(e) * Math.sin(a), view.ty + size * Math.sin(e), view.tz + size * Math.cos(e) * Math.cos(a));
      cam.up.set(0, 1, 0); cam.lookAt(view.tx, view.ty, view.tz);
      cam.near = Math.max(.01, size - S.size * 3); cam.far = size + S.size * 6;
      cam.updateProjectionMatrix();
    }

    // The contact shadow: draw the parts from under the floor into a small target, blur it two times, and lay it on the floor.
    let shadow, shCam, shRT, shRT2, dark, blur, blurCam;
    function shade() {
      if (b.ground === false) return;
      const flat = [floor, shadow], vis = flat.map(o => o.visible);
      flat.forEach(o => { o.visible = false; });
      world.overrideMaterial = dark; gl.setRenderTarget(shRT); gl.setClearColor(0, 0); gl.clear(); gl.render(world, shCam);
      world.overrideMaterial = null;
      flat.forEach((o, i) => { o.visible = vis[i]; });
      const u = blur.children[0].material.uniforms;
      for (const r of [1.6, .8]) {
        u.map.value = shRT.texture; u.step.value.set(r / 512, 0); gl.setRenderTarget(shRT2); gl.render(blur, blurCam);
        u.map.value = shRT2.texture; u.step.value.set(0, r / 512); gl.setRenderTarget(shRT); gl.render(blur, blurCam);
      }
    }

    // Chips: each one goes to the first free place around its point, and keeps its place while that stays free.
    const DIRS = [-45, -135, 0, 180, 45, 135, -90, 90].map(d => [Math.cos(rad(d)), Math.sin(rad(d))]);
    const hit = (p, q, m) => p.x < q.x + q.w + m && q.x < p.x + p.w + m && p.y < q.y + q.h + m && q.y < p.y + p.h + m;
    // The leader of a chip: from its point to the nearest point of its box. Two leaders that cross are hard to follow.
    const lead = (it, bx) => [[it.x, it.y], [clamp(it.x, bx.x, bx.x + bx.w), clamp(it.y, bx.y, bx.y + bx.h)]];
    const side = (p, q, r) => Math.sign((q[0] - p[0]) * (r[1] - p[1]) - (q[1] - p[1]) * (r[0] - p[0]));
    const cross = ([a, b], [c, d]) => side(a, b, c) * side(a, b, d) < 0 && side(c, d, a) * side(c, d, b) < 0;
    function layout() {
      const placed = [], items = [], segs = [];
      for (const q of parts) {
        if (!q.node.classList.contains('rk-chip')) continue;
        const a = q.node.hidden || !S.live(q.b) ? null : q.impl.anchor?.(q);
        let it = null;
        if (a) {
          const v = a.clone().project(cam);
          if (v.z > -1 && v.z < 1) it = {q, x: (v.x + 1) / 2 * W, y: (1 - v.y) / 2 * H, w: q.node.offsetWidth, h: q.node.offsetHeight};
        }
        if (it && it.w) items.push(it); else off(q);
      }
      const free = (bx, it, strict) => bx.x >= 4 && bx.y >= 4 && bx.x + bx.w <= W - 4 && bx.y + bx.h <= H - 4 && !placed.some(p => hit(bx, p, 6))
        && (!strict || (!items.some(o => o !== it && o.x > bx.x - 5 && o.x < bx.x + bx.w + 5 && o.y > bx.y - 5 && o.y < bx.y + bx.h + 5)
                        && !segs.some(s => cross(s, lead(it, bx)))));
      const mid = new T.Vector3(view.tx, view.ty, view.tz).project(cam), mx = (mid.x + 1) / 2 * W, my = (1 - mid.y) / 2 * H;
      for (const it of items) {
        const at = ([dx, dy]) => ({x: it.x + dx - it.w / 2, y: it.y + dy - it.h / 2, w: it.w, h: it.h, d: [dx, dy]});
        const tries = [], ox = it.x - mx, oy = it.y - my, on = Math.hypot(ox, oy) || 1;
        const out = d => (d[0] * ox + d[1] * oy) / on - d[1] * .35;   // away from the middle, and a little up
        const dirs = [...DIRS].sort((p, q) => out(q) - out(p));
        if (it.q.d) tries.push(it.q.d);
        for (const r of [30, 54, 84, 124, 170]) for (const [cx, cy] of dirs) {
          const ext = Math.abs(cx) * it.w / 2 + Math.abs(cy) * it.h / 2;
          tries.push([cx * (r + ext), cy * (r + ext)]);
        }
        // A chip must not cover a part. So the first free place that covers almost no part wins, and a place with no dot
        // under it and no crossed leader wins over one with them. If each free place covers a part, the one that covers the least wins.
        const ok = tries.map(at).filter(x => free(x, it, false)), cs = ok.map(cover), clear = ok.filter((x, i) => cs[i] < .03);
        const bx = clear.find(x => free(x, it, true)) || clear[0] || ok[cs.indexOf(Math.min(...cs))];
        if (!bx) { off(it.q); continue; }
        placed.push(bx); segs.push(lead(it, bx)); it.q.d = bx.d;
        it.q.node.style.transform = `translate(${bx.x.toFixed(1)}px, ${bx.y.toFixed(1)}px)`;
        it.q.node.classList.remove('off');
        const ln = it.q.ln ??= leads.appendChild(sv('g', {}, sv('line'), sv('circle', {r: 2.6})));
        const [, [ex, ey]] = lead(it, bx), [l, c] = ln.children;
        l.setAttribute('x1', it.x); l.setAttribute('y1', it.y); l.setAttribute('x2', ex); l.setAttribute('y2', ey);
        c.setAttribute('cx', it.x); c.setAttribute('cy', it.y);
        ln.style.display = '';
      }
    }
    // The share of a box that covers a part, from a small mask of the parts that draw() reads each frame.
    function cover(bx) {
      if (!mask) return 0;
      const sx = MW / W, sy = MH / H, i0 = Math.max(0, Math.floor(bx.x * sx)), i1 = Math.min(MW, Math.ceil((bx.x + bx.w) * sx));
      const j0 = Math.max(0, Math.floor(bx.y * sy)), j1 = Math.min(MH, Math.ceil((bx.y + bx.h) * sy));
      let n = 0, t = 0;
      for (let j = j0; j < j1; j++) for (let i = i0; i < i1; i++) { t++; if (mask[((MH - 1 - j) * MW + i) * 4] > 127) n++; }
      return t ? n / t : 0;
    }
    function off(q) { q.node.classList.add('off'); q.d = null; if (q.ln) q.ln.style.display = 'none'; }

    function frame(now) {
      raf = 0;
      if (!stage.isConnected) { gone(); return; }
      for (const [k, a] of S.anims) {
        a.k = a.ease((now - a.t0) / a.ms); a.f(a.k);
        if (now - a.t0 >= a.ms) S.anims.delete(k);
      }
      if (tw) {
        const k = inout((now - tw.t0) / tw.ms), f = tw.from, t = tw.to, daz = ((t.az - f.az) % 360 + 540) % 360 - 180;
        for (const key of ['el', 'fov', 'dist', 'tx', 'ty', 'tz']) view[key] = f[key] + (t[key] - f[key]) * k;
        view.az = f.az + daz * k;
        if (k >= 1) tw = null;
      }
      draw();
      if (S.anims.size || tw) kick();
      stage.dataset.rkStill = S.anims.size || tw ? '0' : '1';
    }
    function draw() {
      if (!W || !H) return;
      place();
      world.updateMatrixWorld(true);
      for (const q of parts) q.impl.frame?.(q);
      world.updateMatrixWorld(true);
      shade();
      LIGHT.value.set(-.45, .78, .45).normalize();
      const flat = [floor, shadow], vis = flat.map(o => o.visible);
      flat.forEach(o => { o.visible = false; });
      world.overrideMaterial = S.normal; gl.setRenderTarget(rtN); gl.setClearColor(0, 0); gl.clear(); gl.render(world, cam);
      world.overrideMaterial = S.white; gl.setRenderTarget(rtM); gl.setClearColor(0, 1); gl.clear(); gl.render(world, cam);
      gl.readRenderTargetPixels(rtM, 0, 0, MW, MH, mask);
      flat.forEach((o, i) => { o.visible = vis[i]; });
      world.overrideMaterial = null; gl.setRenderTarget(rtC); gl.setClearColor(col(pal.bg), 1); gl.clear(); gl.render(world, cam);
      const u = post.material.uniforms;
      u.near.value = cam.near; u.far.value = cam.far;
      gl.setRenderTarget(null); gl.render(S.pass, postCam);
      layout();
    }
    function gone() { if (gl) { gl.dispose(); gl.forceContextLoss(); gl = null; } }
    function resize() {
      const pr = Math.min(2, devicePixelRatio || 1);
      W = stage.clientWidth; H = stage.clientHeight;
      if (!W || !H || !gl) return;
      gl.setPixelRatio(pr); gl.setSize(W, H, false);
      rtC.setSize(W * pr, H * pr); rtN.setSize(W * pr, H * pr);
      MH = Math.max(8, Math.round(MW * H / W)); rtM.setSize(MW, MH); mask = new Uint8Array(MW * MH * 4);
      post.material.uniforms.texel.value.set(1 / (W * pr), 1 / (H * pr)); post.material.uniforms.w.value = 1.1 * pr;
      aim(frameOf(S.shot), 0);
    }

    function start(lib) {
      T = S.T = lib;
      gl = new T.WebGLRenderer({canvas: cv, antialias: false, preserveDrawingBuffer: true, powerPreference: 'low-power'});
      LIGHT.value = new T.Vector3();
      pal = palette();
      world = new T.Scene(); S.world = world;
      cam = new T.PerspectiveCamera(32, 1, .1, 100);
      S.normal = new T.MeshNormalMaterial(); S.white = new T.MeshBasicMaterial({color: 0xffffff});
      rtM = new T.WebGLRenderTarget(MW, MH);
      for (const q of parts) q.obj = q.impl.make?.(T, q) ?? null;
      world.updateMatrixWorld(true);
      const all = boxOf(world);
      if (all.isEmpty()) all.set(new T.Vector3(-1, -1, -1), new T.Vector3(1, 1, 1));
      S.size = all.getSize(new T.Vector3()).length();
      S.floor = b.floor ?? all.min.y;
      S.unit = S.size / 40;
      const mags = parts.filter(q => q.b.type === 'force').map(q => Math.abs(S.num(q.b.mag))).filter(Number.isFinite);
      S.scale = b.scale ?? (mags.length && Math.max(...mags) ? S.size * .3 / Math.max(...mags) : 1);
      const flatMat = (frag, u) => new T.ShaderMaterial({uniforms: u, vertexShader: FLAT_V, fragmentShader: frag, transparent: true, depthWrite: false});
      floor = new T.Mesh(new T.PlaneGeometry(1, 1), flatMat(FLOOR_F, {color: {value: col(pal.floor)}}));
      floor.rotation.x = -Math.PI / 2; floor.userData.flat = true;
      const c = all.getCenter(new T.Vector3()), r = Math.max(all.max.x - all.min.x, all.max.z - all.min.z, S.size * .5) * 2.4;
      floor.position.set(c.x, S.floor, c.z); floor.scale.set(r * 1.4, r * 1.4, 1); floor.visible = b.ground !== false;
      world.add(floor);
      const sr = r * .5, fade = S.size * .35;
      shRT = new T.WebGLRenderTarget(512, 512); shRT2 = new T.WebGLRenderTarget(512, 512);
      shCam = new T.OrthographicCamera(-sr, sr, sr, -sr, 0, fade);
      shCam.position.set(c.x, S.floor, c.z); shCam.rotation.x = Math.PI / 2; shCam.updateMatrixWorld();
      dark = new T.ShaderMaterial({uniforms: {floor: {value: S.floor}, fade: {value: fade}}, vertexShader: DARK_V, fragmentShader: DARK_F, side: T.DoubleSide});
      shadow = new T.Mesh(new T.PlaneGeometry(2 * sr, 2 * sr),
                          flatMat(SHADOW_F, {color: {value: col(pal.shade)}, alpha: {value: .62}, map: {value: shRT.texture}}));
      shadow.rotation.x = -Math.PI / 2; shadow.position.set(c.x, S.floor + S.size * 1e-3, c.z);
      shadow.userData.flat = true; shadow.renderOrder = 1; shadow.visible = b.ground !== false;
      world.add(shadow);
      const quad = new T.Mesh(new T.PlaneGeometry(2, 2), new T.ShaderMaterial({uniforms: {map: {value: null}, step: {value: new T.Vector2()}},
        vertexShader: POST_V, fragmentShader: BLUR_F, depthTest: false, depthWrite: false}));
      quad.frustumCulled = false; blur = new T.Scene(); blur.add(quad); blurCam = new T.OrthographicCamera(-1, 1, 1, -1, 0, 1);
      rtC = new T.WebGLRenderTarget(1, 1, {samples: 4, type: T.HalfFloatType});
      rtN = new T.WebGLRenderTarget(1, 1, {depthTexture: new T.DepthTexture(1, 1)});
      post = new T.Mesh(new T.PlaneGeometry(2, 2), new T.ShaderMaterial({
        uniforms: {tC: {value: rtC.texture}, tN: {value: rtN.texture}, tD: {value: rtN.depthTexture}, texel: {value: new T.Vector2()},
                   w: {value: 1}, near: {value: .1}, far: {value: 100}, ink: {value: col(pal.line)}, bg: {value: col(pal.bg)}},
        vertexShader: POST_V, fragmentShader: POST_F, depthTest: false, depthWrite: false}));
      postCam = new T.OrthographicCamera(-1, 1, 1, -1, 0, 1);
      const pass = new T.Scene(); pass.add(post); post.frustumCulled = false; S.pass = pass;
      sync();
      new ResizeObserver(() => { resize(); kick(); }).observe(stage);
      onTheme(() => { if (stage.isConnected) { recolor(); return true; } gone(); return false; });
      stage.dataset.rkGl = 'ready';
    }

    // On each change of the state: the step bar, then each part, then the shot.
    function sync() {
      if (b.bind) {
        const k = S.step();
        count.textContent = `Step ${Math.min(k, N)} of ${N}`;
        prev.disabled = k <= 1 || !ctx.live(b.lock); next.disabled = k >= N || !ctx.live(b.lock);
        if (b.steps) say.textContent = fmt(b.steps[clamp(k, 1, N) - 1], s.st);
      }
      if (!T) return;
      for (const q of parts) { q.impl.sync?.(q, S.live(q.b)); q.node.toggleAttribute('aria-hidden', !S.live(q.b)); }
      // The newest shot wins: a shot that starts to show, or a bound shot whose name changes. When it goes, the last shot that shows wins.
      const shots = parts.filter(q => q.b.type === 'shot');
      for (const q of shots) { const v = S.live(q.b) ? q.impl.name() : null; if (v !== q.was && v != null) S.cur = q; q.was = v; }
      if (!S.cur || !S.live(S.cur.b)) S.cur = shots.findLast(q => S.live(q.b));
      const shot = S.cur?.impl.name(), name = isShot(shot, ids) ? shot : (S.shot || 'wide');
      const now = parts.map(q => S.live(q.b) ? 1 : 0).join('') + name;
      if (now !== sig) {
        const moved = name !== S.shot;
        if (moved) { user.az = 0; user.el = 0; }
        S.shot = name; stage.dataset.rkShot = name;
        aim(frameOf(name), sig ? (moved ? 1300 : 800) : 0);
        sig = now;
      }
      kick();
    }
    s.on(sync);
    (scenes.get(s) || scenes.set(s, []).get(s)).push(S);

    R.need('three').then(lib => {
      try { start(lib); }
      catch (e) { console.error('rupaka: scene', e); msg.hidden = false; msg.textContent = 'This browser cannot draw the 3D view.'; stage.dataset.rkGl = 'error'; }
    }, e => { console.error('rupaka: scene', e); msg.hidden = false; msg.textContent = `The 3D view could not load: ${e.message}`; stage.dataset.rkGl = 'error'; });
    return el('div', {}, R.label(b), stage, b.steps ? say : null, bar, sr);
  });
})();

/* blocks/shot/shot.js */
/* shot: the camera of a scene. `name` is a fixed shot, or `bind` is the state key that holds the shot name. The scene uses the
   last shot that shows, and it moves the camera to it with easing. The scene finds the framing from the bounds of what shows. */
Rupaka.block('shot', (b, ctx) => {
  const S = ctx.scene;
  if (!S) throw new Error('a shot must be inside a scene');
  const name = () => b.name ?? ctx.s.get(b.bind), node = Rupaka.el('li');
  ctx.s.on(() => { node.textContent = `The camera: ${name()}`; });
  return S.part(b, {name}, node);
});

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
