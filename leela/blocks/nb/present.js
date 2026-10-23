/* The open notebook as reveal.js slides, laid over Leela's window. Cells group the way RISE and
   nbconvert group them, from `metadata.slideshow.slide_type`. Speaker notes are never on a slide:
   they go to a page in the machine's own browser, which `/present/events` keeps on the current one. */
const REVEAL_THEMES = new Set(['beige', 'black', 'blood', 'dracula', 'league', 'moon', 'night', 'serif',
                               'simple', 'sky', 'solarized', 'white']);
//: RISE took `linear` from reveal.js 3, which renamed it `slide`.
const RISE_TRANSITIONS = {none: 'none', fade: 'fade', slide: 'slide', convex: 'convex', concave: 'concave',
                          zoom: 'zoom', linear: 'slide'};
const SLIDE_NUMBERS = new Set(['h.v', 'h/v', 'c', 'c/t']);
const NAV_CMDS = new Set(['next', 'prev', 'left', 'right', 'up', 'down']);
const PRESENT_NOT_NOTEBOOK = 'only a notebook can be presented as slides';
const PRESENT_NOTHING = 'this notebook has nothing to present: every cell is empty or skipped';
//: Below this a slide scrolls rather than shrink past reading.
const PRESENT_MIN_ZOOM = .35;

//: The text scale after one press of A- (`d = -1`) or A+ (`d = 1`): tenths, from half to two and a half.
const presentStep = (s, d) => Math.min(2.5, Math.max(.5, Math.round((s + d/10)*10)/10));
const presentKey = (what = 'text') => `lee-present-${what}:${lee.path || lee.tabKey}`;
//: `left`: text left and headings centred, the default; `center`: everything centred, as reveal's themes do.
function presentAlign() {
  try { return localStorage.getItem(presentKey('align')) === 'center' ? 'center' : 'left'; } catch { return 'left'; }
}
function presentStored() {
  try { const s = +localStorage.getItem(presentKey()); return s >= .5 && s <= 2.5 ? s : 1; } catch { return 1; }
}

//: Zoom each slide reveal has laid out (far ones are `display: none`) until its content fits the slide's height.
function presentFit(p) {
  const h = p.reveal.getComputedSlideSize().height, scale = p.reveal.getScale() || 1;
  for (const s of $$('.slides section:not(.stack)', p.root)) {
    if (getComputedStyle(s).display === 'none') continue;
    s.style.zoom = s.style.maxHeight = s.style.overflowY = '';
    const tall = () => s.getBoundingClientRect().height/scale;
    let need = tall(), z = 1;
    for (let k = 0; k < 4 && need > h + 1 && z > PRESENT_MIN_ZOOM; k++) {
      z = Math.max(PRESENT_MIN_ZOOM, z*h/need); s.style.zoom = z; need = tall();
    }
    if (need > h + 1) { s.style.maxHeight = `${h/z}px`; s.style.overflowY = 'auto'; }
  }
}

/* `[[slide, ...subslides], ...]`, each slide `{items: [{i, frag}], notes: [i]}` with `i` an index
   into `cells`. `src` reads a cell's text, so unsaved edits are what gets presented. */
function presentSlides(cells, src = c => String(c.source || '')) {
  const kind = c => c.extra?.slideshow?.slide_type;
  // only a slide boundary makes unmarked cells continue a slide; a skip or notes mark alone does not
  const typed = cells.some(c => kind(c) === 'slide' || kind(c) === 'subslide');
  const deck = []; let stack = null, slide = null;
  const open = sub => { slide = {items: [], notes: [], frag: -1}; if (!sub || !stack) deck.push(stack = []); stack.push(slide); };
  cells.forEach((c, i) => {
    if (c.approval) return;
    const t = kind(c) || (typed ? '-' : 'slide');
    if (t === 'skip') return;
    const empty = !src(c).trim() && !(c.outputs || []).length && !c.reply;
    if (t === 'slide' || t === 'subslide') open(t === 'subslide');
    else if (!slide) open(false);
    if (empty) return;
    if (t === 'notes') return void slide.notes.push(i);
    if (t === 'fragment') slide.frag++;
    slide.items.push({i, frag: slide.frag});
  });
  return deck.map(s => s.filter(x => x.items.length || x.notes.length)).filter(s => s.length);
}

//: Where cell `i` is shown, or the nearest visible cell above it: `{h, v, f}` for `Reveal.slide`.
function presentAt(deck, i) {
  for (let j = i; j >= 0; j--)
    for (const [h, stack] of deck.entries()) for (const [v, s] of stack.entries()) {
      const it = s.items.find(x => x.i === j); if (it) return {h, v, f: it.frag};
    }
  return {h: 0, v: 0, f: -1};
}

