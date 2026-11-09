const LEARN = '/learn/abh';
const LEARN_FIND = () => leeVaultWorkbench('find');
const LEARN_DOC = /^\/v\/([^/]+)\/([^/]+)$/;
const learnDoc = k => { const [, shelf, doc] = LEARN_DOC.exec(k).map(x => x && decodeURIComponent(x)); return () => leeOpenVaultDoc(doc, shelf, 'learn'); };
const LEARN_OWN = new Proxy({'/settings': () => leeAct('settings')?.then(() => $('[data-settings-page="learn"]')?.click()), '/keys': () => leeAct('help')}, {get: (o, k) => o[k] || (typeof k === 'string' && LEARN_DOC.test(k) ? learnDoc(k) : undefined)});
function learnBar(host) {
  const nav = host.querySelector('.lee-learn-nav');
  for (const [name, path] of [['Library', '/library'], ['You', '/you']]) nav.append(Object.assign(document.createElement('button'), {type: 'button', className: 'lee-btn', textContent: name, onclick: () => window.leeLearnNav(path)}));
  const f = Object.assign(document.createElement('form'), {className: 'lee-learn-find', innerHTML: '<input type="search" name="q" class="lee-input" placeholder="Search what you learned" aria-label="Search what you learned" autocomplete="off">'});
  f.onsubmit = e => { e.preventDefault(); if (f.q.value.trim()) window.leeLearnNav('/search?q=' + encodeURIComponent(f.q.value.trim())); };
  host.querySelector('[data-learn-chips]').after(f);
}
async function learnChips(host, path) {
  const html = await fetch(LEARN + '/nav/extra?path=' + encodeURIComponent(path)).then(r => r.ok ? r.text() : '').catch(() => ''), t = document.createElement('template');
  t.innerHTML = html;
  const go = t.content.querySelector('#continue'), job = t.content.querySelector('#activity'), s = job?.querySelector('summary'), l = job?.querySelector('.activity-list a[href]');
  go?.classList.add('lee-learn-chip');
  host.querySelector('[data-learn-chips]')?.replaceChildren(...[go, s && Object.assign(document.createElement(l ? 'a' : 'span'), {className: 'lee-learn-chip', textContent: s.textContent.trim()}, l ? {href: l.getAttribute('href')} : {})].filter(Boolean));
}
function learnClear(host) {
  window.leeLearnClr?.disconnect();
  const tab = host.querySelector('.lee-learn-tab'), shell = $('#shell'), shown = s => { const e = $(s); return e && getComputedStyle(e).display !== 'none' ? e : null; };
  const g = (e, p) => parseFloat(getComputedStyle(e)[p]) || 0, ro = new ResizeObserver(() => set()), mo = new MutationObserver(() => set());
  const set = () => {
    if (!tab?.isConnected) return;
    const r = host.getBoundingClientRect(), l = shown('.restore-left'), rt = shown('.restore-right'), b = shown('.restore-bottom'), st = $('#status');
    const need = b ? Math.max(b.offsetHeight + g(b, 'bottom'), st ? g(st, 'bottom') + g(st, 'minHeight') : 0) : 0;
    tab.style.setProperty('--learn-left', (l ? Math.max(0, l.offsetWidth + g(l, 'left') - r.left) : 0) + 'px');
    tab.style.setProperty('--learn-right', (rt ? Math.max(0, rt.offsetWidth + g(rt, 'right') - (innerWidth - r.right)) : 0) + 'px');
    tab.style.setProperty('--learn-bottom', (need ? Math.max(0, need + 8 - (innerHeight - r.bottom)) : 0) + 'px');
  };
  ['.restore-left', '.restore-right', '.restore-bottom', '#status'].map(s => $(s)).filter(Boolean).forEach(e => ro.observe(e)); ro.observe(host);
  shell && mo.observe(shell, {attributes: true, attributeFilter: ['class']});
  window.leeLearnClr = {disconnect() { ro.disconnect(); mo.disconnect(); }};
  set();
}
const LEARN_KEYS = window.abhyasaKeys ||= {KeyS: ['#send', 'main .go'], KeyW: '#hint', KeyE: '#show-demo', KeyC: ['#continue', '[data-part=continue-card] [data-act=continue]'], KeyX: '#idk, #teach', KeyA: '#another', KeyV: '.walk-demo #keep'};
window.abhyasaGo ||= u => window.leeLearnNav?.(u);
window.abhyasaPane ||= {open: u => window.leeLearnNav?.(u), close: () => window.leeLearnBack?.(), isOpen: () => false};
window.abhyasaMotion ||= () => !matchMedia('(prefers-reduced-motion: reduce)').matches;
const LEARN_HX = '[hx-get],[hx-post],[hx-put],[hx-patch],[hx-delete]';
const learnSeen = el => !el.disabled && (el.checkVisibility ? el.checkVisibility() : el.offsetParent !== null);

