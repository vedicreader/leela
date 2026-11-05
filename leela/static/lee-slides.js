/* The shared slide renderer: one 1280x720 canvas that the presenter screen in the IDE and the audience window draw the same way.
   It reads no global of the IDE page: each input is an argument. The audience page loads it alone as `lee-slides.js`, and it posts nothing. */
const SLIDES_TAGS = new Set('p pre code span div b i em strong br hr h1 h2 h3 h4 h5 h6 table thead tbody tr th td ul ol li img figure figcaption blockquote sup sub del s kbd a'.split(' '));
const SLIDES_GONE = new Set('script style svg math iframe object embed template noscript textarea title select button'.split(' '));
const SLIDES_DATA = /^data:image\/(png|jpeg|gif|webp);base64,[A-Za-z0-9+/=]*$/;
//: Leela's own class names: a notebook that used them could cover the slide with the blank screen or the IDE's chrome.
const SLIDES_OURS = /^(lee-|stage-|rk)/;
//: The body is 28px; the fit shrinks it to 20px and stops.
const SLIDES_FLOOR = 20/28;
//: rupaka's sizes are fixed px for a reading page; on a slide a demo takes the slide's text size and Leela's colours, in both windows.
const SLIDES_RK = `:host{display:block}.rk{font-size:inherit;line-height:1.45;max-width:100%;font-family:var(--lee-sans)}.rk-title{font-size:1.1em}
.rk button,.rk-gate textarea,.rk-gate .verdict,.rk-note{font:inherit}.rk button{padding:.3em .6em;line-height:1.2}.rk-gate .verdict .stale{font-size:inherit}
.rk-lbl,.rk-slider output,.rk kbd{font-size:.85em;letter-spacing:normal;text-transform:none}.rk kbd{font-size:.6em;color:var(--lee-fg2)}.rk-lbl{color:var(--lee-fg)}.rk-note,.rk-gate .note{color:var(--lee-fg2)}
.rk-slider input{font-size:inherit;max-width:24em;accent-color:var(--lee-accent)}.rk-gate{border-color:var(--lee-border)}.rk-gate .verdict .ok{color:var(--lee-green)}`;
//: The room copy has no keys to press, no box to type in and no gate button: an explanation shows as text, an empty one not at all.
const SLIDES_ROOM = `.rk kbd,.rk-gate .acts{display:none}.rk-gate textarea{border:0;padding:0;resize:none;background:none;color:var(--lee-fg);overflow:hidden}.rk-gate textarea.lee-empty{display:none}`;

//: Server HTML as a fragment with only the tags, classes, links and image sources a slide may have; `key` names the images of this presentation.
function slidesSafe(html, key = '') {
  const doc = new DOMParser().parseFromString(`<!doctype html><body>${html || ''}</body>`, 'text/html'), out = document.createDocumentFragment();
  const own = key && /^[0-9a-f]+$/.test(key) ? new RegExp(`^/present/img/[0-9a-f]{64}\\?k=${key}$`) : null;
  const walk = (from, to) => {
    for (const n of from.childNodes) {
      if (n.nodeType === 3) { to.append(n.textContent); continue; }
      if (n.nodeType !== 1) continue;
      const t = n.localName;
      if (SLIDES_GONE.has(t)) continue;
      if (!SLIDES_TAGS.has(t)) { walk(n, to); continue; }
      const el = document.createElement(t), cls = (n.getAttribute('class') || '').split(/\s+/).filter(c => c && !SLIDES_OURS.test(c));
      if (cls.length) el.className = cls.join(' ');
      if (t === 'img') {
        const src = (n.getAttribute('src') || '').trim();
        if (!SLIDES_DATA.test(src) && !own?.test(src)) continue;
        el.setAttribute('src', src);
        for (const a of ['width', 'height']) if (/^\d{1,5}$/.test(n.getAttribute(a) || '')) el.setAttribute(a, n.getAttribute(a));
        if (n.getAttribute('alt')) el.alt = n.getAttribute('alt');
      }
      if (t === 'a' && /^(https?:|mailto:)/i.test((n.getAttribute('href') || '').trim()))
        for (const [a, v] of [['href', n.getAttribute('href').trim()], ['target', '_blank'], ['rel', 'noopener noreferrer']]) el.setAttribute(a, v);
      walk(n, el); to.append(el);
    }
  };
  walk(doc.body, out);
  return out;
}