//: RISE settings as reveal.js options, by name. Nothing else reaches reveal.js.
function riseConfig(rise) {
  const r = rise && typeof rise === 'object' && !Array.isArray(rise) ? rise : {};
  const bool = v => typeof v === 'boolean' ? v : undefined;
  const size = v => typeof v === 'number' && v > 0 ? v : typeof v !== 'string' ? undefined
    : /^\d+(\.\d+)?%$/.test(v.trim()) ? v.trim() : /^\d+$/.test(v.trim()) ? +v : undefined;
  const html = v => typeof v === 'string' && v.trim() ? v : '';
  const reveal = {transition: RISE_TRANSITIONS[r.transition], width: size(r.width), height: size(r.height),
    controls: bool(r.controls), progress: bool(r.progress), center: bool(r.center),
    slideNumber: typeof r.slideNumber === 'boolean' || SLIDE_NUMBERS.has(r.slideNumber) ? r.slideNumber : undefined};
  for (const k of Object.keys(reveal)) if (reveal[k] === undefined) delete reveal[k];
  return {reveal, theme: REVEAL_THEMES.has(r.theme) ? r.theme : 'simple',
          header: html(r.header), footer: html(r.footer), overlay: html(r.overlay),
          start: r.start_slideshow_at === 'beginning' ? 'beginning' : 'selected'};
}

let revealLoading = null;
function loadReveal() {
  if (window.Reveal) return Promise.resolve(window.Reveal);
  return revealLoading ||= new Promise((ok, no) => {
    const s = document.createElement('script'); s.src = '/leestatic/reveal/reveal.js';
    s.onload = () => window.Reveal ? ok(window.Reveal) : no(new Error('reveal.js loaded but defined no Reveal'));
    s.onerror = () => { revealLoading = null; s.remove(); no(new Error('reveal.js could not be loaded')); };
    document.head.appendChild(s);
  });
}
const presentCss = href => new Promise(ok => {
  const l = document.createElement('link'); l.rel = 'stylesheet'; l.href = href; l.dataset.leePresent = '';
  l.onload = l.onerror = () => ok(l); document.head.appendChild(l);
});

