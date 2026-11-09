const LEARN = '/learn/abh';
const LEARN_OWN = {'/settings': () => leeAct('settings'), '/keys': () => leeAct('help'), '/search': () => leeVaultWorkbench('find'), '/library': () => leeVaultWorkbench('library'), '/sources': () => leeVaultWorkbench('library'), '/library/sources': () => leeVaultWorkbench('library')};
const LEARN_KEYS = window.abhyasaKeys ||= {KeyS: ['#send', 'main .go'], KeyW: '#hint', KeyE: '#show-demo', KeyC: ['#continue', '[data-part=continue-card] [data-act=continue]'], KeyX: '#idk, #teach', KeyA: '#another', KeyV: '.walk-demo #keep'};
window.abhyasaMotion ||= () => !matchMedia('(prefers-reduced-motion: reduce)').matches;
const LEARN_HX = '[hx-get],[hx-post],[hx-put],[hx-patch],[hx-delete]';
const learnSeen = el => !el.disabled && (el.checkVisibility ? el.checkVisibility() : el.offsetParent !== null);

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

function leeAbhKey(e) {
  const abh = e.target.closest?.('.abh');
  if (!abh || e.isComposing) return false;
  const box = e.target.matches('textarea, input, select, [contenteditable]');
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
  host.innerHTML = '<div class="lee-learn"><div class="lee-learn-bar"><button type="button" class="lee-btn" data-learn-back disabled>Back</button><button type="button" class="lee-btn" data-learn-home>Home</button></div><div class="abh" hx-push-url="false"></div></div>';
  const abh = host.querySelector('.abh'), back = host.querySelector('[data-learn-back]');
  const trail = []; let cur = null, pending = null, touched = false;
  const open = await fetch(LEARN + '/open', {method: 'POST'}).then(r => r.json()).catch(() => ({}));
  if (!open.ok) { abh.textContent = 'Learn is not available. Turn on Learn and attach the learning vault.'; return; }
  const nav = (path, goBack = false) => { pending = {path, goBack}; return htmx.ajax('GET', path, {source: abh, target: abh, swap: 'innerHTML', select: 'main'}); };
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
    learnSurface(path).then(() => renderMath(abh));
  });
  abh.addEventListener('htmx:afterSwap', () => renderMath(abh));
  back.onclick = () => trail.length && nav(trail.pop(), true);
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
