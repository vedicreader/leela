/* static/rupaka.js */
/* rupaka core: a demo is a JSON spec of blocks over one small state. Named fns compute derived values.
   No network, no eval, no dependencies. Blocks and fns register with Rupaka.block and Rupaka.fn; boot.js mounts every [data-rupaka]. */
(() => {
  if (window.Rupaka && window.Rupaka.core) return;   // the bundle came in twice (an htmx swap): keep the first copy
  const R = window.Rupaka = {blocks: {}, fns: {}, core: true, version: '0.0.21', schema: 1};   // bundle() writes in rupaka.__version__
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
  // A rich text: **bold** goes in a <strong>, and `st` fills {path} in each part. A ** inside $maths$, or with no pair, stays as it is.
  const rich = (s, st) => {
    const ps = String(s ?? '').split(/(\$\$[\s\S]*?\$\$|\$[^$\n]+\$|\*\*)/), out = [], f = t => st ? fmt(t, st) : t;
    let buf = '', at = -1;
    ps.forEach((t, i) => {
      if (t !== '**') { buf += t; return; }
      if (at < 0) { if (ps.slice(i + 1).includes('**')) { if (buf) out.push(f(buf)); buf = ''; at = i; } else buf += t; return; }
      out.push(el('strong', {text: f(buf)})); buf = ''; at = -1;
    });
    if (buf) out.push(f(buf));
    return out;
  };
  const hide = (n, h) => { if (n instanceof SVGElement) n.style.display = h ? 'none' : ''; else n.hidden = h; };

  Object.assign(R, {el, sv, get, fmt, rich, show, hide, block: (name, f) => { R.blocks[name] = f; }, fn: (name, f) => { R.fns[name] = f; }});
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
  R.ownStep = new Set(['body', 'drift', 'force', 'grid', 'label3d', 'layer', 'links', 'path', 'point', 'points', 'shot', 'slider', 'timeline', 'wheel']);
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
                 step: () => s.st.step == null ? Infinity : +s.st.step,   // with no step key, each part shows
                 media: host.closest?.('[data-rk-media]')?.getAttribute('data-rk-media') ?? 'media/'};   // the base URL of profile assets
    ctx.build = b => build(b, ctx);
    // Each block has a stable id: its path in the spec, such as 'blocks.2' or 'blocks.0.blocks.1'. A part adds its own path: 'blocks.2.cells.0'.
    ctx.tag = (b, p) => { if (b && typeof b === 'object') { ctx.ids.set(b, p); (b.blocks || []).forEach((k, i) => ctx.tag(k, `${p}.blocks.${i}`)); } };
    ctx.id = (b, part) => { const p = ctx.ids.get(b); return p == null ? null : part == null ? p : `${p}.${part}`; };
    (spec.blocks || []).forEach((b, i) => ctx.tag(b, `blocks.${i}`));
    ctx.put = (b, k, val) => { if (!ctx.live(b.lock)) return false; s.set(k, val); return true; };   // a locked control refuses
    if (spec.mode === 'learn') { root.dataset.rkMode = 'learn'; root.append(el('p', {class: 'rk-mode', text: 'Explainer'})); }   // no gate, so no prediction step
    if (spec.title) root.append(el('h3', {class: 'rk-title', text: spec.title}));
    if (spec.ask) root.append(el('p', {class: 'rk-ask'}, rich(spec.ask)));
    root.append(...(spec.blocks || []).map(ctx.build));
    if (askable(host, spec, opts)) root.append(ctx.asker = asker(ctx));
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
    list.push(b); at.insertBefore(node, into ? null : ctx.asker ?? null); s.emit('*');
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

  // An ask carries only what the demo has now: the input keys (clipped), the step or the first open gate, and the learner's words.
  // It never carries DOM or HTML. As with rk-predict, a host that takes the ask calls preventDefault.
  const CLIP = {text: 500, str: 200, items: 50, depth: 3};
  const clip = (v, d = 0) => typeof v === 'string' ? v.slice(0, CLIP.str) : typeof v === 'number' ? (Number.isFinite(v) ? v : null)
    : typeof v === 'boolean' ? v : v == null || d >= CLIP.depth || typeof v !== 'object' ? null
    : Array.isArray(v) ? v.slice(0, CLIP.items).map(x => clip(x, d + 1))
    : Object.fromEntries(Object.entries(v).slice(0, CLIP.items).map(([k, x]) => [k.slice(0, CLIP.str), clip(x, d + 1)]));
  const asked = (ctx, text) => {
    const st = ctx.s.st, g = (ctx.gates || []).find(g => !g.done());
    return {demo: clip(ctx.spec.id ?? null), text: String(text ?? '').trim().slice(0, CLIP.text),
            state: Object.fromEntries(inputs(ctx.spec).slice(0, CLIP.items).map(k => [k, clip(st[k], 1)])),
            step: st.step != null ? clip(st.step, 1) : g ? g.id : null};
  };
  R.ask = (host, text) => {
    const ctx = CTX.get(mounted(host));
    return ctx.root.dispatchEvent(new CustomEvent('rk-ask', {bubbles: true, composed: true, cancelable: true, detail: asked(ctx, text)}));
  };
  // The host switch (opts.askable, or data-rk-askable="true" or "false" on the host) comes first, then the spec, then on.
  const askable = (host, spec, opts) => opts?.askable ?? {true: true, false: false}[host.dataset?.rkAskable] ?? spec.askable !== false;
  function asker(ctx) {
    const field = el('input', {type: 'text', maxlength: CLIP.text, 'aria-label': 'Your question', placeholder: 'What do you want to know? You can leave this empty.'});
    const said = el('p', {class: 'rk-note', 'aria-live': 'polite', hidden: true});
    const form = el('form', {hidden: true}, field, el('button', {type: 'submit', text: 'Ask'}));
    const open = el('button', {type: 'button', class: 'rk-askopen', text: 'Ask about this', 'aria-expanded': 'false'});
    const toggle = o => { form.hidden = !o; open.setAttribute('aria-expanded', String(o)); if (o) { said.hidden = true; field.focus(); } };
    open.onclick = () => toggle(form.hidden);
    form.onsubmit = e => {
      e.preventDefault();
      const took = !R.ask(ctx.root.parentNode, field.value);
      field.value = ''; toggle(false); open.focus();
      said.textContent = took ? 'Sent to the tutor.' : 'No tutor is on this page.'; said.hidden = false;
    };
    field.addEventListener('keydown', e => {
      e.stopPropagation();   // ⌘↩ in the field sends the ask; it does not lock in a gate
      if (e.key === 'Escape') { toggle(false); open.focus(); }
      else if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); form.requestSubmit(); }
    });
    return el('div', {class: 'rk-asker'}, open, form, said);
  }

  R.boot = (scope = document) => scope.querySelectorAll('[data-rupaka]:not([data-rk-ready])').forEach(n => {
    const src = n.querySelector('script[type="application/json"]');
    try { R.mount(n, JSON.parse(src ? src.textContent : n.dataset.rupaka)); }
    catch (e) { console.error('rupaka:', e); n.dataset.rkReady = 'error'; n.replaceChildren(el('p', {class: 'rk-err', text: `This demo could not draw: ${e.message}`})); }
  });
})();

/* fns/bubble.js */
/* bubble: one step of a bubble sort of a list. Step 0 is the list as given, and step k is the list after the k-th compare.
   A demo reads each view (bars, counts, code line) from this one row, so the views always show the same run at the same step. */
Rupaka.fn('bubble', (d, st) => {
  const a = [...(Rupaka.get(st, d.from) || [])], n = a.length, last = n * (n - 1) / 2, x = Math.floor(Rupaka.num(d.at, st, 0));
  const k = Number.isFinite(x) ? Math.min(last, Math.max(0, x)) : 0;
  let comps = 0, swaps = 0, j = -1, left = null, right = null, swap = false;
  for (let i = 0; i < n - 1; i++) for (let q = 0; q < n - 1 - i && comps < k; q++) {
    comps++; j = q; left = a[q]; right = a[q + 1]; swap = left > right;
    if (swap) { a[q] = right; a[q + 1] = left; swaps++; }
  }
  const line = comps === 0 ? 1 : swap ? 4 : 3, did = comps === 0 ? 'start' : swap ? 'swap' : 'keep';
  return {step: k, last, list: a, bars: a.map((v, i) => ({id: `a[${i}]`, value: v, parts: j >= 0 && (i === j || i === j + 1) ? [v, 0] : [0, v]})),
          j, left, right, swap, did, cmp: comps === 0 ? '' : `${left} ${swap ? '>' : '≤'} ${right}`, comps, swaps, line,
          mark: [1, 2, 3, 4].map(l => l === line ? '▶' : '·')};
});