//: Shrink the text of canvas `el` in steps until it fits, down to the floor; `{fits}`.
function slidesFit(el) {
  let f = 1; el.style.setProperty('--slide-fit', 1);
  const over = () => el.scrollHeight > el.clientHeight + 1;
  while (over() && f > SLIDES_FLOOR) el.style.setProperty('--slide-fit', f = Math.max(SLIDES_FLOOR, f - .04));
  return {fits: !over()};
}

/* Draw slide `i` of `deck` at `step` into canvas `el`: a block shows when its fragment group is below `step`; a later one keeps its place, hidden.
   `mount(spec, id)` turns each demo into a host; `math(el)` fills the formulas; `outs` maps a code cell to the room output of its last run, in place of
   the deck's. Only the body is redrawn, so the laser dot and the blank screen stay. */
function slidesDraw(el, deck, i, step, {key = '', size = 10, mount = null, math = null, outs = null} = {}) {
  const s = deck?.slides?.[i], body = document.createElement('div');
  body.className = 'lee-slide-body';
  el.style.setProperty('--slide-size', size/10);
  for (const b of s?.blocks || []) {
    const box = body.appendChild(document.createElement('div'));
    box.className = `lee-block ${b.kind}${b.frag >= step ? ' lee-frag-hidden' : ''}`; box.dataset.cell = b.cell;
    box.append(slidesSafe(b.html, key));
    if (b.kind === 'code') box.appendChild(Object.assign(document.createElement('div'), {className: 'lee-out'})).append(slidesSafe(outs && Object.hasOwn(outs, b.cell) ? outs[b.cell] : b.out, key));
    if (!mount) continue;
    [...box.querySelectorAll('pre > code.language-rupaka')].forEach((code, n) => {
      let spec; try { spec = JSON.parse(code.textContent); } catch { return; }
      const host = mount(spec, `${b.cell}:${n}`); if (host) code.parentElement.replaceWith(host);
    });
  }
  el.querySelector(':scope > .lee-slide-body')?.remove();
  el.prepend(body);
  math?.(body);
  return slidesFit(el);
}

//: Output `html` in the box of code cell `cell` on canvas `el`, then the fit again; `{fits}`, or null when that cell is not on the slide drawn.
function slidesOut(el, cell, html, key = '') {
  const box = [...el.querySelectorAll(':scope > .lee-slide-body > .lee-block.code')].find(b => b.dataset.cell === cell)?.querySelector(':scope > .lee-out');
  if (!box) return null;
  box.replaceChildren(slidesSafe(html, key));
  return slidesFit(el);
}
//: Whether output `m` of a run is newer than `old`: a later run `gen`, or a later `seq` of the same run.
const slidesNewer = (m, old) => !old || m.gen > old.gen || m.gen === old.gen && m.seq > old.seq;
//: The room output of each code cell in `outs` (`{cell: {html}}`), as `slidesDraw` takes it.
const slidesHtml = outs => Object.fromEntries(Object.entries(outs).map(([c, o]) => [c, o.html]));

//: The slide sizes on a demo's shadow root `root`, after the sheets it has; `room` adds the rules of the room copy.
function slidesRk(root, room = false) {
  const css = SLIDES_RK + (room ? SLIDES_ROOM : '');
  if (!('adoptedStyleSheets' in root)) return root.append(Object.assign(document.createElement('style'), {textContent: css}));
  const s = (slidesRk.sheets ||= {})[css] ||= new CSSStyleSheet();
  if (!s.cssRules.length) s.replaceSync(css);
  if (!root.adoptedStyleSheets.includes(s)) root.adoptedStyleSheets = [...root.adoptedStyleSheets, s];
}
//: Mark each empty explanation box of a room demo, so the room does not see an empty field.
const slidesWhy = inner => inner.querySelectorAll('.rk-gate textarea').forEach(t => t.classList.toggle('lee-empty', !t.value.trim()));

//: A room demo in a shadow root with rupaka's CSS and the slide's sizes, mounted as `rupakaDraw` mounts it in the IDE; `{host, inner}`.
function slidesMount(spec) {
  const host = Object.assign(document.createElement('div'), {className: 'lee-rupaka'}), inner = document.createElement('div'), root = host.attachShadow({mode: 'open'});
  const css = document.querySelector('meta[name="lee-rupaka-css"]')?.content;
  if (css) root.append(Object.assign(document.createElement('link'), {rel: 'stylesheet', href: css}));
  root.append(inner); slidesRk(root, true);
  try { window.Rupaka.mount(inner, spec, {askable: false}); slidesWhy(inner); } catch (e) { inner.textContent = `This demo could not be drawn: ${e.message || e}`; }
  return {host, inner};
}