function presentMarkdown(host, text, cell) {
  host.dataset.mdBase = nbBase();
  renderMarkdown(host, text, true, cell ? mdAttached(cell) : null);
}
function presentOutputs(box, outputs) {
  $$('[data-markdown]', box).forEach(el => { for (const v of el._leeCodeViews || []) try { LeeCM.destroy(v); } catch {} });
  box.replaceChildren(...(outputs || []).map(outputEl));
}
const presentError = m => { try { return JSON.parse(m).error || m; } catch { return m; } };
const presentFence = (src, lang) => {
  const ticks = '`'.repeat(Math.max(3, ...(src.match(/`+/g) || []).map(s => s.length + 1)));
  return `${ticks}${lang}\n${src}\n${ticks}`;
};

//: One cell on a slide. The host is on the page already: a render that lands on a detached one is dropped.
function presentCell(host, c) {
  host.className = `lee-present-cell ${c.cell_type}`; host.dataset.cellId = c.id;
  if (c.cell_type === 'markdown') return presentMarkdown(host, mdSource(c), c);
  if (c.cell_type === 'raw') return void (host.appendChild(document.createElement('pre')).textContent = mdSource(c));
  if (c.cell_type === 'prompt') {
    host.innerHTML = '<div class="lee-present-question"></div><div class="lee-reply"></div><div class="lee-present-out"></div>';
    presentMarkdown(host.firstChild, mdSource(c));
    if (c.reply) presentMarkdown(host.children[1], (c.calls || []).length ? stripWorkLog(c.reply) : c.reply);
    return presentOutputs(host.lastChild, c.outputs);
  }
  host.innerHTML = '<div class="lee-present-src"></div><div class="lee-present-run">' +
    '<button type="button" title="run this cell" aria-label="run this cell">▶</button><span></span></div>' +
    '<div class="lee-present-out"></div>';
  presentMarkdown(host.firstChild, presentFence(mdSource(c), nbLang()));
  $('button', host).onclick = () => presentRun(host, c.id);
  presentOutputs(host.lastChild, c.outputs);
}
async function presentRun(host, id) {
  const button = $('.lee-present-run button', host), say = $('.lee-present-run span', host);
  const i = lee.cells.findIndex(c => c.id === id);
  if (i < 0) return void (say.textContent = 'this cell is no longer in the notebook');
  button.disabled = true; say.textContent = 'running…'; host.classList.remove('failed'); host.classList.add('running');
  const r = await runCell(i, false);
  if (!host.isConnected) return;
  button.disabled = false; host.classList.remove('running'); host.classList.toggle('failed', !r.ok);
  say.textContent = r.ok ? '' : presentError(r.error);
  const c = lee.cells.find(x => x.id === id); if (c) presentOutputs($('.lee-present-out', host), c.outputs);
  lee.present?.fit?.();
}

function presentTitle(cells, slide) {
  for (const {i} of slide.items) {
    const h = cells[i].cell_type === 'markdown' && mdSource(cells[i]).match(/^ {0,3}#{1,6}\s+(.+?)[\s#]*$/m);
    if (h) return h[1];
  }
  return slide.items.length ? mdSource(cells[slide.items[0].i]).trim().split('\n')[0].slice(0, 80) : '';
}
function presentSay(text) {
  const m = lee.present && $('.lee-present-msg', lee.present.root); if (!m) return;
  m.textContent = text; m.hidden = !text;
  clearTimeout(m._leeTimer); if (text) m._leeTimer = setTimeout(() => { m.hidden = true; }, 6000);
}
const presentSync = data => post('/present/state', data).catch(e => presentSay(`notes page not updated: ${e.message || e}`));
const presentNotesPage = () => openExternal(location.origin + '/present/notes');

async function presentNotebook(start = '') {
  if (lee.kind !== 'notebook') return status(PRESENT_NOT_NOTEBOOK, 'err');
  const cells = lee.cells, deck = presentSlides(cells, mdSource);
  if (!deck.length) return status(PRESENT_NOTHING, 'err');
  closePresentation();
  const cfg = riseConfig(lee.rise), root = document.createElement('div');
  root.className = 'lee-present'; root.tabIndex = -1; root.setAttribute('role', 'dialog'); root.setAttribute('aria-label', 'slides');
  root.innerHTML = '<div class="reveal"><div class="slides"></div></div>' +
    '<div class="lee-present-header"></div><div class="lee-present-footer"></div><div class="lee-present-overlay"></div>' +
    '<div class="lee-present-bar"><button type="button" data-smaller title="smaller text" aria-label="smaller text">A−</button>' +
    '<button type="button" data-bigger title="larger text" aria-label="larger text">A+</button>' +
    '<button type="button" data-align title="centre all text" aria-label="centre all text">↔</button>' +
    '<button type="button" data-notes title="open the speaker notes in your browser">notes</button>' +
    '<button type="button" data-full title="fill the screen">⛶</button>' +
    '<button type="button" data-close title="stop presenting (escape)" aria-label="stop presenting">×</button></div>' +
    '<div class="lee-present-msg" role="status" hidden></div>';
  const p = lee.present = {root, reveal: null, fsExit: 0, text: presentStored(), base: 0, align: presentAlign()};
  const aligned = () => {
    root.dataset.align = p.align;
    const b = $('[data-align]', root), left = p.align === 'left';
    b.textContent = left ? '↔' : '⇤';
    b.title = b.ariaLabel = left ? 'centre all text' : 'text left, headings centred';
  };
  aligned();
  closeInlinePopover(); document.body.appendChild(root); root.focus({preventScroll: true});
  const slidesEl = $('.slides', root), flat = [];
  deck.forEach((stack, h) => {
    const outer = stack.length > 1 ? slidesEl.appendChild(document.createElement('section')) : slidesEl;
    stack.forEach((slide, v) => {
      const sec = outer.appendChild(document.createElement('section'));
      for (const {i, frag} of slide.items) {
        const host = sec.appendChild(document.createElement('div'));
        presentCell(host, cells[i]);
        if (frag >= 0) { host.classList.add('fragment'); host.dataset.fragmentIndex = frag; }
      }
      flat.push({h, v, title: presentTitle(cells, slide), notes: slide.notes.map(i => mdSource(cells[i])).join('\n\n')});
    });
  });
  for (const k of ['header', 'footer', 'overlay']) if (cfg[k]) renderMarkdown($(`.lee-present-${k}`, root), cfg[k], true);
  let fitting = false;
  const layout = p.fit = () => requestAnimationFrame(() => {
    if (!p.reveal || fitting) return;
    fitting = true;
    try { presentFit(p); p.reveal.layout(); } finally { fitting = false; }
  });
  const sized = () => { if (p.base) root.style.setProperty('--r-main-font-size', `${p.base*p.text}px`); };
  const resize = d => {
    p.text = presentStep(p.text, d);
    try { localStorage.setItem(presentKey(), String(p.text)); } catch {}
    sized(); layout(); presentSay(`text ${Math.round(p.text*100)}%`);
  };
  $('[data-smaller]', root).onclick = () => resize(-1);
  $('[data-bigger]', root).onclick = () => resize(1);
  $('[data-align]', root).onclick = () => {
    p.align = p.align === 'left' ? 'center' : 'left';
    try { localStorage.setItem(presentKey('align'), p.align); } catch {}
    aligned(); layout(); presentSay(p.align === 'left' ? 'text left, headings centred' : 'all text centred');
  };
  // a bar button left focused would take reveal's Space and arrows
  $('.lee-present-bar', root).addEventListener('click', () => root.focus({preventScroll: true}));
  root.addEventListener('lee-markdown-rendered', e => { $$('.lee-reply-actions', e.target).forEach(x => x.remove()); layout(); });
  root.addEventListener('load', layout, true);
  root.addEventListener('click', e => { if (e.target.closest('.lee-output-fold')) layout(); });
  $('[data-close]', root).onclick = closePresentation;
  $('[data-notes]', root).onclick = presentNotesPage;
  $('[data-full]', root).onclick = () => {
    if (document.fullscreenElement) return document.exitFullscreen().catch(() => {});
    if (!root.requestFullscreen) return presentSay('use View › Enter Full Screen to fill the screen');
    root.requestFullscreen().catch(() => presentSay('use View › Enter Full Screen to fill the screen'));
  };
  p.onFs = () => { if (!document.fullscreenElement) p.fsExit = performance.now(); layout(); };
  // Chromium spends the first Escape leaving fullscreen, and may deliver it as well.
  p.onKey = e => {
    if (e.key !== 'Escape' || $('.lee-modal') || document.fullscreenElement || performance.now() - p.fsExit < 400) return;
    e.preventDefault(); e.stopPropagation(); closePresentation();
  };
  p.onOutput = e => $$(`.lee-present-cell[data-cell-id="${CSS.escape(e.detail.id)}"] .lee-present-out`, root)
    .forEach(box => { presentOutputs(box, e.detail.outputs); layout(); });
  addEventListener('keydown', p.onKey, true); addEventListener('lee-cell-output', p.onOutput);
  document.addEventListener('fullscreenchange', p.onFs);
  try {
    const [R] = await Promise.all([loadReveal(), presentCss('/leestatic/reveal/reveal.css'),
                                   presentCss(`/leestatic/reveal/theme/${cfg.theme}.css`)]);
    if (lee.present !== p) return;
    p.base = parseFloat(getComputedStyle(root).getPropertyValue('--r-main-font-size')) || 40; sized();
    p.reveal = new R($('.reveal', root), {embedded: true, hash: false, history: false, respondToHashChanges: false,
      fragmentInURL: false, help: false, scrollActivationWidth: null,
      keyboardCondition: () => lee.present === p && !$('.lee-modal'), ...cfg.reveal});
    await p.reveal.initialize();
    if (lee.present !== p) return;
  } catch (e) {
    if (lee.present === p) closePresentation();
    return status(`slides could not start: ${e.message || e}`, 'err');
  }
  const at = (start || cfg.start) === 'selected' ? presentAt(deck, lee.sel) : {h: 0, v: 0, f: -1};
  p.reveal.slide(at.h, at.v, at.f);
  p.reveal.on('slidechanged', layout); p.reveal.on('resize', layout); layout();
  const index = () => { const s = p.reveal.getIndices(); return Math.max(0, flat.findIndex(x => x.h === s.h && x.v === (s.v || 0))); };
  p.reveal.on('slidechanged', () => presentSync({op: 'move', index: index()}));
  await presentSync({op: 'start', title: (lee.path || lee.tabKey).split('/').pop(), slides: flat, index: index()});
  if (lee.present !== p) return;
  p.events = new EventSource('/present/events');
  p.events.addEventListener('nav', e => { const {cmd} = JSON.parse(e.data); if (NAV_CMDS.has(cmd)) p.reveal[cmd](); });
  presentNotesPage();
}

function closePresentation() {
  const p = lee.present; if (!p) return;
  lee.present = null;
  removeEventListener('keydown', p.onKey, true); removeEventListener('lee-cell-output', p.onOutput);
  document.removeEventListener('fullscreenchange', p.onFs);
  p.events?.close();
  if (document.fullscreenElement) document.exitFullscreen().catch(() => {});
  $$('[data-markdown]', p.root).forEach(el => {
    clearTimeout(el._leeMarkdownTimer); if (el._leeCodeFrame) cancelAnimationFrame(el._leeCodeFrame);
    for (const v of el._leeCodeViews || []) try { LeeCM.destroy(v); } catch {}
  });
  $$('iframe', p.root).forEach(f => f.remove());
  try { p.reveal?.destroy(); } catch {}
  p.root.remove(); $$('link[data-lee-present]').forEach(l => l.remove());
  if (p.reveal) presentSync({op: 'end'});
  if (lee.kind === 'notebook' && lee.cells.length) focusCell(lee.sel);
}