/* fns/ease.js */
/* ease: a number moved from 0 to 1 along a curve (linear, in, out, inout, step). The curves are in Rupaka.EASE, and keyframes uses them too. */
(() => {
  const EASE = {linear: u => u, in: u => u * u, out: u => 1 - (1 - u) * (1 - u), inout: u => u < .5 ? 2 * u * u : 1 - (2 - 2 * u) * (2 - 2 * u) / 2, step: u => u < 1 ? 0 : 1};
  Rupaka.EASE = EASE;
  Rupaka.num = (v, st, d) => v == null ? d : typeof v === 'number' ? v : +Rupaka.get(st, v);
  Rupaka.fn('ease', (d, st) => {
    const [a, b] = d.over || [0, 1], kind = d.kind || 'linear';
    if (!Object.hasOwn(EASE, kind)) throw new Error(`ease: "${kind}" is not a curve`);
    return EASE[kind](Math.min(1, Math.max(0, (Rupaka.num(d.in, st) - a) / (b - a))));
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

/* fns/keyframes.js */
/* keyframes: the value at time `in` from [[t, v], ...] keys that go up in t. Before the first key it holds the first value, after the last key the last.
   Each segment eases from its own key: [t, v, 'out'] sets the curve of that segment; `ease` is the default (linear). */
Rupaka.fn('keyframes', (d, st) => {
  const ks = d.keys, x = Rupaka.num(d.in, st), E = Rupaka.EASE;
  if (!Array.isArray(ks) || !ks.length) throw new Error('keyframes: needs a list of [t, value] keys');
  if (x <= ks[0][0]) return ks[0][1];
  const i = ks.findIndex(k => x < k[0]);
  if (i < 0) return ks[ks.length - 1][1];
  const [t0, v0, e] = ks[i - 1], [t1, v1] = ks[i], kind = e || d.ease || 'linear';
  if (!Object.hasOwn(E, kind)) throw new Error(`keyframes: "${kind}" is not a curve`);
  return v0 + (v1 - v0) * E[kind]((x - t0) / (t1 - t0));
});

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

/* fns/signal.js */
/* sample and dft: signals from a formula in time. `sample` takes the value at each tick of a rate; `dft` gives the strength of each whole frequency.
   Both read the formula with Rupaka.expr, so there is no eval. The Python twins are in nbs/00_spec.ipynb. */
(() => {
  const cache = {}, f_of = src => cache[src] ||= Rupaka.expr(src), num = (d, st, k) => +(typeof d[k] === 'number' ? d[k] : st[d[k]]);
  // sample: the points {x, y} of the formula at x = lo, lo + 1/rate, ... up to hi, with `over: {"t": [lo, hi]}`.
  Rupaka.fn('sample', (d, st) => {
    const f = f_of(d.expr), [name, [lo, hi]] = Object.entries(d.over)[0], rate = num(d, st, 'rate');
    if (!(rate > 0)) throw new Error('sample: rate must be above 0');
    const n = Math.floor((hi - lo) * rate + 1e-9) + 1;
    if (n > 4000) throw new Error('sample: more than 4000 points');
    return Array.from({length: n}, (_, k) => { const x = lo + k / rate; return {x, y: f({...st, [name]: x})}; });
  });
  // dft: the amplitude of each frequency k / (hi - lo) for k = 0 .. upto, from n ticks of the formula over [lo, hi) with `over: {"t": [lo, hi, n]}`.
  Rupaka.fn('dft', (d, st) => {
    const f = f_of(d.expr), [name, [lo, hi, n = 64]] = Object.entries(d.over)[0], T = hi - lo, up = Math.min(d.upto ?? n / 2, Math.floor(n / 2));
    const ys = Array.from({length: n}, (_, i) => f({...st, [name]: lo + T * i / n}));
    return Array.from({length: up + 1}, (_, k) => {
      let re = 0, im = 0;
      ys.forEach((y, i) => { const a = 2 * Math.PI * k * i / n; re += y * Math.cos(a); im -= y * Math.sin(a); });
      return {id: String(k / T), value: Math.hypot(re, im) / n * (k === 0 || 2 * k === n ? 1 : 2)};
    });
  });
})();

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

/* blocks/arrow/arrow.js */
/* arrow: a straight arrow on its axis, from `from` to `to` ([x, y]; an item can be a state key). It uses the scale of the axis (ctx.plane).
   The head is a filled triangle with its tip at `to`; its size grows with `width`. With `head` false it is a plain bar, for a beam or a distance. The line stops under the head, so a dashed line
   does not show through it. The label sits past the tip, so it does not cover the line. An arrow of zero length draws nothing. */
Rupaka.block('arrow', (b, ctx) => {
  const {sv, fmt} = Rupaka, s = ctx.s, P = ctx.plane;
  if (!P) throw new Error('an arrow must be inside an axis');
  const w = b.width ?? 2.5, from = b.from || [0, 0], to = b.to || [0, 0];
  const line = sv('line', {class: 'ln', 'stroke-width': w, ...b.dash ? {'stroke-dasharray': `${(w * 2.4).toFixed(1)} ${(w * 2).toFixed(1)}`} : {}});
  const head = sv('path', {class: 'hd'}), txt = sv('text', {class: 'al'});
  const g = sv('g', {role: 'img'}, sv('g', {'clip-path': P.clip}, line, head), txt);
  g.classList.add(`t-${b.tone || 'acc'}`);
  const val = v => typeof v === 'string' ? +s.get(v) : +v, f = n => n.toFixed(2);
  const parts = [line, head, txt], off = empty => { parts.forEach(n => n.style.display = 'none'); g.toggleAttribute('data-rk-empty', empty); };   // empty: nothing to draw on purpose, so check does not call it a broken block
  s.on(() => {
    const label = b.label ? fmt(b.label, s.st) : '';
    g.setAttribute('aria-label', label || 'arrow');
    const [x0, y0] = from.map(val), [x1, y1] = to.map(val);
    if (b.show && !s.get(b.show)) return off(true);
    if (![x0, y0, x1, y1].every(Number.isFinite)) return off(false);   // a bad value is a fault, and check says so
    const ax = P.X(x0), ay = P.Y(P.line ? 0 : y0), tx = P.X(x1), ty = P.Y(P.line ? 0 : y1), dx = tx - ax, dy = ty - ay, len = Math.hypot(dx, dy);
    if (len < 0.5) return off(true);   // zero length: no direction, so no line and no head
    parts.forEach(n => n.style.display = ''); g.removeAttribute('data-rk-empty'); if (b.head === false) head.style.display = 'none';
    const ux = dx / len, uy = dy / len, hl = b.head === false ? 0 : Math.min(4 + w * 4, len * 0.6), hw = hl * 0.45;   // the head: its length and its half width
    const bx = tx - ux * hl, by = ty - uy * hl, cut = Math.max(0, len - hl * 0.85);   // the middle of the base; the line ends under the head
    Object.entries({x1: ax, y1: ay, x2: ax + ux * cut, y2: ay + uy * cut}).forEach(([k, v]) => line.setAttribute(k, f(v)));
    head.setAttribute('d', `M${f(tx)} ${f(ty)}L${f(bx - uy * hw)} ${f(by + ux * hw)}L${f(bx + uy * hw)} ${f(by - ux * hw)}Z`);
    // The label of an arrow goes past the tip, on the far side from the tail. The label of a bar goes at its middle, above it,
    // as on a drawing. Both stay inside the drawing.
    txt.textContent = label;
    const bar = b.head === false, up = ux >= 0 ? 1 : -1;   // (up·uy, −up·ux) is the normal of the bar that points up the screen
    const lx = bar ? (ax + tx) / 2 + up * uy * 9 : tx + ux * 8, ly = bar ? (ay + ty) / 2 - up * ux * 9 + 4 : ty + uy * 8 + (uy < -0.5 ? -4 : uy > 0.5 ? 14 : 5);
    txt.setAttribute('text-anchor', bar || Math.abs(ux) <= 0.35 ? 'middle' : ux > 0 ? 'start' : 'end');
    txt.setAttribute('x', f(Math.min(P.W - 4, Math.max(4, lx)))); txt.setAttribute('y', f(Math.min(P.H - 4, Math.max(14, ly))));
  });
  return g;
});

/* blocks/axis/axis.js */
/* axis: a number line (no y) or x/y axes with ticks. Child blocks (point, plot, arrow) draw on its shared scale. */
(() => {
  let seq = 0;
  const nice = (lo, hi, want) => { const raw = (hi - lo) / want, p = 10 ** Math.floor(Math.log10(raw)), m = raw / p;
    return (m < 1.5 ? 1 : m < 3 ? 2 : m < 7 ? 5 : 10) * p; };
  const ticks = (lo, hi, st) => { const out = []; for (let v = Math.ceil(lo / st - 1e-9) * st; v <= hi + 1e-9; v += st) out.push(+v.toFixed(10)); return out; };
  // Which ticks get a label: every k-th tick from 0 (or from the first tick when 0 is not a tick), out in both directions. k is the
  // smallest step at which no two labels meet (`size(i)` is the width of label i in SVG units) and the label step is round:
  // 1, 2 or 5 × 10ⁿ, or a whole number when the ticks are whole. An end tick off this grid gets a label only when it has room.
  // The SVG scales as one, so this holds at any width.
  const every = (vs, ps, size, gap = 6) => {
    const n = vs.length - 1, st = vs[1] - vs[0], z = vs.findIndex(v => Math.abs(v) < 1e-9), i0 = Math.max(z, 0);
    if (n < 1) return vs.map(() => true);
    const fits = (i, j) => Math.abs(ps[j] - ps[i]) >= (size(i) + size(j)) / 2 + gap, on = k => (i => (i - i0) % k === 0);
    const clash = k => vs.some((_, i) => on(k)(i) && i + k <= n && !fits(i, i + k));
    const round = k => { const q = +(k * st).toFixed(10), m = q / 10 ** Math.floor(Math.log10(q) + 1e-9);
      return Number.isInteger(+st.toFixed(10)) || [1, 2, 5, 10].some(x => Math.abs(m - x) < 1e-6); };
    let k = 1;
    while (k <= n && (clash(k) || !round(k))) k++;
    if (k > n) { k = 1; while (k < n && clash(k)) k++; }
    const out = vs.map((_, i) => on(k)(i));
    if (!out[0]) out[0] = fits(0, out.indexOf(true));
    if (!out[n]) out[n] = fits(out.lastIndexOf(true), n);
    return out;
  };
  Rupaka.block('axis', (b, ctx) => {
    const {el, sv, show} = Rupaka, [x0, x1] = b.x || [-5, 5], line = !b.y, [y0, y1] = b.y || [0, 1], noy = !line && b.yaxis === false;   // noy: a side view, with the x scale only
    const W = 600, H = line ? 80 : (b.height || 360), L = line || noy ? 16 : 40, Rm = 16, T = line ? 30 : 12, B = line ? 30 : 28;
    const X = v => L + (v - x0) / (x1 - x0) * (W - L - Rm), Y = v => line ? T : T + (y1 - v) / (y1 - y0) * (H - T - B);
    const plane = {X, Y, line, W, H, x: [x0, x1], y: [y0, y1], invX: px => x0 + (px - L) / (W - L - Rm) * (x1 - x0), invY: py => y1 - (py - T) / (H - T - B) * (y1 - y0)};
    const id = `rk-clip-${++seq}`;
    const svg = sv('svg', {viewBox: `0 0 ${W} ${H}`, role: 'group', 'aria-label': b.label || 'axes'});
    plane.svg = svg; plane.clip = `url(#${id})`;
    const g = sv('g', {class: 'grid'});
    const xs = ticks(x0, x1, b.xstep || (b.xlog ? 1 : nice(x0, x1, 10))), ys = line || noy ? [] : ticks(y0, y1, b.ystep || nice(y0, y1, 8));
    const ax = line ? T : Y(Math.min(y1, Math.max(y0, 0))), ay = X(Math.min(x1, Math.max(x0, 0)));
    const xl = xs.map(v => b.xlog ? (v >= 3 ? `${show(10 ** (v - 3), 3)}k` : show(10 ** v, 3)) : show(v, 3)), xon = every(xs, xs.map(X), i => 7.5 * xl[i].length), yon = every(ys, ys.map(Y), () => 13, 2);
    xs.forEach((v, i) => { g.append(sv('line', {class: v === 0 && !line ? 'zero' : 'hair', x1: X(v), x2: X(v), y1: line ? T - 5 : T, y2: line ? T + 5 : H - B}),
      ...xon[i] ? [sv('text', {class: 'num', x: X(v), y: line ? T + 22 : H - B + 18, 'text-anchor': 'middle', text: xl[i]})] : []); });
    ys.forEach((v, i) => { g.append(sv('line', {class: v === 0 ? 'zero' : 'hair', x1: L, x2: W - Rm, y1: Y(v), y2: Y(v)}),
      ...yon[i] ? [sv('text', {class: 'num', x: L - 6, y: Y(v) + 4, 'text-anchor': 'end', text: show(v, 3)})] : []); });
    g.append(sv('line', {class: 'main', x1: L, x2: W - Rm, y1: ax, y2: ax}));
    if (!line && !noy) g.append(sv('line', {class: 'main', x1: ay, x2: ay, y1: T, y2: H - B}));
    if (b.xlabel) g.append(sv('text', {class: 'axl', x: W - Rm, y: line ? T - 10 : ax - 8, 'text-anchor': 'end', text: b.xlabel}));
    if (b.ylabel && !line && !noy) g.append(sv('text', {class: 'axl', x: ay + 8, y: T + 12, text: b.ylabel}));
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
/* body: one part of a scene: a shape, or a group that holds bodies. `in` nests it; `at` is in the frame of its parent; `rot` turns it about `pivot`.
   A state key in at, rot, scale, angle, t or arc moves it. `texture` wraps earth, moon or a live sun; `glow` adds a halo; `light` makes it a lamp.
   `drag` gives a grip that writes the state key `to`: an angle (orbit) or a place along x, y or z of `at`. */
(() => {
  const R = Rupaka, SIZE = {box: [1, 1, 1], cylinder: [.5, 1], cone: [.5, 1], sphere: [.5], capsule: [.25, 1], torus: [.5, .15], plane: [1, 1], ring: [.6, 1],
                disc: [.5], map: [], globe: [], group: []};
  const rad = d => d * Math.PI / 180, deg = r => r * 180 / Math.PI, wrap = a => ((a + 540) % 360 + 360) % 360 - 180;
  const clamp = (x, a, b) => Math.min(b, Math.max(a, x));
  const hasKey = v => Array.isArray(v) && v.some(x => typeof x === 'string');
  // The lon/lat window [lon0, lat0, lon1, lat1] of the world picture, as the uv of a flat shape.
  function window_(g, [lo0, la0, lo1, la1]) {
    const uv = g.attributes.uv, u0 = (lo0 + 180) / 360, u1 = (lo1 + 180) / 360, v0 = (la0 + 90) / 180, v1 = (la1 + 90) / 180;
    for (let i = 0; i < uv.count; i++) uv.setXY(i, u0 + (u1 - u0) * uv.getX(i), v0 + (v1 - v0) * uv.getY(i));
    return g;
  }

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
  function shape(T, b, arc = [0, 360]) {
    const z = Object.assign([...SIZE[b.kind]], b.size || []);
    switch (b.kind) {
      case 'box': {
        const r = Math.min(...z) * Math.min(.5, b.round ?? .14);
        return r > 1e-3 ? rounded(T, z, r) : new T.BoxGeometry(...z);
      }
      case 'cylinder': return z.length > 2 ? new T.CylinderGeometry(z[0], z[1], z[2], 40) : new T.CylinderGeometry(z[0], z[0], z[1], 40);
      case 'cone': return new T.ConeGeometry(z[0], z[1], 40);
      case 'sphere': return new T.SphereGeometry(z[0], b.texture ? 72 : 40, b.texture ? 48 : 24);
      case 'capsule': return new T.CapsuleGeometry(z[0], z[1], 8, 32);
      case 'torus': return new T.TorusGeometry(z[0], z[1], 20, 56);
      case 'plane': { const g = new T.PlaneGeometry(z[0], z[1]).rotateX(-Math.PI / 2); return b.uv ? window_(g, b.uv) : g; }
      case 'map': { const [lo0, la0, lo1, la1] = b.uv; return window_(new T.PlaneGeometry(lo1 - lo0, la1 - la0).rotateX(-Math.PI / 2), b.uv); }
      case 'ring': return new T.RingGeometry(z[0], z[1], 128, 1, rad(arc[0]), rad(arc[1] - arc[0])).rotateX(-Math.PI / 2);
      case 'disc': return new T.CircleGeometry(z[0], 96, rad(arc[0]), rad(arc[1] - arc[0])).rotateX(-Math.PI / 2);
      case 'globe': return new T.SphereGeometry(R.GLOBE, 96, 64);
    }
  }

  // A live sun: two layers of noise that drift, hot in the middle and dark at the limb.
  const NOISE = `float hash(vec3 p){p=fract(p*.3183099+.1);p*=17.;return fract(p.x*p.y*p.z*(p.x+p.y+p.z));}
    float noise(vec3 x){vec3 i=floor(x),f=fract(x);f=f*f*(3.-2.*f);return mix(mix(mix(hash(i),hash(i+vec3(1,0,0)),f.x),mix(hash(i+vec3(0,1,0)),hash(i+vec3(1,1,0)),f.x),f.y),
      mix(mix(hash(i+vec3(0,0,1)),hash(i+vec3(1,0,1)),f.x),mix(hash(i+vec3(0,1,1)),hash(i+vec3(1,1,1)),f.x),f.y),f.z);}
    float fbm(vec3 p){float a=.5,s=0.;for(int i=0;i<5;i++){s+=a*noise(p);p=p*2.03+7.;a*=.5;}return s;}`;
  const SUN = {vertexShader: 'varying vec3 vP,vN;void main(){vP=position;vN=normalMatrix*normal;gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.);}',
    fragmentShader: `uniform float time;varying vec3 vP,vN;${NOISE}
      void main(){vec3 p=normalize(vP);float v=fbm(p*5.+vec3(0.,time*.12,0.))*.65+fbm(p*19.+time*.25)*.45,limb=.4+.6*pow(max(normalize(vN).z,0.),.55);
      vec3 c=mix(vec3(1.,.36,.03),vec3(1.,.9,.55),smoothstep(.32,.78,v))+vec3(1.,.95,.8)*pow(v,5.)*.9;gl_FragColor=vec4(c*limb*1.3,1.);}`};
  // The air of a planet: a thin blue rim, bright on the day side.
  const AIR = {vertexShader: 'varying vec3 vN,vW;void main(){vN=normalize(mat3(modelMatrix)*normal);vW=(modelMatrix*vec4(position,1.)).xyz;gl_Position=projectionMatrix*viewMatrix*vec4(vW,1.);}',
    fragmentShader: 'varying vec3 vN,vW;void main(){vec3 n=normalize(vN),v=normalize(cameraPosition-vW);float i=pow(clamp(-dot(n,v)/.36,0.,1.),1.7);gl_FragColor=vec4(vec3(.3,.6,1.)*i*.45,1.);}'};
  const add = {transparent: true, depthWrite: false};

  function material(T, S, b) {
    b = {...b, texture: b.texture ?? (['map', 'globe'].includes(b.kind) ? 'earth' : undefined)};   // a map and a globe show the world by default
    const name = b.color || 'body', tex = b.texture && b.texture !== 'sun' && S.tex(b.texture), keep = (m, c) => (S.recolors.push(() => S.paint(m, S.palette()[c] || S.palette().body)), m);
    let m;
    if (b.texture === 'sun') m = new T.ShaderMaterial({uniforms: {time: {value: 0}}, ...SUN});
    else if (tex && (b.kind === 'map' || b.kind === 'plane')) m = new T.MeshBasicMaterial({map: tex});   // a map is read, not lit
    else if (tex) { S.lights(); m = new T.MeshStandardMaterial({map: tex, roughness: 1, metalness: 0}); }
    else if (b.glow != null || b.light) m = keep(new T.MeshBasicMaterial({color: S.col(S.palette()[b.color || 'glow'])}), b.color || 'glow');
    else if (S.sky && ['ring', 'disc', 'plane'].includes(b.kind)) m = keep(new T.MeshBasicMaterial({color: S.col(S.palette()[name] || S.palette().body)}), name);   // a flat mark in the sky is not lit
    else if (b.opacity != null || b.kind === 'ring' || b.kind === 'disc') {
      S.lights(); m = keep(S.mat(name).clone(), name);
      if (m.uniforms) Object.assign(m.uniforms, {light: S.light, alpha: {value: b.opacity ?? 1}});
    }
    else return S.mat(name);
    if (b.opacity != null) Object.assign(m, {transparent: true, opacity: b.opacity, depthWrite: false});
    if (m.isMeshStandardMaterial || b.kind === 'ring' || b.kind === 'disc') m.side = T.DoubleSide;
    return m;
  }
  // A soft round sprite of `stops` [[at, rgba]], for a halo.
  function sprite(T, stops, s) {
    const c = Object.assign(document.createElement('canvas'), {width: 128, height: 128}), g = c.getContext('2d'), r = g.createRadialGradient(64, 64, 0, 64, 64, 64);
    stops.forEach(([a, v]) => r.addColorStop(a, `rgba(255,255,255,${v})`)); g.fillStyle = r; g.fillRect(0, 0, 128, 128);
    const sp = new T.Sprite(new T.SpriteMaterial({map: new T.CanvasTexture(c), ...add, blending: T.AdditiveBlending})); sp.userData = {flat: true, s};
    return sp;
  }
  // Two white falloffs, a core and a wide veil; the sprite colour tints them, so a halo has the colour of its body.
  const HALO = [[[0, 1], [.16, .7], [.4, .18], [1, 0]], [[0, .3], [.5, .07], [1, 0]]];
  const warm = (c, k) => c.map(x => x + (1 - x) * k);
  // N thin spokes across a ring: the edges of its slices, as on a dial.
  function spokes(T, S, [r0, r1], n) {
    const ps = Array.from({length: n}, (_, i) => { const a = i / n * 2 * Math.PI, c = Math.cos(a), s = -Math.sin(a); return [r0 * c, 0, r0 * s, r1 * c, 0, r1 * s]; }).flat();
    const g = new T.BufferGeometry(); g.setAttribute('position', new T.Float32BufferAttribute(ps, 3));
    const m = new T.LineBasicMaterial({color: S.col(S.palette().lines.ink), transparent: true, opacity: .5, depthWrite: false});
    S.recolors.push(() => S.paint(m, S.palette().lines.ink));
    return new T.LineSegments(g, m);
  }

  // The grip of a body with `drag`: a button over the body. Drag it, or press A/D or ←/→ (⇧ for ten nudges). A locked grip moves nothing
  // and says for two seconds why. The maths runs in the frame of the parent body, so a nested body and the geo and globe coords drag the right way.
  // An orbit with no range writes its angle in [0, 360), so a slider on the same key keeps up; the drag counts the laps itself, so it does not jump.
  function grip(S, b, ctx, P) {
    const orbit = b.drag === 'orbit', ix = {x: 0, y: 1, z: 2}[b.drag], [lo, hi] = b.range || [-Infinity, Infinity], step = b.nudge ?? (orbit ? 1 : .1);
    const g = R.el('button', {type: 'button', class: 'rk-grip', role: 'slider', 'aria-label': b.label || `Move ${b.id}`});
    const note = R.el('div', {class: 'rk-note rk-gripnote', role: 'status', hidden: true, text: 'Lock in your prediction first.'});
    S.gripBox.append(g, note);
    let quiet = 0;
    const tell = () => { note.hidden = false; clearTimeout(quiet); quiet = setTimeout(() => { note.hidden = true; }, 2000); };
    const snap = v => b.nudge ? Math.round(v / b.nudge) * b.nudge : v;   // a drag stops on a whole number of nudges, as the keys do
    const fit = orbit && !b.range ? v => +((snap(v) % 360 + 360) % 360).toFixed(4) % 360 : v => +clamp(snap(v), lo, hi).toFixed(4);
    const cur = () => S.num(b.to), put = v => ctx.put(b, b.to, fit(v));
    const V = (...a) => new S.T.Vector3(...a), par = () => P.outer.parent;
    const world = v => par().localToWorld(v.clone()), local = v => par().worldToLocal(v.clone());
    // Orbit: the plane of the circle. Slide: the plane through the body that holds the axis and faces the camera most.
    const setup = () => {
      if (orbit) {
        const c = V(...S.pos(b.about)), n = V(...S.vec(b.axis, [0, 1, 0])).normalize(), cw = world(c), nw = world(c.clone().add(n)).sub(cw).normalize();
        return {c, n, uv: S.basis(n), plane: new S.T.Plane().setFromNormalAndCoplanarPoint(nw, cw)};
      }
      const at = S.vec(b.at), up = [...at]; up[ix] += 1;
      const p0 = world(V(...S.pos(at))), d = world(V(...S.pos(up))).sub(p0), cd = S.cam().getWorldDirection(V());
      let n = V().crossVectors(d, V().crossVectors(cd, d)); if (n.lengthSq() < 1e-9) n = cd.clone();
      return {d, dd: d.lengthSq() || 1, plane: new S.T.Plane().setFromNormalAndCoplanarPoint(n.normalize(), p0)};
    };
    const hit = (e, k) => {
      const p = S.ray(e.clientX, e.clientY).intersectPlane(k.plane, V());
      if (!p || !orbit) return p;
      const q = local(p).sub(k.c); return deg(Math.atan2(q.dot(k.uv[1]), q.dot(k.uv[0])));
    };
    let k = null, from = 0, v0 = 0;
    g.addEventListener('pointerdown', e => {
      if (!ctx.live(b.lock)) { tell(); return; }
      k = setup(); from = hit(e, k); v0 = cur(); if (from == null) { k = null; return; }
      g.setPointerCapture(e.pointerId); g.classList.add('held'); e.preventDefault();
    });
    g.addEventListener('pointermove', e => {
      const a = k && hit(e, k); if (a == null) return;
      if (orbit) { v0 = clamp(v0 + wrap(a - from), lo, hi); from = a; put(v0); }
      else put(v0 + a.clone().sub(from).dot(k.d) / k.dd);
    });
    const up = () => { k = null; g.classList.remove('held'); };
    g.addEventListener('pointerup', up); g.addEventListener('pointercancel', up);
    g.addEventListener('keydown', e => {
      const d = {ArrowRight: 1, d: 1, ArrowLeft: -1, a: -1}[e.key.length === 1 ? e.key.toLowerCase() : e.key];
      if (!d || e.metaKey || e.ctrlKey || e.altKey) return;
      e.preventDefault(); e.stopPropagation();
      if (!ctx.live(b.lock)) tell(); else put(cur() + d * step * (e.shiftKey ? 10 : 1));
    });
    const sync = () => {
      g.setAttribute('aria-valuenow', String(+cur().toFixed(2))); g.toggleAttribute('data-locked', !ctx.live(b.lock));
      if (Number.isFinite(lo)) g.setAttribute('aria-valuemin', lo);
      if (Number.isFinite(hi)) g.setAttribute('aria-valuemax', hi);
    };
    ctx.s.on(sync); sync();
    g.note = note;
    return g;
  }

  Rupaka.block('body', (b, ctx) => {
    const S = ctx.scene;
    if (!S) throw new Error('a body must be inside a scene');
    if (!Object.hasOwn(SIZE, b.kind)) throw new Error(`"${b.kind}" is not a body kind; use one of: ${Object.keys(SIZE).join(', ')}`);
    if (b.in && !S.ids.has(b.in)) throw new Error(`the body "${b.id}" is in "${b.in}", which is not a body`);
    if (b.kind === 'map' && !b.uv) throw new Error(`the map "${b.id}" needs uv: [lon0, lat0, lon1, lat1]`);
    if (b.drag && !b.to) throw new Error(`the body "${b.id}" has drag, so it needs "to": the state key that it writes`);
    const dyn = [b.at, b.pivot, b.scale].some(hasKey) || !!b.along || !!b.spin || b.orbit != null, live = hasKey(b.arc);
    const arc = () => { const [a, c] = b.arc ? b.arc.map(x => S.num(x)) : [0, 360]; return [a, Math.min(360, Math.max(.01, c - a)) + a]; };
    const mid = () => b.kind === 'map' ? [(b.uv[0] + b.uv[2]) / 2, (b.uv[1] + b.uv[3]) / 2, 0] : [0, 0, 0];
    const size = () => b.kind === 'globe' ? R.GLOBE : b.kind === 'map' ? Math.max(b.uv[2] - b.uv[0], b.uv[3] - b.uv[1]) / 2 : Math.max(...(b.size || SIZE[b.kind]));
    const onOrbit = () => {
      const n = new S.T.Vector3(...S.vec(b.axis, [0, 1, 0])).normalize(), [u, v] = S.basis(n), a = rad(S.num(b.angle)), r = S.num(b.orbit);
      return new S.T.Vector3(...S.pos(b.about)).addScaledVector(u, r * Math.cos(a)).addScaledVector(v, r * Math.sin(a)).toArray();
    };
    const put = P => {   // the place now: on a path, on an orbit, or at `at`; `pivot` is the point that rot turns about
      const at = b.along ? S.paths[b.along]?.at(S.num(b.t)).toArray() ?? [0, 0, 0] : b.orbit != null ? onOrbit() : S.pos(b.at ?? (b.kind === 'map' ? mid() : null)), pv = b.pivot ? S.pos(b.pivot) : at;
      P.outer.position.set(...pv); P.frame.position.set(at[0] - pv[0], at[1] - pv[1], at[2] - pv[2]);
      if (b.scale) P.frame.scale.set(...S.vec(b.scale, [1, 1, 1]).map(x => Math.max(1e-3, x)));
    };
    return S.part(b, {
      make(T, P) {
        const outer = new T.Group(), frame = new T.Group();
        outer.add(frame); Object.assign(P, {outer, frame});
        if (b.kind !== 'group') {
          frame.add(P.mesh = new T.Mesh(shape(T, b, arc()), material(T, S, b))); P.arcK = arc().join();
          const r = size();
          if ((b.texture ?? (b.kind === 'globe' ? 'earth' : 0)) === 'earth' && ['sphere', 'globe'].includes(b.kind)) frame.add(new T.Mesh(new T.SphereGeometry(r * 1.07, 64, 48), new T.ShaderMaterial({...AIR, ...add, side: T.BackSide, blending: T.AdditiveBlending})));
          const hue = () => b.texture === 'sun' ? [1, .62, .22] : S.palette()[b.color || 'glow'] || S.palette().glow;
          if (b.glow != null) frame.add(...(P.halos = HALO.map((st, i) => sprite(T, st, r * (i ? 18 : 6)))));
          if (b.light) { frame.add(P.lamp = new T.PointLight(0xffffff, 3.4, 0, 0)); S.lights(); S.lamp(); }
          const tint = () => { P.halos?.forEach(h => h.material.color.copy(S.col(hue()))); P.lamp?.color.copy(S.col(warm(hue(), .8))); };
          tint(); S.recolors.push(tint);
          if (b.ticks && b.kind === 'ring') frame.add(spokes(T, S, Object.assign([...SIZE.ring], b.size || []), b.ticks));
        }
        if (!b.along || S.paths[b.along]) put(P);
        (b.in ? S.bodies[b.in].frame : S.world).add(outer);
        S.bodies[b.id] = {outer, frame, b, P};
        P.rot = S.vec(b.rot).map(rad); outer.rotation.set(...P.rot);
        if (b.drag) P.grip ??= grip(S, b, ctx, P);
        return outer;
      },
      sync(P, live) {
        S.show(P, P.outer, live);
        P.halos?.forEach(h => h.scale.setScalar(h.userData.s * (.4 + .6 * Math.max(0, S.num(b.glow, 1)))));
        const to = S.vec(b.rot).map(rad), o = P.outer;
        if (to.every((x, i) => x === P.rot[i])) return;
        const from = [o.rotation.x, o.rotation.y, o.rotation.z];
        P.rot = to;
        S.anim(P, b.turn ?? 700, k => o.rotation.set(...from.map((x, i) => x + (to[i] - x) * k)));
      },
      run: () => !!b.spin || b.texture === 'sun',
      frame(P, now = 0) {
        if (dyn) put(P);
        if (live && P.mesh) { const a = arc(), k = a.join(); if (k !== P.arcK) { P.arcK = k; P.mesh.geometry.dispose(); P.mesh.geometry = shape(S.T, b, a); } }   // a new shape only when the arc moves
        const t = S.still() ? 0 : now / 1000;   // with reduced motion a spin and a sun surface stand still, also when the view draws again
        if (b.spin && P.mesh) P.mesh.rotation.y = rad(b.spin * t);
        if (b.texture === 'sun') P.mesh.material.uniforms.time.value = t;
      },
      over(P) {
        if (!P.grip) return;
        const V = () => new S.T.Vector3(), c = P.frame.getWorldPosition(V()), v = S.screen(c);
        let disc = 0;   // the width on screen of the body, so a press anywhere on it takes the grip
        if (P.mesh) {
          const geo = P.mesh.geometry, w = P.mesh.getWorldScale(V()); geo.boundingSphere ?? geo.computeBoundingSphere();
          const e = S.screen(c.clone().addScaledVector(V().setFromMatrixColumn(S.cam().matrixWorld, 0), geo.boundingSphere.radius * Math.max(w.x, w.y, w.z)));
          disc = 2 * Math.hypot(e.x - v.x, e.y - v.y) || 0;
        }
        const at = `translate(${v.x.toFixed(1)}px, ${v.y.toFixed(1)}px)`;
        P.grip.hidden = !(S.live(b) && S.seen(b.id) && v.on); P.grip.style.transform = at; P.grip.style.setProperty('--disc', `${disc.toFixed(1)}px`);
        P.grip.note.style.transform = `${at} translate(24px, -50%)`; if (P.grip.hidden) P.grip.note.hidden = true;
      },
    }, R.el('li', {text: `${b.id}: a ${b.kind}${b.drag ? ', with a grip' : ''}`}));
  });
})();

/* blocks/caption/caption.js */
/* caption: the explain text. Only **bold** and {path} are special; all text goes in with textContent, so no HTML runs. */
Rupaka.block('caption', (b, ctx) => {
  const {el, rich} = Rupaka, p = el('p');
  ctx.s.on(() => p.replaceChildren(...rich(b.text, ctx.s.st)));
  return el('div', {}, Rupaka.label(b), p);
});

/* blocks/choice/choice.js */
/* choice: a row of options with one picked. ←/→ or A/D move, 1-9 pick.
   A new pick sets the keys of `resets` back in the same change, so there is one derive and one draw: no view shows the new pick with an old value. */
Rupaka.block('choice', (b, ctx) => {
  const {el, show} = Rupaka, s = ctx.s, os = b.options || [];
  const pick = o => {
    if (!ctx.live(b.lock)) return false;
    if (o !== s.get(b.bind)) for (const [k, v] of Object.entries(b.resets || {})) s.st[k] = structuredClone(v);
    return ctx.put(b, b.bind, o);
  };
  const box = el('div', {class: 'opts', role: 'radiogroup', 'aria-label': b.label || b.bind});
  const btns = os.map((o, i) => el('button', {type: 'button', role: 'radio', onclick: () => pick(o)}, show(o), i < 9 ? el('kbd', {text: i + 1}) : null));
  box.append(...btns);
  box.addEventListener('keydown', e => {
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    const k = e.key.toLowerCase(), i = os.indexOf(s.get(b.bind));
    const j = ['arrowright', 'd'].includes(k) ? i + 1 : ['arrowleft', 'a'].includes(k) ? i - 1 : /^[1-9]$/.test(k) ? +k - 1 : null;
    if (j == null || j < 0 || j >= os.length) return;
    e.preventDefault();
    if (pick(os[j])) btns[j].focus();
  });
  s.on(() => {
    const v = s.get(b.bind), at = Math.max(0, os.indexOf(v));
    btns.forEach((x, i) => { x.setAttribute('aria-checked', String(os[i] === v)); x.tabIndex = i === at ? 0 : -1; x.disabled = !ctx.live(b.lock); });
  });
  return el('div', {}, Rupaka.label(b), box);
});

/* blocks/drift/drift.js */
/* drift: dots that ride a path, as charge rides a wire. `speed` is laps a second (a key lets a slider set it; below 0 turns them round).
   With reduced motion they stand still. */
(() => {
  const still = () => matchMedia('(prefers-reduced-motion: reduce)').matches;
  Rupaka.block('drift', (b, ctx) => {
    const S = ctx.scene;
    if (!S) throw new Error('a drift must be inside a scene');
    return S.part(b, {
      make(T, P) {
        Object.assign(P, {n: Math.round(b.n ?? 10), ph: 0, t0: null, v: new T.Vector3(), m: new T.Matrix4()});
        P.mesh = new T.InstancedMesh(new T.SphereGeometry(1, 14, 10), S.lineMat(b.tone || 'glow'), P.n);
        P.mesh.frustumCulled = false; S.world.add(P.mesh);
        return P.mesh;
      },
      sync(P, live) { P.mesh.visible = live; },
      run: () => S.num(b.speed) !== 0,
      frame(P, now) {
        const p = S.paths[b.on], r = S.unit * (b.size ?? 1) * .35; if (!p || !S.unit) return;
        if (!still() && P.t0 != null) P.ph += S.num(b.speed) * Math.min(.1, (now - P.t0) / 1000);
        P.t0 = now;
        for (let i = 0; i < P.n; i++) P.mesh.setMatrixAt(i, P.m.makeScale(r, r, r).setPosition(p.at((((i / P.n + P.ph) % 1) + 1) % 1, P.v)));
        P.mesh.instanceMatrix.needsUpdate = true;
      },
    }, Rupaka.el('li', {text: `dots that ride the path ${b.on}`}));
  });
})();

/* blocks/flow/flow.js */
/* flow: a few nodes and the arrows between them, left to right (row) or as a loop (cycle), for example guess → compare → adjust.
   A row where each arrow goes to the next node is HTML: each box grows to fit its words, each arrow has its own gap, and the row
   wraps, or turns into a list from the top down in a narrow column. A row with skips or steps back, and a cycle, are SVG. */
Rupaka.block('flow', (b, ctx) => {
  const {el, sv} = Rupaka, ns = b.nodes || [], n = ns.length, cyc = b.layout === 'cycle', W = 600, LH = 19;
  const at = Object.fromEntries(ns.map((x, i) => [x.id, i]));
  const es = b.edges ?? ns.slice(cyc ? 0 : 1).map((x, i) => ({from: ns[i].id, to: ns[(i + 1) % n].id}));   // no edges: each node points to the next
  const by = new Map(es.map((e, j) => [at[e.from], [e, j]]));
  if (!cyc && es.every(e => at[e.to] - at[e.from] === 1) && by.size === es.length) {
    const arrow = ([e, j]) => el('div', {class: 'edge', style: `--i: ${n + j}`, 'data-rk-id': ctx.id(b, `edges.${j}`)},
      e.text ? el('span', {class: 'et', text: e.text}) : null, el('span', {class: 'ln'}), el('span', {class: 'sk'}));
    return el('div', {}, Rupaka.label(b), el('div', {class: 'chain'}, el('div', {class: 'line'}, ns.map((x, i) => el('div', {class: 'step'},
      i && by.has(i - 1) ? arrow(by.get(i - 1)) : null, el('div', {class: 'node', style: `--i: ${i}`, 'data-rk-id': ctx.id(b, `nodes.${i}`), text: x.text}))))));
  }
  // The words of a node in lines that fit `w`, at about 8 px a letter.
  const wrap = (t, w) => { const per = Math.max(4, Math.floor((w - 20) / 8)), out = [''];
    for (const wd of String(t).split(/\s+/)) { const l = out.length - 1; if (out[l] && (out[l] + ' ' + wd).length > per) out.push(wd); else out[l] = out[l] ? `${out[l]} ${wd}` : wd; }
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
  const {el, fmt, rich, show} = Rupaka, s = ctx.s, id = b.id;
  s.st.gate[id] = 'open';
  let picked = null, said = '', seen = '', froze = null;   // froze: the prompt as it was at lock-in, kept until the gate opens again
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
    verdict.replaceChildren(...(said ? [...rich(said), ' '] : []), 'You said ', el('b', {class: ok ? 'ok' : 'no', text: show(picked)}), '. ',
      ok ? el('span', {class: 'ok', text: 'That is right.'}) : el('span', {}, 'It is ', el('b', {class: 'ok', text: show(a)}), /[.!?]$/.test(show(a)) ? '' : '.'), stale);
  };
  function commit() {
    if (picked == null || !open()) return false;
    const a = ans(), ok = String(picked) === String(a), c = b.context ? fmt(b.context, s.st) : '';
    const detail = {gate: id, picked, ans: a, ok, why: why ? why.value : '', context: c};
    froze = rich(b.prompt, s.st);
    let settled = false;
    const settle = (saved, message = '') => {
      if (settled) return;
      settled = true;
      if (!saved) { s.st.gate[id] = 'open'; froze = null; q.replaceChildren(...rich(b.prompt, s.st)); say(String(message ?? '')); paint(); return; }
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
    picked = null; said = ''; froze = null; if (why) why.value = ''; verdict.replaceChildren();
    s.st.gate[id] = 'open'; s.set('_', (s.st._ || 0) + 1);
  };
  again.onclick = () => { reopen(); box.querySelector('button')?.focus(); };   // only the learner's button moves the focus
  // The host closes the gate. The caller (Rupaka.settle) draws once after it. The answer of the spec comes first.
  const settle = (p, answer) => {
    const w = b.answer ?? answer;
    if (p != null) picked = p;
    froze = rich(b.prompt, s.st);
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
    q.replaceChildren(...(!open() && froze || rich(b.prompt, s.st)));
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

/* blocks/layer/layer.js */
/* layer: one shape on the stage of a layers block. Its numbers are values or state keys. With drag, a handle writes the keys of x and y.
   A/D (←/→) and W/S (↑/↓) move the handle, ⇧ moves ten steps. While a change holds, a faint ghost stays where the layer was. */
(() => {
  const {sv} = Rupaka, HOR = 58;
  let seq = 0;
  const ART = {
    sky: () => {
      const id = `rk-warm-${++seq}`;
      return sv('g', {}, sv('defs', {}, sv('linearGradient', {id, x1: 0, y1: 0, x2: 0, y2: 1},
        sv('stop', {offset: 0, class: 'w0'}), sv('stop', {offset: 1, class: 'w1'}))),
        sv('rect', {class: 'sky', x: -60, y: -5, width: 280, height: 100}), sv('rect', {class: 'warm', x: -60, y: -5, width: 280, height: 100, fill: `url(#${id})`}));
    },
    hill: b => {
      let d = 'M -10 100';
      for (let x = -10; x <= 210; x += 5) d += ` L ${x} ${(HOR - 10 - 8 * Math.sin(x * .045 + (b.seed || 0)) - 5 * Math.sin(x * .11 + (b.seed || 0) * 2.3)).toFixed(2)}`;
      return sv('path', {class: 'hill', d: d + ' L 210 100 Z', style: b.tone != null ? `--tone: ${b.tone}` : null});
    },
    water: b => sv('g', {style: b.tone != null ? `--tone: ${b.tone}` : null}, sv('rect', {class: 'water', x: -60, y: HOR, width: 280, height: 40}),
      ...[[-20, 66, 14], [18, 72, 20], [60, 64, 12], [92, 76, 22], [130, 68, 16], [170, 74, 18]].map(([x, y, w]) => sv('line', {class: 'shine', x1: x, y1: y, x2: x + w, y2: y}))),
    sun: () => sv('g', {}, sv('circle', {class: 'halo', r: 10}), sv('circle', {class: 'disc', r: 5.5})),
    cloud: () => sv('g', {}, sv('ellipse', {cx: 0, cy: 0, rx: 9, ry: 3}), sv('ellipse', {cx: -4, cy: -2, rx: 5, ry: 3}), sv('ellipse', {cx: 4, cy: -1.5, rx: 5.5, ry: 3.2})),
    boat: () => sv('g', {}, sv('path', {class: 'hull', d: 'M -10 0 L 10 0 L 6.5 4.5 L -6.5 4.5 Z'}), sv('line', {class: 'mast', x1: 0, y1: 0, x2: 0, y2: -13}),
      sv('path', {class: 'sail', d: 'M 1 -12 L 9 -2 L 1 -2 Z'}), sv('path', {class: 'sail small', d: 'M -1 -10 L -6 -2 L -1 -2 Z'})),
  };

  Rupaka.block('layer', (b, ctx) => {
    const {sv, show, num} = Rupaka, s = ctx.s, P = ctx.stage;
    if (!P) throw new Error('a layer must be inside layers');
    if (!ART[b.art]) throw new Error(`unknown art "${b.art}"`);
    const drag = b.drag || '', step = b.step ?? .5, ghosted = b.ghost ?? !!drag;
    const body = ART[b.art](b), posed = sv('g', {class: 'pose'}, body);
    const gpose = ghosted ? sv('g', {class: 'ghost', 'aria-hidden': 'true'}, body.cloneNode(true)) : null;
    if (gpose) gpose.style.display = 'none';
    const node = sv('g', {class: `art-${b.art}`}, gpose, posed);
    const pose = st => {
      const yv = num(b.y, st, 0);
      return {x: num(b.x, st, 0) - P.pan(st) * (b.depth || 0), y: b.up ? P.H - yv : yv, k: num(b.scale, st, 1), r: num(b.rotate, st, 0), o: num(b.opacity, st, 1), tint: num(b.tint, st, 0)};
    };
    const tf = p => `translate(${p.x} ${p.y}) rotate(${p.r}) scale(${p.k})`;
    const hold = on => ctx.root.dispatchEvent(new CustomEvent('rk-hold', {detail: {on}}));
    let hand = null, txt, ring, timer;
    if (drag) {
      ring = sv('circle', {class: 'ring', r: 7});
      txt = sv('text', {class: 'tag', 'text-anchor': 'middle'});
      hand = sv('g', {class: 'handle', tabindex: 0, role: 'slider', 'aria-label': b.label || b.art}, ring, sv('circle', {class: 'dot', r: 1.6}), txt);
      P.top.append(hand);
      const rng = {x: b.xr || [0, P.W], y: b.yr || [0, P.H]}, axes = [...drag];
      const clamp = (v, [lo, hi]) => +Math.min(hi, Math.max(lo, Math.round(v / step) * step)).toFixed(6);
      const at = e => { const pt = P.svg.createSVGPoint(); pt.x = e.clientX; pt.y = e.clientY; return pt.matrixTransform(P.svg.getScreenCTM().inverse()); };
      const put = (x, y) => { if (x != null && x !== s.get(b.x)) ctx.put(b, b.x, x); if (y != null && y !== s.get(b.y)) ctx.put(b, b.y, y); };
      let off = null;
      hand.addEventListener('pointerdown', e => {
        if (!ctx.live(b.lock)) return;
        e.stopPropagation(); hand.setPointerCapture(e.pointerId); hand.classList.add('held'); hold(true);
        const p = at(e), h = pose(s.st); off = {x: p.x - h.x, y: p.y - h.y};
      });
      hand.addEventListener('pointermove', e => {
        if (!hand.hasPointerCapture(e.pointerId)) return;
        const p = at(e), sh = pose(s.st).x - num(b.x, s.st, 0), yv = b.up ? P.H - (p.y - off.y) : p.y - off.y;
        put(axes.includes('x') ? clamp(p.x - off.x - sh, rng.x) : null, axes.includes('y') ? clamp(yv, rng.y) : null);
      });
      const drop = () => { if (!off) return; off = null; hand.classList.remove('held'); hold(false); };
      hand.addEventListener('pointerup', drop); hand.addEventListener('pointercancel', drop);
      hand.addEventListener('keydown', e => {
        const k = e.key.toLowerCase(), d = step * (e.shiftKey ? 10 : 1), one = axes.length === 1;
        const dx = ['arrowright', 'd'].includes(k) ? d : ['arrowleft', 'a'].includes(k) ? -d : 0;
        const up = ['arrowup', 'w'].includes(k) ? d : ['arrowdown', 's'].includes(k) ? -d : 0;
        let mx = axes.includes('x') ? dx || (one ? up : 0) : 0, my = axes.includes('y') ? (b.up ? up : -up) || (one ? dx : 0) : 0;
        if (!mx && !my) return;
        e.preventDefault();
        if (!timer) hold(true);
        clearTimeout(timer); timer = setTimeout(() => { timer = 0; hold(false); }, 800);
        put(mx ? clamp(+s.get(b.x) + mx, rng.x) : null, my ? clamp(+s.get(b.y) + my, rng.y) : null);
      });
    }
    s.on(() => {
      const p = pose(s.st);
      posed.setAttribute('transform', tf(p)); posed.setAttribute('opacity', p.o); posed.style.setProperty('--tint', p.tint);
      const h = gpose && P.held ? pose(P.held) : null;
      const moved = h && (Math.abs(h.x - p.x) + Math.abs(h.y - p.y) + Math.abs(h.k - p.k) + Math.abs(h.r - p.r) + Math.abs(h.tint - p.tint)) > .05;
      if (gpose) gpose.style.display = moved ? '' : 'none';
      if (moved) { gpose.setAttribute('transform', tf(h)); gpose.style.setProperty('--tint', h.tint); }
      if (hand) {
        hand.setAttribute('transform', `translate(${p.x} ${p.y})`);
        const v = +s.get(drag[0] === 'y' ? b.y : b.x), t = show(v, 1);
        txt.setAttribute('y', -9); txt.textContent = b.label ? `${b.label} ${t}` : t;
        hand.setAttribute('aria-valuenow', v); hand.setAttribute('aria-valuetext', `${b.label || b.art} ${t}`);
        hand.style.display = ctx.live(b.lock) ? '' : 'none';
      }
    });
    return node;
  });
})();

/* blocks/layers/layers.js */
/* layers: a flat picture of layer blocks, back to front, on a 160 x 90 stage. A layer with depth shifts by -pan * depth (parallax).
   A control that starts a change sends rk-hold on the demo root; while it holds, each layer can show a faint ghost at the held values. */
Rupaka.block('layers', (b, ctx) => {
  const {el, sv} = Rupaka, s = ctx.s, W = 160, H = 90;
  const svg = sv('svg', {viewBox: `0 0 ${W} ${H}`, role: 'group', 'aria-label': b.label || 'A picture in layers', class: 'stage'});
  const stage = {svg, W, H, held: null, top: sv('g', {class: 'handles'}), pan: st => Rupaka.num(b.pan, st, 0)};
  ctx.root.addEventListener('rk-hold', e => { stage.held = e.detail.on ? structuredClone(s.st) : null; s.emit('hold'); });
  const c2 = Object.assign(Object.create(ctx), {stage});
  svg.append(...(b.blocks || []).map(k => Rupaka.build(k, c2)), stage.top);
  return el('div', {}, svg, b.note ? el('div', {class: 'rk-note', text: b.note}) : null);
});

/* blocks/links/links.js */
/* links: arcs between the bodies of `nodes`, as thick and as solid as their weights. `w` is a matrix (row i, column j) or a list (the weights
   from node `row`). With `row`, only the arcs of that node show. A weight of a node on itself is a small ring round it. */
(() => {
  const num = x => { const n = +(x != null && typeof x === 'object' ? x.value : x); return Number.isFinite(n) ? n : 0; };
  Rupaka.block('links', (b, ctx) => {
    const S = ctx.scene;
    if (!S) throw new Error('links must be inside a scene');
    const bad = (b.nodes || []).find(id => !S.ids.has(id));
    if (bad) throw new Error(`links names "${bad}", which is not a body`);
    const edges = () => {   // [i, j, w] for each weight that shows
      const w = S.list(b.w), r = b.row == null ? null : Math.round(S.num(b.row)), n = b.nodes.length;
      const all = Array.isArray(w[0]) ? w.flatMap((row, i) => Array.isArray(row) ? row.map((x, j) => [i, j, num(x)]) : []) : w.map((x, j) => [r ?? 0, j, num(x)]);
      return all.filter(([i, j, x]) => i < n && j < n && (r == null || i === r) && x >= (b.min ?? .02));
    };
    function build(T, P) {
      const es = edges(), all = b.row == null && Array.isArray(S.list(b.w)[0]), at = b.nodes.map(id => S.bodies[id].frame.getWorldPosition(new T.Vector3()));
      const top = Math.max(...es.map(e => e[2]), 1e-9), gap = Math.min(...at.flatMap((p, i) => at.slice(i + 1).map(q => p.distanceTo(q))), S.size);
      const sig = JSON.stringify(es) + at.map(p => p.toArray().map(x => x.toFixed(2))).join() + S.unit;
      if (sig === P.sig) return;
      P.sig = sig;
      P.g.children.slice().forEach(c => { c.geometry.dispose(); c.material.dispose(); P.g.remove(c); });
      for (const [i, j, x] of es) {
        const a = at[i], c = at[j], k = .25 + .75 * x / top, r = Math.min(S.unit * (b.width ?? 1) * .3, gap * .06) * k, d = c.clone().sub(a).normalize();
        const up = new T.Vector3(0, 1, 0).addScaledVector(d, -d.y);   // up, with the part along the arc taken out; for a line that goes up, to the side
        if (up.lengthSq() < .05) up.set(1, 0, 0).addScaledVector(d, -d.x);
        up.normalize().multiplyScalar(i > j && all ? -1 : 1);
        const geo = i === j ? new T.TorusGeometry(gap * .22, r, 6, 40).rotateX(Math.PI / 2).translate(a.x, a.y, a.z)
          : new T.TubeGeometry(new T.QuadraticBezierCurve3(a, a.clone().lerp(c, .5).addScaledVector(up, (b.lift ?? .45) * a.distanceTo(c)), c), 28, r, 6, false);
        const m = P.mat.clone(); Object.assign(m, {transparent: true, opacity: Math.max(.2, k), depthWrite: false});
        P.g.add(new T.Mesh(geo, m));
      }
    }
    return S.part(b, {
      make(T, P) { P.mat = S.lineMat(b.tone || 'acc'); P.g = new T.Group(); S.world.add(P.g); S.recolors.push(() => { P.sig = P.ver = null; }); return P.g; },
      sync(P, live) { P.g.visible = live; },
      frame(P) { if (P.ver !== S.ver) { P.ver = S.ver; build(S.T, P); } },   // once a change: the nodes have moved by then
    }, Rupaka.el('li', {text: 'links between the bodies'}));
  });
})();

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

/* blocks/path/path.js */
/* path: a line in 3D through `pts`, round a `circle`, or through a state list (`of`). A width under 0.5 is a hairline, else a thin tube.
   `grow` (0 to 1) draws the first part only. S.paths[id].at(t) gives a place on the whole path, for a body with `along` and for a drift. */
(() => {
  const clamp = (x, a, b) => Math.min(b, Math.max(a, x));
  // A polyline as a function of the share t of its length.
  function line(T, pts, closed) {
    const P = closed && pts.length > 1 ? [...pts, pts[0]] : pts, cum = [0];
    for (let i = 1; i < P.length; i++) cum.push(cum[i - 1] + P[i].distanceTo(P[i - 1]));
    const L = cum.at(-1), at = (t, out = new T.Vector3()) => {
      if (P.length < 2) return P.length ? out.copy(P[0]) : out.set(0, 0, 0);
      const d = clamp(t, 0, 1) * L; let i = 1;
      while (i < P.length - 1 && cum[i] < d) i++;
      const w = cum[i] - cum[i - 1];
      return out.lerpVectors(P[i - 1], P[i], w > 0 ? clamp((d - cum[i - 1]) / w, 0, 1) : 0);
    };
    return {P, L, at};
  }
  // The points of a polyline up to the share g of its length.
  const trim = (ln, g) => {
    const d = g * ln.L, out = [ln.P[0]]; let run = 0;
    for (let i = 1; i < ln.P.length; i++) {
      const w = ln.P[i].distanceTo(ln.P[i - 1]);
      if (run + w >= d) return [...out, ln.P[i - 1].clone().lerp(ln.P[i], w > 0 ? (d - run) / w : 0)];
      run += w; out.push(ln.P[i]);
    }
    return out;
  };

  // A tube through the points P: three rings a leg (at its start, and close to each end), so a corner stays sharp.
  function tube(T, P, r) {
    P = P.filter((p, i) => !i || p.distanceTo(P[i - 1]) > 1e-9);
    const n = P.length - 1, e = i => clamp(r * 1.5 / (P[i + 1].distanceTo(P[i]) || 1), 0, .3);
    class Poly extends T.Curve {
      getUtoTmapping(u) { return u; }
      getPoint(t, o = new T.Vector3()) {
        const x = clamp(t, 0, 1) * n * 3, j = Math.min(n * 3 - 1, Math.floor(x)), i = Math.floor(j / 3), k = j % 3, f = x - j, w = e(i), at = [0, w, 1 - w, 1];
        return o.lerpVectors(P[i], P[i + 1], at[k] + (at[k + 1] - at[k]) * f);
      }
    }
    return new T.TubeGeometry(new Poly(), n * 3, r, 8, false);
  }

  Rupaka.block('path', (b, ctx) => {
    const S = ctx.scene;
    if (!S) throw new Error('a path must be inside a scene');
    const closed = b.circle != null || !!b.closed, thin = (b.width ?? 1) < .5;
    const points = T => {
      if (b.circle != null) {
        const r = S.num(b.circle), c = new T.Vector3(...S.pos(b.about)), [u, v] = S.basis(new T.Vector3(...S.vec(b.axis, [0, 1, 0])).normalize());
        return Array.from({length: 192}, (_, i) => { const a = i / 96 * Math.PI; return c.clone().addScaledVector(u, r * Math.cos(a)).addScaledVector(v, r * Math.sin(a)); });
      }
      const ps = (b.of ? S.rows(b.of) : b.pts || [])
        .map(p => new T.Vector3(...S.pos(p)));
      return b.smooth && ps.length > 2 ? new T.CatmullRomCurve3(ps, !!b.closed, 'centripetal').getPoints(ps.length * 16) : ps;
    };
    function build(T, P) {
      const full = line(T, points(T), closed), g = b.grow == null ? 1 : clamp(S.num(b.grow), 0, 1), r = (S.unit || 1e-2) * .15 * (b.width ?? 1);
      if (b.id) S.paths[b.id] = {at: full.at, length: () => full.L, closed};
      const sig = full.P.map(p => p.toArray().map(x => x.toFixed(3))).join() + g.toFixed(3) + r;
      if (sig === P.sig) return;
      P.sig = sig; P.mesh.geometry.dispose();
      const cut = g >= 1 ? full : line(T, trim(full, g), false), ok = cut.P.length > 1 && cut.L > 1e-6;
      P.mesh.visible = ok; P.tip.visible = ok && !!b.arrow;
      if (!ok) { P.mesh.geometry = new T.BufferGeometry(); return; }
      P.mesh.geometry = thin ? new T.BufferGeometry().setFromPoints(cut.P) : tube(T, closed && g >= 1 ? [cut.P[0].clone().lerp(cut.P[1], .5), ...cut.P.slice(1), cut.P[0].clone().lerp(cut.P[1], .5)] : cut.P, r);
      if (!b.arrow) return;
      const e = cut.at(1), d = e.clone().sub(cut.at(.98)).normalize(), h = Math.max(r * 7, (S.unit || 1e-2) * .8);
      P.tip.geometry.dispose(); P.tip.geometry = new T.ConeGeometry(h * .43, h, 16).translate(0, h / 2, 0);
      P.tip.position.copy(e).addScaledVector(d, -h * .6); P.tip.quaternion.setFromUnitVectors(new T.Vector3(0, 1, 0), d);
    }
    return S.part(b, {
      make(T, P) {
        const op = b.opacity ?? (thin ? .55 : null), o = op != null ? {transparent: true, opacity: op, depthWrite: false} : {};
        const m = thin ? new T.LineBasicMaterial({color: S.col(S.palette().lines[b.tone || 'ink']), ...o}) : S.lineMat(b.tone || 'ink', o);
        if (thin) S.recolors.push(() => S.paint(m, S.palette().lines[b.tone || 'ink']));
        P.mesh = thin ? new T.Line(new T.BufferGeometry(), m) : new T.Mesh(new T.BufferGeometry(), m);
        P.tip = new T.Mesh(new T.BufferGeometry(), thin ? S.lineMat(b.tone || 'ink') : m);
        P.g = new T.Group(); P.g.add(P.mesh, P.tip); S.world.add(P.g);
        build(T, P);
        return P.g;
      },
      sync(P, live) { P.g.visible = live; build(S.T, P); },   // a path reads only the state, so it changes only here
    }, Rupaka.el('li', {text: `${b.id ? b.id + ': ' : ''}a path`}));
  });
})();

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
/* plot: a line (or dots) through a derived series of {x, y}, on its axis. With `ghost`, the line from before the latest change stays faint.
   With `guess` (a gate id) and `guesses` (one series key for each option of that gate, in the order of its options), the curve that the learner
   predicted is drawn dashed beside the true one from the moment of Lock in. It is a copy made then, so it stays while the inputs move.
   Two small tags, `your guess` and `true`, sit beside the two curves where they are farthest apart. Where the curves meet, one tag names both, in the right-most place where it touches no label, dot or line. */
Rupaka.block('plot', (b, ctx) => {
  const {sv} = Rupaka, P = ctx.plane;
  if (!P) throw new Error('a plot must be inside an axis');
  const ghost = sv('path', {class: 'gh', 'clip-path': P.clip}), path = sv('path', {class: 'ln', 'clip-path': P.clip}), dots = sv('g', {class: 'dots', 'clip-path': P.clip});
  const gs = sv('path', {class: 'gs', 'clip-path': P.clip}), guess = b.guess && b.guesses && !b.dots;
  const tg = sv('text', {class: 'tg', 'text-anchor': 'middle', display: 'none'}), tt = sv('text', {class: 'tg', 'text-anchor': 'middle', display: 'none'});
  const g = sv('g', {role: 'img', 'aria-label': b.label || b.series}, ...b.ghost && !b.dots ? [ghost] : [], ...guess ? [gs] : [], path, dots, ...guess ? [tg, tt] : []);
  if (b.tone) g.classList.add(`t-${b.tone}`);
  let cur = null, old = '', at = -1e9, kept = null;   // the line now, the line before this burst of changes, the time of the last change, the guess drawn
  const line = xs => { let d = '', pen = false; for (const p of xs) { const ok = Number.isFinite(p.y) && Math.abs(P.Y(p.y)) < 1e5; if (ok) { d += `${pen ? 'L' : 'M'}${P.X(p.x).toFixed(2)} ${P.Y(p.y).toFixed(2)}`; pen = true; } else pen = false; } return d; };
  // The tags keep a readable size: a narrow axis scales its drawing down, so the font grows to make up for it.
  let fs = 13, last = [];   // last: the series as drawn now
  const fit = () => { const w = P.svg.getBoundingClientRect().width; if (w) { fs = Math.max(13, 12 * P.W / w); [tg, tt].forEach(t => t.style.fontSize = `${fs.toFixed(1)}px`); if (kept) tag(last); } };
  if (guess && typeof ResizeObserver !== 'undefined') new ResizeObserver(fit).observe(P.svg);
  const spot = (text, x, y) => {   // the place for a tag, kept inside the plot box
    const [x0, x1] = [P.X(P.x[0]), P.X(P.x[1])], [y0, y1] = [P.Y(P.y[1]), P.Y(P.y[0])], hw = text.length * fs * 0.3;
    return [+Math.min(x1 - hw, Math.max(x0 + hw, x)).toFixed(1), +Math.min(y1 - 4, Math.max(y0 + fs, y)).toFixed(1)];
  };
  const put = (t, text, x, y) => {
    const [cx, cy] = spot(text, x, y);
    t.textContent = text; t.removeAttribute('display'); t.setAttribute('x', cx); t.setAttribute('y', cy);
  };
  // Where a tag touches no text, no dot and no line: the nearest such place to the curve (its right-most one), above it or below it. null if the browser cannot measure.
  const clear = (t, text, xs) => {
    try {
      t.textContent = text; t.removeAttribute('display'); t.setAttribute('x', 0); t.setAttribute('y', 0);
      const m = t.getBBox(), pad = 3, hw = m.width / 2 + pad, top = m.y - pad, bot = m.y + m.height + pad;
      const boxes = [...P.svg.querySelectorAll('text:not(.tg), .rk-point circle')].map(e => e.getBBox()).filter(r => r.width);
      const dots = [...P.svg.querySelectorAll('path.ln, path.gs')].filter(e => e.getAttribute('d')).flatMap(e => {
        const n = Math.ceil(e.getTotalLength() / 3); return Array.from({length: n + 1}, (_, i) => e.getPointAtLength(e.getTotalLength() * i / n)); });
      for (let k = 0; k < 14; k++) for (const lift of [-fs * (0.5 + k * 0.8), fs * (1.2 + k * 0.8)]) for (let i = xs.length - 1; i >= 0; i--) {
        if (!Number.isFinite(xs[i].y)) continue;
        const [cx, cy] = spot(text, P.X(xs[i].x), P.Y(xs[i].y) + lift), a = cx - hw, z = cx + hw, u = cy + top, v = cy + bot;
        if (!boxes.some(r => a < r.x + r.width && r.x < z && u < r.y + r.height && r.y < v) && !dots.some(q => q.x > a && q.x < z && q.y > u && q.y < v)) return [cx, cy];
      }
    } catch (e) { /* no layout: the caller falls back */ }
    return null;
  };
  const tag = xs => {
    [tg, tt].forEach(t => t.setAttribute('display', 'none'));
    if (!kept) return;
    const gaps = xs.map((p, i) => { const q = kept[i]; return q && Number.isFinite(p.y) && Number.isFinite(q.y) ? Math.abs(P.Y(q.y) - P.Y(p.y)) : -1; });
    const gap = Math.max(...gaps), best = gaps.findLastIndex(d => d >= gap * 0.6);   // the right-most place where they are far apart: it leaves the middle to the labels of points
    if (gap < 0) return;
    const p = xs[best], X = P.X(p.x), yt = P.Y(p.y), yg = P.Y(kept[best].y), side = (a, o) => a < o ? -fs * 0.5 : fs * 1.2;
    if (gap < fs * 1.5) return put(tg, 'your guess, true', ...clear(tg, 'your guess, true', xs) || [X, yt - fs * 0.5]);
    put(tg, 'your guess', X, yg + side(yg, yt)); put(tt, 'true', X, yt + side(yt, yg));
  };
  const pts = k => (ctx.s.get(k) || []).map(p => Array.isArray(p) ? {x: p[0], y: p[1]} : p);
  // The curve of the option that the learner locked in, copied once; a gate opened again takes it away.
  const guessed = () => {
    if (!guess) return;
    if (ctx.s.get(`gate.${b.guess}`) !== 'done') { kept = null; gs.removeAttribute('d'); return; }
    if (kept) return;
    const gt = ctx.gates?.find(x => x.id === b.guess), log = [...(ctx.s.get('log') || [])].reverse().find(e => e.gate === b.guess);
    const k = gt && log && b.guesses[gt.options().indexOf(log.picked)];
    if (!k) return;
    kept = pts(k); gs.setAttribute('d', line(kept));
    gs.setAttribute('aria-label', 'what you predicted');
  };
  ctx.s.on(() => {
    guessed();
    const xs = (ctx.s.get(b.series) || []).map(p => Array.isArray(p) ? {x: p[0], y: p[1]} : p);
    let d = '', pen = false;
    for (const p of xs) {
      const ok = Number.isFinite(p.y) && Math.abs(P.Y(p.y)) < 1e5;
      if (ok) { d += `${pen ? 'L' : 'M'}${P.X(p.x).toFixed(2)} ${P.Y(p.y).toFixed(2)}`; pen = true; } else pen = false;
    }
    if (b.ghost && cur !== null && d !== cur) {
      const now = performance.now();
      if (now - at > 500) { old = cur; ghost.setAttribute('d', old); }
      at = now;
    }
    cur = d;
    path.setAttribute('d', b.dots ? '' : d);
    last = xs;
    if (guess) queueMicrotask(() => tag(xs));   // after the dots and labels beside it have moved
    dots.replaceChildren(...(b.dots ? xs.filter(p => Number.isFinite(p.y)).map(p => sv('circle', {cx: P.X(p.x), cy: P.Y(p.y), r: 3.5})) : []));
  });
  return g;
});

/* blocks/point/point.js */
/* point: a dot on its axis. It drags when its key is a state input; a point on a derived value only shows it.
   Arrows or WASD move one step; ⇧ moves ten. On a number line ↑/↓ move it too.
   With `along`, the dot sits on a curve (its y is derived): a drag or A/D or ←/→ changes only the state key of x, and y follows. */
Rupaka.block('point', (b, ctx) => {
  const {sv, show} = Rupaka, s = ctx.s, P = ctx.plane;
  if (!P) throw new Error('a point must be inside an axis');
  const kx = b.bind || b.x, ky = b.y, st = ctx.spec.state || {}, step = b.step ?? 1;
  const along = !!b.along && !!ky, drag = b.drag ?? (Object.hasOwn(st, kx) && (along || !ky || Object.hasOwn(st, ky)));
  const dot = sv('circle', {class: 'dot', r: 7}), ring = sv('circle', {class: 'halo', r: 14}), txt = sv('text', {class: 'pl', 'text-anchor': 'middle'});
  const g = sv('g', drag ? {tabindex: 0, role: 'slider', 'aria-label': b.label || kx} : {role: 'img'}, ring, dot, txt);
  if (drag) g.classList.add('drag');
  const snap = (v, [lo, hi]) => +Math.min(hi, Math.max(lo, Math.round(v / step) * step)).toFixed(6);
  const put = (x, y) => { if (x !== s.get(kx)) ctx.put(b, kx, x); if (ky && !along && y !== s.get(ky)) ctx.put(b, ky, y); };
  const at = e => { const pt = P.svg.createSVGPoint(); pt.x = e.clientX; pt.y = e.clientY; return pt.matrixTransform(P.svg.getScreenCTM().inverse()); };
  if (drag) {
    g.addEventListener('pointerdown', e => { if (!ctx.live(b.lock)) return; e.stopPropagation(); g.setPointerCapture(e.pointerId); g.classList.add('held'); });
    g.addEventListener('pointermove', e => { if (!g.hasPointerCapture(e.pointerId)) return; const p = at(e); put(snap(P.invX(p.x), P.x), ky ? snap(P.invY(p.y), P.y) : null); });
    g.addEventListener('pointerup', () => g.classList.remove('held'));
    g.addEventListener('keydown', e => {
      const k = e.key.toLowerCase(), d = step * (e.shiftKey ? 10 : 1);
      const dx = ['arrowright', 'd'].includes(k) ? d : ['arrowleft', 'a'].includes(k) ? -d : 0;
      const dy = along ? 0 : ['arrowup', 'w'].includes(k) ? d : ['arrowdown', 's'].includes(k) ? -d : 0;
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

/* blocks/points/points.js */
/* points: glowing dots, each with a name if you like. `stars`: the 815 brightest stars (real places, sizes and colours), with `lines` the
   star figures. `round: N`: N places round a circle, named in flat text, as a zodiac or a clock. `pts`: places that can be state keys. `of`: a state list. */
(() => {
  // A star is four ints: right ascension and declination (deg x 10), magnitude x 10, colour index B-V x 10.
  const STARS = [58035,-167,-14,0,54998,-527,-6,2,122567,192,0,12,125993,-608,0,7,159987,388,0,0,45361,460,1,8,45052,-82,2,0,65793,52,4,4,13997,-572,4,-2,50873,74,4,15,120871,-604,6,-2,170570,89,8,2,106943,-631,8,-2,39523,165,9,15,115336,-112,10,-2,141721,-264,11,19,66652,280,12,10,197332,-296,12,1,109968,-597,12,-2,177823,453,12,1,125993,-608,14,9,87141,120,14,-1,59966,-290,15,-2,65117,319,16,0,107596,-571,16,16,150917,-371,16,-2,46570,64,16,-2,46736,286,16,-1,79240,-697,17,1,48157,-12,17,-2,190256,-470,17,-1,48810,-19,17,-2,70119,-473,18,-1,110873,560,18,0,29267,499,18,5,158159,-344,18,0,95071,618,18,11,61364,-264,18,7,118539,493,18,-1,71981,-595,19,12,151450,-430,19,4,51497,450,19,1,144483,-690,19,14,56969,164,19,0,75161,-547,19,0,175560,-567,19,-1,21744,893,20,6,54815,-180,20,-2,81303,-87,20,14,18214,235,20,12,88803,198,20,11,6245,-180,20,10,162617,-263,20,-1,121278,-364,21,10,1203,291,21,0,9987,356,21,16,49813,-97,21,-2,127586,742,21,15,195190,-469,21,16,151106,126,21,2,26952,410,21,0,17745,423,21,14,101562,146,21,1,8125,607,22,0,109080,-490,22,0,69271,-400,22,-3,79796,-593,22,2,133883,267,22,0,78495,-434,22,17,115153,549,22,1,175073,403,22,7,5804,565,22,12,154212,515,22,15,47555,-3,22,-2,1312,592,23,4,117439,-535,23,-2,137556,-226,23,-1,144695,-343,23,11,126326,-474,23,-2,125409,-422,23,-2,94802,564,23,0,126767,271,24,10,186813,99,24,15,152189,-390,24,-2,3764,-423,24,11,102250,537,24,0,147588,-157,24,1,198209,281,24,17,63610,-293,24,-1,183140,626,24,3,80518,-550,25,-1,178505,340,25,10,198352,152,25,0,26110,41,25,16,142833,-106,25,0,119679,-473,26,-2,96561,205,26,1,138289,-198,26,-1,47659,-178,26,2,104330,-507,26,-1,105396,-175,26,-1,163665,-299,26,1,131351,-94,26,-1,135258,64,26,12,16421,208,26,2,48650,-341,26,-1,51526,372,26,-1,108060,-234,26,9,12290,602,27,2,119559,184,27,6,128704,-431,27,-2,42542,332,27,15,92642,-494,27,9,108461,-691,27,-2,150510,-373,27,-2,62619,-371,27,16,157707,-298,27,14,169916,106,27,15,139567,-37,27,16,140948,615,27,9,92097,-644,27,-2,109103,-14,27,4,48048,-59,28,-2,114678,-367,28,1,127609,-160,28,2,152332,46,28,12,44095,-51,28,2,141841,215,28,10,148201,144,28,12,105304,-588,28,-2,150464,523,28,10,133952,-412,28,-2,47017,-208,28,8,143423,316,28,6,3690,-772,28,6,142649,-282,28,-2,158704,-254,28,10,1896,152,28,-2,69838,-243,28,5,136817,-634,28,3,33535,319,28,3,149725,-555,28,15,150665,-499,28,-1,32584,241,28,-1,112036,110,28,9,187220,-161,28,2,17011,-616,29,3,169733,451,29,0,54855,225,29,16,131626,-687,29,0,191729,-603,29,14,25537,-403,29,1,164691,-210,29,4,64051,83,29,-1,111160,383,29,-1,137344,-261,29,-2,34068,400,29,-2,140547,-256,29,3,185002,-56,29,8,26471,535,29,7,84099,-651,29,3,195235,302,29,8,58717,-506,29,12,107412,-165,29,0,189907,-3,30,10,34097,-135,30,16,48363,211,30,-2,83915,238,30,8,155529,-304,30,10,114437,-232,30,9,152922,-401,30,5,164066,139,30,0,18558,350,30,1,95925,445,30,11,131883,718,30,1,144941,-380,30,-2,188205,-374,30,-1,31931,478,30,-1,54477,-301,30,-2,60596,-238,30,-1,104582,-226,30,13,43253,438,30,5,109762,-681,30,-2,124916,383,30,2,167693,280,30,11,174895,-148,30,8,57857,251,31,14,89141,415,31,16,165092,677,31,10,157225,-368,31,16,76690,60,31,10,93054,-162,31,12,99666,-630,31,0,177267,-473,31,10,50271,-358,31,12,77235,480,31,2,145909,-560,31,16,148259,248,31,1,128795,-421,31,-2,80363,344,31,16,81824,-570,32,15,148259,368,32,14,56975,-432,32,-1,82053,517,32,5,147365,657,32,-1,161236,-270,32,-1,43906,412,32,-2,126412,-650,32,3,41517,70,32,5,43757,-224,32,15,145772,94,32,12,153243,-370,32,12,182332,302,32,10,203308,776,32,10,131975,-406,32,-2,140134,-47,32,10,157752,-29,32,9,184590,706,32,-2,58470,-619,32,2,173509,-8,32,-1,64349,-433,32,15,121232,-267,32,11,129500,-253,32,17,163144,327,32,0,32550,-742,33,16,5632,309,33,13,149256,-250,33,-2,196903,-158,33,1,44822,-162,33,-1,87909,-700,33,-1,132485,590,33,12,39248,-550,33,-1,90533,-617,33,-1,53698,225,33,16,149743,-564,33,-2,9465,-467,33,9,26522,388,33,15,105344,570,33,1,147846,-432,33,4,154561,-98,33,10,164290,-277,33,12,36446,-625,33,9,96578,154,33,0,67219,-249,33,12,16387,637,34,-2,46478,-24,34,-2,58052,129,34,4,73092,607,34,9,166943,31,34,3,132164,-447,34,-2,75453,64,34,7,116694,-6,34,1,48002,99,34,-2,88390,-613,34,15,111097,34,34,16,190629,582,34,16,38486,159,34,2,12657,-433,34,15,34475,125,34,-1,118820,-417,34,-2,130674,-521,34,9,178373,618,34,9,195018,108,34,-1,16198,296,34,5,137527,-384,34,-2,152756,277,34,8,178327,-662,34,2,78919,-590,34,-2,88333,234,34,3,164187,-49,34,-1,88390,429,34,0,7036,578,35,6,9826,-102,35,12,68291,-530,35,-2,131139,333,35,10,23394,32,35,1,118831,-425,35,-2,86992,168,35,0,143652,389,35,9,14908,-159,35,7,60407,-279,35,17,97185,331,35,14,129196,404,35,10,158560,-460,35,-2,196032,-513,35,1,58705,-325,35,-1,63043,220,35,4,196192,662,35,10,171710,195,35,16,196238,246,35,9,31977,-98,35,9,83245,99,35,5,85497,-546,35,-1,161872,334,35,0,162966,-211,35,12,190537,62,35,1,38474,192,35,10,71121,92,35,15,99265,-319,35,10,136026,-34,35,0,151490,-154,35,3,36939,-338,36,-1,49698,-148,36,1,123100,-461,36,-2,157712,727,36,5,173136,-662,36,8,2785,-88,36,12,19555,-515,36,-1,97311,-148,36,11,145004,-380,36,-2,66526,244,36,9,77871,472,36,0,124882,304,36,13,132038,-363,36,15,62750,165,36,1,174471,-125,36,9,14037,486,36,13,45493,-68,36,-1,49343,-224,36,5,101797,18,36,5,106192,-604,36,14,12038,-82,36,11,59129,340,36,1,74525,-529,36,-2,81750,-405,36,4,134221,-281,36,14,150556,-607,36,-1,24351,273,36,-1,29335,90,36,9,87462,-124,36,10,112053,-716,36,12,152653,-647,36,12,13104,154,36,10,32825,240,36,-1,66641,-380,36,17,145331,-424,36,14,197945,423,36,-1,101070,-667,36,2,177267,146,36,4,37214,156,36,10,81864,631,36,4,135533,154,36,1,155650,-501,36,-1,193207,0,36,4,132903,291,37,3,134450,-298,37,-2,120951,644,37,0,179737,-584,37,12,41711,56,37,-2,75000,-332,37,-2,170083,185,37,13,199023,-212,37,12,5294,539,37,-2,16610,-516,37,8,43327,411,37,12,83829,-625,37,10,101133,478,37,12,186223,-167,37,3,28579,-218,37,16,154378,292,37,9,200128,33,37,9,42147,24,37,-2,51051,-142,37,3,67638,-406,37,10,136192,45,37,2,155753,96,37,2,171217,64,37,8,30499,-95,37,9,32212,241,37,-1,51497,543,37,10,181186,439,37,16,29673,97,37,-1,126945,19,37,0,153770,569,37,12,186423,-774,37,10,196610,-76,37,16,15968,-103,37,11,140650,192,37,3,182602,380,37,4,77945,-471,38,12,152963,27,38,0,47790,-625,38,6,50323,-209,38,10,55691,-70,38,-1,163963,-217,38,10,167550,517,38,2,193557,503,38,0,24448,559,38,17,32258,426,38,4,37661,175,38,10,48524,-26,38,-2,72439,-661,38,11,74576,-466,38,7,144643,-590,38,16,177565,159,38,-1,184303,-224,38,10,190079,254,38,4,61415,-705,38,10,63845,278,38,10,84655,590,38,3,93604,-588,38,9,126217,137,38,0,178717,-95,38,5,27141,449,38,10,93581,342,38,10,97145,315,38,6,27513,-290,38,5,65724,-268,38,-2,133900,105,38,3,165745,534,38,10,173841,467,38,13,39471,-306,38,10,89937,-587,38,3,135040,263,38,0,203051,465,38,10,17481,28,38,0,80048,368,38,1,99036,693,38,16,141939,20,38,0,151759,460,38,-2,89679,-168,38,15,120075,-421,38,-2,127179,-790,38,14,32114,-648,38,11,32131,323,38,0,38468,160,38,10,76639,-606,38,-1,90642,93,38,-2,91289,-482,38,3,107785,-721,38,-2,155781,288,38,0,156670,-211,38,2,170191,703,38,9,36383,-423,38,11,49744,-511,38,2,54735,-334,38,9,88052,-421,38,0,107928,698,38,-1,108535,-485,38,0,137000,157,38,5,158091,218,38,12,159741,-82,38,13,8130,385,39,1,39849,-143,39,11,47441,-355,39,11,139721,-637,39,11,142300,-789,39,9,154160,372,39,14,192176,-14,39,-1,32349,244,39,-1,75350,-460,39,0,120132,-448,39,-2,126492,-57,39,4,137063,-292,39,-2,170810,10,39,6,1346,-458,39,10,16261,193,39,0,84907,260,39,12,130623,-487,39,0,199154,-452,39,10,25273,-89,39,11,59318,-242,39,17,79406,23,39,-1,105986,-7,39,0,171360,351,39,10,83056,-11,39,13,97546,-545,39,-2,116173,-394,39,12,34830,60,39,0,72433,-39,39,0,107149,-502,39,-2,129649,-470,39,-1,134003,-148,39,10,140340,463,39,-2,146144,309,39,0,166398,-178,39,2,182751,52,39,6,3753,-437,39,2,13069,-491,39,10,24958,528,39,8,39580,-34,39,-2,66154,-726,39,10,95770,-590,39,12,138484,-207,39,0,154790,29,39,0,9798,-552,39,-1,66068,-96,39,10,66434,-290,39,2,75155,182,39,11,180075,412,39,0,17681,724,40,0,56820,-193,40,10,35621,477,40,0,51446,-428,40,12,77441,418,40,5,78965,-623,40,-2,166536,-445,40,-1,166714,-406,40,-1,174105,477,40,14,200959,-201,40,11,37821,-340,40,15,50346,392,40,11,62573,-680,40,8,74502,-353,40,9,104800,-524,40,-2,136215,-336,40,0,171973,-729,40,0,193270,-435,40,10,195740,236,40,11,34228,358,40,0,185352,456,40,9,17189,-211,40,16,53692,-63,40,13,89439,-740,40,4,115342,550,40,2,200169,-582,40,4,77699,-664,40,1,97964,105,40,4,139229,-195,40,1,14851,507,40,-1,40898,-32,40,-2,60751,206,40,9,62281,-268,40,-2,126331,-378,40,-2,137779,586,40,5,140352,-502,40,11,160864,-714,40,11,176099,304,40,4,75991,-277,40,13,104336,-247,40,3,163241,151,40,11,163534,-57,40,11,19670,338,40,0,43459,604,40,9,75441,288,40,10,110953,-572,40,-2,155478,25,40,9,176643,113,40,-1,206167,69,40,4,36079,-68,40,3,101104,65,40,15,123931,518,40,5,194141,-1,40,-1,27084,496,40,6,71408,-769,40,4,75115,-426,40,9,97563,60,40,-1,118814,158,40,15,123266,-379,40,0,125747,-494,40,-2,196181,-136,40,16,42450,135,41,12,65306,269,41,15,98102,-177,41,2,105648,-680,41,16,105774,-640,41,-2,126572,-352,41,14,146047,-532,41,14,122613,-60,41,5,130182,-453,41,-2,131425,-588,41,1,193253,584,41,8,6778,243,41,11,20306,-687,41,0,22844,3,41,-2,26127,-236,41,2,59330,-120,41,14,82282,-592,41,0,94504,-183,41,11,162623,440,41,14,181335,-172,41,0,183644,198,41,11,48260,93,41,10,135894,181,41,16,13866,414,41,5,23520,492,41,5,67214,-464,41,-2,158830,-491,41,10,164731,-393,41,12,23016,-399,41,10,60699,-156,41,-1,74146,-430,41,1,84723,-148,41,9,91026,-786,41,16,101202,-612,41,9,134175,-663,41,12,164651,-379,41,0,197796,-528,41,10,22861,-683,41,-1,36509,484,41,9,51910,96,41,2,103877,87,41,10,171211,-419,41,11,179313,-269,41,16,193339,-438,41,16,46404,-78,41,9,55714,202,41,-1,136628,-167,41,10,178488,-253,41,4,195671,-814,41,2,203394,56,41,5,30206,129,41,11,32418,240,41,0,74146,57,41,0,104118,-646,41,4,133631,314,41,-1,137166,269,41,12,186876,256,41,4,191362,378,41,14,61862,-5,42,0,149496,372,42,0,203457,443,42,-1,52156,233,42,8,64332,318,42,3,138134,-114,42,5,149880,-242,42,3,4727,629,42,1,32865,-362,42,9,191488,-78,42,10,122166,-103,42,13,122670,461,42,1,142718,-353,42,15,191230,570,42,3,194897,-270,42,-1,118809,-344,42,15,161242,206,42,5,47384,60,42,-1,68302,-229,42,7,89937,367,42,9,142397,424,42,0,195762,122,42,5,197092,-325,42,10,29949,599,42,4,38010,223,42,1,144093,820,42,9,176127,630,42,2,184269,-654,42,5,24437,383,42,3,32492,-232,42,4,67798,-481,42,-1,138455,-368,42,-2,141383,-185,42,2,157672,713,42,-1,161454,-48,42,11,162176,-622,42,-2,162508,369,42,16,178431,307,42,10,182974,394,42,1,199722,-60,42,15,2876,-649,42,6,66366,289,42,11,113428,279,42,6,118270,-330,42,4,120556,15,42,1,138765,449,42,0,143681,-775,42,11,164210,-371,42,5,186715,588,42,22,187185,493,42,-1,9849,863,42,12,21056,-477,42,-1,23508,-139,42,-1,105762,-793,42,-1,107968,414,42,6,142008,-347,42,-2,152034,-129,42,1,199945,-91,42,11,10852,-689,42,5,35323,504,42,0,39483,102,42,2,39631,413,42,12,44284,-88,42,-2,72027,432,42,16,110787,-402,42,2,124263,757,42,14,186991,611,42,5,9958,472,43,0,15097,92,43,9,28636,-431,43,7,30625,-216,43,-1,36675,-515,43,3,42118,663,43,0,77132,119,43,1,151341,-386,43,11,154916,216,43,4,189620,646,43,4,9018,79,43,10,23629,101,43,3,36601,89,43,0,39843,125,43,1,40428,230,43,-1,112718,-499,43,-2,131568,-479,43,-1,166616,-448,43,4,178568,161,43,10,201675,64,43,11,38148,228,43,3,82661,813,43,15,89834,-311,43,14,150023,-299,43,4,173807,566,43,1,183667,-168,43,9,190508,332,43,5,198656,-435,43,4,31066,4,43,6,45774,-132,43,-2,91576,-556,43,10,102118,-339,43,-1,135224,778,43,0,141967,-166,43,9,189999,-139,43,-1,193591,-324,43,0,203131,433,43,-1,8394,-294,43,-2,21222,85,43,0,32258,245,43,-1,32745,-376,43,0,38027,179,43,0,51555,459,43,17,74949,34,43,-2,93908,248,43,0,99832,-8,43,10,101654,-638,43,-2,107728,-162,43,4,123232,-564,43,1,174414,-125,43,9,74570,-598,43,-1,124177,-837,43,13,132422,374,43,3,138570,-209,43,8,177376,-11,43,10,31008,482,43,-1,40170,-197,43,16,47584,186,43,21,53766,295,43,10,75396,-136,43,9,81893,230,43,15,103568,-633,43,3,113159,175,43,5,119152,-330,43,-2,127718,-436,43,-2,149089,-128,43,0,64194,89,43,14,110741,-489,43,13,124074,-454,43,4,148304,-266,43,8,155930,-637,43,2,157546,361,43,12,5283,337,43,-1,5523,293,43,9,10187,552,43,2,49383,-657,43,2,56127,-234,43,-2,71711,-775,43,12,79670,-575,43,16,82626,-494,43,2,120568,-456,43,6,134364,-426,43,14,149903,41,43,15,161110,376,43,2,161437,182,43,2,186859,174,43,12,193305,477,43,17,27450,197,44,10,41625,89,44,0,56574,-530,44,0,59771,584,44,8,69889,-686,44,-1,75693,58,44,0,106988,283,44,11,131471,-302,44,11,150717,866,44,0,158027,-615,44,15,165636,381,44,13,186922,-330,44,0,4521,-630,44,-1,6211,-575,44,0,19051,88,44,9,30160,480,44,14,35048,221,44,11,41952,-54,44,3,44868,-129,44,-1,51211,-353,44,-2,59605,-170,44,-1,69987,-30,44,10,121186,-412,44,-2,168553,-13,44,-1,281,-60,44,16,53938,-351,44,10,62842,-250,44,-1,94561,-422,44,1,155953,208,44,-2,171847,-353,44,-2,113153,-55,44,0,173159,777,44,0,201400,-206,44,15,202392,-378,44,-1,16278,-463,44,16,32876,655,44,19,47962,95,44,-2,50764,203,44,6,54970,46,44,2,69082,23,44,12,87078,100,44,14,129334,21,44,10,145245,102,44,-1,149112,-211,44,4,169034,180,44,8,169172,175,44,10,183329,-534,44,2,8193,234,44,9,67048,-259,44,-1,70050,-192,44,-2,162858,-672,44,5,188778,-550,44,3];
  // The star figures: each a list of right ascension and declination pairs (deg x 10).
  const FIGS = [[310,423,174,356,98,309,21,291],[143,234,118,243,96,293,98,309,92,337,3545,433,3455,423],[3545,433,3551,443,3544,465],[174,356,142,385,124,411,174,472,245,486],[3551,443,3565,464],[1423,-360,1568,-311,1642,-371],[2220,-790,2451,-787,2508,-775,2484,-789],[3119,-95,3132,-90,3229,-56,3314,-3,3354,-14,3372,0,3388,-1,3432,-76,3495,-92,3474,-212],[3229,-56,3316,-139],[3314,-3,3342,-78],[3372,0,3363,14],[3507,-201,3495,-92,3554,-178],[2966,106,2977,89,2988,64,3028,-8,2981,10,2914,31,2864,139,2977,89,2914,31,2866,-49],[2614,-564,2628,-607,2524,-590,2547,-560,2549,-532,2630,-499,2613,-555],[425,273,318,235,287,208,284,193],[899,450,792,460,766,412,742,332,816,286,899,372,899,450,899,543,792,460,755,438,756,411],[2068,175,2087,184,2139,192,2180,304,2180,383,2255,404,2289,333,2212,271,2139,192,2203,137],[2180,383,2141,461,2134,518,2163,518,2141,461],[677,-450,701,-419,705,-371,761,-355],[743,538,758,604,735,663,576,713,574,655,523,599],[735,663,947,693,1050,770],[1346,119,1312,182,1308,215,1317,288],[1312,182,1241,92],[1940,383,1884,414],[957,-180,1013,-167,1058,-238,1071,-264,1054,-279,1047,-290,951,-301],[1110,-293,1071,-264],[1013,-167,1040,-170,1059,-156,1036,-120,1040,-170],[1148,52,1118,83],[3044,-125,3052,-148,3072,-178,3115,-253,3130,-269,3217,-224,3268,-161,3250,-167,3206,-168,3165,-172,3044,-125],[994,-432,960,-527,1383,-697,1534,-700,1607,-644,1580,-617,1543,-613,1393,-593,1256,-595,1192,-530,1224,-473,1312,-547,1393,-593],[1607,-644,1666,-624,1671,-620,1682,-603,1672,-590,1634,-588,1580,-617],[286,637,214,602,142,607,101,565,23,592],[1702,-545,1821,-507,1870,-502,1904,-490,2050,-535,2089,-473,2074,-425,2074,-417,2117,-364,2189,-422,2248,-421],[2074,-417,2002,-367],[2199,-608,2050,-535,2110,-604],[1870,-502,1829,-524,1729,-594],[3074,630,3113,618,3196,626,3259,588,3338,570,3327,582,3373,584,3424,662,3548,776,3222,706,3196,626],[3222,706,3424,662],[408,32,390,56,370,85,412,101,449,89,456,41,408,32,399,3,348,-30,279,-103,260,-159,109,-180,49,-88,172,-102,210,-82,279,-103],[1246,-769,1589,-786,1613,-805,1846,-793,1799,-782,1589,-786],[2294,-588,2206,-650,2308,-593],[955,-334,877,-358,849,-341,828,-355],[877,-358,898,-428],[1975,175,1980,279,1867,283],[2847,-371,2866,-371,2874,-379,2875,-393,2871,-405,2858,-421,2824,-434,2784,-423],[2332,314,2320,291,2337,267,2357,263,2374,261,2394,269,2404,298],[1821,-247,1825,-226,1840,-175,1875,-165,1886,-234,1825,-226],[1742,-98,1712,-109,1698,-148,1649,-183,1679,-228,1708,-188,1712,-177,1762,-184,1790,-172],[1698,-148,1712,-177],[1919,-597,1838,-588],[1866,-631,1878,-571],[3182,302,3116,340,3056,403,2962,451,2924,517,2893,534],[3104,453,3056,403,2991,351,2927,280],[3083,113,3094,146,3099,159,3117,161,3109,151,3094,146],[640,-515,685,-550,834,-625,862,-657,885,-631,834,-625,764,-575,685,-550],[2684,569,2692,515,2626,523,2631,552,2684,569,2881,677,2752,713,2572,657,2460,615,2405,586,2312,590,2111,644,1884,698,1728,693],[2752,713,2753,727],[2881,677,2970,703],[3190,52,3186,100,3176,101],[770,-51,714,-32,691,-34,630,-68,595,-135,565,-121,558,-98,532,-95,441,-89,410,-139,413,-186,456,-236,499,-218,534,-216,567,-232,689,-306,660,-340,645,-338,574,-362,543,-403,500,-431,446,-403,402,-399,368,-477,341,-515,290,-516,244,-572],[480,-290,423,-324,311,-293],[937,225,957,225,1010,251,1078,302,1136,319,1163,280,1140,269,1100,220,1060,206,994,164,1013,129],[1100,220,1095,165],[3452,-528,3421,-513,3407,-469,3374,-438,3321,-470,3407,-469],[3373,-435,3339,-414,3315,-395,3285,-374],[2455,192,2476,215,2503,316,2507,389,2485,424,2449,463,2422,449,2382,424],[2503,316,2551,309],[2507,389,2588,368],[2691,372,2609,372,2588,368,2551,309,2588,248,2666,277,2694,292,2719,288],[2587,144,2476,215],[635,-423,406,-508,394,-525,402,-546,459,-597,447,-641],[1317,64,1321,58,1308,34,1297,33,1294,57,1317,64,1338,60,1386,23,1450,-11,1419,-87,1479,-148,1526,-124,1565,-168,1624,-162,1732,-319,1782,-339,1997,-232,2116,-267,2226,-280],[64,-772,568,-742,399,-683,354,-687,287,-676,297,-616],[3094,-473,3110,-519,3137,-584,3295,-550,3200,-534,3094,-473],[3359,522,3378,503,3374,477,3353,465,3376,431,3401,443,3374,477,3361,495,3359,522],[3376,431,3335,397,3340,378],[1521,120,1518,168,1550,198,1685,205,1773,146,1686,154,1521,120],[1550,198,1542,234,1482,260,1465,238],[1519,352,1565,338,1633,342,1570,367,1519,352,1436,364],[915,-149,891,-142,867,-148,832,-178,782,-162,764,-224,821,-208,861,-224,878,-209],[783,-129,782,-162,799,-132],[2260,-253,2227,-160,2292,-94,2339,-148,2343,-281,2347,-298],[2227,-160,2339,-148],[2377,-336,2349,-344,2304,-363,2303,-406,2246,-431,2205,-474,2281,-521,2296,-479,2307,-447,2338,-412,2400,-384,2416,-368],[2303,-406,2338,-412],[949,590,1043,584,1117,492,1257,432,1352,418,1397,368,1403,344],[2812,376,2811,396,2792,388,2812,376,2836,369,2847,327,2825,334,2812,376],[926,-748,830,-763,738,-749,757,-713],[3125,-338,3121,-440,3202,-408,3195,-322,3153,-323,3125,-338],[1153,-96,1222,-30,1080,-5,972,-70,937,-63],[1080,-5,1020,24,959,46,982,73,1002,99],[1764,-667,1844,-680,1893,-691,1916,-681,1956,-716,1881,-721,1893,-691],[2416,-452,2468,-476,2450,-502,2408,-492,2416,-452],[2167,-837,3415,-814,3254,-774,2167,-837],[2698,-98,2670,27,2659,46,2637,126,2544,94,2477,20,2436,-37,2446,-47,2493,-106,2576,-157],[2544,94,2493,-106,2478,-166,2468,-185,2460,-200,2464,-234],[2659,46,2576,-157,2605,-250,2618,-299],[919,148,886,203,910,201,930,142,906,96,888,74,813,64,737,102],[746,17,736,24,728,56,725,70,726,89,737,102,741,135,761,154,774,156],[786,-82,811,-24,830,-3,813,64,838,99,888,74,852,-19,869,-97],[852,-19,840,-12,830,-3],[3064,-567,3112,-662,3022,-662,2830,-622,2758,-615,2722,-637,2664,-647,2808,-714,3002,-729,3112,-662,3216,-654],[3325,332,3408,302,3459,281,21,291,33,152,3462,152,3417,122,3404,108,3326,62,3260,99],[3462,152,3459,281,3425,246,3416,236,3318,254,3262,256],[561,323,585,319,597,358,595,400,563,426,557,478,541,482,511,499,462,535,427,559,436,528,473,496,474,449,470,410,478,396,463,388,447,397,449,410,470,410],[616,504,637,484,622,477,557,478],[473,496,410,492,259,507],[66,-423,165,-467,221,-433,228,-491,171,-552,165,-467,24,-458,66,-423],[1020,-619,875,-562,868,-511],[184,246,179,301,199,273,184,246,179,210,229,154,264,92,305,28,284,32,254,55,226,61,184,76,157,79,122,76,3598,69,3550,56,3520,64,3501,54,3493,33,3517,13,3555,18,3566,35,3550,56],[3493,33,3460,38],[3402,-270,3444,-296,3440,-325,3431,-329,3379,-324,3321,-330,3262,-330,3269,-309,3321,-330,3402,-270],[994,-432,1093,-371,1138,-284,1147,-268,1173,-249,1192,-229,1219,-243,1209,-400,1224,-473],[1173,-249,1170,-259,1160,-290,1138,-284],[1209,-400,1300,-353,1309,-332,1326,-277],[636,-625,641,-593,597,-614,560,-648,636,-625],[2950,180,2968,185,2997,195],[2953,175,2968,185],[2744,-368,2760,-344,2752,-298,2770,-254,2734,-211],[2907,-445,2910,-406,2856,-299,2814,-270,2770,-254],[2988,-419,2999,-353,2990,-263,2942,-249,2913,-245,2889,-253,2838,-263,2814,-270,2752,-298,2714,-304,2760,-344,2856,-299,2867,-277,2838,-263,2862,-217,2874,-210,2894,-190,2904,-178,2904,-160],[2862,-217,2844,-211,2835,-227,2838,-263],[2397,-261,2401,-226,2414,-198],[2401,-226,2453,-256,2474,-264,2490,-282,2525,-343,2530,-380,2536,-424,2580,-432,2643,-430,2669,-401,2656,-390,2634,-371],[146,-294,3572,-281,3497,-325,3532,-378],[2788,-82,2818,-48,2806,-90,2773,-146,2788,-82],[2366,154,2354,197,2372,181,2391,157,2366,154,2337,105,2361,64,2377,45,2436,-37],[2576,-157,2644,-154,2698,-98,2708,-82,2753,-29,2840,42],[1520,-4,1481,-81,1574,-27,1576,-6],[844,211,690,165,672,159,650,156,657,175,672,192,816,286],[650,156,602,125,518,97,608,60],[518,97,512,90,542,4],[2728,-460,2767,-460,2772,-491],[283,296,324,350,343,338,283,296],[2522,-690,2388,-634,2297,-687,2522,-690],[3346,-603,3494,-582,79,-630,50,-649,3600,-656,3368,-650,3346,-603],[1839,570,1659,618,1655,564,1785,537,1839,570,1935,560,2010,549,2069,493],[1785,537,1765,478,1696,331,1696,315],[1765,478,1674,445,1556,415],[1674,445,1543,429],[1659,618,1429,631,1276,607,1478,590,1655,564],[1655,564,1480,541,1432,517,1348,480],[1359,472,1432,517],[2360,778,2444,758,2302,718,2227,742,2360,778,2515,820,2630,866,380,893],[1312,-547,1405,-550,1492,-546,1617,-494,1537,-421,1427,-405,1370,-434,1224,-473],[1765,65,1777,18,1850,-7,1904,-14,1975,-55,2013,-112,2140,-60,2208,-57],[1955,110,1939,34,1904,-14],[1975,-55,2037,-6,2104,15,2216,19],[1356,-664,1264,-661,1220,-686,1092,-680,1072,-705,1220,-686,1356,-664],[2890,214,2922,247,2984,241,3003,278,3039,278]];
  const rad = d => d * Math.PI / 180, OBL = 23.44;
  const tint = bv => bv < 0 ? [.62, .74, 1] : bv < .5 ? [.78, .85, 1 - bv * .3] : bv < 1 ? [1, .95 - (bv - .5) * .35, .8 - (bv - .5) * .9]
    : [1, .7 - Math.min(.3, (bv - 1) * .25), .45 - Math.min(.3, (bv - 1) * .2)];
  const VS = `attribute float size; attribute vec3 tint; uniform float px; varying vec3 vC;
    void main() { vC = tint; gl_PointSize = size * px; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.); }`;
  const FS = `uniform float alpha; varying vec3 vC;
    void main() { float a = smoothstep(1., 0., length(gl_PointCoord - .5) * 2.); gl_FragColor = vec4(vC, a * a * alpha); }`;
  const css = c => `rgb(${c.map(x => Math.round(x * 255)).join()})`;
  // A name as flat text that faces the viewer: a sprite with no leader line, so a ring of names stays clean.
  function word(T, text, color, font, shade) {
    const c = Object.assign(document.createElement('canvas'), {width: 256, height: 64}), g = c.getContext('2d');
    Object.assign(g, {font: `500 28px ${font}`, textAlign: 'center', textBaseline: 'middle', fillStyle: css(color), shadowColor: css(shade), shadowBlur: 8});
    g.fillText(String(text), 128, 32);
    const t = new T.CanvasTexture(c); t.colorSpace = T.SRGBColorSpace;
    const sp = new T.Sprite(new T.SpriteMaterial({map: t, transparent: true, depthWrite: false})); sp.userData.flat = true;
    return sp;
  }

  Rupaka.block('points', (b, ctx) => {
    const S = ctx.scene;
    if (!S) throw new Error('points must be inside a scene');
    if (!b.stars && !b.pts && !b.of && !b.round) throw new Error('points needs stars, pts, of or round');
    const tone = () => S.palette().lines[b.tone || 'ink'];
    const ring = T => {   // the place of slice k round the circle: its middle, or its first edge
      const [u, v] = S.basis(new T.Vector3(...S.vec(b.axis, [0, 1, 0])).normalize()), c = new T.Vector3(...S.pos(b.about)), r = S.num(b.r, 1), off = S.num(b.offset);
      return (k, mid = true) => { const a = rad(off + (k + (mid ? .5 : 0)) * 360 / b.round); return c.clone().addScaledVector(u, r * Math.cos(a)).addScaledVector(v, r * Math.sin(a)); };
    };
    const places = T => b.stars ? [] : b.round ? Array.from({length: b.round}, (_, k) => ring(T)(k))
      : (b.of ? S.rows(b.of) : b.pts).map(p => new T.Vector3(...S.pos(p)));
    const sky = T => { const k = new T.Matrix4().makeRotationX(b.frame === 'equatorial' ? 0 : rad(-OBL));
      return (ra, de) => new T.Vector3(Math.cos(rad(de)) * Math.cos(rad(ra)), Math.sin(rad(de)), -Math.cos(rad(de)) * Math.sin(rad(ra))).applyMatrix4(k); };
    function dots(T) {
      const pos = [], size = [], col = [];
      if (b.stars) { const at = sky(T);
        for (let i = 0; i < STARS.length; i += 4) { pos.push(...at(STARS[i] / 10, STARS[i + 1] / 10).toArray()); size.push(Math.max(1.1, 4.6 - STARS[i + 2] * .08)); col.push(...tint(STARS[i + 3] / 10)); }
      }
      else for (const p of b.round && b.edge ? Array.from({length: b.round}, (_, k) => ring(T)(k, false)) : places(T)) { pos.push(...p.toArray()); size.push(b.size ?? 4); col.push(...tone()); }
      return {pos, size, col};
    }
    function fill(T, P) {
      const d = dots(T), g = new T.BufferGeometry();
      [['position', d.pos, 3], ['size', d.size, 1], ['tint', d.col, 3]].forEach(([k, v, n]) => g.setAttribute(k, new T.Float32BufferAttribute(v, n)));
      P.cloud.geometry.dispose(); P.cloud.geometry = g; P.at = places(T);
    }
    return S.part(b, {
      make(T, P) {
        P.cloud = new T.Points(new T.BufferGeometry(), new T.ShaderMaterial({uniforms: {px: {value: 1}, alpha: {value: b.opacity ?? 1}}, vertexShader: VS, fragmentShader: FS,
          transparent: true, blending: T.AdditiveBlending, depthWrite: false}));
        P.cloud.frustumCulled = false; P.cloud.userData.flat = true; P.g = new T.Group(); P.g.add(P.cloud); S.world.add(P.g);
        fill(T, P); S.recolors.push(() => { P.ver = null; });
        if (b.stars && b.lines) {
          const at = sky(T), ps = FIGS.flatMap(f => f.slice(2).flatMap((_, i) => i % 2 ? [] : [...at(f[i] / 10, f[i + 1] / 10).toArray(), ...at(f[i + 2] / 10, f[i + 3] / 10).toArray()]));
          const g = new T.BufferGeometry(); g.setAttribute('position', new T.Float32BufferAttribute(ps, 3));
          const fig = new T.LineSegments(g, new T.LineBasicMaterial({color: S.col(S.palette().lines.dim), transparent: true, opacity: .22, depthWrite: false})); fig.userData.flat = true; P.cloud.add(fig);
          S.recolors.push(() => S.paint(fig.material, S.palette().lines.dim));
        }
        P.words = b.round ? (b.names || []).map(n => word(T, n, tone(), S.font(), S.palette().bg)) : [];
        if (P.words.length) P.g.add(...P.words);
        if (!b.round) (b.names || []).forEach((name, i) => {   // names of free places are chips, so the scene keeps them apart
          const pb = {type: 'label3d', tone: b.tone, after: b.after, step: b.step, show: b.show};
          S.chipBox.append(S.part(pb, {anchor: () => P.at[i]?.clone() ?? null}, S.chip(pb, String(name))));
        });
        return P.g;
      },
      sync(P, live) { P.g.visible = live; },
      frame(P) {
        P.cloud.material.uniforms.px.value = Math.min(2, devicePixelRatio || 1);
        if (b.stars) P.cloud.scale.setScalar(S.size * (b.radius ?? 3.2));
        if (P.ver !== S.ver) { P.ver = S.ver; if (!b.stars) fill(S.T, P); }
        P.words.forEach((w, i) => { const p = P.at[i]; if (p) { w.position.copy(p); w.scale.set(S.unit * 6 * (b.text ?? 1), S.unit * 1.5 * (b.text ?? 1), 1); } });
      },
    }, Rupaka.el('li', {text: b.stars ? 'the stars' : b.names ? `places: ${b.names.join(', ')}` : 'dots'}));
  });
})();

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
   `bind` is the step: a part with `step: n` shows from step n. Keys on the view: A/D back and next, 1-9 a step, Q/E turn, W/S tilt, R/F in and out.
   `look: "sky"` is a dark, lit view with no floor and no ink, for space, circuits and maps. `coords` ("geo", "globe") reads at and pts as
   [lon, lat, alt]. A body with `drag` has a grip: a button that the learner drags, or moves with A/D, and that writes a state key. */
(() => {
  const R = Rupaka, {el, sv, fmt} = R;
  const SHOTS = {wide: {az: 30, el: 18, fov: 30}, high: {az: 20, el: 40, fov: 30}, side: {az: 0, el: 4, fov: 12}, front: {az: 90, el: 4, fov: 12},
                 top: {az: 0, el: 89, fov: 12}, close: {az: 30, el: 18, fov: 28}};
  const clamp = (x, a, b) => Math.min(b, Math.max(a, x));
  const inout = t => (t = clamp(t, 0, 1)) < .5 ? 4 * t ** 3 : 1 - (2 - 2 * t) ** 3 / 2;
  const settle = t => { t = clamp(t, 0, 1) - 1; return 1 + 2.4 * t ** 3 + 1.4 * t ** 2; };   // a small overshoot, then rest
  const still = () => matchMedia('(prefers-reduced-motion: reduce)').matches;
  const rad = d => d * Math.PI / 180;
  const lum = c => .2126 * c[0] + .7152 * c[1] + .0722 * c[2];
  const mix = (a, b, t) => a.map((x, i) => x + (b[i] - x) * t);
  // Where [lon, lat, alt] is. "geo": a flat map, x = lon, z = -lat, y = alt (one unit is one degree). "globe": a ball of radius GLOBE.
  const GLOBE = 10, FLAT = {geo: ([lo, la, h]) => [lo, h, -la],
    globe: ([lo, la, h]) => { const r = GLOBE + h, p = rad(la), l = rad(lo); return [r * Math.cos(p) * Math.cos(l), r * Math.sin(p), -r * Math.cos(p) * Math.sin(l)]; }};
  R.GLOBE = GLOBE;
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
  const TOON_F = `uniform vec3 color; uniform vec3 light; uniform float alpha; varying vec3 vN;
    void main() {
      vec3 n = normalize(vN); if (!gl_FrontFacing) n = -n;
      float d = dot(n, light), a = fwidth(d) + .11;
      float band = .66 + .16 * smoothstep(-.3 - a, -.3 + a, d) + .18 * smoothstep(.3 - a, .3 + a, d);
      gl_FragColor = vec4(color * band, alpha);
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
    // With no look, a lamp body gives the sky look: the toon key light would light the night side of every body.
    const look = b.look || ((b.blocks || []).some(k => k.type === 'body' && k.light) ? 'sky' : 'toon'), sky = look === 'sky', s = ctx.s, parts = [], specs = Object.fromEntries((b.blocks || []).filter(k => k.type === 'body').map(k => [k.id, k]));
    const pathSpec = Object.fromEntries((b.blocks || []).filter(k => k.type === 'path' && k.id).map(k => [k.id, k])), ids = new Set(Object.keys(specs)), S = {b, s, ids, bodies: {}, anims: new Map()};
    S.part = (pb, impl, node) => { parts.push({b: pb, impl, node}); return node; };
    S.num = (v, d = 0) => { const n = typeof v === 'number' ? v : +s.get(v); return Number.isFinite(n) ? n : d; };   // a bad value is d, so one key cannot blank the view
    S.list = k => { const v = s.get(k); return Array.isArray(v) ? v : []; };
    S.rows = k => S.list(k).filter(p => p && typeof p === 'object').map(p => Array.isArray(p) ? p : [p.x, p.y, p.z]).map(p => [0, 1, 2].map(i => typeof p[i] === 'number' ? p[i] : 0));
    S.vec = (v, d = [0, 0, 0]) => Array.isArray(v) ? v.map((x, i) => { const n = S.num(x); return Number.isFinite(n) ? n : d[i]; }) : d;
    S.pos = (v, d) => v == null ? d ?? [0, 0, 0] : (FLAT[b.coords] || (a => a))(S.vec(v, d));   // a place: at, pivot and pts go through the coords
    S.sky = sky; S.paths = {}; S.still = still;   // paths: id -> {at(t), length()}, for the parts that ride it; still: reduced motion is on
    S.step = () => b.bind ? (+s.get(b.bind) || 1) : Infinity;
    const own = pb => ctx.live(pb.after) && (pb.step == null || S.step() >= pb.step) && (pb.show == null || !!s.get(pb.show));
    S.seen = id => !!specs[id] && own(specs[id]) && (!specs[id].in || S.seen(specs[id].in));   // a body and each body that holds it
    const rides = pb => [pb.type === 'drift' && pathSpec[pb.on], pb.type === 'body' && pathSpec[pb.along]].filter(Boolean);
    S.live = pb => own(pb) && (pb.on == null || !['force', 'label3d'].includes(pb.type) || S.seen(pb.on))   // a part shows only with the bodies and paths it uses
      && rides(pb).every(own) && (pb.type !== 'links' || pb.nodes.every(S.seen));
    S.shotKey = () => parts.find(p => p.b.type === 'shot' && p.b.bind)?.b.bind;
    // A chip: a label in screen space with a leader line to its point. Its text fills {path} from the state.
    S.chip = (pb, tpl, tone) => {
      const t = el('span', {class: 'txt'}), n = el('div', {class: 'rk-chip off', 'data-tone': pb.tone || tone || 'ink'}, t);
      const fill = () => { t.textContent = fmt(tpl, s.st); };
      s.on(fill); if (S.T) fill();   // a chip that a part makes late (a name of points) has its text at once
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
      const v = new S.T.Vector3(...S.pos(at));
      return on ? S.bodies[on].frame.localToWorld(v) : v;
    };

    S.gripBox = el('div', {class: 'grips'});
    const chips = el('div', {class: 'chips'}); S.chipBox = chips;   // a part can add chips of its own (points with names)
    // A frame across the axis n: u and v, so that the angle a gives cos(a) u + sin(a) v. For n = y: x = cos a, z = -sin a.
    S.basis = n => {
      const u = new S.T.Vector3(1, 0, 0).addScaledVector(n, -n.x);
      if (u.lengthSq() < 1e-6) u.set(0, 0, 1).addScaledVector(n, -n.z);
      u.normalize(); return [u, new S.T.Vector3().crossVectors(n, u)];
    };
    const c2 = Object.assign(Object.create(ctx), {scene: S});
    const nodes = (b.blocks || []).map(k => R.build(k, c2));
    let cv = el('canvas', {class: 'gl'});
    const leads = sv('svg', {class: 'leads', 'aria-hidden': 'true'});
    const msg = el('p', {class: 'rk-note msg', hidden: true});
    const stage = el('div', {class: 'stage', tabindex: 0, role: 'group', 'aria-roledescription': '3D scene',
                             'aria-label': b.label || 'A 3D scene', 'data-look': look, style: `height: ${b.height ?? 380}px`}, cv, leads, chips, S.gripBox, msg);
    const sr = el('ul', {class: 'rk-sr'});
    nodes.forEach(n => (n.classList.contains('rk-chip') ? chips : sr).append(n));

    const N = b.steps?.length || Math.max(1, ...(b.blocks || []).map(k => k.step || 1));
    const say = el('p', {class: 'say', 'aria-live': 'polite'}), count = el('span', {class: 'count'});
    const go = d => { if (b.bind) { const v = clamp(S.step() + d, 1, N); if (v !== S.step()) ctx.put(b, b.bind, v); } };
    const prev = el('button', {type: 'button', onclick: () => go(-1)}, 'Back', el('kbd', {text: 'A'}));
    const next = el('button', {type: 'button', onclick: () => go(1)}, 'Next', el('kbd', {text: 'D'}));
    const bar = b.bind ? el('div', {class: 'bar'}, prev, count, next) : null;

    const user = {az: 0, el: 0, zoom: 0};
    const turn = (daz, del, now, dz = 0) => { user.az += daz; user.el = clamp(user.el + del, -20, 60); user.zoom = clamp(user.zoom + dz, -3, 4); if (S.T) aim(frameOf(S.shot), now ? 0 : 260); };
    stage.addEventListener('keydown', e => {
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const k = e.key.toLowerCase();
      if (k === 'a' || k === 'arrowleft') go(-1);
      else if (k === 'd' || k === 'arrowright') go(1);
      else if (k === 'q') turn(-20, 0); else if (k === 'e') turn(20, 0);
      else if (k === 'w') turn(0, 10); else if (k === 's') turn(0, -10);
      else if (k === 'r') turn(0, 0, false, 1); else if (k === 'f') turn(0, 0, false, -1);
      else if (/^[1-9]$/.test(k) && b.bind && +k <= N) ctx.put(b, b.bind, +k);
      else return;
      e.preventDefault();
    });
    let held = null;
    stage.addEventListener('pointerdown', e => { if (e.target.closest?.('.rk-grip')) return; held = [e.clientX, e.clientY]; stage.setPointerCapture(e.pointerId); });
    stage.addEventListener('wheel', e => { if (!e.ctrlKey && !e.metaKey) return; e.preventDefault(); turn(0, 0, true, -Math.sign(e.deltaY) * .5); }, {passive: false});
    stage.addEventListener('pointermove', e => {
      if (!held) return;
      turn((e.clientX - held[0]) * .4, (e.clientY - held[1]) * .3, true); held = [e.clientX, e.clientY];
    });
    stage.addEventListener('pointerup', () => { held = null; });

    // three.js parts, made when the library is there.
    let rtM, mask, MW = 96, MH = 48;
    let T, gl, world, cam, post, postCam, rtC, rtN, floor, W = 0, H = 0, raf = 0, sig = '', pal;
    const view = {az: 35, el: 22, fov: 32, dist: 10, tx: 0, ty: 0, tz: 0};
    let tw = null, last = 0;
    S.kick = () => kick();
    const texs = {};   // a vendored picture (window.RupakaTEX, data URIs), loaded once; the view draws again when it is there
    S.tex = name => texs[name] ??= (u => { if (!u) return null; const t = new T.TextureLoader().load(u, () => kick()); t.colorSpace = T.SRGBColorSpace; t.anisotropy = 4; t.wrapS = T.RepeatWrapping; return t; })(window.RupakaTEX?.[name]);
    const kick = () => { again(); if (!raf && gl) raf = requestAnimationFrame(frame); };
    // A host can take the view off the page and put it back (a tab switch): the view keeps its renderer then. When it has no renderer
    // (the browser took the WebGL context away), it makes a new one on a new canvas as soon as it is on the page again.
    const again = () => {
      if (gl || !T || !stage.isConnected || stage.dataset.rkGl === 'error') return;
      try { start(T); } catch (e) { console.error('rupaka: scene', e); gl = null; msg.hidden = false; msg.textContent = 'This browser cannot draw the 3D view.'; stage.dataset.rkGl = 'error'; }
    };
    // A real teardown: the host mounted another demo in place of this one, so this view never comes back.
    const over = () => !stage.isConnected && (!ctx.root?.parentNode || ctx.root.parentNode.rupaka !== s);

    function palette() {
      const g = v => R.rgb(stage, v).map(x => x / 255);
      const bg = g('--rk-bg'), fg = g('--rk-fg'), acc = g('--rk-acc'), ok = g('--rk-ok'), no = g('--rk-no');
      // On a dark page the parts take a dimmed paper, so a light part does not glare.
      const night = lum(bg) < lum(fg), paper = night ? mix(fg, bg, .25) : bg, ink = night ? bg : fg;
      const tint = c => mix(c, paper, night ? .35 : .62), deep = c => mix(c, paper, night ? .12 : .3);
      return {night, bg, floor: mix(bg, fg, night ? .07 : .05), shade: mix(ink, [0, 0, 0], .5), line: mix(ink, [0, 0, 0], night ? .7 : .3),
              body: mix(paper, ink, night ? .2 : .12), light: night ? mix(paper, fg, .3) : mix(paper, [1, 1, 1], .35), dark: mix(paper, ink, .4),
              glass: mix(mix(paper, ink, .45), acc, .12), acc: tint(acc), ok: tint(ok), no: tint(no), up: deep(ok), down: deep(no), side: deep(acc),
              glow: mix(acc, [1, 1, 1], .3), mute: mix(paper, ink, .35), ink: mix(paper, ink, .6), lines: {ink: fg, acc, ok, no, dim: mix(fg, bg, .55), mute: mix(fg, bg, .55), glow: mix(acc, [1, 1, 1], .3), light: mix(fg, [1, 1, 1], .5)}};
    }
    const mats = {};
    const col = c => new T.Color().setRGB(c[0], c[1], c[2], T.SRGBColorSpace);
    const LIGHT = {value: null}; S.light = LIGHT;
    const paint = (m, c) => { if (m.uniforms) m.uniforms.color.value = col(c); else m.color.copy(col(c)); };
    S.mat = name => mats[name] ??= sky ? new T.MeshStandardMaterial({color: col(pal[name] || pal.body), roughness: .85, metalness: 0})
                                       : new T.ShaderMaterial({uniforms: {color: {value: col(pal[name] || pal.body)}, light: LIGHT, alpha: {value: 1}}, vertexShader: TOON_V, fragmentShader: TOON_F});
    S.col = col; S.paint = paint; S.palette = () => pal; S.font = () => getComputedStyle(stage).fontFamily || 'serif';
    // The colour of a line, a dot or a halo: full strength, from the tone name. It follows the theme.
    S.lineMat = (tone, opts) => {
      const m = new T.MeshBasicMaterial({color: col(pal.lines[tone] || pal.lines.ink), ...opts});
      S.recolors.push(() => paint(m, pal.lines[tone] || pal.lines.ink));
      return m;
    };
    S.recolors = [];   // functions that a part gives to repaint what it made when the theme changes
    // Lights for lit materials: an ambient, and a sun in the toon look. A lamp body dims the ambient, so its far side goes dark.
    S.lights = () => {
      if (S.lit?.parent === world) return S.lit;
      S.lit = new T.Group(); S.lit.add(S.amb = new T.AmbientLight(0xffffff, sky ? .55 : .9));
      const key = new T.DirectionalLight(0xffffff, sky ? 2.2 : 1.6); key.position.set(-.45, .78, .45); S.lit.add(key);
      S.lamp = () => { S.amb.intensity = sky ? .09 : .5; if (sky) key.intensity = 0; };   // a lamp body is the only light of a sky
      world.add(S.lit);
      return S.lit;
    };
    function recolor() {
      if (!T) return;
      pal = palette();
      for (const [k, m] of Object.entries(mats)) paint(m, pal[k] || pal.body);
      S.recolors.forEach(f => f());
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
        if (!(m.isMesh || m.isLine) || m.userData.flat) return;
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
      const sb = S.cur?.b || {}, az = p.az + (sb.turn || 0) + user.az, elv = clamp(p.el + (sb.tilt || 0) + user.el, -10, 89), a = rad(az), e = rad(elv);
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
      return {az, el: elv, fov: p.fov, dist: fit() * .8 ** user.zoom, tx: c.x, ty: c.y, tz: c.z};
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
    // In globe coords: a point near the ball that the ball hides from the camera.
    const behind = a => { if (b.coords !== 'globe' || a.length() > GLOBE * 1.5) return false;
      const d = cam.position.clone().sub(a), t = -a.dot(d) / d.lengthSq();
      return t > 1e-3 && t < 1 && a.clone().addScaledVector(d, t).length() < GLOBE * .995; };
    function layout() {
      const placed = [], items = [], segs = [];
      for (const q of parts) {
        if (!q.node.classList.contains('rk-chip')) continue;
        const a = q.node.hidden || !S.live(q.b) ? null : q.impl.anchor?.(q);
        let it = null;
        if (a && !behind(a)) {
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
        for (const r of [22, 40, 64, 96]) for (const [cx, cy] of dirs) {
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
      if (!stage.isConnected || !gl) { if (over()) gone(); return; }   // only off the page: the context stays for when the view comes back
      if (!S.anims.size && !tw && running() && now - last < 33) { kick(); return; }   // a steady motion draws at about 30 frames a second
      last = now;
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
      draw(now);
      if (S.anims.size || tw || running()) kick();
      stage.dataset.rkStill = S.anims.size || tw ? '0' : '1';
    }
    // A part with `run` moves with no change of state (a drift, a spin). Not with reduced motion.
    const running = () => !still() && parts.some(q => q.impl.run?.(q) && S.live(q.b));
    function draw(now = performance.now()) {
      if (!W || !H) return;
      place();
      world.updateMatrixWorld(true);
      for (const q of parts) q.impl.frame?.(q, now);
      world.updateMatrixWorld(true);
      if (sky) { gl.setRenderTarget(null); gl.setClearColor(col(pal.bg), 1); gl.clear(); gl.render(world, cam); layout(); for (const q of parts) q.impl.over?.(q); return; }
      shade();
      LIGHT.value.set(-.45, .78, .45).normalize();
      const flat = [], vis = [];
      world.traverseVisible(o => { if (o.userData.flat || o.isSprite || o.isPoints || o.isLine) { flat.push(o); vis.push(true); } });
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
      for (const q of parts) q.impl.over?.(q);
    }
    // Helpers for a part that the learner moves: a screen point of a world point, and the ray under a pointer.
    S.screen = v => { const p = v.clone().project(cam); return {x: (p.x + 1) / 2 * W, y: (1 - p.y) / 2 * H, on: p.z > -1 && p.z < 1}; };
    S.ray = (cx, cy) => {
      const r = stage.getBoundingClientRect(), rc = new T.Raycaster();
      rc.setFromCamera(new T.Vector2((cx - r.left) / r.width * 2 - 1, -((cy - r.top) / r.height * 2 - 1)), cam);
      return rc.ray;
    };
    S.cam = () => cam;
    function gone() { if (gl) { gl.dispose(); gl.forceContextLoss(); gl = null; } }
    function resize() {
      const pr = Math.min(2, devicePixelRatio || 1);
      again();
      W = stage.clientWidth; H = stage.clientHeight;
      if (!W || !H || !gl) return;
      gl.setPixelRatio(pr); gl.setSize(W, H, false);
      rtC.setSize(W * pr, H * pr); rtN.setSize(W * pr, H * pr);
      MH = Math.max(8, Math.round(MW * H / W)); rtM.setSize(MW, MH); mask = sky ? null : new Uint8Array(MW * MH * 4);
      post.material.uniforms.texel.value.set(1 / (W * pr), 1 / (H * pr)); post.material.uniforms.w.value = 1.1 * pr;
      aim(frameOf(S.shot), 0);
    }

    let wired = false;
    function start(lib) {
      T = S.T = lib;
      if (wired) { const c = cv.cloneNode(); cv.replaceWith(c); cv = c; }   // a canvas whose context is lost cannot give a new one
      gl = new T.WebGLRenderer({canvas: cv, antialias: sky, preserveDrawingBuffer: true, powerPreference: 'low-power'});
      LIGHT.value = new T.Vector3(); for (const k of Object.keys(mats)) delete mats[k];   // a new renderer: new materials
      pal = palette();
      world = new T.Scene(); S.world = world; S.recolors.length = 0;
      if (sky) S.lights();
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
      floor.position.set(c.x, S.floor, c.z); floor.scale.set(r * 1.4, r * 1.4, 1); floor.visible = b.ground !== false && !sky;
      world.add(floor);
      const sr = r * .5, fade = S.size * .35;
      shRT = new T.WebGLRenderTarget(512, 512); shRT2 = new T.WebGLRenderTarget(512, 512);
      shCam = new T.OrthographicCamera(-sr, sr, sr, -sr, 0, fade);
      shCam.position.set(c.x, S.floor, c.z); shCam.rotation.x = Math.PI / 2; shCam.updateMatrixWorld();
      dark = new T.ShaderMaterial({uniforms: {floor: {value: S.floor}, fade: {value: fade}}, vertexShader: DARK_V, fragmentShader: DARK_F, side: T.DoubleSide});
      shadow = new T.Mesh(new T.PlaneGeometry(2 * sr, 2 * sr),
                          flatMat(SHADOW_F, {color: {value: col(pal.shade)}, alpha: {value: .62}, map: {value: shRT.texture}}));
      shadow.rotation.x = -Math.PI / 2; shadow.position.set(c.x, S.floor + S.size * 1e-3, c.z);
      shadow.userData.flat = true; shadow.renderOrder = 1; shadow.visible = b.ground !== false && !sky;
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
      cv.addEventListener('webglcontextlost', () => { gl?.dispose(); gl = null; cancelAnimationFrame(raf); raf = 0; stage.dataset.rkGl = 'lost'; });
      stage.dataset.rkGl = 'ready';
      if (wired) { resize(); return; }
      wired = true;
      new ResizeObserver(() => { resize(); kick(); }).observe(stage);
      onTheme(() => { if (over()) { gone(); return false; } if (stage.isConnected && gl) recolor(); return true; });
    }

    // On each change of the state: the step bar, then each part, then the shot.
    function sync() {
      S.ver = (S.ver || 0) + 1;
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
      const now = parts.map(q => S.live(q.b) ? 1 : 0).join('') + name + parts.indexOf(S.cur);
      if (now !== sig) {
        const moved = name !== S.shot;
        if (moved) { user.az = 0; user.el = 0; user.zoom = 0; }
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

/* blocks/sound/sound.js */
/* sound: voices are data. Only the local Play click creates or resumes audio. Technique media exists in the page only while the block may show. */
Rupaka.block('sound', (b, ctx) => {
  const {el} = Rupaka, web = u => typeof u === 'string' && /^https?:\/\//i.test(u);
  const prof = b.play ? ctx.spec.profiles?.[b.play.profile] : null, data = prof?.data || {}, tech = data.techniques?.[b.play?.technique];
  const v = b.voice || tech?.voice, recs = data.media || {};
  // Only a hash-named asset on the host origin, or a YouTube id; never another URL.
  const asset = src => { const m = /^asset:([0-9a-f]{64}\.[a-z0-9]+)$/.exec(src || ''); return m ? ctx.media + m[1] : null; };
  const sample = v?.kind === 'sample' && recs[v.media]?.kind === 'audio' ? recs[v.media] : null, tapeUrl = asset(sample?.src);
  const sounds = v?.kind === 'strike' || !!tapeUrl;
  const play = el('button', {type: 'button'}, 'Play', el('kbd', {text: 'W'}));
  const note = el('span', {class: 'rk-note', text: !sounds ? 'This technique has no sound.' : tapeUrl ? 'Recorded sample.' : 'Synthesised approximation; a real instrument sounds different.'});
  const status = el('span', {class: 'rk-note', 'aria-live': 'polite'});
  let audio, tape, active = [], epoch = 0, shown = false;
  const allowed = () => ctx.live(b.after) && ctx.live(b.lock);
  const stop = () => {
    epoch++;
    tape?.pause();
    active.splice(0).forEach(({source, gain}) => {
      gain.disconnect();
      try { source.stop(); } catch (_) { /* A source can already have ended. */ }
      source.disconnect();
    });
  };
  const envelope = (source, level, duration, at) => {
    const gain = audio.createGain();
    gain.gain.setValueAtTime(Math.max(.00001, level), at);
    gain.gain.exponentialRampToValueAtTime(.00001, at + duration);
    source.connect(gain); gain.connect(audio.destination);
    const part = {source, gain}; active.push(part);
    source.onended = () => { source.disconnect(); gain.disconnect(); active = active.filter(x => x !== part); };
    source.start(at); source.stop(at + duration);
  };
  // Keep a local audio or video inside [start, end]. With loop() true, go back to start at the end.
  const windowed = (m, r, loop = () => false) => {
    const s = +r.start || 0, e = r.end == null ? null : +r.end;
    m.addEventListener('loadedmetadata', () => { m.currentTime = s; });
    m.addEventListener('timeupdate', () => { if (e != null && m.currentTime >= e) { if (loop()) m.currentTime = s; else m.pause(); } });
    m.addEventListener('ended', () => { if (loop()) { m.currentTime = s; m.play().catch(() => {}); } });
    return m;
  };
  const sampled = () => {
    if (!tape) { tape = windowed(el('audio', {src: tapeUrl, preload: 'auto', hidden: true}), sample); root.append(tape); }
    tape.currentTime = +sample.start || 0;
    tape.play().then(() => { status.textContent = ''; }, () => { status.textContent = 'Sound could not start. Try Play again.'; });
  };
  play.addEventListener('click', async () => {
    if (!allowed() || !root.isConnected || !root.getClientRects().length || !sounds) return;
    stop(); const ticket = epoch;
    if (tapeUrl) return sampled();
    try {
      audio ||= new (window.AudioContext || window.webkitAudioContext)();
      if (audio.state === 'suspended') await audio.resume();
      if (ticket !== epoch || !allowed() || !root.isConnected) return;
      const at = audio.currentTime, scale = v.gain / Math.max(1, v.partials.reduce((n, p) => n + p.gain, 0) + (v.noise || 0));
      v.partials.forEach(p => {
        const source = audio.createOscillator();
        source.frequency.setValueAtTime(v.frequency * p.ratio, at);
        source.detune.setValueAtTime(v.bend || 0, at);
        source.detune.linearRampToValueAtTime(0, at + Math.min(.08, v.decay));
        envelope(source, scale * p.gain, v.decay, at);
      });
      if (v.noise) {
        const duration = Math.min(.04, v.decay), buffer = audio.createBuffer(1, Math.ceil(audio.sampleRate * duration), audio.sampleRate);
        const data = buffer.getChannelData(0);
        for (let i = 0; i < data.length; i++) data[i] = Math.random() * 2 - 1;
        const source = audio.createBufferSource(); source.buffer = buffer;
        envelope(source, scale * v.noise, duration, at);
      }
      status.textContent = '';
    } catch (_) { stop(); status.textContent = 'Sound could not start. Try Play again.'; }
  });
  const key = (btn, k) => btn.addEventListener('keydown', e => {
    if (e.key.toLowerCase() !== k || e.repeat || e.metaKey || e.ctrlKey || e.altKey) return;
    e.preventDefault(); btn.click();
  });
  key(play, 'w');
  const ref = b.ref && web(b.ref.url) ? el('a', {href: b.ref.url, title: b.ref.title, target: '_blank', rel: 'noopener noreferrer', text: 'Hear it played'}) : null;
  // A fact or a media entry with no school holds for all schools. A per-school one shows only for the embed school, never for another school.
  const schools = data.schools || {}, school = prof?.school, facts = tech?.facts || [], used = new Set(tech?.sources || []);
  const ours = x => x.school == null || (school != null && x.school === school);
  const lines = [...new Set(facts.map(f => f.key))].map(k => {
    const fs = facts.filter(f => f.key === k), all = fs.find(f => f.school == null);
    const f = all || (school != null ? fs.find(x => x.school === school) : null);
    (f?.sources || []).forEach(s => used.add(s));
    const who = all ? '' : ` (${schools[school]?.label || 'no school chosen'})`;
    return el('li', {text: `${k}${who}: ${f ? String(f.value) : 'unknown'}`});
  });
  const parts = (tech?.parts || []).map(p => data.parts?.[p]?.label).filter(Boolean);
  const chips = [...used].map(s => data.sources?.[s]).filter(s => s && web(s.url))
    .map(s => el('a', {class: 'rk-sound-src', href: s.url, title: s.passage, target: '_blank', rel: 'noopener noreferrer', text: s.title}));
  const about = tech ? el('div', {class: 'rk-sound-about'},
    parts.length ? el('span', {class: 'rk-note', text: `Played on: ${parts.join(', ')}`}) : null,
    lines.length ? el('ul', {class: 'rk-sound-facts'}, ...lines) : null,
    chips.length ? el('div', {class: 'rk-sound-srcs'}, el('span', {class: 'rk-note', text: 'Sources:'}), ...chips) : null) : null;
  const credit = r => el('p', {class: 'rk-note rk-sound-credit'}, `${r.credit?.who}, ${r.credit?.license}. `,
    web(r.credit?.url) ? el('a', {href: r.credit.url, target: '_blank', rel: 'noopener noreferrer', text: 'Source'}) : null);
  const youtube = (r, id) => {
    const box = el('div', {class: 'rk-sound-yt'}), load = el('button', {type: 'button'}, 'Load video', el('kbd', {text: 'E'}));
    const src = `https://www.youtube-nocookie.com/embed/${id}?start=${Math.floor(+r.start)}&end=${Math.ceil(+r.end)}&rel=0`;
    load.addEventListener('click', () => box.replaceChildren(el('iframe', {src, title: r.alt || 'Video clip', allow: 'encrypted-media; picture-in-picture',
      referrerpolicy: 'strict-origin-when-cross-origin', sandbox: 'allow-scripts allow-same-origin allow-presentation'})));
    key(load, 'e');
    box.append(load, el('span', {class: 'rk-note', text: 'The video loads from YouTube only when you click Load video.'}));
    return box;
  };
  const looped = (r, u) => {
    let on = false;
    const lp = el('button', {type: 'button', 'aria-pressed': 'false'}, 'Loop', el('kbd', {text: 'Q'}));
    lp.addEventListener('click', () => { on = !on; lp.setAttribute('aria-pressed', String(on)); });
    key(lp, 'q');
    return el('div', {class: 'rk-sound-clip'}, windowed(el('video', {src: u, controls: true, preload: 'metadata', 'aria-label': r.alt || null}), r, () => on), lp);
  };
  const item = r => {
    const yt = r.kind === 'video' && /^youtube:([A-Za-z0-9_-]{11})$/.exec(r.src || ''), u = asset(r.src);
    if (yt) return youtube(r, yt[1]);
    if (!u) return null;
    if (r.kind === 'image') return el('img', {src: u, alt: r.alt || ''});
    if (r.kind === 'video') return looped(r, u);
    if (r.kind === 'audio') return windowed(el('audio', {src: u, controls: true, preload: 'metadata', 'aria-label': r.alt || null}), r);
    return null;
  };
  const build = () => [sample && tapeUrl ? credit(sample) : null,
    ...(tech?.media || []).filter(x => x && ours(x)).map(x => recs[x.media]).filter(Boolean)
      .map(r => { const n = item(r); return n && el('figure', {class: 'rk-sound-item'}, n, credit(r)); })].filter(Boolean);
  const shelf = el('div', {class: 'rk-sound-media'});
  const root = el('div', {}, el('span', {class: 'rk-lbl', text: b.label || tech?.label || 'Sound'}), el('div', {class: 'rk-sound-acts'}, play, ref), about, shelf, note, status);
  const sync = () => {
    const ok = allowed();
    play.disabled = !sounds || !ok; if (play.disabled) stop();
    if (!ok && tape) { tape.remove(); tape = null; }
    if (ok !== shown) { shown = ok; shelf.replaceChildren(...(ok ? build() : [])); }
  };
  ctx.s.on(sync); sync();
  return root;
});

/* blocks/stack/stack.js */
/* stack: child blocks one above the other, as one group (one `after` can hide them all). */
Rupaka.block('stack', (b, ctx) => Rupaka.el('div', {}, (b.blocks || []).map(ctx.build)));

/* blocks/timeline/timeline.js */
/* timeline: the time t of a scene. Drag the bar, press Play (rAF), or jump to a marker. A/D step (⇧ ten), Q/E the marker before and after, W play and pause.
   A drag or a key sends rk-hold, so layers can show a ghost at the earlier time. */
Rupaka.block('timeline', (b, ctx) => {
  const {el, show} = Rupaka, s = ctx.s, lo = b.min ?? 0, hi = b.max ?? 100, step = b.step ?? 1, speed = b.speed ?? (hi - lo) / 10;
  const marks = [...(b.markers || [])].sort((a, c) => a.t - c.t), name = b.label || 'Time';
  const inp = el('input', {type: 'range', min: lo, max: hi, step, 'aria-label': name}), out = el('output');
  const btn = el('button', {type: 'button', class: 'rk-tl-play', text: 'Play', 'aria-pressed': 'false'});
  const chips = marks.map(m => {
    const c = el('button', {type: 'button', class: 'rk-tl-mark', text: m.label, 'aria-label': `${name} ${m.label}`});
    c.style.setProperty('--p', (m.t - lo) / (hi - lo));
    c.addEventListener('click', () => nudge(() => go(m.t)));
    return c;
  });
  const wrap = el('div', {}, el('span', {class: 'rk-lbl'}, name, out), el('div', {class: 'rk-tl'}, btn, el('div', {class: 'rk-tl-bar'}, inp, el('div', {class: 'rk-tl-marks'}, chips))));
  const hold = on => ctx.root.dispatchEvent(new CustomEvent('rk-hold', {detail: {on}}));
  let timer = 0, playing = false, raf = 0, last = null;
  const nudge = f => { if (!timer) hold(true); clearTimeout(timer); timer = setTimeout(() => { timer = 0; hold(false); }, 800); f(); };
  const put = v => ctx.put(b, b.bind, +Math.min(hi, Math.max(lo, v)).toFixed(6));
  const go = v => { stop(); put(Math.round(v / step) * step); };
  const tick = now => {
    if (!playing) return;
    if (!wrap.isConnected) { playing = false; return; }
    const dt = last == null ? 0 : Math.min(.1, (now - last) / 1000); last = now;
    const v = +s.get(b.bind) + speed * dt;
    if (v >= hi && !b.loop) { put(hi); stop(); return; }
    put(v >= hi ? lo : v);
    raf = requestAnimationFrame(tick);
  };
  const stop = () => { playing = false; cancelAnimationFrame(raf); last = null; btn.textContent = 'Play'; btn.setAttribute('aria-pressed', 'false'); };
  const play = () => {
    if (!ctx.live(b.lock)) return;
    if (+s.get(b.bind) >= hi) put(lo);
    playing = true; btn.textContent = 'Pause'; btn.setAttribute('aria-pressed', 'true'); raf = requestAnimationFrame(tick);
  };
  btn.addEventListener('click', () => playing ? stop() : play());
  inp.addEventListener('pointerdown', () => { stop(); hold(true); });
  ['pointerup', 'pointercancel'].forEach(ev => inp.addEventListener(ev, () => hold(false)));
  inp.addEventListener('input', () => { if (!put(+inp.value)) inp.value = s.get(b.bind); });
  wrap.addEventListener('keydown', e => {
    const k = e.key.toLowerCase(), t = +s.get(b.bind);
    if (k === 'w') { e.preventDefault(); playing ? stop() : play(); }
    else if (k === 'a' || k === 'd') { e.preventDefault(); nudge(() => go(t + (k === 'd' ? 1 : -1) * step * (e.shiftKey ? 10 : 1))); }
    else if (k === 'q' || k === 'e') {
      e.preventDefault();
      const to = k === 'q' ? marks.filter(m => m.t < t - 1e-6).pop()?.t ?? lo : marks.find(m => m.t > t + 1e-6)?.t ?? hi;
      nudge(() => go(to));
    }
  });
  s.on(() => {
    const t = +s.get(b.bind), cur = marks.filter(m => m.t <= t + 1e-6).length - 1;
    inp.value = t; out.textContent = show(t, 1); inp.disabled = !ctx.live(b.lock);
    inp.setAttribute('aria-valuetext', `${name} ${show(t, 1)}${cur >= 0 ? `, ${marks[cur].label}` : ''}`);
    chips.forEach((c, i) => { c.classList.toggle('on', i === cur); i === cur ? c.setAttribute('aria-current', 'true') : c.removeAttribute('aria-current'); });
  });
  return wrap;
});

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