//: Fit the 1280x720 canvas inside `root` at the largest scale that shows all of it.
function slidesScale(root) {
  const fit = () => root.style.setProperty('--slide-scale', Math.min(root.clientWidth/1280, root.clientHeight/720) || 1);
  fit(); new ResizeObserver(fit).observe(root);
}

//: Leela's theme `family:mode:density` on `html`, following the system for `system`, and the editor font as `--lee-mono`.
function slidesTheme(theme, mono = '') {
  const [family = 'cursor', mode = 'light', density = 'tight'] = String(theme || '').split(':'), root = document.documentElement;
  const q = slidesTheme.q ||= matchMedia('(prefers-color-scheme: dark)');
  const paint = () => { const m = mode === 'system' ? (q.matches ? 'dark' : 'light') : mode; Object.assign(root.dataset, {theme: family, mode: m, density}); root.style.colorScheme = m; };
  q.onchange = paint; paint();
  if (mono) root.style.setProperty('--lee-mono', `${mono}, ui-monospace, monospace`);
}

//: KaTeX for the formulas of `el`, loaded from the page's own copy the first time a slide has one.
function slidesMath(el) {
  const todo = [...el.querySelectorAll('span.math, div.math')];
  if (!todo.length) return;
  const meta = n => document.querySelector(`meta[name="${n}"]`)?.content;
  slidesMath.p ||= new Promise(ok => {
    if (window.katex) return ok(window.katex);
    document.head.append(Object.assign(document.createElement('link'), {rel: 'stylesheet', href: meta('lee-katex-css')}));
    document.head.append(Object.assign(document.createElement('script'), {src: meta('lee-katex-src'), onload: () => ok(window.katex), onerror: () => ok(null)}));
  });
  slidesMath.p.then(k => k && todo.forEach(m => { try { k.render(m.textContent, m, {displayMode: m.classList.contains('display'), throwOnError: false, trust: false}); } catch {} }));
}

//: The audience window waits this long before it asks again after a failure, doubling from the first to the most.
const SLIDES_WAIT = [1000, 15000];
/* The audience window: the room copy and the room stream, with abhyasa's `stage.js` for the laser dot, the blank screen and the mirrored demos.
   The audience key stays in the address, because a reload asks the server for the page with it. It uses GET only. One room stream at a time,
   one retry at a time with a growing wait, and nothing after the end. */