const leeAbhSettled = abh => abh.getAttribute('aria-busy') !== 'true' ? Promise.resolve() : new Promise(ok => abh.addEventListener('lee:settled', ok, {once: true}));
window.leeAbhSettled = leeAbhSettled;
const learnLoaded = window.learnLoaded ||= new Set();
async function learnSurface(path) {
  const s = await fetch('/learn/abh-surface?path=' + encodeURIComponent(path)).then(r => r.json()).catch(() => null);
  if (!s) return;
  const once = u => !learnLoaded.has(u) && learnLoaded.add(u);
  s.css.filter(once).forEach(href => document.head.append(Object.assign(document.createElement('link'), {rel: 'stylesheet', href})));
  for (const src of s.js) {
    const again = s.rerun.includes(src);
    if (again || once(src)) await new Promise(ok => { const sc = Object.assign(document.createElement('script'), {src, onload: ok, onerror: ok}); if (again) sc.addEventListener('load', () => sc.remove()); document.head.append(sc); });
  }
}
window.leeAbhTheme ||= new MutationObserver(() => document.dispatchEvent(new CustomEvent('abhyasa:theme'))).observe(document.documentElement, {attributes: true, attributeFilter: ['data-theme', 'data-mode', 'data-density']}) || 1;

const learnFitOn = () => localStorage.getItem('lee-learn-fit') !== '0';
function leeLearnFit(on) {
  const shell = $('#shell'), hid = window.leeLearnHid ||= [];
  if (!shell) return;
  if (on) for (const w of ['left', 'bottom']) { if (!shell.classList.contains('no-' + w) && !hid.includes(w)) { hid.push(w); leePane(w, false, false); } }
  else while (hid.length) { const w = hid.pop(); if (shell.classList.contains('no-' + w)) leePane(w, true, false); }
}
window.leeLearnFit = leeLearnFit;

function leeAbhKey(e, home) {
  const abh = home || e.target.closest?.('.abh') || (e.code === 'KeyB' && getSelection()?.anchorNode?.parentElement?.closest('.abh'));
  if (!abh || e.isComposing) return false;
  if (!home && abh.getAttribute('aria-busy') === 'true' && e.altKey) { e.preventDefault(); e.stopPropagation(); leeAbhSettled(abh).then(() => leeAbhKey(e, abh)); return true; }
  const box = e.target.matches('textarea, input, select, [contenteditable]');
  if (e.altKey && !e.metaKey && !e.ctrlKey && e.code === 'KeyB' && window.abhyasaDetourKey) { window.abhyasaDetourKey(e); return e.defaultPrevented; }
  let el = null;
  if (e.altKey && !e.metaKey && !e.ctrlKey) {
    const mark = '⌥' + e.code.replace(/^(?:Key|Digit)/, '');
    el = [...abh.querySelectorAll('button kbd, a kbd')].filter(k => k.textContent.trim() === mark).map(k => k.closest('button, a')).find(learnSeen);
    for (const s of el ? [] : [].concat(LEARN_KEYS[e.code] || [])) if ((el = [...(abh.closest('.lee-learn-tab') || abh).querySelectorAll(s)].find(learnSeen))) break;
  } else if (e.key === 'Enter' && (e.metaKey || e.ctrlKey) && box && e.target.form) {
    e.preventDefault(); e.stopPropagation(); e.target.form.requestSubmit(e.target.form.querySelector('button.go') || undefined); return true;
  } else if (e.key === '/' && !box && !e.metaKey && !e.ctrlKey && !e.altKey) {
    e.preventDefault(); e.stopPropagation(); LEARN_FIND(); return true;
  }
  if (!el) return false;
  e.preventDefault(); e.stopPropagation();
  el.matches('textarea, input') ? el.focus() : el.click();
  return true;
}
window.leeAbhKey = leeAbhKey;

