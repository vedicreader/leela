const LEARN = '/learn/abh';
const LEARN_OWN = {'/settings': () => leeAct('settings'), '/keys': () => leeAct('help'), '/search': () => leeVaultWorkbench('find'), '/library': () => leeVaultWorkbench('library'), '/sources': () => leeVaultWorkbench('library'), '/library/sources': () => leeVaultWorkbench('library')};
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
    for (const s of el ? [] : [].concat(LEARN_KEYS[e.code] || [])) if ((el = [...abh.querySelectorAll(s)].find(learnSeen))) break;
  } else if (e.key === 'Enter' && (e.metaKey || e.ctrlKey) && box && e.target.form) {
    e.preventDefault(); e.stopPropagation(); e.target.form.requestSubmit(e.target.form.querySelector('button.go') || undefined); return true;
  } else if (e.key === '/' && !box && !e.metaKey && !e.ctrlKey && !e.altKey) {
    e.preventDefault(); e.stopPropagation(); LEARN_OWN['/search'](); return true;
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
  host.innerHTML = '<div class="lee-learn-tab"><div class="lee-learn-bar"><button type="button" class="lee-btn" data-learn-back disabled>Back</button><button type="button" class="lee-btn" data-learn-home>Home</button><button type="button" class="lee-btn" data-learn-fit title="Hide the files and exec panels while this tab is open">Wide</button></div><div class="abh" hx-push-url="false"></div></div>';
  window.leeLearnObs?.disconnect();
  const fit = host.querySelector('[data-learn-fit]'), sync = () => {
    const here = !!host.querySelector('.lee-learn-tab');
    leeLearnFit(here && learnFitOn()); fit?.setAttribute('aria-pressed', String(learnFitOn()));
    if (!here) window.leeLearnObs?.disconnect();
  };
  (window.leeLearnObs = new MutationObserver(sync)).observe(host, {childList: true});
  fit.onclick = () => { localStorage.setItem('lee-learn-fit', learnFitOn() ? '0' : '1'); sync(); };
  sync();
  const abh = host.querySelector('.abh'), back = host.querySelector('[data-learn-back]');
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
  const own = u => LEARN_OWN[u.pathname];
  const local = u => u.origin === location.origin && !/^\/(?:assets|vendor)\//.test(u.pathname);
  abh.addEventListener('click', e => {
    const a = e.target.closest('a[href]');
    if (!a || a.target || a.getAttribute('href').startsWith('#') || a.matches(LEARN_HX)) return;
    const u = new URL(a.href, location.origin);
    if (!local(u)) return;
    e.preventDefault(); e.stopImmediatePropagation();
    own(u) ? own(u)() : nav(u.pathname + u.search + u.hash);
  }, true);
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
    cur = path; pending = null; back.disabled = !trail.length;
    const main = abh.querySelector('main');
    if (main && !ran.has(main)) { ran.add(main); busy.add(main); abh.setAttribute('aria-busy', 'true'); learnSurface(path).then(() => renderMath(abh)).finally(() => idle(main)); }
  });
  abh.addEventListener('htmx:afterSettle', e => idle(e.detail.xhr));
  abh.addEventListener('htmx:afterSwap', () => renderMath(abh));
  back.onclick = () => trail.length && nav(trail.pop(), true);
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