function slidesAudience() {
  const k = new URLSearchParams(location.search).get('k') || '';
  // a window the IDE opened gets a copy of the IDE tab's storage, the presenter record among it
  for (const n of Object.keys(sessionStorage)) if (n.startsWith('lee-present:')) sessionStorage.removeItem(n);
  sessionStorage.setItem('lee-present-k', k);
  const root = document.body.appendChild(Object.assign(document.createElement('div'), {className: 'lee-stage'}));
  const canvas = root.appendChild(Object.assign(document.createElement('div'), {className: 'lee-slide'}));
  const q = `?k=${encodeURIComponent(k)}`, demos = new Map(), fns = {};
  let deck = null, at = {slide: 's1', step: 0, blank: false, size: 10}, held = {demo: {}, answers: {}, outs: {}}, es = null, stage = null, done = false;
  let boot = '', wait = 0, timer = 0;
  slidesScale(root);
  const name = () => String(deck?.title || '').replace(/\.ipynb$/i, '');
  const card = (text, title = name()) => {
    done = true; es?.close(); es = null; clearTimeout(timer); stage?.stop();
    const c = Object.assign(document.createElement('div'), {className: 'lee-end'});
    c.append(Object.assign(document.createElement('h1'), {textContent: text}));
    if (title) c.append(Object.assign(document.createElement('p'), {textContent: title}));
    root.replaceChildren(c);
  };
  const ended = (b = '') => card('The presentation has ended.', b && boot && b !== boot ? 'Leela restarted. The presenter can start again.' : name());
  // only the server's 403 means a bad link and its 410 the end; any other failure asks again later
  const ask = then => fetch('/present/deck' + q).then(r => {
    if (done) return;
    if (r.status === 410) return ended(r.headers.get('X-Leela-Boot') || '');
    if (r.status === 403) return card('This presentation link is not valid.');
    return r.ok ? then(r) : again(then);
  }).catch(() => again(then));
  const again = then => {
    if (done || timer) return;
    timer = setTimeout(() => { timer = 0; ask(then); }, wait);
    wait = Math.min(SLIDES_WAIT[1], wait ? wait*2 : SLIDES_WAIT[0]);
  };
  const ch = {on(t, f) { (fns[t] ||= []).push(f); return () => { fns[t] = fns[t].filter(x => x !== f); }; }, send() {}, close() {}};
  const emit = m => { m = {v: 1, ...m}; if (abhyasaStage.valid(m)) for (const f of fns[m.t] || []) f(m); };
  const show = (d, slug) => {
    if (!d.mirror) return;
    const s = held.demo[slug], a = held.answers[slug];
    try { d.mirror.apply(s?.state || {}, s?.gates || {}, s?.pick || {}); if (a) d.mirror.reveal(a.gates); else d.mirror.forget(); } catch {}
    slidesWhy(d.inner);
  };
  const mount = (spec, id) => {
    let d = demos.get(id);
    if (!d) {
      d = {...slidesMount(spec), slug: spec.id};
      try { d.mirror = abhyasaStage.mirror(d.inner); } catch {}
      demos.set(id, d);
    }
    return d.host;
  };
  const draw = () => {
    if (done || !deck) return;
    const i = Math.max(0, Math.min(deck.slides.length - 1, +at.slide.slice(1) - 1));
    slidesDraw(canvas, deck, i, at.step, {key: k, size: at.size, mount, math: slidesMath, outs: slidesHtml(held.outs)});
    for (const d of demos.values()) if (canvas.contains(d.host)) show(d, d.slug);
  };
  // a demo state drops the answers of each gate it does not list as done, as the server does, so a reopened gate never shows an old answer
  const keep = m => {
    const a = m.t === 'demo' && held.answers[m.slug], g = a && Object.fromEntries(Object.entries(a.gates).filter(([id]) => m.gates[id] === 'done'));
    if (a) { if (Object.keys(g).length) held.answers[m.slug] = {...a, gates: g}; else delete held.answers[m.slug]; }
    held[m.t][m.slug] = m; for (const d of demos.values()) if (d.slug === m.slug && canvas.contains(d.host)) show(d, d.slug);
  };
  const on = {
    state: d => { wait = 0; at = d.at; held = {demo: Object.fromEntries(d.demo.map(x => [x.slug, {t: 'demo', ...x}])), answers: Object.fromEntries(d.answers.map(x => [x.slug, {t: 'answers', ...x}])),
                                  outs: Object.fromEntries((d.outs || []).map(x => [x.cell, x]))};
                  slidesTheme(d.look?.theme, deck.look?.mono); emit({t: 'point', off: true}); emit({t: 'blank', on: !!at.blank}); draw(); },
    at: d => { if (d.slide !== at.slide) held.answers = {}; at = d; emit({t: 'go', slide: d.slide, beat: Math.min(50, d.step + 1)}); emit({t: 'blank', on: !!d.blank}); },
    point: d => emit({t: 'point', ...d}),
    demo: d => emit({t: 'demo', ...d}),
    answers: d => emit({t: 'answers', ...d}),
    look: d => slidesTheme(d.theme, deck.look?.mono),
    out: d => { if (!slidesNewer(d, held.outs[d.cell])) return; held.outs[d.cell] = d; if (!done && deck) slidesOut(canvas, d.cell, d.html, k); },
    end: () => emit({t: 'end'}),
  };
  // the browser connects an open stream again by itself; a closed one is asked about first, so a 403 or 410 shows its card
  const listen = () => {
    if (done) return;
    es?.close();
    const s = es = new EventSource('/present/room' + q);
    for (const [t, f] of Object.entries(on)) s.addEventListener(t, e => { if (s === es) try { f(JSON.parse(e.data)); } catch {} });
    s.onerror = () => { if (s === es && s.readyState === EventSource.CLOSED) again(listen); };
  };
  addEventListener('keydown', e => { if (e.code === 'KeyF' && !e.metaKey && !e.ctrlKey && !e.altKey) document.documentElement.requestFullscreen?.().catch(() => {}); });
  addEventListener('dblclick', () => document.documentElement.requestFullscreen?.().catch(() => {}));
  const load = async r => {
    boot = r.headers.get('X-Leela-Boot') || '';
    try { deck = await r.json(); } catch { return again(load); }
    document.title = name() || 'Presentation';
    slidesTheme(deck.look?.theme, deck.look?.mono);
    stage = abhyasaStage.audience(canvas, {ch, title: name(), draw: m => m.t === 'go' ? draw() : m.t === 'end' ? ended() : (m.t === 'demo' || m.t === 'answers') && keep(m)});
    listen();
  };
  ask(load);
}

if (typeof document !== 'undefined' && document.body?.dataset.page === 'audience') slidesAudience();
