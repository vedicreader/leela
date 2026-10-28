// The side page: a Leela page in the split editor, the host half and the in-pane half of abhyasa's pane (abhyasa/core/pane.py).
// Top-level function declarations only, and no wiring before DOMContentLoaded: tests/test_learn_pane.py evaluates this file in Node.
function leeIsLocal(u) {
  "As `is_local` in learn.py."
  return typeof u === 'string' && u.startsWith('/') && !u.startsWith('//') && !/[\x00-\x1f\x7f\\]/.test(u);
}
function leeQueryWithout(search, k) { return search.replace(/^\?/, '').split('&').filter(x => x && !x.startsWith(k + '=')); }
function leeJoinURL(path, q, hash = '') { return path + (q.length ? '?' + q.join('&') : '') + hash; }
function leeURLParts(u) {
  "The path, the query and the fragment of a local URL.";
  const i = u.indexOf('#'), pq = i < 0 ? u : u.slice(0, i), j = pq.indexOf('?');
  return [j < 0 ? pq : pq.slice(0, j), j < 0 ? '' : pq.slice(j), i < 0 ? '' : u.slice(i)];
}
function leePaneURL(u) {
  "As `pane_url` in learn.py."
  if (!leeIsLocal(u)) return null;
  const [p, q, h] = leeURLParts(u);
  return leeJoinURL(p, [...leeQueryWithout(q, 'pane'), 'pane=1'], h);
}
function leeOwnURL(u) { const [p, q, h] = leeURLParts(u); return leeJoinURL(p, leeQueryWithout(q, 'pane'), h); }
function leeTrail(t) {
  "A copy of the trail `[[label, url], ...]`, or null when it is not a list or a part is not a text label and a local URL.";
  if (t === undefined) return [];
  return Array.isArray(t) && t.every(x => Array.isArray(x) && typeof x[0] === 'string' && leeIsLocal(x[1])) ? t.map(([l, h]) => [l, h]) : null;
}

function leePaneMessage(e, host) {
  "Act on a message from the page in the pane. True when it acted.";
  if (!host || !host.frame || e.origin !== location.origin || e.source !== host.frame.contentWindow) return false;
  const d = e.data;
  if (!d || typeof d !== 'object' || Array.isArray(d)) return false;
  if (d.type === 'rh:at') {
    const trail = leeTrail(d.trail);
    if (!leeIsLocal(d.url) || !trail || (d.title !== undefined && typeof d.title !== 'string')) return false;
    host.trail = trail; host.at(d.url, d.title || '', trail); return true;
  }
  if (d.type === 'rh:open') { if (!leeIsLocal(d.url)) return false; host.trail = []; host.open(d.url); return true; }
  if (d.type === 'rh:close') {
    if (d.level === undefined) { host.close(); return true; }
    if (d.level !== 1) return false;
    const t = host.trail || [];
    if (t.length) { host.trail = t.slice(0, -1); host.open(t[t.length - 1][1]); } else host.close();
    return true;
  }
  if (d.type !== 'rh:done') return false;
  document.dispatchEvent(new CustomEvent('abhyasa:rh-done', {detail: {slug: String(d.slug), outcome: String(d.outcome)}}));
  return true;
}

function leeSavedSplit(raw) {
  "The split that the `lee-editor-split` value asks for: `{page, title, direction}`, `{path, direction}`, null for none, or false for a bad value.";
  let s;
  try { s = JSON.parse(raw || 'null'); } catch (_) { return false; }
  if (s === null) return null;
  if (typeof s !== 'object' || Array.isArray(s)) return false;
  const direction = s.direction === 'horizontal' ? 'horizontal' : 'vertical';
  if ('page' in s) return leeIsLocal(s.page) ? {page: leeOwnURL(s.page), title: typeof s.title === 'string' ? s.title : '', direction} : false;
  return typeof s.path === 'string' && s.path ? {path: s.path, direction} : null;
}
function leeSidePageOpen(url, title = '') { return leeIsLocal(url) && mountPage(url, title); }
function leeSidePageClose() { leeCloseSplit(); }

function leePaneHere(loc) { return leeJoinURL(loc.pathname, leeQueryWithout(loc.search, 'pane'), loc.hash); }
function leePaneTell(m) { if (window.parent !== window) window.parent.postMessage(m, location.origin); }
function leePaneAt() {
  let trail = [];
  try { trail = JSON.parse(document.querySelector('[data-rh-trail]').dataset.rhTrail); } catch (_) {}
  leePaneTell({type: 'rh:at', url: leePaneHere(location), title: document.title, trail});
}
function leePaneKey(e) {
  if (e.key !== 'Escape' || e.defaultPrevented) return;
  const t = e.target;
  if (t && (t.isContentEditable || (t.matches && t.matches('textarea, select, input:not([type=button], [type=submit], [type=reset], [type=checkbox], [type=radio])')))) return;
  e.preventDefault(); leePaneTell({type: 'rh:close', level: 1});
}
async function leeScratch(btn) {
  "Post the button's snippet to `/learn/scratch` for its notebook, and say the result in the page's status line.";
  const say = t => { const s = document.querySelector('[role=status]'); if (s) s.textContent = t; };
  btn.disabled = true;
  try {
    const r = await fetch('/learn/scratch', {method: 'POST', headers: {'Content-Type': 'application/json'},
                                             body: JSON.stringify({path: btn.dataset.path, snippet: btn.dataset.snippet})});
    const d = await r.json().catch(() => ({}));
    say(r.ok && d.ok ? 'Added a scratch cell at the end of the notebook.' : String(d.error || 'Leela did not add the cell.'));
  } catch (_) { say('Leela did not add the cell.'); }
  finally { btn.disabled = false; }
}
function leePaneBoot() {
  if (document.documentElement.classList.contains('in-pane')) { leePaneAt(); document.addEventListener('keydown', leePaneKey); return; }
  if (typeof lee === 'undefined') return;   // a learn page in a tab of its own: no split editor to host a pane
  window.leeSidePage = {open: leeSidePageOpen, close: leeSidePageClose};
  window.addEventListener('message', e => leePaneMessage(e, lee.sidePage));
}
document.addEventListener('DOMContentLoaded', leePaneBoot);