async function learnMount(host, st) {
  if (!document.getElementById('lee-abh-css')) {
    const link = document.createElement('link'); link.id = 'lee-abh-css'; link.rel = 'stylesheet'; link.href = '/learn/abh.css'; document.head.append(link);
  }
  if (!window.abhyasaGrip) await new Promise(ok => { const sc = document.createElement('script'); sc.src = '/learn/abh-grip.js'; sc.onload = sc.onerror = ok; document.head.append(sc); });
  const start = st.path || (st.walk ? '/w/' + encodeURIComponent(st.walk) + '/0' : '/');
  host.innerHTML = '<div class="lee-learn-tab"><div class="lee-learn-bar"><button type="button" class="lee-btn" data-learn-back disabled>Back</button><span class="lee-learn-nav" role="group" aria-label="Learn"><button type="button" class="lee-btn" data-learn-home>Home</button></span><span class="lee-learn-chips" data-learn-chips></span><button type="button" class="lee-btn" data-learn-fit title="Hide the files and exec panels while this tab is open">Wide</button><button type="button" class="lee-btn" data-learn-ask title="Ask the agent about what you see (Ctrl+Opt+Shift+Cmd+E)">I don&#39;t get this</button><button type="button" class="lee-btn" data-learn-change hidden title="Change this walk with the agent">Change with the builder</button></div><div class="abh" hx-push-url="false"></div></div>';
  window.leeLearnObs?.disconnect();
  const fit = host.querySelector('[data-learn-fit]'), sync = () => {
    const here = !!host.querySelector('.lee-learn-tab');
    leeLearnFit(here && learnFitOn()); fit?.setAttribute('aria-pressed', String(learnFitOn()));
    $('#shell')?.classList.toggle('lee-learn-on', here);
    here ? learnClear(host) : window.leeLearnClr?.disconnect();
    if (!here) window.leeLearnObs?.disconnect();
  };
  (window.leeLearnObs = new MutationObserver(sync)).observe(host, {childList: true});
  fit.onclick = () => { localStorage.setItem('lee-learn-fit', learnFitOn() ? '0' : '1'); sync(); };
  sync(); learnBar(host);
  const abh = host.querySelector('.abh'), back = host.querySelector('[data-learn-back]'), change = host.querySelector('[data-learn-change]');
  const trail = [], ran = new WeakSet(); let cur = null, pending = null, touched = false;
  const open = await fetch(LEARN + '/open', {method: 'POST'}).then(r => r.json()).catch(() => ({}));
  if (!open.ok) { abh.textContent = 'Learn is not available. Turn on Learn and attach the learning vault.'; return; }
  const nav = (path, goBack = false) => { pending = {path, goBack}; return htmx.ajax('GET', path, {source: abh, target: abh, swap: 'innerHTML', select: 'main'}); };
  const known = new Set((await fetch('/learn/abh-surface').then(r => r.json()).catch(() => ({}))).known);
  abh.addEventListener('htmx:beforeSwap', e => {
    const d = e.detail;
    if (d.target === abh && typeof d.serverResponse === 'string') d.serverResponse = d.serverResponse.replace(/<script\b[^>]*\bsrc="[^"]*?([\w.-]+)(?:\?[^"]*)?"[^>]*>\s*<\/script>/g, (m, n) => known.has(n) ? '' : m);
  });
  const busy = new Set(), idle = x => { busy.delete(x); if (!busy.size) { abh.removeAttribute('aria-busy'); abh.dispatchEvent(new CustomEvent('lee:settled')); } };
  abh.addEventListener('htmx:beforeRequest', e => { busy.add(e.detail.xhr); abh.setAttribute('aria-busy', 'true'); });
  for (const ev of ['htmx:responseError', 'htmx:sendError', 'htmx:swapError', 'htmx:targetError', 'htmx:sendAbort', 'htmx:timeout']) abh.addEventListener(ev, e => idle(e.detail.xhr));
  abh.addEventListener('htmx:afterRequest', e => { const x = e.detail.xhr; if (!e.detail.successful || x.status === 204 || x.status === 205) idle(x); });
  const own = u => u.pathname.startsWith('/build') ? () => window.leeLearnChange?.() : LEARN_OWN[u.pathname];
  const local = u => u.origin === location.origin && !/^\/(?:assets|vendor)\//.test(u.pathname);
  abh.addEventListener('click', e => {
    const a = e.target.closest('a[href]');
    if (!a || (a.target && !a.dataset.pane) || a.getAttribute('href').startsWith('#') || a.matches(LEARN_HX)) return;
    const u = new URL(a.href, location.origin);
    if (!local(u)) return;
    e.preventDefault(); e.stopImmediatePropagation();
    own(u) ? own(u)() : nav(u.pathname + u.search + u.hash);
  }, true);
  host.querySelector('[data-learn-chips]').addEventListener('click', e => {
    const a = e.target.closest('a[href]'); if (!a) return;
    e.preventDefault(); const u = new URL(a.href, location.origin); own(u) ? own(u)() : nav(u.pathname + u.search + u.hash);
  });
  abh.addEventListener('submit', e => {
    const f = e.target;
    if (f.matches(LEARN_HX) || f.closest(LEARN_HX)) return;
    e.preventDefault(); e.stopImmediatePropagation();
    const u = new URL(f.getAttribute('action') || cur, location.origin), get = (f.method || 'get').toLowerCase() === 'get', values = Object.fromEntries(new FormData(f));
    if (own(u)) return own(u)();
    if (get) { new URLSearchParams(values).forEach((v, k) => u.searchParams.set(k, v)); return nav(u.pathname + u.search); }
    pending = {path: u.pathname + u.search, goBack: false};
    htmx.ajax('POST', u.pathname + u.search, {source: abh, target: abh, swap: 'innerHTML', select: 'main', values});
  }, true);
  abh.addEventListener('htmx:configRequest', e => {
    const d = e.detail, u = new URL(d.path, location.origin);
    if (u.origin === location.origin && !u.pathname.startsWith(LEARN + '/') && !/^\/(?:assets|vendor)\//.test(u.pathname)) d.path = LEARN + u.pathname + u.search;
    if (!u.searchParams.has('pane')) d.parameters.pane = '1';
  });
  for (const ev of ['pointerdown', 'keydown']) abh.addEventListener(ev, () => { touched = true; }, true);
  abh.addEventListener('htmx:afterSettle', e => {
    if (!touched && document.activeElement?.closest('.abh')) document.activeElement.blur();
    if (e.target !== abh) return;
    const r = e.detail.xhr?.responseURL ? new URL(e.detail.xhr.responseURL) : null;
    let path = r ? r.pathname + r.search : pending?.path;
    path = path.replace(LEARN, '').replace(/([?&])pane=1&?/, '$1').replace(/[?&]$/, '') || '/';
    if (cur && path !== cur && !(pending?.goBack)) trail.push(cur);
    if (path !== cur) fetch('/learn/tab/page', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({path})});
    cur = path; pending = null; learnChips(host, cur); back.disabled = !trail.length; change.hidden = !/^\/w\//.test(cur);
    const main = abh.querySelector('main');
    if (main && !ran.has(main)) { ran.add(main); busy.add(main); abh.setAttribute('aria-busy', 'true'); learnSurface(path).then(() => renderMath(abh)).finally(() => idle(main)); }
  });
  abh.addEventListener('htmx:afterSettle', e => idle(e.detail.xhr));
  abh.addEventListener('htmx:afterSwap', () => renderMath(abh));
  back.onclick = () => trail.length && nav(trail.pop(), true);
  host.querySelector('[data-learn-ask]').onclick = () => window.leeLearnAsk?.();
  change.onclick = () => window.leeLearnChange?.();
  const sides = [];
  const closeSide = async () => {
    const sid = sides.pop();
    if (!sid || !trail.length) return back.onclick();
    const r = await fetch(LEARN + '/rh/back/' + encodeURIComponent(sid), {method: 'POST'}).catch(() => null);
    if (!r?.ok) return back.onclick();
    const u = new URL(r.url);
    trail.pop(); nav(u.pathname.replace(LEARN, '') + u.search.replace(/([?&])pane=1&?/, '$1').replace(/[?&]$/, ''), true);
  };
  Object.assign(window.abhyasaPane ||= {}, {open: u => { const m = /^\/w\/([^/?#]+)/.exec(u); if (m) sides.push(decodeURIComponent(m[1])); return nav(u); }, close: closeSide});
  window.leeLearnReload = async walk => {
    if (!cur || abh.getAttribute('aria-busy') === 'true' || !abh.isConnected || (walk && cur !== '/' && !cur.startsWith('/w/' + encodeURIComponent(walk)))) return false;
    if ([...abh.querySelectorAll('textarea, input[type=text]')].some(x => x.value.trim())) { status('The plan changed. Leave the box and press Home to see it.', 'err'); return false; }
    const scrolls = []; for (let e = abh; e; e = e.parentElement) scrolls.push([e, e.scrollTop]);
    const at = document.activeElement?.closest('.abh') && document.activeElement, sel = at?.id ? '#' + CSS.escape(at.id) : at?.name ? `[name="${CSS.escape(at.name)}"]` : '';
    const keep = () => { for (const [e, t] of scrolls) e.scrollTop = t; if (sel) abh.querySelector(sel)?.focus({preventScroll: true}); };
    abh.addEventListener('htmx:afterSettle', () => requestAnimationFrame(keep), {once: true});
    await nav(cur, true); await leeAbhSettled(abh); keep();
    return true;
  };
  window.leeLearnNav = nav; window.leeLearnBack = () => back.onclick();
  host.querySelector('[data-learn-home]').onclick = () => nav('/');
  new ResizeObserver(() => abh.classList.toggle('wide', abh.clientWidth >= 940)).observe(abh);
  htmx.process(abh);
  nav(start);
}
registerTabMount('learn_walk', learnMount);
registerTabMount('learn', learnMount);

function leeLearnOpen(path = '/') {
  return htmx.ajax('POST', '/learn/tab/open?path=' + encodeURIComponent(path), {target: '#tabbar', swap: 'outerHTML'}).then(() => mountTab());
}
window.leeLearnOpen = leeLearnOpen;
