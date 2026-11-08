let termBundle = null;
function loadTermBundle() {
  if (window.LeeTerm) return Promise.resolve();
  if (termBundle) return termBundle;
  termBundle = new Promise((resolve, reject) => {
    const script = document.createElement('script');
    script.src = $('#termwrap')?.dataset.termSrc || '/leestatic/lee-term.js';
    script.onload = resolve; script.onerror = () => reject(new Error('terminal bundle failed to load'));
    document.head.appendChild(script);
  });
  return termBundle;
}
// Multiple xterm instances keep their websocket and pty alive while hidden, and the 285kb bundle
// loads only on the first terminal action.
// `taken` is the set of ids the server is holding. A pty deliberately outlives its websocket so a
// reload can reattach, and this counter restarts at zero on reload, so an id in `taken` must be
// skipped rather than reused.
function nextTermId(kind, taken = []) {
  if (kind === 'git') return 'git';
  const used = new Set([...lee.terms.keys(), ...taken]);
  do { lee.termSeq += 1; } while (used.has('term-' + lee.termSeq));
  return 'term-' + lee.termSeq;
}
/* `root` names the package a pipeline terminal is watching. There is one of these per package,
   and two of them are otherwise the same word. */
function termLabel(kind, id, root = '') {
  const name = kind === 'git' ? 'lazygit' : kind === 'release' ? (root ? 'release' : 'release pipeline')
    : kind === 'deploy' ? 'deploy' : kind === 'drive' ? 'drive' : kind === 'gh-auth' ? 'gh auth'
    : `terminal ${id.split('-').pop()}`;
  return root ? `${name} · ${root.replace(/\/+$/, '').split('/').pop()}` : name;
}
function paintTermTabs() {
  const bar = $('#termtabs'); if (!bar) return;
  /* The close control belongs to the tab, not the header, so a background terminal is closed
     without selecting it first. */
  bar.innerHTML = [...lee.terms.entries()].map(([id, t]) =>
    `<span role="tab" aria-selected="${id === lee.activeTerm}" class="lee-termtab${id === lee.activeTerm ? ' active' : ''}" ` +
    `data-term="${esc(id)}" title="${esc(t.cwd || '')}"><button class="lee-termtab-name" data-term-pick="${esc(id)}">${esc(t.label)}</button>` +
    `<button class="lee-termtab-x" data-term-close="${esc(id)}" title="Close ${esc(t.label)}" aria-label="Close ${esc(t.label)}">×</button></span>`).join('');
  bar.querySelectorAll('[data-term-pick]').forEach(b => b.onclick = () => switchTerm(b.dataset.termPick));
  bar.querySelectorAll('[data-term-close]').forEach(b => b.onclick = e => {
    e.stopPropagation();            // closing a tab must not also select it
    closeTerm(b.dataset.termClose);
  });
  $('#termempty')?.toggleAttribute('hidden', lee.terms.size > 0);
}
function leeLeft(which = 'files') {
  const left = $('#left'); if (!left) return;
  leePane('left', true);
  left.classList.toggle('left-files', which === 'files');
  left.classList.toggle('left-symbols', which === 'symbols');
  left.classList.toggle('left-git', which === 'git');
  left.classList.toggle('left-workflows', which === 'workflows');
  left.classList.toggle('left-releases', which === 'releases');
  left.classList.toggle('left-deploys', which === 'deploys');
  left.classList.toggle('left-drive', which === 'drive');
  $$('.lee-activity-btn', left).forEach(b => {
    const active = b.dataset.left === which; b.classList.toggle('active', active);
    b.setAttribute('aria-pressed', String(active));
  });
  localStorage.setItem('lee-left-view', which);
  if (which === 'git') { setScope('files'); renderGitPanel(); }
  else if (which === 'workflows') { setScope('files'); leeWorkflows(); }
  else if (which === 'releases') { setScope('files'); leeReleases(); }
  else if (which === 'deploys') { setScope('files'); leeDeploys(); }
  else if (which === 'drive') { setScope('files'); leeDrive(); }
  else if (which === 'symbols') { setScope('files'); leeSymbols(); }
  else { setScope('files'); requestAnimationFrame(() => $('#filetree')?.focus()); }
}
window.leeLeft = leeLeft;
/* Expansion: one slot, one mode, one writer.

   `wide` gives the pane the dominant share of the grid it sits in, and `full` lifts it over the
   whole shell. Only one slot is expanded at a time. Everything expansion touches is written by
   `leeSyncExpand` from the stored value alone, so the `#shell` classes, the agent panel's timeline
   layout and every button label cannot disagree. Closing the pane clears it, because a wide grid
   track behind a hidden pane is dead space. */
const PANE_HIDDEN = {left: 'no-left', right: 'no-right', bottom: 'no-bottom'};
const EXPAND_MODES = ['wide', 'full'];

function leeExpandState() {
  const [which, mode] = (localStorage.getItem('lee-expand') || '').split(':');
  return PANE_HIDDEN[which] && EXPAND_MODES.includes(mode) ? {which, mode} : {which: '', mode: ''};
}
const leaveChord = () => displayChord((lee.keys || []).find(k => k.action === 'leave_full_screen')?.key?.split(' ')[0] || '');
function leeSyncExpand() {
  const shell = $('#shell'); if (!shell) return;
  let {which, mode} = leeExpandState();
  // A pane hidden by a reload, or by anything that forgot to say so, cannot stay expanded.
  if (which && shell.classList.contains(PANE_HIDDEN[which])) { which = mode = ''; localStorage.setItem('lee-expand', ''); }
  for (const slot in PANE_HIDDEN) shell.classList.toggle('expand-' + slot, slot === which);
  for (const m of EXPAND_MODES) shell.classList.toggle('expand-' + m, m === mode);
  $('.lee-agent')?.classList.toggle('timeline-workspace', which === 'right' && !!mode);
  $$('[data-pane-expand]').forEach(b => {
    const slot = b.dataset.paneExpand, own = slot === which ? mode : '';
    const label = own === 'wide' ? 'full screen' : own === 'full' ? 'restore' : 'expand';
    b.textContent = b.dataset.paneExpandIcon ? (own === 'full' ? '\u2921' : '\u2922') : label;
    b.title = `${label} the ${slot} pane${own === 'full' && leaveChord() ? ` (${leaveChord()})` : ''}`;
    b.setAttribute('aria-label', `${label} the ${slot} pane`);
    b.setAttribute('aria-pressed', String(!!own));
  });
}
function leeExpand(which = '', mode = '') {
  const wanted = PANE_HIDDEN[which] && EXPAND_MODES.includes(mode) ? which + ':' + mode : '';
  if (wanted) leePane(which, true);
  localStorage.setItem('lee-expand', wanted);
  leeSyncExpand();
  requestAnimationFrame(() => lee.term?.refit());
}
function leeExpandPane(which) {
  const cur = leeExpandState(), mode = cur.which !== which ? 'wide' : cur.mode === 'wide' ? 'full' : '';
  leeExpand(which, mode);
  status(`${which} pane ${mode === 'wide' ? 'expanded' : mode === 'full' ? 'full screen' : 'restored'}${mode === 'full' && leaveChord() ? ` · ${leaveChord()} to leave` : ''}`);
}
window.leeExpand = leeExpand; window.leeExpandPane = leeExpandPane;

function leeLeaveFullScreen() {
  if (leeExpandState().mode === 'full') leeExpand(''); else status('no pane is full screen');
}
window.leeLeaveFullScreen = leeLeaveFullScreen;

// Full screen hides the layout you would otherwise click back from, so Escape is the way out, except
// in a terminal, where Escape belongs to the program running there. `leave_full_screen` works anywhere.
document.addEventListener('keydown', e => {
  if (e.key !== 'Escape' || $$('.lee-modal, .lee-ctxmenu').length || lee.present || leeExpandState().mode !== 'full') return;
  if ((e.composedPath?.() || [e.target]).some(n => n.matches?.('#termwrap, .xterm'))) return;
  e.preventDefault(); e.stopPropagation(); leeExpand('');
}, true);

// New terminals read these when they are made; `leeTermOptionMeta` also reaches the open ones.
const termOptionMeta = () => prefGet('terminal', 'macOptionIsMeta', true) !== false;
window.leeTermDefaults = () => ({optionMeta: termOptionMeta(), mode: document.documentElement.dataset.mode});
function leeTermOptionMeta(on = !termOptionMeta()) {
  prefSet('terminal', 'macOptionIsMeta', on);
  for (const t of lee.terms.values()) t.view.setOptionMeta(on);
  status(`terminal: Option key ${on ? 'acts as Meta' : 'types composed characters'}`, 'ok');
}
window.leeTermOptionMeta = leeTermOptionMeta;

function leePane(which, show = null, persist = true) {
  const shell = $('#shell'); if (!shell) return;
  const cls = PANE_HIDDEN[which] || 'no-bottom';
  const hidden = show === null ? !shell.classList.contains(cls) : !show;
  shell.classList.toggle(cls, hidden);
  // Closing the pane that is expanded: without this its grid track stays wide and the hidden pane
  // keeps the room.
  if (hidden && leeExpandState().which === which) leeExpand('');
  if (matchMedia('(max-width: 1100px)').matches && which !== 'bottom') {
    shell.classList.toggle('mobile-' + which, !hidden);
    if (!hidden) {
      const other = which === 'left' ? 'right' : 'left';
      shell.classList.remove('mobile-' + other);
      shell.classList.add(other === 'left' ? 'no-left' : 'no-right');
    }
  }
  // An auto-close is not a preference: the pane was got out of the way for one keystroke, and
  // recording it as hidden would mean it never came back after a reload.
  if (persist) localStorage.setItem('lee-pane-' + which, hidden ? 'hidden' : 'shown');
  leeSyncExpand();
  if (!hidden && which === 'bottom') requestAnimationFrame(() => lee.term?.refit());
}
window.leePane = leePane;

/* Docking: a pane is either pinned open, or closes when you work somewhere else.

   The file and agent panes are furniture on a wide screen and an obstruction on a narrow one, so
   each carries its own answer. Pinned is the default, and nothing moves until you unpin it. */
const DOCKABLE = {left: '#left', right: '#right'};

const PINNABLE = Object.keys(DOCKABLE);
/* One list, where there was a key per pane. An empty `workbench.pinnedPanes` is what a fresh
   install holds, not two panes somebody unpinned, so the list is believed only once something has
   been written into it; until then the answer is the per-origin keys it replaces, which is also
   what the gather below writes, once. */
function pinsSaved() {
  const origin = lee.settingsMeta?.origins?.workbench?.pinnedPanes;
  return (origin && origin !== 'default') || localStorage.getItem('lee-pref:workbench.pinnedPanes') !== null;
}
function pinnedPanes() {
  if (pinsSaved()) return prefGet('workbench', 'pinnedPanes', PINNABLE) || PINNABLE;
  return PINNABLE.filter(p => localStorage.getItem('lee-pin-' + p) !== '0');
}
function leePinned(which) { return pinnedPanes().includes(which); }
let pinsAdopted = false;
async function adoptPins() {
  if (pinsAdopted) return;
  pinsAdopted = true;
  if (pinsSaved() || !PINNABLE.some(p => localStorage.getItem('lee-pin-' + p) !== null)) return;
  await prefSet('workbench', 'pinnedPanes', pinnedPanes());
  PINNABLE.forEach(leeSyncPin);
}
function leeSyncPin(which) {
  adoptPins().catch(() => {});
  const pinned = leePinned(which);
  $('#shell')?.classList.toggle('unpinned-' + which, !pinned);
  $$(`[data-pane-pin="${which}"]`).forEach(b => {
    b.textContent = pinned ? '●' : '○';
    b.classList.toggle('pinned', pinned);
    b.setAttribute('aria-pressed', String(pinned));
    b.title = pinned ? 'pinned open. Unpin it to close it when you click away'
                     : 'closes when you click away. Pin it to keep it open';
  });
}

async function leePinPane(which) {
  const now = leePinned(which);
  await prefSet('workbench', 'pinnedPanes', PINNABLE.filter(p => p === which ? !now : leePinned(p)));
  leeSyncPin(which);
  status(leePinned(which) ? `${which} pane pinned open` : `${which} pane closes when you click away`);
}
window.leePinPane = leePinPane;

/* Modals, context menus, the restore tabs and the splitters are not "somewhere else". Each is
   opened from a pane or acts on one, and closing the pane underneath would pull the ground out
   from under the dialog. */
function leeAutoClosePanes(target) {
  const shell = $('#shell');
  if (!shell || !(target instanceof Element)) return;
  if (target.closest('.lee-modal, .lee-ctxmenu, .lee-pane-restore, .lee-split, .lee-editor-splitter')) return;
  for (const [which, sel] of Object.entries(DOCKABLE)) {
    const pane = $(sel);
    if (leePinned(which) || !pane || pane.contains(target)) continue;
    if (shell.classList.contains(which === 'left' ? 'no-left' : 'no-right')) continue;
    // Two more ways a pane is in use without holding the keyboard. A model mid-answer must not be
    // closed out of sight, and a pane must not shut under a pointer travelling towards it, which
    // is what focus moving elsewhere looks like from here.
    if (which === 'right' && lee.agentBusy) continue;
    if (pane.matches(':hover')) continue;
    leePane(which, false, false);
  }
}
document.addEventListener('focusin', e => leeAutoClosePanes(e.target), true);
document.addEventListener('mousedown', e => leeAutoClosePanes(e.target), true);

// Escape from inside an unpinned pane puts you back in the editor, the only way out that does not
// need the mouse.
document.addEventListener('keydown', e => {
  if (e.key !== 'Escape' || lee.present) return;
  for (const [which, sel] of Object.entries(DOCKABLE)) {
    if (leePinned(which) || !$(sel)?.contains(e.target)) continue;
    leePane(which, false, false);
    setScope('editor'); curEditor()?.focus();
  }
}, true);
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
function leeWeb(u) {
  "Whether `u` is a web address that may leave the pane: http or https, with no control character or backslash.";
  return typeof u === 'string' && /^https?:\/\/[^\/]/i.test(u) && !/[\x00-\x20\x7f\\]/.test(u);
}
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
  if (d.type === 'rh:link') { if (!leeWeb(d.url) || !host.link) return false; host.link(d.url); return true; }
  if (d.type === 'rh:key') {
    if (!leePaneChord(d.key, d.meta || d.ctrl, d.alt) || !host.key) return false;
    host.key({key: d.key, code: typeof d.code === 'string' ? d.code : '', metaKey: !!d.meta, ctrlKey: !!d.ctrl, shiftKey: !!d.shift}); return true;
  }
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
  const here = document.documentElement.dataset?.rhUrl;
  leePaneTell({type: 'rh:at', url: leeIsLocal(here) ? here : leePaneHere(location), title: document.title, trail});
}
function leePaneLink(e) {
  "A web link on a learn page opens in a new tab. In the pane a plain click goes to the IDE, so the site never loads in the frame.";
  if (e.defaultPrevented || e.button > 1) return;
  const a = e.target?.closest?.('a[href]');
  if (!a || !leeWeb(a.href) || a.href.startsWith(location.origin + '/')) return;
  a.target = '_blank'; a.rel = 'noopener noreferrer';
  if (!document.documentElement.classList.contains('in-pane') || e.button === 1 || e.metaKey || e.ctrlKey || e.shiftKey) return;
  e.preventDefault(); leePaneTell({type: 'rh:link', url: a.href});
}
function leePaneChord(key, mod, alt) {
  "Whether a key is one of the IDE chords a pane page hands on: Cmd or Ctrl with P, S, W, N, O, J or 1 to 5, and no Alt.";
  return typeof key === 'string' && !!mod && !alt && ['p', 's', 'w', 'n', 'o', 'j', '1', '2', '3', '4', '5'].includes(key.toLowerCase());
}
function leePaneTyping(t) { return !!t && (t.isContentEditable || (!!t.matches && t.matches('textarea, select, input:not([type=button], [type=submit], [type=reset], [type=checkbox], [type=radio])'))); }
function leePaneKey(e) {
  if (!e.defaultPrevented && leePaneChord(e.key, e.metaKey || e.ctrlKey, e.altKey)) {
    e.preventDefault(); leePaneTell({type: 'rh:key', key: e.key, code: e.code, meta: e.metaKey, ctrl: e.ctrlKey, shift: e.shiftKey}); return;
  }
  if (e.key !== 'Escape' || e.defaultPrevented || leePaneTyping(e.target)) return;
  e.preventDefault(); leePaneTell({type: 'rh:close', level: 1});
}
function leeLearnKey(e) {
  "On a Mac `e.key` is the composed character, so match the physical key.";
  if (e.defaultPrevented || e.isComposing || e.repeat || e.code !== 'KeyS' || !e.altKey || e.metaKey || e.ctrlKey || e.shiftKey || leePaneTyping(e.target)) return;
  const f = document.querySelector('form[action="/learn/open"]'); if (!f) return;
  e.preventDefault(); f.requestSubmit();
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
function leeLearnMath() {
  "Draw each `.math` of a learn page with KaTeX, which the page loads deferred; a formula KaTeX cannot read stays as its text.";
  if (!window.katex) return;
  for (const e of document.querySelectorAll('.lee-learn .math'))
    try { katex.render(e.textContent, e, {displayMode: e.classList.contains('display'), throwOnError: false}); } catch (_) {}
}
function leeEnvNext(was, d) {
  "What a step page does with a `/learn/tool` answer `d` while its environment was in the state `was`: `reload`, `say` or `wait`.";
  if (!d || !d.ok || typeof d.state !== 'string') return 'wait';
  return d.state !== was ? 'reload' : 'say';
}
function leeEnvWatch(every = 2000) {
  "While the step's environment installs or indexes, ask `/learn/tool` every `every` ms, say its state, and reload the page when the state changes.";
  const e = document.querySelector('[data-env-state]');
  if (!e || !['installing', 'indexing'].includes(e.dataset.envState)) return;
  const tick = async () => {
    let d = null;
    try { d = await (await fetch('/learn/tool?key=' + encodeURIComponent(e.dataset.envKey), {cache: 'no-store'})).json(); } catch (_) {}
    const next = leeEnvNext(e.dataset.envState, d);
    if (next === 'reload') { location.reload(); return; }
    if (next === 'say' && typeof d.say === 'string') e.textContent = d.say;
    setTimeout(tick, every);
  };
  setTimeout(tick, every);
}
function leePaneBoot() {
  if (document.documentElement.classList.contains('lee-learn-page')) { leeLearnMath(); document.addEventListener('click', leePaneLink); document.addEventListener('auxclick', leePaneLink); document.addEventListener('keydown', leeLearnKey); leeEnvWatch(); }
  if (document.documentElement.classList.contains('in-pane')) { leePaneAt(); document.addEventListener('keydown', leePaneKey); return; }
  if (typeof lee === 'undefined') return;   // a learn page in a tab of its own: no split editor to host a pane
  window.leeSidePage = {open: leeSidePageOpen, close: leeSidePageClose};
  window.addEventListener('message', e => leePaneMessage(e, lee.sidePage));
}
document.addEventListener('DOMContentLoaded', leePaneBoot);
/* The detail a status line cannot hold. Git's refusal names the files it would overwrite, and a
   toast shows one clipped sentence of it. `/dev/log` keeps what a dev server prints.

   Kept in memory for this session, because a store that outlives the question would need
   retention rules. */
const LOG_MAX = 500;
lee.logs = [];

function leeLog(source, title, detail = '', kind = '') {
  lee.logs.push({at: new Date(), source, title: String(title || ''), detail: String(detail || ''), kind});
  if (lee.logs.length > LOG_MAX) lee.logs.splice(0, lee.logs.length - LOG_MAX);
  const dock = $('#bottomdock');
  if (dock?.classList.contains('dock-logs')) renderLogs();
  else if (kind === 'err') $$('.lee-docktab').forEach(b => {
    if (b.dataset.dock === 'logs') b.classList.add('has-error');   // a failure you have not read
  });
}
window.leeLog = leeLog;

function renderLogs() {
  const el = $('#loglist'); if (!el) return;
  const want = lee.logFilter || '';
  if (want === 'history') {
    const rows = lee.gitHistory || [];
    el.innerHTML = rows.length ? rows.map(c =>
      `<article class="lee-logrow"><div class="lee-loghead"><time>${new Date(c.timestamp * 1000).toLocaleString()}</time>` +
      `<span class="lee-logsource">git</span><strong>${esc(c.short)} ${esc(c.subject)}</strong></div>` +
      `<pre class="lee-logdetail">${esc(c.author)}${c.decoration ? '\n' + c.decoration : ''}</pre></article>`).join('')
      : `<div class="lee-dim lee-logempty">no Git history for this repository</div>`;
  } else {
    const rows = lee.logs.filter(r => !want || r.source === want);
    el.innerHTML = rows.length ? rows.map(r =>
      `<article class="lee-logrow${r.kind ? ' ' + r.kind : ''}">` +
      `<div class="lee-loghead"><time>${r.at.toTimeString().slice(0, 8)}</time>` +
      `<span class="lee-logsource">${esc(r.source)}</span><strong>${esc(r.title)}</strong></div>` +
      (r.detail ? `<pre class="lee-logdetail">${esc(r.detail)}</pre>` : '') + `</article>`).join('')
      : `<div class="lee-dim lee-logempty">nothing logged${want ? ' for ' + esc(want) : ''} yet</div>`;
  }
  el.scrollTop = el.scrollHeight;
}

/* "See logs" has to end with you seeing the log. Sending the reader off to find it, through a dock
   showing something else and a filter they set an hour ago, loses the thing worth keeping. A
   failure opens the log it just wrote, on a filter that can show it. */
function showLog(source = '') {
  if (lee.logFilter && lee.logFilter !== source) leeLogFilter('');
  leeDock('logs');
}
// The first line of git's refusal is usually the whole story ("would be overwritten by
// checkout"), and the files it names are the part that needs the pane.
function firstLine(text, max = 96) {
  const line = String(text || '').replace(/^\w*Error:\s*/, '').split('\n').find(x => x.trim()) || '';
  return line.length > max ? line.slice(0, max - 1) + '…' : line;
}

/* Said only in the status line, the detail is gone, because the toast clips to a sentence and times
   out. The whole message goes to the log. The error carries that it has been reported, so an outer
   catch around `gitDo` can call this without saying it twice. */
function leeFail(source, what, e) {
  if (e && e.reported) return;
  if (e) e.reported = true;
  const detail = (e && e.message) || String(e || '');
  leeLog(source, `${what} failed`, detail, 'err');
  showLog(source);
  status(`${source} ${what} failed: ${firstLine(detail)}`, 'err');
}
window.leeFail = leeFail;

async function leeLogFilter(which) {
  lee.logFilter = which || '';
  $$('.lee-logfilter').forEach(b => b.classList.toggle('active', (b.dataset.logFilter || '') === lee.logFilter));
  if (lee.logFilter === 'history') {
    try { lee.gitHistory = (await api('/git/history?limit=100&repo=' + encodeURIComponent(gitUI.repo || ''))).commits || []; }
    catch (e) { lee.gitHistory = []; return leeFail('git', 'history', e); }
  }
  renderLogs();
}
function leeLogClear() { lee.logs = []; renderLogs(); }
async function leeLogCopy() {
  const want = lee.logFilter || '';
  const text = lee.logs.filter(r => !want || r.source === want)
    .map(r => `${r.at.toTimeString().slice(0, 8)} ${r.source} ${r.title}` + (r.detail ? '\n' + r.detail : '')).join('\n');
  try { await navigator.clipboard.writeText(text); status('log copied', 'ok'); }
  catch (e) { status('could not copy the log', 'err'); }
}
window.leeLogFilter = leeLogFilter; window.leeLogClear = leeLogClear; window.leeLogCopy = leeLogCopy;

/* Managed runs keep their output after exit. Polling creates the activity record whether or not
   Logs is visible, and a failed run opens the useful filter automatically. */
lee.runSeen = new Map(); lee.runFinished = new Set();
lee.runs = [];

/* What is running, next to the kernel it is not. A dev server is a process leela started and can
   end, and the only evidence one existed was output arriving, which is what a broken one does not
   do. */
/* A run is up while its process is: the inspector outlives the command, and keeps its ports. */
const runUp = s => s.running !== false || !!s.alive;
function paintRunsPill() {
  const pill = $('#runspill'); if (!pill) return;
  const runs = lee.runs || [];
  const live = runs.filter(runUp);
  const dead = runs.filter(s => !runUp(s) && s.code);
  pill.className = 'lee-pill ' + (dead.length ? 'lee-pill-err' : live.length ? 'lee-pill-on' : 'lee-pill-off');
  pill.textContent = live.length === 1 ? '▶ ' + (live[0].label || 'run')
    : live.length ? `▶ ${live.length} runs`
    : dead.length ? `⚠ ${dead.length} stopped` : '○ runs';
  pill.title = runs.length ? runs.map(s => `${s.label}: ${runState(s)}`).join('\n')
                           : 'nothing is running. Click to start a script';
}
function runState(s) {
  if (s.running === false) return (s.code ? `exited ${s.code}` : 'finished') + (s.alive ? ' · still up' + (s.pid ? ' · pid ' + s.pid : '') : '');
  return 'running' + (s.app_url ? ' · ' + s.app_url : s.pid ? ' · pid ' + s.pid : '');
}
async function leeRunsMenu(anchor) {
  await pollRunLogs();
  const runs = lee.runs || [];
  const rows = runs.map(s => ({
    label: (runUp(s) ? '▶ ' : '⚠ ') + (s.label || s.path),
    detail: runState(s), run: () => leeRunTerm(s.script || s.path, s.label, s.pid),
  }));
  // Where each running app is listening, as rows: a port is the thing you want back after a reload.
  const urls = runs.filter(runUp).flatMap(s => (s.urls || []).map(url => ({url, s})));
  if (urls.length) rows.push({separator: true});
  for (const {url, s} of urls) rows.push({label: 'open ' + url, detail: s.label || s.path, run: () => openExternal(url)});
  if (rows.length) rows.push({separator: true});
  for (const s of runs.filter(runUp)) rows.push({
    label: 'stop ' + (s.label || s.path), warn: true,
    run: async () => {
      try { await post('/dev/stop?path=' + encodeURIComponent(s.script || s.path)); }
      catch (e) { return status(String(e.message || e), 'err'); }
      status(`${s.label} stopped`, 'ok'); pollRunLogs();
    },
  });
  rows.push({label: rows.length ? 'run another script…' : 'run a script…', run: () => runApp()});
  openChromeMenu(anchor, rows);
}
window.leeRunsMenu = leeRunsMenu;

/* A reload closes the page, not the servers. The first poll after one puts each running server
   back on a terminal, so what is running is on screen rather than only in a pill's tooltip. */
function adoptRuns(servers) {
  if (lee.runsAdopted) return;
  lee.runsAdopted = true;
  const up = servers.filter(s => runUp(s) && s.pid && !lee.terms.has('run:' + (s.script || s.path)));
  for (const s of up) leeRunTerm(s.script || s.path, s.label, s.pid, true).catch(() => {});
  if (up.length) status(`${up.length === 1 ? up[0].label || 'a run' : up.length + ' runs'} still running. See the runs pill.`);
}

async function pollRunLogs() {
  let servers = [];
  try { servers = (await api('/dev/list')).servers || []; } catch (_) { lee.runs = []; paintRunsPill(); return false; }
  lee.runs = servers.map(s => ({...s, path: s.path || s.script || ''}));
  paintRunsPill(); adoptRuns(servers);
  for (const srv of servers) {
    const path = srv.path || srv.script || '';
    if (!path) continue;
    let lines = [];
    try { lines = (await api('/dev/log?n=200&path=' + encodeURIComponent(path))).log || []; }
    catch (_) { continue; }
    const seen = lee.runSeen.get(path) || 0;
    if (lines.length < seen) { lee.runSeen.set(path, 0); lee.runFinished.delete(path); }
    const fresh = lines.slice(lee.runSeen.get(path) || 0);
    lee.runSeen.set(path, lines.length);
    if (fresh.length) leeLog('runs', srv.label || path.split('/').pop(), fresh.join('\n'));
    // `running`, not `alive`: the child keeps the inspector up after the command returns, so
    // liveness of the inspector says nothing about whether the command is still going.
    const code = srv.code !== undefined && srv.code !== null ? srv.code : srv.returncode;
    if (!srv.running && code !== null && code !== undefined && !lee.runFinished.has(path)) {
      lee.runFinished.add(path);
      const failed = code !== 0;
      leeLog('runs', `${srv.label || path.split('/').pop()} ${failed ? 'failed' : 'finished'} · exit ${code}`, '', failed ? 'err' : 'ok');
      if (failed) { leeLogFilter('runs'); leeDock('logs'); status(`${srv.label || path.split('/').pop()} failed with exit code ${code}`, 'err'); }
    }
  }
  return servers.length;
}

// A dev server's output has to arrive promptly. An empty list has nothing to say for 15s.
async function runLogLoop() {
  const busy = await pollRunLogs();
  setTimeout(runLogLoop, busy ? 2000 : 15000);
}

function leeDock(which) {
  const dock = $('#bottomdock'); if (!dock) return;
  try { localStorage.setItem('lee-dock-view', which); } catch (_) {}
  leePane('bottom', true);
  const centre = $('.lee-centre');
  dock.classList.toggle('dock-exec', which === 'exec');
  dock.classList.toggle('dock-term', which === 'term');
  dock.classList.toggle('dock-logs', which === 'logs');
  if (which === 'logs') {
    $$('.lee-docktab').forEach(b => { if (b.dataset.dock === 'logs') b.classList.remove('has-error'); });
    renderLogs();
  }
  $$('.lee-docktab', dock).forEach(b => {
    const active = b.dataset.dock === which; b.classList.toggle('active', active);
    b.setAttribute('aria-selected', String(active));
  });
  if (which === 'term') requestAnimationFrame(() => lee.term?.refit());
}
window.leeDock = leeDock;
function switchTerm(id) {
  const t = lee.terms.get(id); if (!t) return;
  leeDock('term'); lee.activeTerm = id; lee.term = t.view;
  $$('.lee-term-session').forEach(x => x.hidden = x.dataset.term !== id);
  paintTermTabs(); $('#shell').classList.add('show-term'); setScope('term');
  requestAnimationFrame(() => { t.view.refit(); t.view.focus(); });
}
function cycleTerm(d) {
  const ids = [...lee.terms.keys()]; if (!ids.length) return;
  const at = Math.max(0, ids.indexOf(lee.activeTerm));
  switchTerm(ids[(at + d + ids.length) % ids.length]);
}
async function openTerm(kind = 'shell', forceNew = false) {
  await loadTermBundle();
  const d = await api('/term/info');
  if (!d.enabled) return status(d.why, 'err');
  if (kind === 'git' && !d.lazygit) return status(d.lazygit_why, 'err');
  const external = $('#termexternal');
  if (external) external.hidden = !(d.external || []).length;
  const live = (d.open || []).filter(t => t.alive).map(t => t.id).filter(Boolean);
  // A shell is one process in one directory and cannot follow the project by itself, so there is
  // one per checkout, the way there is one kernel per project. Switching to a file in another repo
  // reaches that repo's shell; the one you were using stays exactly where you left it.
  const here = t => kind !== 'shell' || (t.project || '') === (d.project || '');
  if (!forceNew) {
    const existing = [...lee.terms.entries()].find(([, t]) => t.kind === kind && here(t));
    if (existing) return switchTerm(existing[0]);
    // A session this page has never seen, still running from before a reload. Reattaching is the
    // point of letting a pty outlive its socket, and it has to be visible to be closable, or its
    // process is orphaned where nobody can stop it.
    const orphan = (d.open || []).filter(t => t.alive && t.id && !lee.terms.has(t.id))
      .find(t => (kind === 'git' ? t.id === 'git' : String(t.id).startsWith('term-')) && here(t));
    if (orphan) return adoptTerm(orphan.id, kind, d, orphan.project);
  }
  const id = nextTermId(kind, live);
  if (lee.terms.has(id)) return switchTerm(id);
  $('#shell').classList.add('show-term');
  const parent = $('#terms'); if (!parent) return status('no terminal pane', 'err');
  const host = document.createElement('div'); host.className = 'lee-term lee-term-session';
  host.dataset.term = id; parent.appendChild(host);
  const record = {id, kind, label: termLabel(kind, id, kind === 'shell' ? d.project : ''),
                  cwd: d.cwd, project: d.project || '', host, view: null};
  record.view = LeeTerm.create(host, {
    token: d.token, cwd: d.cwd, kind, id,
    onStatus: m => status(`${record.label}: ${m}`),
    onExit: () => { record.exited = true; paintTermTabs(); status(`${record.label} exited`); },
  });
  lee.terms.set(id, record); switchTerm(id);
}
// The pipeline's pty is opened by the pipeline, not by whoever attaches, so this terminal talks to
// `/release/ws` instead of `/term/ws`. Everything else is the same component the shell uses. `cwd`
// carries the project root, the only thing that socket needs to know which pipeline is watched.
async function openReleaseTerm(root = '', kind = 'release') {
  await loadTermBundle();
  const d = await api('/term/info');
  if (!d.enabled) return status(d.why, 'err');
  /* Keyed by the root as well as the kind. The server already keeps one pipeline per package,
     but a single `release` record held the socket opened with whichever package came first, so
     moving to another package re-showed that one and closing it was the only way through. */
  const at = String(root || '').replace(/\/+$/, '');
  const id = at ? `${kind}:${at}` : kind, prior = lee.terms.get(id);
  if (prior && !prior.exited) return switchTerm(id);
  if (prior) { prior.view.dispose(); prior.host.remove(); lee.terms.delete(id); }
  $('#shell').classList.add('show-term');
  const parent = $('#terms'); if (!parent) return status('no terminal pane', 'err');
  const host = document.createElement('div'); host.className = 'lee-term lee-term-session';
  host.dataset.term = id; parent.appendChild(host);
  const label = termLabel(kind, id, at);
  const record = {id, kind, label, cwd: at || d.cwd, host, view: null};
  record.view = LeeTerm.create(host, {
    token: d.token, cwd: at || d.cwd, kind, id,
    url: kind === 'drive' ? '/drive/ws' : '/pipeline/ws',
    onStatus: m => status(`${label}: ${m}`),
    onExit: () => { record.exited = true; paintTermTabs(); },
  });
  lee.terms.set(id, record); switchTerm(id);
}
/* A run's own terminal. The Logs pane answers what happened, this answers what it is doing, which
   for a dev server is colour, progress, a traceback as it arrives, and a keyboard so ctrl-c reaches
   the app. Same component as the shell, pointed at `/run/ws`, which hands back the pty the run is
   already on rather than starting anything. */
async function leeRunTerm(path, label = '', pid = null, quiet = false) {
  if (!path) return;
  await loadTermBundle();
  const d = await api('/term/info');
  if (!d.enabled) return status(d.why, 'err');
  const id = 'run:' + path, prior = lee.terms.get(id);
  // Same path, another process: the view was attached to the run that ended, so Stop then Run
  // kept showing the first run's output. A new pid gets a new view.
  if (prior && !prior.exited && (!pid || prior.pid === pid)) return quiet ? undefined : switchTerm(id);
  if (prior) { prior.view.dispose(); prior.host.remove(); lee.terms.delete(id); }
  const parent = $('#terms'); if (!parent) return status('no terminal pane', 'err');
  // `quiet` is a reload adopting a run that is still up: the tab appears, hidden, and nothing
  // else moves. `switchTerm` refits it when it is chosen.
  const host = document.createElement('div'); host.className = 'lee-term lee-term-session';
  host.dataset.term = id; host.hidden = quiet; parent.appendChild(host);
  const name = label || path.split('/').pop();
  const record = {id, kind: 'run', label: name, cwd: path, pid, host, view: null};
  record.view = LeeTerm.create(host, {
    token: d.token, cwd: path, kind: 'run', id, url: '/run/ws',
    onStatus: m => status(`${name}: ${m}`),
    onExit: () => { record.exited = true; paintTermTabs(); },
  });
  lee.terms.set(id, record);
  if (quiet) { paintTermTabs(); return; }
  $('#shell').classList.add('show-term');
  switchTerm(id);
}
window.leeRunTerm = leeRunTerm;

// Reconnect to a pty that is already running rather than starting one. Same component and the same
// id, so the server hands back the session it still has, which makes the process inside it visible
// in a tab and therefore closable.
function adoptTerm(id, kind, d, project = '') {
  $('#shell').classList.add('show-term');
  const parent = $('#terms'); if (!parent) return status('no terminal pane', 'err');
  const host = document.createElement('div'); host.className = 'lee-term lee-term-session';
  host.dataset.term = id; parent.appendChild(host);
  const record = {id, kind, label: termLabel(kind, id, kind === 'shell' ? project : ''),
                  cwd: d.cwd, project: project || '', host, view: null};
  record.view = LeeTerm.create(host, {
    token: d.token, cwd: d.cwd, kind, id,
    onStatus: m => status(`${record.label}: ${m}`),
    onExit: () => { record.exited = true; paintTermTabs(); status(`${record.label} exited`); },
  });
  lee.terms.set(id, record); switchTerm(id);
  status(`${record.label} was still running. Leela connected to it again`);
}

// xterm.js cannot attach to a terminal application that is already running, because that program
// is itself an emulator with its own pty. What it can do is hand the project over. The button stays
// hidden unless the server found a terminal to hand it to.
async function leeExternalTerm() {
  try {
    const d = await post('/term/external');
    status(`opened ${(d.argv || []).includes('-a') ? d.argv[d.argv.indexOf('-a') + 1] : (d.argv || [])[0] || 'terminal'}`, 'ok');
  } catch (e) { status(e.message || String(e), 'err'); }
}
window.leeExternalTerm = leeExternalTerm;

function leeNewTerm() { return openTerm('shell', true); }
window.leeNewTerm = leeNewTerm;

// The IDE follows the system's light and dark setting through a media query. The terminal reads its
// colours from CSS once, when it is created, so it has to be told.
try {
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
    for (const t of lee.terms.values()) t.view.retheme();
  });
} catch (e) {}

function leeTermExpand() {
  leeDock('term'); leeExpandPane('bottom');
  requestAnimationFrame(() => { lee.term?.refit(); lee.term?.focus(); });
}
window.leeTermExpand = leeTermExpand;

function closeTerm(id = lee.activeTerm) {
  const t = lee.terms.get(id); if (!t) return;
  t.view.dispose(); t.host.remove(); lee.terms.delete(id); post('/term/close?id=' + encodeURIComponent(id));
  const next = [...lee.terms.keys()].at(-1);
  lee.term = null; lee.activeTerm = '';
  if (next) switchTerm(next);
  else {
    paintTermTabs(); $('#shell').classList.remove('show-term'); leeDock('exec');
    leeExpand(''); setScope('editor');
  }
  // A shell or lazygit may have changed the working tree under us.
  refreshFileTree(undefined, false).catch(e => status(String(e.message || e), 'err'));
}

/* Themes are families with a dark and a light variant: `data-theme` is the family,
   `data-mode` the resolved variant. Each entry's swatch colours are [bg, bg1, accent],
   read from the same palette its CSS block declares, so the picker cannot drift from it. */
const THEMES = {
  leela: {blurb: 'the house palette', dark: ['#0d1117', '#161b22', '#58a6ff'], light: ['#ffffff', '#f6f8fa', '#0969da']},
  cursor: {blurb: 'thin quiet chrome', dark: ['#141414', '#1a1a1a', '#6a9fff'], light: ['#fbfbfb', '#f4f4f4', '#171717']},
  vscode: {blurb: 'Dark+ / Light+', dark: ['#1e1e1e', '#252526', '#3794ff'], light: ['#ffffff', '#f3f3f3', '#005fb8']},
  jetbrains: {blurb: 'Darcula / IntelliJ', dark: ['#2b2b2b', '#313335', '#589df6'], light: ['#ffffff', '#f7f8fa', '#2470b3']},
  solarized: {blurb: 'Ethan Schoonover', dark: ['#002b36', '#073642', '#268bd2'], light: ['#fdf6e3', '#f5eeda', '#268bd2']},
  gruvbox: {blurb: 'warm retro groove', dark: ['#282828', '#32302f', '#83a598'], light: ['#fbf1c7', '#f2e5bc', '#076678']},
  nord: {blurb: 'arctic bluish', dark: ['#2e3440', '#333b48', '#88c0d0'], light: ['#eceff4', '#e5e9f0', '#5e81ac']},
  dracula: {blurb: 'the famous fangs', dark: ['#282a36', '#21222c', '#bd93f9'], light: ['#faf9f2', '#f2f1e8', '#7b48c8']},
  github: {blurb: 'Primer, as on github.com', dark: ['#0d1117', '#161b22', '#4493f8'], light: ['#ffffff', '#f6f8fa', '#0969da']},
  ember: {blurb: 'warm and dim, for late nights', dark: ['#221d18', '#29231d', '#d0a76c'], light: ['#efe6d6', '#e8dece', '#87582a']},
  dusk: {blurb: 'soft slate, low glare', dark: ['#252a33', '#2b313b', '#8eaacb'], light: ['#e6eaf0', '#dde2e9', '#3b628c']},
};
const THEME_MODES = ['system', 'dark', 'light'];
// Density is its own axis, so the tight chrome can be had with another family's colours.
const THEME_DENSITIES = ['tight', 'relaxed'];
const THEME_DEFAULT = 'cursor:light:tight';
// What `lee-theme` held before families existed. Dropping these would silently reset everyone.
const THEME_LEGACY = {system: 'leela:system:relaxed', dark: 'leela:dark:relaxed',
                      light: 'leela:light:relaxed', cursor: 'cursor:light:tight'};
const darkQuery = () => matchMedia('(prefers-color-scheme: dark)');

function parseTheme(theme) {
  "A stored value, a `family:mode:density` string or a {family, mode, density} object, validated."
  if (theme && typeof theme === 'object') theme = `${theme.family}:${theme.mode}:${theme.density}`;
  const [family, mode, density] = String(theme || '').includes(':') ? String(theme).split(':')
    : (THEME_LEGACY[theme] || THEME_DEFAULT).split(':');
  return {family: family in THEMES ? family : 'cursor',
          mode: THEME_MODES.includes(mode) ? mode : 'light',
          // A two-field value predates the split, when density was whatever the family implied.
          density: THEME_DENSITIES.includes(density) ? density : family === 'cursor' ? 'tight' : 'relaxed'};
}
const themeText = theme => {const {family, mode, density} = parseTheme(theme); return `${family}:${mode}:${density}`;};
async function saveTheme(theme, scope = 'user') {
  "Write the theme to settings.json. Never under `languages.<lang>`: a theme is not per language."
  const value = themeText(theme);
  await post('/settings/save', {scope, language: '', section: 'appearance', values: {theme: value}});
  lee.appearancePrefs = {...lee.appearancePrefs, theme: value};
}
/* `localStorage` is per origin and Leela's port moves whenever 5001 is taken, so a theme kept only
   there is gone on the next launch. settings.json is the theme; `lee-theme` is the first-paint
   cache the boot script in `app.py` reads, and the store one already-set theme is migrated from. */
function readTheme() {
  const durable = lee.appearancePrefs?.theme ?? lee.workbenchPrefs?.theme,
        cached = localStorage.getItem('lee-theme');
  if (!durable && cached && cached !== THEME_DEFAULT) saveTheme(cached).catch(() => {});
  return parseTheme(durable || cached);
}
const themeMode = mode => mode === 'system' ? (darkQuery().matches ? 'dark' : 'light') : mode;

function paintTheme() {
  "Write the family, the resolved mode and the density onto <html>, and retheme what CSS cannot reach."
  const {family, mode, density} = lee.theme, resolved = themeMode(mode), root = document.documentElement;
  root.dataset.theme = family; root.dataset.mode = resolved; root.dataset.density = density;
  // color-scheme only accepts dark/light; a family name here is ignored and native controls stay wrong.
  root.style.colorScheme = resolved;
  const pill = $('#themepill'); if (pill) pill.textContent = mode === 'system' ? `${family} · auto` : `${family} · ${mode}`;
  for (const t of lee.terms.values()) t.view.retheme();
  nativeBackground(getComputedStyle(root).getPropertyValue('--lee-bg').trim());
}
/* The desktop window's own background shows while it opens and while it grows faster than the page
   redraws. pywebview injects its bridge after load, so the first paint waits for `pywebviewready`. */
function nativeBackground(colour) {
  const send = () => window.pywebview?.api?.set_background?.(colour)?.catch?.(() => {});
  if (window.pywebview?.api?.set_background) return send();
  window.removeEventListener('pywebviewready', lee.nativeBackgroundWait);
  window.addEventListener('pywebviewready', lee.nativeBackgroundWait = send, {once: true});
}
function applyTheme(theme) {
  lee.theme = parseTheme(theme);
  const {family, mode, density} = lee.theme;
  localStorage.setItem('lee-theme', `${family}:${mode}:${density}`);   // the cache, not the record
  paintTheme();
}
// Following the system means following it now, not at the next reload.
darkQuery().addEventListener('change', () => { if (lee.theme?.mode === 'system') paintTheme(); });
async function editorSettings(languageScope = null) {
  if(typeof languageScope!=='string'){
    // Default to All languages, never to the focused tab's language. Saving remembers the scope,
    // so one derived from `curLang()` would send every later edit into `languages.<lang>`. A
    // language scope is only ever chosen explicitly.
    const remembered=localStorage.getItem('lee-settings-language-scope');
    languageScope=remembered!==null?remembered:'';
  }
  const rememberedScope=localStorage.getItem('lee-settings-save-scope')||'user';
  await loadSettings(languageScope);
  const original = {...lee.editorPrefs}, originalFiles = {...lee.filePrefs},
        originalWorkbench = {...lee.workbenchPrefs}, originalDebug = {...lee.debugPrefs},
        originalTheme = lee.theme || readTheme();
  let saved = false, previewView = null;
  const selected = (value, current) => value === current ? ' selected' : '';
  const prefsOf = section => section === 'editor' ? lee.editorPrefs : section === 'files' ? lee.filePrefs :
    section === 'workbench' ? lee.workbenchPrefs : section === 'backups' ? (lee.backupPrefs || {}) :
    section === 'agent' ? (lee.agentPrefs || {}) : lee.debugPrefs;
  const checked = (section, key) => prefsOf(section)[key] ? ' checked' : '';
  const fontSelect = CODE_FONTS.map(([name, detail]) =>
    `<option value="${esc(name)}"${selected(name, lee.editorPrefs.fontFamily)}>${esc(name)} · ${esc(detail)}</option>`).join('');
  const field = (section, key, label, input, help='') => `<label>${label}${input.replace('data-setting', `data-pref-section="${section}" data-pref="${key}"`)}${help ? `<small>${help}</small>` : ''}</label>`;
  const check = (section, key, label, help='') => `<label class="lee-settings-toggle"><input type="checkbox" data-pref-section="${section}" data-pref="${key}"${checked(section,key)}><span>${label}${help ? `<small>${help}</small>` : ''}</span></label>`;
  const select = (section, key, label, values, help='') => field(section,key,label,
    `<select class="lee-select" data-setting>${values.map(([value,text]) => `<option value="${value}"${selected(value,prefsOf(section)[key])}>${text}</option>`).join('')}</select>`,help);
  const swatch = (family, mode) => {
    const [bg, bg1, accent] = THEMES[family][themeMode(mode)];
    return `background: linear-gradient(135deg, ${bg} 0 42%, ${bg1} 42% 62%, ${accent} 62%)`;
  };
  const themeButtons = mode => Object.entries(THEMES).map(([family, {blurb}]) =>
    `<button class="lee-theme-choice${family === originalTheme.family ? ' active' : ''}" data-theme="${family}" aria-pressed="${family === originalTheme.family}">` +
    `<span class="lee-theme-swatch" style="${swatch(family, mode)}"></span><strong>${family}</strong><span>${esc(blurb)}</span></button>`).join('');
  const modeButtons = mode => THEME_MODES.map(m =>
    `<button class="lee-theme-mode${m === mode ? ' active' : ''}" data-theme-mode="${m}" aria-pressed="${m === mode}">${m === 'system' ? 'follow system' : m}</button>`).join('');
  const densityButtons = density => THEME_DENSITIES.map(d =>
    `<button class="lee-theme-mode${d === density ? ' active' : ''}" data-theme-density="${d}" aria-pressed="${d === density}">${d}</button>`).join('');
  const m = modal(`<div class="lee-mhead">settings<span class="sub">user · workspace · language-aware</span></div>` +
    `<div class="lee-settings-scope"><label>Save to <select class="lee-select" data-settings-scope><option value="user"${selected('user',rememberedScope)}>User</option><option value="workspace"${selected('workspace',rememberedScope)}>Workspace</option></select></label>` +
    `<label>Apply to <select class="lee-select" data-settings-language><option value=""${selected('',languageScope)}>All languages</option><option value="python"${selected('python',languageScope)}>Python</option><option value="markdown"${selected('markdown',languageScope)}>Markdown</option></select></label>` +
    `<span data-settings-target></span><span data-settings-path>${esc(lee.settingsMeta?.paths?.user || '')}</span></div>` +
    `<div class="lee-settings-shadow" data-settings-shadow hidden></div>` +
    (lee.settingsMeta?.ignored?.length ? `<div class="lee-settings-shadow" data-settings-ignored>This project's settings file sets ${esc(lee.settingsMeta.ignored.join(', '))}. Leela ignores these values: only your user settings choose the shell and the agent's folder.</div>` : '') +
    `<div class="lee-settings-layout"><nav class="lee-settings-nav" aria-label="Settings sections">` +
    `<button class="active" data-settings-page="editor">Text editor</button><button data-settings-page="appearance">Appearance</button>` +
    `<button data-settings-page="files">Files & save</button><button data-settings-page="debug">Run & debug</button>` +
    `<button data-settings-page="agent">Agent</button>` +
    `<button data-settings-page="environment">Environment</button>` +
    `<button data-settings-page="backups">Backups</button>` +
    `<button data-settings-page="keys">Keybindings</button></nav><div class="lee-settings-content">` +
    `<section data-settings-section="editor"><div class="lee-settings-title"><span>Text editor</span><kbd>${esc(displayChord(lee.keys.find(k=>k.action==='settings')?.key||'mod+,'))}</kbd></div>` +
    `<p>Editing behavior updates live. Portable values are saved as JSON, not trapped in this browser.</p>` +
    `<div class="lee-settings-group"><h4>Typography</h4><div class="lee-settings-grid">` +
    `<label class="wide">Code font<select class="lee-select" data-pref-section="editor" data-pref="fontFamily">${fontSelect}</select><small>JetBrains Mono and Fira Code are bundled for reliable offline rendering.</small></label>` +
    field('editor','fontSize','Size',`<input class="lee-input" data-setting type="number" min="9" max="28" value="${lee.editorPrefs.fontSize}">`) +
    field('editor','lineHeight','Line height',`<input class="lee-input" data-setting type="number" min="1" max="2.4" step="0.1" value="${lee.editorPrefs.lineHeight}">`) +
    field('editor','tabSize','Tab size',`<input class="lee-input" data-setting type="number" min="1" max="8" value="${lee.editorPrefs.tabSize}">`) + `</div>` +
    `<div class="lee-ligature-proof"><span>Ligature proof</span><code>!=  ->  =>  <=  >=  ===  ::</code></div></div>` +
    `<div class="lee-settings-group"><h4>Wrapping and line length</h4><div class="lee-settings-grid lee-settings-line-grid">` +
    select('editor','wordWrap','Word wrap',[['off','Off'],['viewport','At viewport'],['column','At preferred column']]) +
    field('editor','lineLength','Preferred column',`<input class="lee-input" data-setting type="number" min="40" max="240" value="${lee.editorPrefs.lineLength}">`) +
    `<label class="wide">Additional guides<input class="lee-input" data-pref-section="editor" data-pref="guideColumns" value="${esc(lee.editorPrefs.guideColumns)}" placeholder="88, 120"><small>Comma-separated; preferred column remains the primary guide.</small></label></div></div>` +
    `<div class="lee-settings-checks">${check('editor','visualGuides','Visual column guides')}${check('editor','ligatures','Programming ligatures','Visible with the proof row above.')}` +
    `${check('editor','useTabs','Indent with tabs')}${check('editor','detectIndentation','Detect existing indentation')}${check('editor','activeLine','Highlight active line')}` +
    `${check('editor','bracketMatching','Match brackets')}${check('editor','closeBrackets','Auto-close brackets and quotes')}${check('editor','folding','Code folding')}` +
    `${check('editor','stickyNavigation','Sticky Python symbol')}${check('editor','scrollPastEnd','Scroll past end')}${check('editor','smoothScrolling','Smooth scrolling')}</div>` +
    `<div class="lee-settings-preview" id="settingspreview"></div><div class="lee-setting-row"><span><strong>Python language service</strong><small>Pyright diagnostics and code intelligence</small></span><span class="lee-setting-state" data-lsp-state>checking…</span></div></section>` +
    `<section data-settings-section="appearance" hidden><h3>Appearance</h3><p>Reduce navigation friction without crowding the editor.</p>` +
    `<div class="lee-theme-modes" role="group" aria-label="Theme variant">Variant ${modeButtons(originalTheme.mode)}` +
    `<span class="lee-spacer"></span>Layout ${densityButtons(originalTheme.density)}<small>tight thins the chrome; it is independent of the palette</small></div>` +
    `<div class="lee-theme-options" role="group" aria-label="Theme family">${themeButtons(originalTheme.mode)}</div>` +
    `<div class="lee-settings-group"><h4>Editor chrome</h4><div class="lee-settings-grid">` +
    select('editor','lineNumbers','Line numbers',[['off','Off'],['absolute','Absolute'],['relative','Relative'],['hybrid','Hybrid']]) +
    select('editor','renderWhitespace','Whitespace',[['none','None'],['selection','Selection'],['trailing','Trailing'],['all','All']]) +
    select('editor','cursorStyle','Caret',[['line','Line'],['block','Block'],['underline','Underline']]) +
    select('editor','cursorBlinking','Blinking',[['off','Off'],['blink','Blink'],['smooth','Smooth']]) +
    select('editor','overviewMode','Overview stripe',[['off','Off'],['long','Long files only'],['always','Always']], 'The scrollbar, marked up: a tick for each problem and a bar for each uncommitted line. Long-file mode keeps it out of notebook cells.') +
    field('editor','overviewThreshold','Long file threshold',`<input class="lee-input" data-setting type="number" min="20" max="5000" value="${lee.editorPrefs.overviewThreshold}">`) + `</div>` +
    `<div class="lee-settings-checks">${check('editor','indentGuides','Indent guides')}${check('editor','methodSeparators','Function separators')}${check('editor','bracketColors','Bracket-pair colors')}${check('editor','highlightSelection','Highlight selected occurrences')}</div></div>` +
    `<div class="lee-settings-group"><h4>Navigation</h4><div class="lee-settings-grid">` +
    select('workbench','breadcrumbs','Breadcrumbs',[['off','Off'],['path','File path'],['symbols','Symbols'],['pathAndSymbols','Path and symbols']]) +
    `</div><div class="lee-settings-checks">${check('editor','inlayHints','Inferred type and parameter hints from Pyright')}${check('workbench','dependencyHints','Dependency version hints')}</div></div></section>` +
    `<section data-settings-section="files" hidden><h3>Files & save</h3><p>Recovery is always enabled; choose when durable disk writes happen.</p><div class="lee-settings-group"><div class="lee-settings-grid">` +
    select('files','autoSave','Auto save',[['off','Off'],['afterDelay','After delay'],['onFocusChange','On editor focus change'],['onWindowChange','On window focus change']]) +
    field('files','autoSaveDelay','Delay (ms)',`<input class="lee-input" data-setting type="number" min="100" max="60000" value="${lee.filePrefs.autoSaveDelay||900}">`) + `</div>` +
    `<div class="lee-settings-checks">${check('files','trimTrailingWhitespace','Trim trailing whitespace')}${check('files','trimFinalNewlines','Remove final blank lines')}${check('files','insertFinalNewline','Ensure final newline')}${check('files','formatOnSave','Format on save')}${check('files','confirmDelete','Confirm destructive deletes')}</div></div>` +
    `<div class="lee-settings-group"><h4>Opening folders</h4><div class="lee-settings-grid">` +
    `<label class="wide">Where the folder picker starts<input class="lee-input" data-pref-section="workbench" data-pref="projectFolder" value="${esc(lee.workbenchPrefs.projectFolder||'')}" placeholder="~/code"><small>Empty falls back to ~/code, then your home folder.</small></label></div></div>` +
    `<div class="lee-setting-row"><span><strong>Crash recovery</strong><small>Unsaved drafts stay in IndexedDB and external writes require review.</small></span><span class="lee-setting-state">always on</span></div></section>` +
    `<section data-settings-section="debug" hidden><h3>Run & debug</h3><p>Defaults for notebook DAP and direct debugpy sessions.</p><div class="lee-settings-checks">` +
    `${check('debug','justMyCode','Just my code')}${check('debug','stopOnEntry','Stop on entry')}${check('debug','subProcess','Debug subprocesses')}${check('debug','showInlineValues','Inline paused values')}${check('debug','breakOnRaised','Break on raised exceptions')}${check('debug','breakOnUncaught','Break on uncaught exceptions')}</div>` +
    `<div class="lee-setting-row"><span><strong>debugpy</strong><small>Python files, modules, tests, applications, and attach sessions use the selected project interpreter.</small></span><button class="lee-btn" data-open-runs>Run configurations…</button></div></section>` +
    `<section data-settings-section="agent" hidden><h3>Agent</h3>` +
    `<p>Where this agent's durable conversations live. Ramabana writes the log, the session names, ` +
    `the branches and the plans from the same code Leela drives, so one folder can serve both: ` +
    `point this at Ramabana's config dir and the conversations you had in the CLI are the ` +
    `conversations you see here.</p>` +
    `<div class="lee-settings-grid"><label class="wide">Conversation folder` +
    `<input class="lee-input" data-pref-section="agent" data-pref="configFolder" spellcheck="false" ` +
    `placeholder="${esc(lee.settingsMeta?.paths?.user?.replace(/settings\.json$/, '') || '')}" ` +
    `value="${esc(lee.agentPrefs?.configFolder || '')}">` +
    `<small>Empty means Leela's own config dir, which is where it has always been. ` +
    `Backups and the pre-write copy follow this folder. Conversations already open keep the folder ` +
    `they started in, so restart Leela after changing it.</small></label></div></section>` +
    `<section data-settings-section="backups" hidden><h3>Backups</h3>` +
    `<p>Dated copies of what cannot be rebuilt: conversations and their titles, branches, notes, ` +
    `workspaces, keymaps and settings. A copy is also taken before anything overwrites the ` +
    `conversation log, whatever the cadence says.</p>` +
    `<div class="lee-settings-group"><div class="lee-settings-grid">` +
    select('backups','cadence','Cadence',[['off','Off (pre-write copies only)'],['hourly','Hourly'],['sixhourly','Every six hours'],['daily','Daily'],['weekly','Weekly']],'How often a dated copy is taken while Leela is running.') +
    field('backups','keepNewest','Keep newest',`<input class="lee-input" data-setting type="number" min="1" max="50" value="${lee.backupPrefs?.keepNewest??5}">`) +
    `<label class="wide">Age bands (days)<input class="lee-input" data-pref-section="backups" data-pref="ageBands" value="${esc(lee.backupPrefs?.ageBands||'2,14,60')}"><small>One copy is kept inside each band, so a mistake noticed weeks later still has something to go back to.</small></label>` +
    `</div></div>` +
    `<div class="lee-settings-group"><h4>What a copy holds</h4>` +
    `<div class="lee-settings-checks" data-backup-entries>reading…</div>` +
    `<small>Anything unticked is not copied. Journals alone are tens of megabytes; the vault is a live database outside the config dir.</small></div>` +
    `<div class="lee-setting-row"><span><strong>Take one now</strong><small data-backup-dir></small></span>` +
    `<button class="lee-btn" data-backup-now>Back up now</button></div>` +
    `<div class="lee-settings-group"><h4>Restore</h4><div data-backup-list class="lee-backup-list">reading…</div></div></section>` +
    `<section data-settings-section="environment" hidden><h3>Environment</h3>` +
    `<p>What Leela exports to the models, the kernels and the terminals it starts. Leela asks your ` +
    `shell for these at startup; anything set here is used instead, which is the way out when ` +
    `asking the shell gives the wrong answer.</p>` +
    `<div class="lee-settings-group"><div data-env-list class="lee-env-list">reading…</div></div>` +
    `<div class="lee-settings-group"><h4>Add or replace</h4><div class="lee-settings-grid">` +
    `<label>Name<input class="lee-input" data-env-key placeholder="OPENAI_API_KEY" spellcheck="false"></label>` +
    `<label>Value<input class="lee-input" data-env-value type="password" autocomplete="off" spellcheck="false"></label>` +
    `</div><div class="lee-setting-row"><span data-env-note class="lee-dim"></span>` +
    `<button class="lee-btn go" data-env-save>Set variable</button></div></div></section>` +
    `<section data-settings-section="keys" hidden><h3>Keybindings</h3><p>Every command can be rebound from the same single-source keymap.</p><button class="lee-btn" data-open-keys>Edit keybindings…</button></section>` +
    `</div></div><div class="lee-mfoot"><button class="lee-btn" data-reset>Reset this section</button><span class="lee-spacer"></span><button class="lee-btn" data-cancel>Cancel</button><button class="lee-btn go" data-save>Save settings</button></div>`,
    null,()=>{if(previewView)LeeCM.destroy(previewView);if(!saved){applyEditorPrefs(original);lee.filePrefs=originalFiles;lee.workbenchPrefs=originalWorkbench;lee.debugPrefs=originalDebug;applyTheme(originalTheme);}},
    {className:'lee-settings-modal',storageKey:'settings'});
  api('/lsp/status').then(d=>{const el=$('[data-lsp-state]',m);if(el){el.textContent=d.available?(d.alive?'connected':'available'):'optional';el.title=d.note||'';}}).catch(()=>{});
  await document.fonts.ready;
  previewView=createEditor($('#settingspreview',m),{doc:'# Programming ligatures and line guides\nfrom pathlib import Path\n\ndef compare(left: int, right: int) -> bool:\n    return left != right and left <= 100  # => result\n',lang:'python',lineNums:true});
  const sections={editor:lee.editorPrefs,files:lee.filePrefs,workbench:lee.workbenchPrefs,debug:lee.debugPrefs,backups:lee.backupPrefs||{},agent:lee.agentPrefs||{}};
  const initialSections=Object.fromEntries(Object.entries(sections).map(([name,values])=>[name,{...values}]));
  const update=()=>{$$('[data-pref]',m).forEach(input=>{const target=sections[input.dataset.prefSection];target[input.dataset.pref]=input.type==='checkbox'?input.checked:input.type==='number'?Number(input.value):input.value;});
    const entries=$$('[data-backup-entry]',m); if(entries.length)sections.backups.include=entries.filter(b=>b.checked).map(b=>b.dataset.backupEntry);
    applyEditorPrefs(sections.editor);LeeCM.configure(previewView,sections.editor);};
  $$('[data-pref]',m).forEach(input=>input.addEventListener('input',update));
  let page='editor';
  $$('[data-settings-page]',m).forEach(button=>button.onclick=()=>{page=button.dataset.settingsPage;$$('[data-settings-page]',m).forEach(x=>x.classList.toggle('active',x===button));$$('[data-settings-section]',m).forEach(x=>x.hidden=x.dataset.settingsSection!==page);paintSettingsOrigins();});
  /* Which layer supplies a value is the one thing this panel could not say, and the reason
     "I saved it to user and nothing happened" is a fair thing to think: a `languages.python` block
     in the same file beats the plain section, and a workspace file beats both. The server has
     always worked this out; `describe` returns it as `origins` and nothing read it. */
  const ORIGIN_RANK = target => ({default: 0, user: 1, workspace: 2}[target] ?? (target.startsWith('workspace:') ? 4 : 3));
  // Every layer holding the key, not just the one in charge: a `languages.python` block is
  // invisible from the all-languages view, and that is exactly the case worth warning about.
  const layersOf = (section, key) => lee.settingsMeta?.layers?.[section]?.[key] || [];
  const originOf = (section, key) =>
    layersOf(section, key).slice().sort((a, b) => ORIGIN_RANK(a) - ORIGIN_RANK(b)).pop()
    || lee.settingsMeta?.origins?.[section]?.[key] || 'default';
  const savingAs = () => scope.value + (language.value ? ':' + language.value : '');
  function paintSettingsOrigins() {
    const here = ORIGIN_RANK(savingAs()), over = new Map();
    for (const input of $$('[data-pref]', m)) {
      const section = input.dataset.prefSection, origin = originOf(section, input.dataset.pref);
      const row = input.closest('label') || input.parentElement;
      $('[data-origin]', row)?.remove();
      if (origin === 'default') continue;
      const beats = ORIGIN_RANK(origin) > here;
      row.insertAdjacentHTML('beforeend',
        `<small data-origin class="lee-origin${beats ? ' beats' : ''}" title="${beats
          ? 'set in ' + esc(origin) + ', which is more specific than what you are saving to, so it wins'
          : 'the value in effect comes from ' + esc(origin)}">from ${esc(origin)}</small>`);
      if (beats && input.offsetParent !== null) over.set(origin, (over.get(origin) || 0) + 1);
    }
    const note = $('[data-settings-shadow]', m); if (!note) return;
    note.hidden = !over.size;
    if (!over.size) return;
    const [origin, n] = [...over.entries()][0];
    note.innerHTML = `<span><strong>${n} of these come from ${esc(origin)}</strong>` +
      `<small>More specific than ${esc(savingAs())}, so it wins whatever you save here. ` +
      `Saving to all languages does not clear it.</small></span>` +
      `<button class="lee-btn" data-clear-shadow="${esc(origin)}">Clear ${esc(origin)} for this section</button>`;
    $('[data-clear-shadow]', note).onclick = async () => {
      const [oscope, olang] = origin.split(':');
      const section = page === 'appearance' ? 'editor' : page;
      if (!sections[section]) return status('nothing to clear on this page', 'err');
      try {
        await post('/settings/reset', {scope: oscope, section, language: olang || ''});
        await loadSettings(language.value);
        status(`${origin} cleared for ${section}`, 'ok');
        saved = true; m.remove(); setTimeout(() => editorSettings(language.value), 0);
      } catch (e) { status(String(e.message || e), 'err'); }
    };
  }
  const scope=$('[data-settings-scope]',m),language=$('[data-settings-language]',m),path=$('[data-settings-path]',m),target=$('[data-settings-target]',m);
  const paintPath=()=>{path.textContent=shownPath(lee.settingsMeta?.paths?.[scope.value]);path.title=lee.settingsMeta?.paths?.[scope.value]||'';target.textContent=`${scope.value} · ${language.value||'all languages'}`;paintSettingsOrigins();};
  scope.onchange=()=>{localStorage.setItem('lee-settings-save-scope',scope.value);paintPath();};paintPath();
  language.onchange=()=>{localStorage.setItem('lee-settings-language-scope',language.value);saved=true;m.remove();editorSettings(language.value);};
  // Every click previews live; the modal's close handler puts the original back unless saved.
  const paintPicker=()=>{const {family,mode}=lee.theme;
    $$('[data-theme]',m).forEach(b=>{const on=b.dataset.theme===family;b.classList.toggle('active',on);b.setAttribute('aria-pressed',on);
      $('.lee-theme-swatch',b).style.cssText=swatch(b.dataset.theme,mode);});
    $$('[data-theme-mode]',m).forEach(b=>{const on=b.dataset.themeMode===mode;b.classList.toggle('active',on);b.setAttribute('aria-pressed',on);});
    $$('[data-theme-density]',m).forEach(b=>{const on=b.dataset.themeDensity===lee.theme.density;b.classList.toggle('active',on);b.setAttribute('aria-pressed',on);});};
  $$('[data-theme]',m).forEach(b=>b.onclick=()=>{applyTheme({...lee.theme,family:b.dataset.theme});paintPicker();});
  $$('[data-theme-mode]',m).forEach(b=>b.onclick=()=>{applyTheme({...lee.theme,mode:b.dataset.themeMode});paintPicker();});
  $$('[data-theme-density]',m).forEach(b=>b.onclick=()=>{applyTheme({...lee.theme,density:b.dataset.themeDensity});paintPicker();});
  $('[data-reset]',m).onclick=async()=>{const targets=page==='appearance'?['appearance','editor']:[page]; if(!targets.every(t=>t==='appearance'||sections[t]))return;try{for(const section of targets)await post('/settings/reset',{scope:scope.value,section,language:section==='appearance'?'':language.value});}catch(e){return status(String(e.message||e),'err');}saved=true;m.remove();applyEditorPrefs(EDITOR_DEFAULTS);setTimeout(editorSettings,0);};
  $('[data-cancel]',m).onclick=()=>m.remove();
  const same=(a,b)=>Array.isArray(a)||Array.isArray(b)?JSON.stringify(a)===JSON.stringify(b):a===b;
  $('[data-save]',m).onclick=async()=>{update();let count=0;try{for(const [section,values] of Object.entries(sections)){const changed=Object.fromEntries(Object.entries(values).filter(([key,value])=>!same(value,initialSections[section][key])));if(Object.keys(changed).length){await post('/settings/save',{scope:scope.value,language:language.value,section,values:changed});count+=Object.keys(changed).length;}}}catch(e){return status(String(e.message||e),'err');}const themeSaved=themeText(lee.theme)!==themeText(originalTheme);if(themeSaved){await saveTheme(lee.theme,scope.value);count++;}localStorage.setItem('lee-settings-save-scope',scope.value);localStorage.setItem('lee-settings-language-scope',language.value);localStorage.removeItem('lee-editor-settings');await loadSettings(language.value);saved=true;m.remove();status(`${count||'no'} setting${count===1?'':'s'} saved to ${scope.value} · ${language.value||'all languages'} (${shownPath(lee.settingsMeta?.paths?.[scope.value])})${themeSaved&&language.value?', and the theme to all languages':''}`,'ok');};
  /* A secret's value never comes back from the server, so a row says that it is set, not what it is. */
  const paintEnv=async(d=null)=>{
    const list=$('[data-env-list]',m); if(!list) return;
    try{ d=d||await api('/settings/env'); }catch(e){ list.textContent=String(e.message||e); return; }
    $('[data-env-note]',m).textContent=d.note||'';
    list.innerHTML=(d.entries||[]).map(e=>`<div class="lee-env-row"><span><strong>${esc(e.key)}</strong>`+
      `<small>${e.set?(e.secret?'set':esc(e.value)):'not set'}${e.source?` · ${esc(e.source)}`:''}</small></span>`+
      (e.removable?`<button class="lee-btn" data-env-remove="${esc(e.key)}">Remove</button>`:'')+`</div>`).join('');
    $$('[data-env-remove]',m).forEach(b=>b.onclick=async()=>{
      try{ paintEnv(await post('/settings/env/remove',{key:b.dataset.envRemove})); status(`${b.dataset.envRemove} removed`,'ok'); }
      catch(e){ status(String(e.message||e),'err'); }});
  };
  $('[data-env-save]',m).onclick=async()=>{
    const key=$('[data-env-key]',m).value.trim(), value=$('[data-env-value]',m).value;
    try{ const d=await post('/settings/env/save',{key,value});
      $('[data-env-key]',m).value=''; $('[data-env-value]',m).value='';
      paintEnv(d); status(`${key} set`,'ok'); }
    catch(e){ status(String(e.message||e),'err'); }};
  paintEnv();
  /* Restoring is a write over live state, so the list says what each copy holds and asks first. */
  const paintBackups=async()=>{
    const list=$('[data-backup-list]',m); if(!list) return;
    let d; try{ d=await api('/backups'); }catch(e){ list.textContent=String(e.message||e); return; }
    $('[data-backup-dir]',m).textContent=d.dir;
    /* Painted once: a repaint after a run would drop ticks the person has not saved yet. */
    const chooser=$('[data-backup-entries]',m);
    if(chooser&&!$('[data-backup-entry]',chooser)){
      chooser.innerHTML=(d.entries||[]).map(e=>`<label class="lee-settings-toggle">`+
        `<input type="checkbox" data-backup-entry="${esc(e.name)}"${e.chosen?' checked':''}>`+
        `<span>${esc(e.label)}<small>${esc(e.name)}</small></span></label>`).join('');
      chooser.addEventListener('change',update);
    }
    if(!d.backups.length){ list.innerHTML='<div class="lee-dim">no copies yet</div>'; return; }
    list.innerHTML=d.backups.map(b=>`<div class="lee-backup-row"><span><strong>${esc(b.name)}</strong>`+
      `<small>${b.files} file${b.files===1?'':'s'} · ${Math.max(1,Math.round(b.bytes/1024))} KB`+
      `${b.archived?'':' · uncompressed'}${b.reason?` · ${esc(b.reason)}`:''}`+
      `${b.entries&&b.entries.length?`<br>${esc(b.entries.join(', '))}`:''}</small></span>`+
      `<button class="lee-btn" data-restore="${esc(b.name)}">restore</button></div>`).join('');
    $$('[data-restore]',list).forEach(button=>button.onclick=async()=>{
      const name=button.dataset.restore;
      if(!await confirmDialog('Restore this backup',
        `Put the copy from ${name} back over the current conversations, notes and settings? `+
        `A copy of what it replaces is kept first.`,'restore')) return;
      try{ const out=await post('/backups/restore',{name});
           status(`restored ${out.restored.length} item(s) from ${name} · ${out.note}`,'ok'); }
      catch(e){ status(String(e.message||e),'err'); }
    });
  };
  $('[data-backup-now]',m).onclick=async()=>{
    try{ const out=await post('/backups/run',{reason:'asked for'});
         status(out.name?`backed up as ${out.name}`:'nothing to back up yet','ok'); await paintBackups(); }
    catch(e){ status(String(e.message||e),'err'); }
  };
  paintBackups();
  $('[data-open-keys]',m).onclick=()=>{saved=true;m.remove();editKeys();};
  $('[data-open-runs]',m).onclick=()=>{saved=true;m.remove();editRuns();};
}
function leeTheme() { editorSettings(); }
window.leeTheme = leeTheme; window.leeEditorSettings = editorSettings;

/* The update notice. `/update` decides; it offers nothing outside the packaged Mac app. */
function updateBar(text, buttons) {
  let el = $('#leeupdate');
  if (!el) {
    el = document.createElement('div'); el.id = 'leeupdate'; el.className = 'lee-offer'; el.setAttribute('role', 'status');
    document.body.append(el);
  }
  el.hidden = false; el.title = text;
  el.innerHTML = `<span>${esc(text)}</span>` + buttons.map(([label], i) => `<button class="lee-btn${i ? '' : ' go'}" data-update="${i}">${esc(label)}</button>`).join('');
  buttons.forEach(([, fn], i) => { el.querySelector(`[data-update="${i}"]`).onclick = fn; });
  return el;
}
const updateHide = () => { const el = $('#leeupdate'); if (el) el.hidden = true; };
/* Per version, or a new package set: a newer release that the hourly check finds shows the bar again. */
const updateLater = d => ['Not now', () => { updateHide(); sessionStorage.setItem('lee-update-later', d.latest || ''); }];
const updateText = d => ({lock: `A new set of Leela packages is ready${d.changes ? ` (${d.changes})` : ''}. Kernels stop when Leela restarts to use it.`,
  'app-needed': `The newest Leela packages need Leela app ${d.latest}. Get it from the release page.`,
  download: `Leela ${d.latest} is available. You have ${d.current}. Get it from the release page.`})[d.kind] || `Leela ${d.latest} is available. You have ${d.current}.`;
const updateNotes = d => [d.kind === 'lock' ? 'Details' : 'Release notes', () => openExternal(d.url)];
const updateBusy = d => ['running', 'done'].includes(d.job?.state);
const updateRestart = (text, d = {}) => updateBar(text, [[d.kind === 'lock' ? 'Restart to update' : 'Restart Leela',
  () => post('/update/restart', {}).catch(e => status(String(e.message || e), 'err'))]]);
const updateInstalled = (d, line) => d.kind === 'lock' ? 'The new packages are installed. Restart to update; running kernels stop.' : `${line || `Leela ${d.latest} is installed.`} Restart now to use it.`;
function oldExtrasOffer(o) {
  if (!o || sessionStorage.getItem('lee-old-extras-later')) return;
  updateBar(`The old Leela app left ${o.mb} MB of packages in ${o.path}. This Leela does not use them.`,
    [['Remove them', async () => { const r = await post('/update/old-extras', {}).catch(() => ({})); updateHide(); if (!r.ok) status('Leela could not remove the old packages', 'err'); }],
     ['Not now', () => { updateHide(); sessionStorage.setItem('lee-old-extras-later', '1'); }]]);
}
/* A run in progress or already installed comes first, so a reload or a second window picks it up. */
function updateOffer(d) {
  if (d.job?.state === 'running') return leeUpdateRun(d);
  if (d.job?.state === 'done') return updateRestart(updateInstalled(d, d.job.line), d);
  updateBar(updateText(d), d.install ? [['Update', () => leeUpdateRun(d)], updateNotes(d), updateLater(d)] : [updateNotes(d), updateLater(d)]);
}
/* At start and then each hour (`boot.js`); a bar on screen or a run in progress is left alone. */
async function leeUpdateNotice() {
  if (updateRunning || $('#leeupdate')?.hidden === false) return;
  const d = await api('/update');
  if (updateBusy(d) || (d.notice && sessionStorage.getItem('lee-update-later') !== d.latest)) return updateOffer(d);
  oldExtrasOffer(d.old_extras);
}
/* "Check for updates…": asks GitHub now, past the cache and past "Not now", and always answers. */
async function leeUpdateCheck() {
  if (updateRunning) return;
  updateBar('Checking for updates…', []);
  const d = await api('/update?fresh=1').catch(() => ({failed: true}));
  if (updateBusy(d) || d.outdated) return updateOffer(d);
  if (d.failed) return updateBar('Leela could not check for updates. Make sure that the network is on, then try again.',
    [['Try again', leeUpdateCheck], ['Close', updateHide]]);
  updateBar(`Leela is up to date (${d.current}).`, [['OK', updateHide]]);
}
/* One run per window: the bar, the dialog and a second click share it. */
let updateRunning = null;
function leeUpdateRun(d) { return updateRunning ||= updateRunOnce(d).finally(() => { updateRunning = null; }); }
async function updateRunOnce(d) {
  const err = e => ({state: 'error', line: String(e.message || e)});
  let s = d.job?.state === 'running' ? d.job : await post('/update/install', {}).catch(err);
  while (s.state === 'running') {
    updateBar(`Updating Leela: ${s.line || '…'}`, []);
    await new Promise(r => setTimeout(r, 1000));
    s = await api('/update/status').catch(err);
  }
  if (s.state === 'done') return updateRestart(updateInstalled(d, s.line), d);
  if (d.kind === 'lock') return updateBar(`The update did not install. Leela still runs the current version.${s.line ? ' ' + s.line : ''}`,
    [['Try again', () => leeUpdateRun(d)], updateNotes(d), updateLater(d)]);
  if (s.state === 'same') return updateBar(s.line || 'Homebrew does not list the new Leela yet. Try again in a few minutes.',
    [['Try again', () => leeUpdateRun(d)], updateNotes(d), updateLater(d)]);
  if (s.state === 'unavailable') return updateBar('This Leela was not installed with Homebrew. Get the new version from the release page.', [updateNotes(d), updateLater(d)]);
  updateBar(`The update did not finish: ${s.line || s.state}`, [['Try again', () => leeUpdateRun(d)], updateNotes(d), updateLater(d)]);
}
window.leeUpdateNotice = leeUpdateNotice;
window.leeUpdateCheck = leeUpdateCheck;
window.leeUpdateRun = leeUpdateRun;
// The file tree's marks span every open repository and its folders, so `paintTreeGit` owns them.
function paintGitTree() { paintTreeGit(); }
async function refreshOpenGitMarks() {
  if (lee.kind === 'notebook') return paintNotebookGitMarks();
  if (lee.kind !== 'text' || !lee.path) return;
  try {
    lee.fileGit = await api('/git/file?path=' + encodeURIComponent(lee.path));
    const view = lee.editors.get('file'); if (view) LeeCM.setChangedLines(view, lee.fileGit.ranges || []);
  } catch (_) {}
}
// The same mark a file gets, at the unit a notebook has. Line numbers say nothing useful about an
// .ipynb, since it is JSON and editing one cell moves every line below it, so the server answers
// per cell id and the whole cell carries the bar.
async function paintNotebookGitMarks() {
  if (lee.kind !== 'notebook' || !lee.path) return;
  try { lee.notebookGit = await api('/git/notebook?path=' + encodeURIComponent(lee.path)); }
  catch (_) { return; }
  repaintNotebookGitMarks();
}
function repaintNotebookGitMarks() {
  const cells = lee.notebookGit?.cells || {}, lines = lee.notebookGit?.lines || {};
  $$('.lee-cell').forEach(el => {
    const kind = cells[el.dataset.id] || '';
    el.classList.toggle('changed', !!kind);
    el.classList.toggle('changed-added', kind === 'added');
    // The bar on the cell says that it differs, the lines inside say where. A mounted editor is
    // told directly, because `mountCell` reads these only when it is created.
    const view = lee.editors.get(el.dataset.id);
    if (view) LeeCM.setChangedLines(view, lines[el.dataset.id] || []);
  });
  paintNotebookOverview();
}

/* The notebook's overview stripe.

   A file gets one from CodeMirror, because the editor owns the scrollbar. A notebook scrolls as a
   page of cells, so its scrollbar belongs to `#editor` and nothing inside a cell can mark it,
   which left the per-cell change marks invisible until you had scrolled to them.

   Same rules as the editor's: it stands where the scrollbar was, it maps the whole document onto
   its height, and it is never a second thing to scroll. */
const NB_OVERVIEW_W = 14;
function nbOverview() {
  const stage = $('#editorstage'); if (!stage) return null;
  let c = $('#nboverview');
  if (!c) {
    c = document.createElement('canvas'); c.id = 'nboverview'; c.className = 'lee-nb-overview';
    c.setAttribute('aria-label', 'notebook overview: uncommitted cells and failures');
    const seek = e => {
      const host = $('#editor'); if (!host) return;
      const box = c.getBoundingClientRect();
      const at = Math.max(0, Math.min(1, (e.clientY - box.top) / (box.height || 1)));
      host.scrollTop = Math.max(0, at * host.scrollHeight - host.clientHeight / 2);
    };
    c.addEventListener('pointerdown', e => { c.setPointerCapture(e.pointerId); e.preventDefault(); seek(e); });
    c.addEventListener('pointermove', e => { if (e.buttons & 1) { e.preventDefault(); seek(e); } });
    stage.appendChild(c);
  }
  return c;
}
function paintNotebookOverview() {
  const host = $('#editor'), stage = $('#editorstage'), c = nbOverview();
  if (!c || !host || !stage) return;
  watchNotebookPane();
  nbPaneSize = host.clientWidth + 'x' + host.clientHeight;
  // Nothing to overview when the whole notebook fits, and the stripe would take the scrollbar
  // away to say so.
  const on = lee.kind === 'notebook' && host.scrollHeight > host.clientHeight + 4;
  // `LeeCM.overviewGutter` rather than the class alone: it holds back the width the hidden bar
  // was taking, which is what stops the pane rewrapping into a different answer every frame.
  // Named, because a file's stripe hides the bar of this same pane: unnamed, the `off` below ran
  // on every scroll of a text tab and put the bar back beside a stripe that had replaced it.
  c.hidden = !on; LeeCM.overviewGutter(host, on, 'nb');
  if (!on) return;
  const stageBox = stage.getBoundingClientRect(), box = host.getBoundingClientRect();
  // Measured rather than pinned to the stage, so a split editor puts it on the notebook's own
  // right edge.
  c.style.left = (box.right - stageBox.left - NB_OVERVIEW_W) + 'px';
  c.style.top = (box.top - stageBox.top) + 'px';
  const dpr = devicePixelRatio || 1, w = NB_OVERVIEW_W, h = Math.max(40, host.clientHeight);
  c.width = w * dpr; c.height = h * dpr; c.style.width = w + 'px'; c.style.height = h + 'px';
  const ctx = c.getContext('2d'); ctx.scale(dpr, dpr); ctx.clearRect(0, 0, w, h);
  const css = getComputedStyle(document.documentElement);
  const colour = (name, fallback) => css.getPropertyValue(name).trim() || fallback;
  const total = host.scrollHeight || 1, changed = lee.notebookGit?.cells || {};
  const y = px => px / total * h;
  for (const el of $$('.lee-cell', host)) {
    const top = y(el.getBoundingClientRect().top - box.top + host.scrollTop);
    const tall = Math.max(2, y(el.offsetHeight));
    const kind = changed[el.dataset.id];
    if (kind) {
      ctx.fillStyle = kind === 'added' ? colour('--lee-green', '#3fb950') : colour('--lee-orange', '#d29922');
      ctx.fillRect(0, top, 2, tall);
    }
    // A failed run is the other thing worth seeing from the top of a long notebook.
    if ($('.lee-cell-state.error', el)) {
      ctx.fillStyle = colour('--lee-red', '#f85149');
      ctx.fillRect(3, Math.min(h - 2, top), w - 5, 2);
    }
  }
  ctx.fillStyle = colour('--lee-fg4', '#6e7681'); ctx.globalAlpha = .28;
  ctx.fillRect(0, y(host.scrollTop), w, Math.max(6, y(host.clientHeight)));
  ctx.globalAlpha = 1;
}
let nbOverviewFrame = 0;
function queueNotebookOverview() {
  cancelAnimationFrame(nbOverviewFrame);
  nbOverviewFrame = requestAnimationFrame(paintNotebookOverview);
}
/* The stripe is placed by measuring the pane, and a pane resize is not a window resize. Opening the
   agent pane, dragging a splitter or collapsing the bottom dock moves the notebook's right edge
   without one, and the stripe stayed where that edge used to be, hanging in the middle of the page.

   Only a size that really changed queues a paint, because the paint pads the pane it measures and
   the observer would otherwise wake itself. */
let nbPane = null, nbPaneObserver = null, nbPaneSize = '';
function watchNotebookPane() {
  if (!('ResizeObserver' in window)) return;
  const host = $('#editor'); if (!host) return;
  nbPaneObserver ||= new ResizeObserver(() => {
    const el = $('#editor'); if (!el) return;
    const size = el.clientWidth + 'x' + el.clientHeight;
    if (size === nbPaneSize) return;
    nbPaneSize = size; queueNotebookOverview();
  });
  if (host === nbPane) return;
  if (nbPane) nbPaneObserver.unobserve(nbPane);
  nbPaneObserver.observe(host); nbPane = host;
}
document.addEventListener('scroll', e => {
  if (e.target?.id === 'editor') queueNotebookOverview();
}, true);
addEventListener('resize', queueNotebookOverview);
/* Everything downstream of a branch, without a page refresh.

   The pill and the tree badges were repainted by this poll and nothing else was. A checkout from
   the panel, from lazygit or from the agent left the editor's change marks describing the branch
   you came from, the History and Branches lists unchanged, and the release panel counting against
   the old tag.

   `head` is in the signature because a commit is the case the others miss: branch, counts and file
   list all read the same afterwards, and only the sha moved. */
function gitSignature(d) {
  /* Each changed file's own state, not how many there are. Typing in a file that was already
     modified moves no count, so a signature built from counts alone never moves. The status codes
     and line counts are what differ, and `/git/info` already returns all of it on every poll. */
  const changes = (d.changes || []).map(c =>
    [c.path, c.index, c.worktree,
     (c.staged_stat || {}).additions, (c.staged_stat || {}).deletions,
     (c.unstaged_stat || {}).additions, (c.unstaged_stat || {}).deletions].join(':')).join(',');
  return [d.root, d.branch, d.head, d.upstream, d.ahead, d.behind, changes,
          (d.stashes || []).length, (d.operation || {}).active || ''].join('|');
}
function noticeGitState(d) {
  const sig = gitSignature(d), had = lee.gitSignature;
  lee.gitSignature = sig;
  if (had && had !== sig) gitChanged(d);    // `had` empty on the first look: nothing has moved yet
}
// The signature is the active tab's repository. A panel pinned elsewhere leaves it alone.
function noteGitSignature(d) { if (!gitUI.repo && d) lee.gitSignature = gitSignature(d); }
function gitChanged(d = null) {
  refreshOpenGitMarks();                    // the file's lines, or the notebook's cells
  const left = $('#left');
  // The snapshot and the loaded history are both about the commit we were on, open or not: a stale
  // snapshot would steer `gitUrl` to the repository we left.
  if (d?.root && !gitUI.repo) gitAdopt(d.root);
  gitUI.snapshot = null; gitUI.history = [];
  if (left?.classList.contains('left-git')) renderGitPanel();
  // A release is measured from the last tag on this branch and a deploy from what is committed,
  // so both are answers about the branch rather than about the panel.
  if (left?.classList.contains('left-releases')) leeReleases();
  if (left?.classList.contains('left-deploys')) leeDeploys();
}
window.leeGitChanged = gitChanged;

// Choosing another folder is a bigger change than a commit. `gitChanged` reloads what depends on
// the branch, this reloads what depends on which project it is, so drive and workflows are here:
// a commit does not change where a project deploys to, and a different project does.
function projectChanged() {
  // Every cached answer describes the folder we just left, on screen or not. They all go, or
  // opening one of these panels a minute later shows the old project's state.
  gitUI.snapshot = null; gitUI.history = [];
  // Which repositories the workspace has changes when a folder is opened or closed, and this list
  // was loaded once per page: a folder added afterwards never appeared under All repos, and the
  // window that had been open longest was the one that showed least.
  gitUI.repos = null; gitUI.reposResults = [];
  relUI.data = drvUI.data = null;
  Object.assign(wfUI, {data: null, runs: null, env: null, catalogue: null, docker: null});
  Object.assign(depUI, {data: null, infra: null, stack: null, records: null});
  gitChanged();
  const left = $('#left');
  if (left?.classList.contains('left-drive')) leeDrive();
  if (left?.classList.contains('left-workflows')) leeWorkflows();
  // A shell cannot cd itself, and typing into one somebody is using is not a fix. Reaching for the
  // one that belongs to this checkout is, and only where the pane is already open: switching a
  // project should not start a process nobody asked for.
  if ($('#shell')?.classList.contains('show-term')) openTerm('shell').catch(() => {});
}

// Which repository a panel request is about lives in `gitUI.repo`, and `gitUrl` puts it on the
// query. These two only ask whether Source Control is on screen.
function scmPanelOpen() { return !!$('#left')?.classList.contains('left-git'); }
function refreshScmIfOpen(snapshot = null) {
  if (!scmPanelOpen()) return;
  if (snapshot) renderGitPanel(snapshot);
  else leeGitRefresh();
}

async function refreshProjectPills() {
  try {
    const d = await api('/workspace/info');
    lee.roots = d.roots || []; lee.home = d.home || lee.home || '';
    const active = (d.roots || []).find(r => r.path === (gitUI.repo || d.active)) || (d.roots || [])[0];
    const name = $('#workspacename'); if (name) name.textContent = active?.name || 'open workspace';
    const workspace = $('#workspacepill');
    if (workspace) { workspace.title = active?.path || 'open workspace'; workspace.setAttribute('aria-label', `switch workspace: ${active?.name || 'none open'}`); }
    // The loose window's folder is Leela's own; the title calls it `loose`, as `title_folder` does.
    lee.titleFolder = active ? (active.loose ? 'loose' : active.name) : ''; paintTitle();
  } catch (_) {}
  try {
    const d = await api('/cwd');
    const cwd = $('#cwdpill');
    if (cwd) { cwd.textContent = (d.explicit ? 'cwd ' : 'cwd auto ') + (d.cwd.split('/').pop() || d.cwd);
               cwd.title = d.cwd || 'choose a working directory'; }
  } catch (_) {}
  await refreshGitPill();
}
async function refreshGitPill() {
  try {
    // Bare, not `gitUrl`: the pill and the tree badges describe the repository the active tab is
    // in, so a panel pinned elsewhere must not repaint them. `api`, not `gitInfo`, because that
    // helper throws for a folder outside a repository, and being outside one is a normal answer.
    const d = await api('/git/info');
    const git = $('#gitpill'); if (!git) return;
    if (!d || d.repo === false) {
      // With no folder open there is nothing to be inside or outside of, so the pill hides.
      paintBranchPill(d, d && String(d.note || '').startsWith('no folder') ? 'nofolder' : 'nogit');
      git.title = (d && d.note) || 'not inside a Git repository';
      return;
    }
    paintBranchPill(d);
    git.title = `${d.root}${d.upstream ? ' · ' + d.upstream : ''}${d.ahead ? ' · ahead ' + d.ahead : ''}${d.behind ? ' · behind ' + d.behind : ''}`;
    paintGitTree(d);
    noticeGitState(d);
  } catch (e) {
    // A failure is not an absence. Saying `no git` here claims the folder is not a checkout,
    // which is a statement about the user's project rather than about the request.
    paintBranchPill(null, 'error');
    const git = $('#gitpill'); if (git) git.title = 'could not read the repository: ' + ((e && e.message) || e);
    console.error('git pill', e);
  }
}

/* A change on disk that git can see: a save, another editor, or a commit, checkout or stage made
   outside Leela. The pill's repository is looked at, and a pinned panel's own. One look at a time,
   at most one a second, and a burst during a look gives one more after it. */
const GIT_DISK_GAP = 1000;
let gitDiskBusy = null, gitDiskAgain = false, gitDiskAt = 0;
function noticeGitDisk() {
  if (gitDiskBusy) { gitDiskAgain = true; return gitDiskBusy; }
  return gitDiskBusy = (async () => {
    do {
      gitDiskAgain = false;
      const wait = gitDiskAt + GIT_DISK_GAP - performance.now();
      if (wait > 0) await new Promise(r => setTimeout(r, wait));
      gitDiskAt = performance.now();
      await refreshGitPill();
      if (!gitUI.repo || !scmPanelOpen() || !gitUI.snapshot) continue;
      const d = await gitInfoOrNull(gitUrl('/git/info'));
      if (d && gitUI.snapshot && gitSignature(d) !== gitSignature(gitUI.snapshot)) gitChanged();
    } while (gitDiskAgain);
  })().finally(() => { gitDiskBusy = null; });
}

// `/git/info` answers 200 with `repo: false` outside a checkout. A surface that only works inside
// one wants the throw it always had, and chrome wants to go quiet.
async function gitInfo(url = '/git/info') {
  const d = await api(url);
  if (d && d.repo === false) throw new Error(d.note || 'not inside a Git repository');
  return d;
}
async function gitInfoOrNull(url = '/git/info') {
  try { const d = await api(url); return d && d.repo === false ? null : d; }
  catch (_) { return null; }
}

async function leeCwd() {
  const d = await api('/cwd');
  const value = await inputDialog('script working directory', 'Directory inside an open folder', d.cwd,
                                  'Leave empty to use the Git repository root');
  if (value === null) return;
  const r = await post('/cwd/set', {path: value});
  status(`${r.explicit ? 'working directory' : 'automatic repository root'}: ${r.cwd}`, 'ok');
  refreshProjectPills();
  // A new working directory can imply a different repository, so an open panel is stale.
  refreshScmIfOpen();
}
window.leeCwd = leeCwd;

/* Coloured code per patch line, keyed by the exact patch text it was made for, and by each hunk as
   `gitPatchParts` cuts it. A patch whose text changed finds nothing, so stale colours never paint. */
const PATCH_HL = new Map(), PATCH_HL_MAX = 400;
function noteHl(d) {
  const keep = (text, hl) => { PATCH_HL.delete(text); PATCH_HL.set(text, hl); while (PATCH_HL.size > PATCH_HL_MAX) PATCH_HL.delete(PATCH_HL.keys().next().value); };
  for (const f of ['text', 'content', 'patch', 'diff']) {
    const text = d?.[f], hl = d?.[f + '_hl'];
    if (typeof text !== 'string' || !Array.isArray(hl) || hl.length !== text.split('\n').length) continue;
    keep(text, hl);
    const {hunks, starts} = gitPatchParts(text);
    hunks.forEach((h, i) => keep(h, [...hl.slice(starts[i], starts[i] + h.split('\n').length - 1), null]));
  }
  return d;
}
function gitPatchHtml(text) {
  if (!text) return '<div class="lee-git-empty-state"><strong>No patch yet</strong><span>Stage an untracked file to create its first patch.</span></div>';
  const lines = String(text).split('\n'), hl = PATCH_HL.get(String(text));
  return lines.map((line, i) => {
    const kind = line.startsWith('@@') ? 'hunk' : line.startsWith('+') && !line.startsWith('+++') ? 'add' :
                 line.startsWith('-') && !line.startsWith('---') ? 'del' : line.startsWith('diff ') || line.startsWith('index ') ? 'meta' : '';
    if (hl?.[i] != null) return `<div class="lee-patch-line ${kind} hl"><span class="lee-patch-mark">${esc(line.slice(0, 1))}</span>${hl[i]}</div>`;
    return `<div class="lee-patch-line ${kind}">${esc(line) || ' '}</div>`;
  }).join('');
}
function gitPatchParts(text) {
  const lines = String(text || '').split('\n'), first = lines.findIndex(x => x.startsWith('@@'));
  if (first < 0) return {header: text, hunks: []};
  const header = lines.slice(0, first).join('\n') + '\n', hunks = [], starts = [];
  let current = [];
  lines.slice(first).forEach((line, i) => {
    if (line.startsWith('@@') && current.length) { hunks.push(current.join('\n') + '\n'); current = []; }
    if (!current.length) starts.push(first + i);
    current.push(line);
  });
  if (current.length) hunks.push(current.join('\n') + '\n');
  return {header, hunks, starts};
}
function showGitFileDiff(path, patch = '', line = 0, rawPatch = '', notebook = false, options = {}) {
  const name = String(path || '').split('/').pop(), parts = gitPatchParts(rawPatch || patch);
  const canPartial = !notebook && parts.hunks.length > 0 && options.group;
  const controls = canPartial ? `<button class="lee-btn" id="githunks">select hunks</button>` : '';
  const m = modal(`<div class="lee-mhead">${esc(name)}<span class="sub">${esc(options.label || 'working tree against HEAD')}${line ? ' · line ' + line : ''}</span>` +
    `<span class="lee-spacer"></span>${notebook ? '<button class="lee-btn active" id="gitcontent">cell content</button><button class="lee-btn" id="gitraw">raw notebook</button>' : ''}` +
    `${controls}<button class="lee-btn" id="gitexpand">expand</button></div>` +
    `<div class="lee-git-patch">${gitPatchHtml(patch)}</div>` +
    `<div class="lee-mfoot"><button class="lee-btn" id="gitopenfile">open file</button><span class="lee-dim">Unified patch · additions and removals retain Git semantics.</span></div>`);
  m.querySelector('#gitopenfile').onclick = () => { m.remove(); leeOpenFile(path); };
  const repaint = (text, active) => {
    m.querySelector('.lee-git-patch').innerHTML = gitPatchHtml(text);
    for (const id of ['gitcontent', 'gitraw']) m.querySelector('#' + id)?.classList.toggle('active', id === active);
  };
  m.querySelector('#gitcontent')?.addEventListener('click', () => repaint(patch, 'gitcontent'));
  m.querySelector('#gitraw')?.addEventListener('click', () => repaint(rawPatch, 'gitraw'));
  m.querySelector('#githunks')?.addEventListener('click', () => {
    const body = m.querySelector('.lee-git-patch');
    body.innerHTML = parts.hunks.map((h, i) => `<label class="lee-git-hunk"><input type="checkbox" data-hunk="${i}" checked><span>hunk ${i + 1}</span>${gitPatchHtml(h)}</label>`).join('');
    const foot = m.querySelector('.lee-mfoot');
    foot.innerHTML = `<button class="lee-btn go" id="gitapplyhunks">${options.group === 'staged' ? 'unstage' : 'stage'} selected hunks</button><span class="lee-dim">Only checked hunks will move between the index and working tree.</span>`;
    foot.querySelector('#gitapplyhunks').onclick = async () => {
      const selected = [...body.querySelectorAll('[data-hunk]:checked')].map(x => parts.hunks[+x.dataset.hunk]);
      if (!selected.length) return status('select at least one hunk', 'err');
      try {
        const d = await gitDo('apply_patch', {patch: parts.header + selected.join(''), staged: true, reverse: options.group === 'staged'});
        m.remove(); renderGitPanel(d);
      } catch (e) { leeFail('git', 'stage hunks', e); }
    };
  });
  m.querySelector('#gitexpand').onclick = e => {
    const expanded = m.classList.toggle('lee-git-diff-expanded');
    e.target.textContent = expanded ? 'restore' : 'expand';
  };
}

/* The change gutter popup: the mark thickens under the pointer, and clicking it shows what the
 * line used to say beside step, revert, copy and commit-only-this.
 *
 * The hunks come from `/git/file`, cut out of a three-context diff so each one is a patch Git can
 * place by its own context. The browser never assembles a patch of its own, because a hand-built
 * hunk with the wrong line numbers is applied silently in the wrong place.
 */
const fileHunks = () => lee.fileGit?.hunks || [];

function hunkAtLine(line) {
  const hunks = fileHunks();
  const inside = hunks.findIndex(h => line >= h.from && line <= h.to);
  if (inside >= 0) return inside;
  // Three context lines can merge two changes into one hunk, so a mark drawn from the exact
  // zero-context ranges can sit just outside the span of the hunk that carries it. The nearest
  // change is the right answer there.
  let best = -1, gap = Infinity;
  hunks.forEach((h, i) => {
    const d = Math.min(Math.abs(line - h.from), Math.abs(line - h.to));
    if (d < gap) { gap = d; best = i; }
  });
  return best;
}

/* Which words of the old line the new one no longer has. A plain LCS over words is enough at one
 * line's length. */
function tokenDiffHtml(before, after) {
  const a = String(before ?? '').match(/\w+|\s+|[^\w\s]/g) || [];
  const b = String(after ?? '').match(/\w+|\s+|[^\w\s]/g) || [];
  if (!a.length) return '';
  if (!b.length) return `<mark>${esc(before)}</mark>`;
  const n = a.length, m = b.length;
  const dp = Array.from({length: n + 1}, () => new Uint16Array(m + 1));
  for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--)
    dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
  let out = '', run = '', i = 0, j = 0;
  const flush = () => { if (run) out += `<mark>${esc(run)}</mark>`; run = ''; };
  while (i < n) {
    if (j < m && a[i] === b[j]) { flush(); out += esc(a[i]); i++; j++; }
    else if (j < m && dp[i + 1][j] < dp[i][j + 1]) j++;
    else run += a[i++];
  }
  flush();
  return out;
}

function closeChangePopup() {
  const pop = $('.lee-change-pop');
  if (!pop) return;
  pop._leeOff?.(); pop.remove();
}

/* The mark widens only while the pointer is on it. 12px is the editor bundle's own click target
 * for a change mark, and the two numbers must agree. */
function armChangeGutter(host) {
  if (!host || host._leeGutterArmed) return;
  host._leeGutterArmed = true;
  let hot = null;
  const cool = () => { hot?.classList.remove('lee-change-hot'); hot = null; };
  host.addEventListener('mousemove', e => {
    const line = e.target.closest?.('.cm-lee-change');
    if (!line || e.clientX > line.getBoundingClientRect().left + 12) return cool();
    if (line === hot) return;
    cool(); hot = line; line.classList.add('lee-change-hot');
  });
  host.addEventListener('mouseleave', cool);
}

function changePopupBody(h) {
  if (!h.old) return '<div class="lee-change-new">These lines are new. No commit has them yet.</div>';
  const old = h.old.replace(/\n$/, '').split('\n'), now = (h.new || '').replace(/\n$/, '').split('\n');
  return `<pre class="lee-change-old">${old.map((l, k) => tokenDiffHtml(l, now[k])).join('\n')}</pre>`;
}

function showChangePopup(path, line) {
  closeChangePopup();
  const hunks = fileHunks(), at = hunkAtLine(line);
  // An untracked file has no committed version, so the whole-file diff is the honest answer.
  if (at < 0) return showGitFileDiff(path, lee.fileGit?.diff || '', line);
  const h = hunks[at], name = String(path || '').split('/').pop();
  const pop = document.createElement('div');
  pop.className = 'lee-change-pop'; pop.setAttribute('role', 'dialog');
  pop.setAttribute('aria-label', `change ${at + 1} of ${hunks.length} in ${name}, line ${h.from}`);
  pop.innerHTML =
    `<div class="lee-change-tools">` +
    `<button class="lee-change-icon" data-act="prev" title="previous change" aria-label="previous change">↑</button>` +
    `<button class="lee-change-icon" data-act="next" title="next change" aria-label="next change">↓</button>` +
    `<button class="lee-change-icon" data-act="revert" title="revert this change" aria-label="revert this change">⟲</button>` +
    `<button class="lee-change-icon" data-act="diff" title="show this file's whole diff" aria-label="show diff">◫</button>` +
    `<button class="lee-change-icon" data-act="copy" title="copy the previous version" aria-label="copy the previous version">⧉</button>` +
    `<span class="lee-change-count">${at + 1} / ${hunks.length}</span>` +
    `<input class="lee-input lee-change-msg" placeholder="Commit this change" aria-label="commit message for this change">` +
    `<button class="lee-btn go" data-act="commit">commit</button></div>` + changePopupBody(h);
  document.body.appendChild(pop);
  const anchor = $(`#filecm .cm-lee-change[data-change-line="${h.from}"]`) ||
                 $(`#filecm .cm-lee-change[data-change-line="${line}"]`) || $('#filecm');
  const rect = anchor.getBoundingClientRect(), size = pop.getBoundingClientRect();
  pop.style.left = Math.max(4, Math.min(rect.left, innerWidth - size.width - 4)) + 'px';
  pop.style.top = Math.max(4, Math.min(rect.bottom + 4, innerHeight - size.height - 4)) + 'px';

  const away = e => { if (!pop.contains(e.target)) closeChangePopup(); };
  const key = e => { if (e.key === 'Escape') { e.stopPropagation(); closeChangePopup(); } };
  // Deferred by a tick: the click that opened this popup is still on its way up.
  setTimeout(() => document.addEventListener('mousedown', away), 0);
  document.addEventListener('keydown', key, true);
  pop._leeOff = () => {
    document.removeEventListener('mousedown', away);
    document.removeEventListener('keydown', key, true);
  };

  pop.addEventListener('click', e => {
    const act = e.target.closest('[data-act]')?.dataset.act;
    if (!act) return;
    if (act === 'prev' || act === 'next') {
      const next = hunks[(at + (act === 'next' ? 1 : hunks.length - 1)) % hunks.length];
      jumpToLine(next.from);
      // The line has to be laid out before it can be measured, and the editor only renders the
      // lines it has scrolled to.
      return requestAnimationFrame(() => showChangePopup(path, next.from));
    }
    if (act === 'diff') { closeChangePopup(); return showGitFileDiff(path, lee.fileGit?.diff || '', h.from); }
    if (act === 'copy') return copyChangeHunk(h);
    if (act === 'revert') return revertChangeHunk(path, h);
    if (act === 'commit') return commitChangeHunk(path, h, pop.querySelector('.lee-change-msg').value);
  });
  return pop;
}

async function copyChangeHunk(h) {
  try { await navigator.clipboard.writeText(h.old || h.new || ''); status('previous version copied', 'ok'); }
  catch (_) { status('clipboard access failed', 'err'); }
}

/* Git reads and writes the file on disk, and this editor may hold a newer version of it. Both
 * directions are silent data loss: the revert overwrites the unsaved edit, or the next autosave
 * writes the reverted lines back. So the file is saved first and the buffer reloaded after. */
async function refreshFileChanges(path, fromDisk = false, had = null) {
  const v = lee.editors.get('file');
  if (!v) return;
  if (fromDisk) {
    const st = await api('/tab/state?path=' + encodeURIComponent(path)).catch(() => null);
    // Typing since `had` was read is newer than the file git just wrote, so it stays.
    if (had !== null && LeeCM.getDoc(v) !== had) status(`${path.split('/').pop()} changed on disk. Leela keeps your unsaved text.`, 'err');
    else if (typeof st?.text === 'string') {
      lee.dirtyBuffers.delete(path); lee.buffers.delete(path);
      if (st.text !== LeeCM.getDoc(v)) LeeCM.setDoc(v, st.text);
      $$('.lee-tab').find(x => x.title === path)?.classList.remove('dirty');
    }
  }
  const git = await api('/git/file?path=' + encodeURIComponent(path)).then(noteHl).catch(() => null);
  if (!git) return;
  lee.fileGit = git; LeeCM.setChangedLines(v, git.ranges || []);
}

async function revertChangeHunk(path, h) {
  if ($('.lee-tab.active.dirty') && !await saveTab(true)) return;
  const ok = await confirmDialog('Revert this change?',
    `Lines ${h.from}–${h.to} of ${String(path).split('/').pop()} go back to their committed ` +
    `version. Every other change in the file is left alone.`, 'revert');
  if (!ok) return;
  closeChangePopup();
  const view = lee.editors.get('file'), had = view ? LeeCM.getDoc(view) : null;
  // Reverse against the working tree, not the index. This is an edit to the file.
  try { await gitDo('apply_patch', {patch: h.patch, staged: false, reverse: true}); }
  catch (_) { return; }
  await refreshFileChanges(path, true, had);
}

async function commitChangeHunk(path, h, message) {
  const text = String(message || '').trim();
  if (!text) return status('write a message to commit this change', 'err');
  if ($('.lee-tab.active.dirty') && !await saveTab(true)) return;
  /* Git can only commit what is in the index, so this stages the hunk and commits, and anything
   * already staged rides along. The choice is put to whoever is looking at it rather than
   * quietly widening the commit or quietly unstaging deliberate work. */
  const snapshot = gitUI.snapshot || await gitInfoOrNull();
  const staged = (snapshot?.changes || []).filter(c => c.staged && c.path !== path).map(c => c.path);
  if (staged.length) {
    const shown = staged.slice(0, 3).join(', ') + (staged.length > 3 ? `, and ${staged.length - 3} more` : '');
    const ok = await confirmDialog('Something else is already staged',
      `${shown} ${staged.length === 1 ? 'is' : 'are'} staged and would be committed together with ` +
      `this change. Unstage first to commit this change on its own.`, 'commit anyway');
    if (!ok) return;
  }
  closeChangePopup();
  try {
    await gitDo('apply_patch', {patch: h.patch, staged: true, reverse: false});
    await gitDo('commit', {message: text});
  } catch (_) { return; }
  await refreshFileChanges(path);
}

function gitChangeRow(c, group) {
  const state = c.conflicted ? 'conflict' : c.untracked ? 'new file' : group === 'staged' ? 'will commit' : 'not staged';
  const selected = gitUI.selectedChanges.has(`${group}:${c.path}`);
  const list = gitUI.changeLists[c.path], stat = group === 'staged' ? c.staged_stat : c.unstaged_stat;
  return `<article class="lee-git-change ${group}${selected ? ' selected' : ''}" data-path="${esc(c.path)}" data-group="${group}">` +
    `<input type="checkbox" data-select-change aria-label="Select ${esc(c.path)}" ${selected ? 'checked' : ''}>` +
    `<button class="lee-git-file" title="review diff"><span class="lee-git-status">${esc(group === 'staged' ? c.index : c.worktree)}</span><span>${esc(c.path)}</span></button>` +
    `${list ? `<i class="lee-git-changelist">${esc(list)}</i>` : ''}${stat ? `<small class="lee-git-line-stat">${stat.binary ? 'binary' : `+${stat.additions} −${stat.deletions}`}</small>` : ''}` +
    `<span class="sub">${state}</span><span class="lee-spacer"></span>${c.conflicted ? '<button class="lee-btn warn" data-resolve>resolve</button>' : '<button class="lee-btn" data-blame title="file history and blame">blame</button>'}` +
    `<button class="lee-btn" data-open title="open file">open</button>` +
    `${group === 'unstaged' ? '<button class="lee-btn" data-git="stage">stage</button>' : '<button class="lee-btn" data-git="unstage">unstage</button>'}` +
    `${group === 'unstaged' && !c.untracked ? '<button class="lee-btn warn" data-git="discard">discard</button>' : ''}</article>`;
}
function gitRelative(stamp) {
  if (!stamp) return 'date unavailable';
  const seconds = Math.max(0, Date.now() / 1000 - stamp), units = [[31536000, 'y'], [2592000, 'mo'], [604800, 'w'], [86400, 'd'], [3600, 'h'], [60, 'm']];
  for (const [size, label] of units) if (seconds >= size) return `${Math.floor(seconds / size)}${label} ago`;
  return 'just now';
}
function gitFreshness(stamp) { return stamp ? `fetched ${gitRelative(stamp)}` : 'remote refs have not been fetched'; }
let savedGitLists = {}, savedGitReviews = {}, savedGitNotes = {};
try { savedGitLists = JSON.parse(localStorage.getItem('lee-git-changelists') || '{}'); } catch (_) {}
try { savedGitReviews = JSON.parse(localStorage.getItem('lee-git-reviews') || '{}'); } catch (_) {}
try { savedGitNotes = JSON.parse(localStorage.getItem('lee-git-review-notes') || '{}'); } catch (_) {}
const gitUI = {tab: 'changes', snapshot: null, repo: '', repos: null, reposResults: [], expect: '', history: [], historyQuery: '', branchQuery: '', branchScope: 'all', compareFrom: '', compareTo: '', reviewBase: '', reviewHead: '', reviewMode: 'review', review: null, reviewFile: '', reviewPatch: '', root: '', selectedCommit: null, selectedChanges: new Set(), commitDraft: '', changeLists: savedGitLists, reviewed: savedGitReviews, reviewNotes: savedGitNotes, busy: ''};
// The repository the panel's data came from: the pinned one, else the snapshot's. Empty means the one
// the active tab lives in, which is what the branch pill, the file tree and the change marks mean.
function gitRepo() { return gitUI.repo || gitUI.snapshot?.root || ''; }
// A sha or ref from the panel names its repository: the active tab can be in another by now.
function gitUrl(path, params = {}) {
  const q = new URLSearchParams(params);
  if (!q.has('repo') && gitRepo()) q.set('repo', gitRepo());
  const query = q.toString();
  return query ? `${path}?${query}` : path;
}
function gitRepoName(root) { return String(root || '').split('/').filter(Boolean).pop() || root; }
function saveGitWorkflowState() { localStorage.setItem('lee-git-changelists', JSON.stringify(gitUI.changeLists)); localStorage.setItem('lee-git-reviews', JSON.stringify(gitUI.reviewed)); localStorage.setItem('lee-git-review-notes', JSON.stringify(gitUI.reviewNotes)); }
function gitReviewKey(d, path) { return `${d.root || gitUI.snapshot?.root || ''}\0${d.base}\0${d.head}\0${d.mode}\0${path}`; }
function paintGitPill(d) {
  // The pill and the tree badges belong to the repository the active tab is in. A panel pinned to
  // another repository must not repaint them from a snapshot that is not theirs, because a clean
  // pill over a dirty file tree is worse than no pill.
  if (gitUI.repo) return;
  const git = $('#gitpill'); if (!git || !d) return;
  paintBranchPill(d);
  git.title = `${d.root}${d.upstream ? ' · ' + d.upstream : ' · no upstream'} · ${gitFreshness(d.fetched_at)}`;
  paintGitTree(d);
}
/* The one painter of the branch pill. `state` is `branch`, `nogit` (not a checkout), `pending` (not asked yet),
   `nofolder` (hidden: no folder is open) or `error` (the repository could not be read). */
const BRANCH_WORDS = {nogit: 'no git', pending: 'git …', error: 'git ?', nofolder: ''};
function paintBranchPill(d, state = 'branch') {
  const git = $('#gitpill'); if (!git) return;
  const n = state === 'branch' ? (d?.changes || []).length : 0;
  const name = state in BRANCH_WORDS ? BRANCH_WORDS[state] : d?.branch || (d?.head ? `detached at ${String(d.head).slice(0, 7)}` : 'detached');
  git.dataset.state = state; git.hidden = state === 'nofolder';
  git.textContent = state === 'branch' ? `${name}${n ? ' · ' + n : ''}${d?.ahead ? ' · ↑' + d.ahead : ''}${d?.behind ? ' · ↓' + d.behind : ''}` : name;
  git.className = 'lee-branch-switcher' + (state === 'branch' ? (n ? ' lee-pill-warn' : ' lee-pill-on') : state === 'error' ? ' lee-pill-warn' : '');
  git.setAttribute('aria-label', `switch branch: ${name}${n ? `, ${n} changed file${n === 1 ? '' : 's'}` : ''}`);
}
async function gitDo(op, extra = {}) {
  const started = performance.now(), name = op.replaceAll('_', ' ');
  gitUI.busy = op; status(`git ${name}…`);
  try {
    const d = await post('/git/action', {op, repo: gitUI.repo, ...extra});
    gitUI.snapshot = d; paintGitPill(d);
    // Immediately rather than up to one look later. The new signature is stored, so the next look
    // does not treat our own mutation as news, and still sees a switch to another repository.
    noteGitSignature(d); gitChanged();
    // What the operation left behind beats how long it took. A squash that staged twelve files and
    // a merge that stopped at a conflict both "complete". One call, not two, because a second
    // `status` replaces the first.
    const said = d.outcome?.summary || `complete · ${Math.round(performance.now() - started)} ms`;
    status(`git ${name} · ${said}${d.outcome?.note ? '. ' + d.outcome.note : ''}`,
           d.outcome?.note ? 'err' : 'ok');
    // `recover` is the only handle on a deleted branch or a dropped stash, and a status line is
    // gone in seconds, so the log is where it has to end up.
    leeLog('git', `${name} · ${gitRepoName(gitUI.repo || d.root || '')}`,
           [extra.branch, extra.ref, extra.message, d.outcome?.recover].filter(Boolean).join(' ') || '', 'ok');
    return d;
  } catch (e) {
    /* Reporting the failure here is what clears the running status line. Git refusing a switch
       because local changes would be overwritten is a normal, fast answer. */
    leeFail('git', name, e);
    throw e;
  } finally { gitUI.busy = ''; }
}
function gitOperationBanner(d) {
  const op = d.operation || {};
  if (!op.active) return '';
  return `<section class="lee-git-operation"><div><strong>${esc(op.active)} in progress</strong><span>Resolve the listed conflicts, then continue or abort.</span></div>` +
    `<span class="lee-spacer"></span><button data-conflict-center>resolve conflicts</button>${op.can_continue ? '<button data-operation="continue">continue</button>' : ''}${op.can_skip ? '<button data-operation="skip">skip</button>' : ''}` +
    `${op.can_abort ? '<button data-operation="abort" class="warn">abort</button>' : ''}</section>`;
}
// Why a file will not stay staged, said once, where the file list is. Git treats a filter it
// cannot run as nothing having gone wrong, so this is the only place the reason can come from.
function gitFilterBanner(d) {
  const f = d.filters || {};
  if (f.ok !== false || !f.explain) return '';
  return `<section class="lee-git-operation lee-git-filters"><div>` +
    `<strong>a filter changes files here when they are staged</strong><span>${esc(f.explain)}</span></div></section>`;
}

/* The way back from the last thing that moved this branch, because "that merge was not what I
   wanted" arrives a minute later.

   Only the guarded operations take a safepoint. Discard, branch create and delete, stash drop and
   apply_patch take none, so after one of those the newest safepoint is some older merge, and the
   banner was offering to undo that instead. It says how long ago, which is what tells the two
   apart. */
function gitUndoBanner(d) {
  const point = (d.safepoints || [])[0];
  if (!point) return '';
  const when = point.at ? gitRelative(point.at) : '';
  return `<section class="lee-git-undo"><span>last undoable: ${esc(point.describe)}` +
    `${when ? ` <small>${esc(when)}</small>` : ''}</span>` +
    `<span class="lee-spacer"></span><button data-git-undo="${esc(point.token)}">undo</button></section>`;
}

function gitNav() {
  return `<nav class="lee-git-nav" aria-label="Source control views">${[['changes','Changes'],['review','Review'],['branches','Branches'],['history','History'],['resources','Repository'],['repos','All repos']].map(([id, label]) =>
    `<button data-git-tab="${id}" class="${gitUI.tab === id ? 'active' : ''}">${label}</button>`).join('')}</nav>`;
}
function gitSummary(d) {
  return `<header class="lee-sc-branch"><div><strong>${esc(d.branch)}</strong><span>${esc(d.upstream || 'unpublished branch')}</span></div>` +
    `<span class="lee-spacer"></span>${d.behind ? `<b>↓${d.behind}</b>` : ''}${d.ahead ? `<b>↑${d.ahead}</b>` : ''}` +
    `<small title="Branch data from the remote, as of the last fetch">${esc(gitFreshness(d.fetched_at))}</small></header>`;
}
function gitChangesView(d) {
  const staged = (d.changes || []).filter(c => c.staged), unstaged = (d.changes || []).filter(c => c.unstaged);
  const allStats = [...staged.map(c => c.staged_stat), ...unstaged.map(c => c.unstaged_stat)].filter(Boolean);
  const additions = allStats.reduce((n, x) => n + (x.additions || 0), 0), deletions = allStats.reduce((n, x) => n + (x.deletions || 0), 0);
  const rows = (items, group) => items.length ? items.map(c => gitChangeRow(c, group)).join('') :
    `<div class="lee-git-empty-state"><strong>${group === 'staged' ? 'Nothing staged' : 'Working tree clean'}</strong><span>${group === 'staged' ? 'Stage files or individual hunks to prepare a commit.' : 'There are no local file changes.'}</span></div>`;
  return gitOperationBanner(d) + gitFilterBanner(d) + gitUndoBanner(d) + `<div class="lee-git-change-summary"><strong>${d.changes.length} changed file${d.changes.length === 1 ? '' : 's'}</strong><span>+${additions}</span><span>−${deletions}</span><small>${staged.length} staged · ${unstaged.length} unstaged</small></div>` + `<div class="lee-sc-actions"><button data-top="fetch">fetch</button><button data-top="pull">pull</button><button data-top="push">push</button>` +
    `${!d.upstream ? '<button data-top="publish">publish branch</button>' : ''}<button id="scstash">stash</button></div>` +
    `<div class="lee-git-selection" ${gitUI.selectedChanges.size ? '' : 'hidden'}><strong>${gitUI.selectedChanges.size} selected</strong><button data-selected-action="stage">stage</button><button data-selected-action="unstage">unstage</button><button data-selected-action="changelist">move to changelist</button><button data-selected-action="clear">clear</button></div>` +
    `<form id="sccommit" class="lee-sc-commit"><label>Commit message<textarea rows="3" placeholder="Describe this change" aria-label="Commit message">${esc(gitUI.commitDraft)}</textarea></label>` +
    `<label class="lee-git-check"><input type="checkbox" name="amend"> amend previous commit</label><button type="button" id="screviewstaged" ${staged.length ? '' : 'disabled'}>review staged</button><button ${staged.length ? '' : 'disabled'}>commit ${staged.length || ''}</button></form>` +
    `<details class="lee-sc-group" open><summary><span>Staged changes</span><b>${staged.length}</b>${staged.length ? '<button type="button" id="scunstageall">unstage all</button>' : ''}</summary><div>${rows(staged, 'staged')}</div></details>` +
    `<details class="lee-sc-group" open><summary><span>Changes</span><b>${unstaged.length}</b>${unstaged.length ? '<button type="button" id="scstageall">stage all</button>' : ''}</summary><div>${rows(unstaged, 'unstaged')}</div></details>` +
    `<details class="lee-sc-group"><summary><span>Stashes</span><b>${(d.stashes || []).length}</b></summary><div class="lee-sc-refs">` +
    `${(d.stashes || []).map(s => `<div class="lee-sc-ref" data-stash="${esc(s.ref)}"><span>${esc(s.ref)}</span><small>${esc(s.subject)} · ${gitRelative(s.timestamp)}</small><button data-apply>apply</button><button data-pop>pop</button><button data-drop>drop</button></div>`).join('') || '<div class="lee-dim lee-git-empty">No stashes</div>'}</div></details>`;
}
function gitBranchesView(d) {
  let branches = [...(d.branches || [])];
  const q = gitUI.branchQuery.toLowerCase();
  if (q) branches = branches.filter(b => `${b.name} ${b.subject} ${b.author}`.toLowerCase().includes(q));
  if (gitUI.branchScope === 'local') branches = branches.filter(b => !b.remote);
  if (gitUI.branchScope === 'remote') branches = branches.filter(b => b.remote);
  if (gitUI.branchScope === 'unmerged') branches = branches.filter(b => !b.merged);
  branches.sort((a, b) => b.timestamp - a.timestamp);
  return `<div class="lee-git-filter"><input id="gitbranchfilter" class="lee-input" value="${esc(gitUI.branchQuery)}" placeholder="Filter branches, commits, authors…">` +
    `<select id="gitbranchscope"><option value="all">all refs</option><option value="local">local</option><option value="remote">remote</option><option value="unmerged">unmerged</option></select><button id="scbranch">new branch</button></div>` +
    `<div class="lee-git-branch-list">${branches.map((b, index) => `<article class="lee-git-branch-row${b.current ? ' current' : ''}${b.latest ? ' latest' : ''}" data-branch="${esc(b.name)}">` +
      `<button data-switch ${b.current ? 'disabled' : ''} title="${b.remote ? 'create local tracking branch' : 'switch branch'}">${b.current ? '●' : '○'}</button><div class="lee-git-branch-copy"><strong>${esc(b.name)}</strong>` +
      `<span>${esc(b.subject || 'No commit subject')}</span><small>${esc(b.author)} · ${gitRelative(b.timestamp)} · ${esc(b.oid)}</small></div>` +
      `<div class="lee-git-badges">${index === 0 ? '<i>latest commit</i>' : ''}${b.default ? '<i>default</i>' : ''}${b.remote ? '<i>remote</i>' : ''}${b.merged ? '<i>merged</i>' : '<i>unmerged</i>'}${b.track ? `<i>${esc(b.track)}</i>` : ''}</div>` +
      `${b.current ? '<span></span>' : '<button data-compare title="Review changes proposed by this branch">review</button>'}${b.remote ? '<span></span>' : '<button data-more title="branch actions">•••</button>'}</article>`).join('') || '<div class="lee-git-empty-state"><strong>No matching branches</strong><span>Change the filter or fetch remote refs.</span></div>'}</div>` +
    `<details class="lee-sc-group"><summary><span>Tags</span><b>${(d.tags || []).length}</b><button id="sctag">new tag</button></summary><div class="lee-sc-meta">` +
    `${(d.tag_details || []).map(t => `<span class="lee-sc-tag" data-tag="${esc(t.name)}">${esc(t.name)} <small>${gitRelative(t.timestamp)}</small><button data-delete-tag>×</button></span>`).join('') || '<span>no tags</span>'}</div></details>`;
}
function gitReviewView(d) {
  if (!gitUI.reviewBase) gitUI.reviewBase = d.branch;
  if (!gitUI.reviewHead) gitUI.reviewHead = (d.branches || []).find(b => !b.current && !b.merged)?.name || (d.branches || []).find(b => !b.current)?.name || d.upstream || d.branch;
  const refs = [...new Set([d.branch, ...(d.branches || []).map(b => b.name), ...(d.tags || [])])];
  const options = refs.map(ref => `<option value="${esc(ref)}"></option>`).join('');
  const r = gitUI.review;
  const reviewedCount = r ? r.files.filter(f => gitUI.reviewed[gitReviewKey({...r, root: d.root}, f.path)]).length : 0;
  const summary = r ? `<div class="lee-git-review-summary"><strong>${r.summary.files} files</strong><span class="add">+${r.summary.additions}</span><span class="del">−${r.summary.deletions}</span><span>${reviewedCount}/${r.summary.files} reviewed</span><button id="gitreviewcopynotes">copy notes</button></div>` : '';
  const commits = r?.commits.length ? `<details class="lee-git-review-commits"><summary>${r.commits.length} incoming commit${r.commits.length === 1 ? '' : 's'}</summary>${r.commits.map(c => `<button data-commit="${esc(c.oid)}"><code>${esc(c.short)}</code><span>${esc(c.subject)}</span><small>${esc(c.author)} · ${gitRelative(c.timestamp)}</small></button>`).join('')}</details>` : '';
  const alternative = r?.snapshot_alternative?.files ? `<div class="lee-git-review-direction"><strong>No changes are proposed by ${esc(r.head)}</strong><span>${esc(r.head)} is already contained in ${esc(r.base)}. The refs still have ${r.snapshot_alternative.files} file difference${r.snapshot_alternative.files === 1 ? '' : 's'} because ${esc(r.base)} is ${r.base_only} commit${r.base_only === 1 ? '' : 's'} ahead.</span><button id="gitreviewsnapshot">show ${r.snapshot_alternative.files} snapshot differences</button><button id="gitreviewswap">review the opposite direction</button></div>` : '';
  const files = r?.files.length ? r.files.map((f, i) => {
    const reviewed = !!gitUI.reviewed[gitReviewKey({...r, root: d.root}, f.path)];
    const note = gitUI.reviewNotes[gitReviewKey({...r, root: d.root}, f.path)];
    return `<button class="lee-git-review-file${f.path === gitUI.reviewFile ? ' active' : ''}${reviewed ? ' reviewed' : ''}" data-review-path="${esc(f.path)}" data-review-index="${i}"><b>${reviewed ? '✓' : f.status}</b><span>${f.old_path ? `${esc(f.old_path)} → ` : ''}${esc(f.path)}${note ? ' · note' : ''}</span><small>${f.binary ? 'binary' : `+${f.additions} −${f.deletions}`}</small></button>`;
  }).join('') : r ? '<div class="lee-git-empty-state"><strong>No files in this review direction</strong><span>Swap base and branch, or use complete snapshots to see content that differs.</span></div>' : '<div class="lee-git-empty-state"><strong>Choose a branch to review</strong><span>Review proposed branch changes or compare complete snapshots.</span></div>';
  return `<section class="lee-git-review-controls"><label>Base<input id="gitreviewbase" list="gitreviewrefs" value="${esc(gitUI.reviewBase)}"></label><label>Branch<input id="gitreviewhead" list="gitreviewrefs" value="${esc(gitUI.reviewHead)}"></label>` +
    `<datalist id="gitreviewrefs">${options}</datalist><button id="gitreviewcontrolswap" title="Swap base and branch">swap direction</button><select id="gitreviewmode"><option value="review">proposed changes</option><option value="snapshot">complete snapshots</option></select><button id="gitreviewload">review</button></section>` + summary + alternative + commits +
    `<div class="lee-git-review-workspace"><header><strong>Changed files</strong><span>Click a file to open its diff in an editor tab.</span></header><aside class="lee-git-review-files">${files}</aside></div>`;
}
function gitCommitInspector() {
  const c = gitUI.selectedCommit; if (!c) return '';
  const files = c.files.map(f => `<button class="lee-git-commit-file" data-commit-file="${esc(f.path)}"><b>${esc(f.status)}</b><span>${f.old_path ? `${esc(f.old_path)} → ` : ''}${esc(f.path)}</span><small>${f.binary ? 'binary' : `+${f.additions} −${f.deletions}`}</small></button>`).join('');
  return `<article class="lee-git-commit-inspector"><header><div><strong>${esc(c.message.split('\n')[0])}</strong><span>${esc(c.author)} · ${gitRelative(c.timestamp)} · ${esc(c.short)}</span></div><button data-cherry>cherry-pick</button><button data-revert>revert</button><button data-reset>reset…</button><button data-close-commit aria-label="Close commit details">×</button></header><section class="lee-git-commit-stats"><b>${c.summary.files} files</b><span>+${c.summary.additions}</span><span>−${c.summary.deletions}</span><code>${esc(c.oid)}</code></section>${c.message.includes('\n') ? `<div class="lee-git-commit-message">${esc(c.message)}</div>` : ''}<details open><summary>changed files</summary><div>${files}</div></details></article>`;
}
function gitHistoryView(d) {
  const refs = [...new Set([...(d.branches || []).map(b => b.name), ...(d.tags || [])])];
  if (!gitUI.compareTo) gitUI.compareTo = d.branch;
  if (!gitUI.compareFrom) gitUI.compareFrom = (d.branches || []).find(b => b.default && b.name !== d.branch)?.name || (d.branches || []).find(b => !b.current)?.name || d.upstream || d.branch;
  const suggestions = refs.map(ref => `<option value="${esc(ref)}"></option>`).join('');
  return `<div class="lee-git-filter"><input id="githistoryfilter" class="lee-input" value="${esc(gitUI.historyQuery)}" placeholder="Search commit messages…"><button id="githistorygo">search</button>` +
    `<select id="githistoryref"><option value="--all">all refs</option>${(d.branches || []).map(b => `<option value="${esc(b.name)}">${esc(b.name)}</option>`).join('')}</select><button id="gitreflog">reflog</button></div>` +
    `<section class="lee-git-compare"><header><strong>Compare snapshots</strong><span>All file changes, including branches behind current</span></header>` +
    `<div class="lee-git-compare-fields"><label>From (base)<input id="gitcompareleft" list="gitcomparerefs" value="${esc(gitUI.compareFrom)}" autocomplete="off"></label>` +
    `<button id="gitcompareswap" title="Swap comparison direction" aria-label="Swap comparison direction">⇄</button><label>To (target)<input id="gitcompareright" list="gitcomparerefs" value="${esc(gitUI.compareTo)}" autocomplete="off"></label>` +
    `<datalist id="gitcomparerefs">${suggestions}</datalist><button id="gitcomparego">compare files</button></div><small>Shows the exact change needed to turn the base snapshot into the target.</small></section>` +
    gitCommitInspector() + `<div id="githistoryrows" class="lee-git-history">${gitUI.history.length ? gitUI.history.map(c => `<button class="lee-git-commit-row${gitUI.selectedCommit?.oid === c.oid ? ' active' : ''}" data-history-commit="${c.oid}"><span class="lee-git-graph">${c.parents.length > 1 ? '◆' : '●'}</span><span><strong>${esc(c.subject)}</strong><small>${esc(c.author)} · ${gitRelative(c.timestamp)} · ${esc(c.short)}${c.decoration ? ' · ' + esc(c.decoration) : ''}</small></span></button>`).join('') : '<div class="lee-git-loading"><span></span><span></span><span></span><small>reading commit graph</small></div>'}</div>`;
}
function gitResourcesView(d) {
  const hosted = (d.remotes || []).find(r => r.web_url);
  const pr = hosted ? `${hosted.web_url}/${hosted.web_url.includes('gitlab') ? '-/merge_requests/new?merge_request[source_branch]=' : 'compare/' + encodeURIComponent(d.branch) + '?expand=1'}${hosted.web_url.includes('gitlab') ? encodeURIComponent(d.branch) : ''}` : '';
  return `<section class="lee-git-resource"><header><strong>Remotes</strong>${pr ? `<button data-hosted-pr data-url="${esc(pr)}">open pull request</button>` : ''}<button id="gitaddremote">add remote</button></header><div class="lee-sc-meta">` +
    `${(d.remotes || []).map(r => `<article data-remote="${esc(r.name)}"><strong>${esc(r.name)}</strong><code>${esc(r.fetch)}</code><code>${esc(r.push)}</code><span>${r.web_url ? `<button data-open-remote data-url="${esc(r.web_url)}">open host</button>` : ''}<button data-fetch-remote>fetch</button><button data-edit-remote>edit</button><button data-remove-remote class="warn">remove</button></span></article>`).join('') || '<div class="lee-git-empty-state"><strong>No remotes</strong><span>Add a remote to fetch, publish, and collaborate.</span></div>'}</div></section>` +
    `<section class="lee-git-resource"><header><strong>Worktrees</strong><button id="gitaddworktree">add worktree</button></header><div id="gitworktrees"><div class="lee-git-loading"><small>reading worktrees</small></div></div></section>` +
    `<section class="lee-git-resource"><header><strong>Submodules</strong></header><div id="gitsubmodules"><div class="lee-git-loading"><small>reading submodules</small></div></div></section>`;
}
function gitScope() {
  if (!gitUI.repo) return '';
  return `<div class="lee-git-scope" title="The branch pill, tree badges and editor change marks still follow the file you have open."><b>${esc(gitRepoName(gitUI.repo))}</b>` +
    `<span>pinned</span><span class="lee-spacer"></span><button id="gitscopeclear">follow active tab</button></div>`;
}
function gitRepoBadges(r) {
  if (r.error) return `<i class="warn">${esc(r.error)}</i>`;
  return [r.changed ? `<i class="warn">${r.changed} changed</i>` : '<i>clean</i>',
    r.behind ? `<i class="warn">↓${r.behind}</i>` : '', r.ahead ? `<i>↑${r.ahead}</i>` : '',
    r.upstream ? '' : '<i>unpublished</i>', r.off_branch ? '<i class="warn">off branch</i>' : '',
    r.unreleased ? `<i>${r.unreleased} since ${esc(r.tag)}</i>` : '',
    r.operation ? `<i class="warn">${esc(r.operation)} in progress</i>` : ''].filter(Boolean).join('');
}
function gitReposView() {
  const d = gitUI.repos;
  if (!d) return '<div class="lee-git-loading"><span></span><span></span><span></span><small>reading repositories</small></div>';
  const s = d.summary || {}, rows = d.repos || [];
  const results = gitUI.reposResults.length ? `<details class="lee-sc-group" open><summary><span>Last run</span><b>${gitUI.reposResults.length}</b></summary>` +
    `<div class="lee-git-repo-results">${gitUI.reposResults.map(r => `<article class="${r.ok === false ? 'failed' : r.skipped ? 'skipped' : 'done'}">` +
      `<strong>${esc(r.name || r.spec || '')}</strong><span>${esc(r.error || r.skipped || r.output || 'done')}</span></article>`).join('')}</div></details>` : '';
  const list = rows.length ? rows.map(r => `<article class="lee-git-repo-row${r.root === gitUI.repo ? ' active' : ''}${r.off_branch ? ' off-branch' : ''}${gitUI.reposBusy?.has(r.root) ? ' working' : ''}" data-repo="${esc(r.root)}" title="${esc(r.root)}">` +
    `<button data-repo-open title="Point source control at this repository">${gitUI.reposBusy?.has(r.root) ? '<span class="lee-spin"></span>' : (r.root === gitUI.repo ? '●' : '○')}</button>` +
    `<div class="lee-git-repo-copy"><strong>${esc(r.name)}</strong><span>${esc(r.branch || 'no branch')}${r.upstream ? ' · ' + esc(r.upstream) : ''}</span>` +
    `<small>${esc(r.last_commit?.subject || 'no commits yet')}${r.last_commit?.timestamp ? ' · ' + gitRelative(r.last_commit.timestamp) : ''}</small>` +
    `<div class="lee-git-badges">${gitRepoBadges(r)}<button data-repo-fetch title="Fetch this repository">fetch</button></div></div>` +
    `<button data-repo-remove title="Stop listing this repository here" aria-label="Stop listing this repository">×</button></article>`).join('') :
    `<div class="lee-git-empty-state"><strong>No repositories in this workspace</strong><span>Open a folder that is a checkout or holds them, clone one, or add a checkout from elsewhere.</span></div>`;
  return `<section class="lee-git-repos-summary"><strong>${s.repos || 0} repositor${s.repos === 1 ? 'y' : 'ies'}</strong>` +
    `${s.dirty ? `<span class="warn">${s.dirty} dirty</span>` : '<span>all clean</span>'}` +
    `${s.behind ? `<span class="warn">${s.behind} behind</span>` : ''}${s.ahead ? `<span>${s.ahead} ahead</span>` : ''}` +
    `${s.off_branch ? `<span class="warn">${s.off_branch} off branch</span>` : ''}` +
    `${s.unreleased ? `<span>${s.unreleased} unreleased</span>` : ''}${s.errors ? `<span class="warn">${s.errors} unreadable</span>` : ''}</section>` +
    `<div class="lee-sc-actions"><button data-repos-op="status">refresh</button><button data-repos-op="fetch">fetch all</button>` +
    `<button data-repos-op="pull">pull all</button><button data-repos-op="push">push all</button>` +
    `<button id="gitrepoclone">clone…</button><button id="gitrepoadd">add repository…</button></div>` +
    `<div class="lee-git-filter"><input id="gitrepoexpect" class="lee-input" value="${esc(gitUI.expect)}" placeholder="Expected branch. Default: ${esc(d.expected_branch || 'the one most share')}" aria-label="Expected branch"></div>` +
    `<div class="lee-git-repo-list">${list}</div>` + results;
}
async function loadGitRepos() {
  try { gitUI.repos = await api('/git/repos' + (gitUI.expect ? '?expect=' + encodeURIComponent(gitUI.expect) : '')); }
  catch (e) { return leeFail('git', 'workspace repositories', e); }
  if (gitUI.tab === 'repos') renderGitPanel(gitUI.snapshot);
}
async function gitReposDo(op, extra = {}) {
  const started = performance.now();
  const targets = (extra.paths && extra.paths.length ? extra.paths
                   : ((gitUI.repos && gitUI.repos.repos) || []).map(r => r.root));
  /* The fan-out answers all at once, so there is no per-repository progress to stream. Naming the
     repositories in flight beats "workspace fetch…" when one of them is slow. */
  gitUI.reposBusy = new Set(targets);
  gitUI.reposResults = [];
  if (gitUI.tab === 'repos') renderGitPanel(gitUI.snapshot);
  status(`workspace ${op} · ${targets.length} ${targets.length === 1 ? 'repository' : 'repositories'}…`);
  try {
    const d = await post('/git/repos/action', {op, expect: gitUI.expect, ...extra});
    gitUI.repos = d; gitUI.reposResults = d.results || [];
    const failed = gitUI.reposResults.filter(r => r.ok === false).length;
    const skipped = gitUI.reposResults.filter(r => r.ok !== false && r.skipped).length;
    const done = gitUI.reposResults.length - failed - skipped;
    status(`workspace ${op}: ${done} done · ${skipped} skipped · ${failed} failed · ${Math.round(performance.now() - started)} ms`,
           failed ? 'err' : 'ok');
    for (const r of gitUI.reposResults) {
      leeLog('git', `${op} · ${r.name}${r.skipped ? ': ' + r.skipped : ''}`,
             r.ok === false ? (r.error || 'failed') : (r.output || ''), r.ok === false ? 'err' : '');
    }
    if (failed) showLog('git');       // one repository refusing is the reason to read the log
    if (gitUI.repo && !(d.repos || []).some(r => r.root === gitUI.repo)) gitUI.repo = '';
    gitUI.snapshot = null;
    await renderGitPanel();
    refreshProjectPills();
    return d;
  } catch (e) { leeFail('git', `workspace ${op}`, e); }
  finally {
    gitUI.reposBusy = null;
    if (gitUI.tab === 'repos') renderGitPanel(gitUI.snapshot);
  }
}
// Pinning is a scope change, not a filter: every ref, commit and review already loaded belongs to
// the repository being left, so all of it goes rather than being shown against the wrong one.
function gitForget() {
  gitUI.snapshot = null; gitUI.history = []; gitUI.review = null; gitUI.reviewFile = ''; gitUI.reviewPatch = '';
  gitUI.reviewBase = ''; gitUI.reviewHead = ''; gitUI.compareFrom = ''; gitUI.compareTo = '';
  gitUI.selectedCommit = null; gitUI.selectedChanges.clear();
}
// `gitUI.root` is the repository the loaded refs, commit and review came from. Another one drops them.
function gitAdopt(root) {
  if (gitUI.root && root !== gitUI.root) gitForget();
  gitUI.root = root;
}
async function gitPinRepo(root, tab = 'changes') {
  gitUI.repo = String(root || '');
  gitForget(); gitUI.root = '';
  gitUI.tab = tab;
  await renderGitPanel();
  if (!gitUI.repo) refreshProjectPills();
}

// Both panels are about a project rather than a file, so they ask which repository, as the
// source-control panel does. Empty means the one the active tab is in.
const wfUI = {data: null, runs: null, env: null, catalogue: null, docker: null, open: '', view: 'graph', preview: '', busy: ''};
const relUI = {data: null, busy: '', poll: 0};
function projectRepo() { return gitUI.repo || ''; }
function projectQuery(params = {}) {
  const q = new URLSearchParams(params);
  if (projectRepo()) q.set('repo', projectRepo());
  const query = q.toString();
  return query ? `?${query}` : '';
}
function wfStatusNote(st) {
  if (!st) return '';
  if (!st.gheasy) return `<div class="lee-wf-note"><strong>Local only</strong><span>${esc(st.why)}</span><code>pip install gheasy</code></div>`;
  if (!st.repo) return '<div class="lee-wf-note"><strong>No GitHub remote</strong><span>Runs and secrets need one; the files below still read.</span></div>';
  if (!st.token) return `<div class="lee-wf-note"><strong>No GITHUB_TOKEN</strong><span>Set it in Environment below and the run history appears.</span></div>`;
  return '';
}
function wfJobBox(job, run) {
  const jr = (run?.jobs || []).find(j => j.name === job.name || j.name === job.id);
  const state = jr ? (jr.conclusion || jr.status || '') : '';
  return `<article class="lee-wf-job ${state ? 'state-' + esc(state) : ''}" data-job="${esc(job.id)}">` +
    `<header><strong>${esc(job.name)}</strong>${state ? `<i>${esc(state)}</i>` : ''}</header>` +
    `<small>${esc(job.runs_on || job.uses || '')}${job.environment ? ' · ' + esc(job.environment) : ''}</small>` +
    `${job.if ? `<code class="lee-wf-if">if ${esc(job.if)}</code>` : ''}` +
    `<ol class="lee-wf-steps">${job.steps.map(st => `<li title="${esc(st.uses || st.run)}">${esc(st.name)}</li>`).join('')}</ol></article>`;
}
function wfGraph(wf, run) {
  if (wf.error) return `<div class="lee-git-empty-state"><strong>${esc(wf.file)}</strong><span>${esc(wf.error)}</span></div>`;
  if (!wf.jobs.length) return `<div class="lee-git-empty-state"><strong>No jobs</strong><span>${esc(wf.file)} declares no jobs.</span></div>`;
  const byId = Object.fromEntries(wf.jobs.map(j => [j.id, j]));
  return `<div class="lee-wf-graph">${wf.levels.map((row, i) => `<div class="lee-wf-level">` +
    `${i ? '<span class="lee-wf-edge" aria-hidden="true"></span>' : ''}` +
    `<div class="lee-wf-row">${row.map(id => wfJobBox(byId[id], run)).join('')}</div></div>`).join('')}</div>`;
}
function wfRunRow(r) {
  const state = r.conclusion || r.status || '';
  return `<button class="lee-wf-run state-${esc(state)}" data-run="${r.id}" data-url="${esc(r.url)}">` +
    `<b>${state === 'success' ? '✓' : state === 'failure' ? '✗' : state === 'in_progress' ? '•' : '·'}</b>` +
    `<span><strong>${esc(r.title || r.name || r.file)}</strong><small>${esc(r.file)} · ${esc(r.branch)} · ${esc(r.event)}${r.actor ? ' · ' + esc(r.actor) : ''}</small></span>` +
    `<small>#${r.number || ''}</small></button>`;
}
function wfPickRows(cat) {
  if (!cat) return '<div class="lee-git-loading"><span></span><span></span><span></span><small>reading the project</small></div>';
  const d = cat.detect || {};
  const tags = Object.entries(d).filter(([k, v]) => v === true).map(([k]) => `<i>${esc(k)}</i>`).join('');
  const rows = (cat.workflows || []).map(w => `<article class="lee-wf-pick${w.recommended ? ' recommended' : ''}${w.present ? ' present' : ''}" data-pick="${esc(w.id)}">` +
    `<div><strong>${esc(w.name)}</strong><small>${esc(w.doc)}</small>` +
    `${w.recommended ? `<i class="lee-wf-because">recommended · ${esc(w.why)}</i>` : ''}</div>` +
    `<span class="lee-wf-pickfile">${esc(w.file)}</span>` +
    `<button data-pick-preview>preview</button>` +
    `${w.present ? '<span class="lee-wf-has">already here</span>' : '<button data-pick-add>add</button>'}</article>`).join('');
  return `<div class="lee-wf-detect"><strong>detected</strong>${tags || '<i>nothing conclusive</i>'}` +
    `${d.build ? `<code>${esc(d.build)}</code>` : d.build_why ? `<small>${esc(d.build_why)}</small>` : ''}</div>` +
    `<div class="lee-wf-picks">${rows}</div>`;
}
// Where `refresh`'s answer about what GitHub has is shown. Secret values are not readable by
// GitHub's design, so remote presence is all there is to show for one.
function wfRemoteMark(remote, key) {
  if (!remote) return '';
  const hit = (remote.secrets || []).find(s => s.name === key) || (remote.variables || []).find(v => v.name === key);
  if (!hit) return '<span class="lee-wf-remote missing" title="not on GitHub">·</span>';
  const when = String(hit.updated_at || '').slice(0, 10);
  return `<span class="lee-wf-remote" title="on GitHub${when ? ', updated ' + when : ''}">gh</span>`;
}
function wfRemoteExtra(remote, entries) {
  if (!remote) return '';
  const declared = new Set((entries || []).map(e => e.key));
  const extra = [...(remote.secrets || []), ...(remote.variables || [])].map(x => x.name).filter(n => !declared.has(n));
  return extra.length ? `<div class="lee-wf-remote-extra">on GitHub but not declared here: ${extra.map(esc).join(', ')}</div>` : '';
}
function wfEnvRows(entries, remote) {
  if (!entries?.length) return '<div class="lee-git-empty-state"><strong>Nothing declared</strong><span>Add <code>env_schema</code> to .gheasy/config.json, or a release step that needs a key.</span></div>';
  return entries.map(e => `<article class="lee-wf-env${e.set ? ' is-set' : ''}" data-env="${esc(e.key)}">` +
    `<div><strong>${esc(e.key)}</strong><small>${e.target}${e.declared ? '' : ' · from a release step'}</small></div>` +
    `<span class="lee-wf-envval">${e.secret ? (e.set ? '••••••••' : 'not set') : esc(e.value || 'not set')}</span>` +
    wfRemoteMark(remote, e.key) +
    `<button data-env-set>${e.set ? 'change' : 'set'}</button>${e.set ? '<button data-env-unset aria-label="remove">×</button>' : ''}</article>`).join('')
    + wfRemoteExtra(remote, entries);
}
function renderWorkflowsPanel() {
  const host = $('#workflowspanel'); if (!host) return;
  const d = wfUI.data;
  if (!d) { host.innerHTML = '<div class="lee-git-loading"><span></span><span></span><span></span><small>reading workflows</small></div>'; return; }
  const st = d.status || {};
  const wf = d.workflows.find(w => w.file === wfUI.open) || d.workflows[0];
  if (wf) wfUI.open = wf.file;
  const tabs = d.workflows.map(w => `<button data-wf="${esc(w.file)}" class="${w.file === wfUI.open ? 'active' : ''}">${esc(w.name)}</button>`).join('');
  const runsFor = (wfUI.runs || []).filter(r => !wf || !r.file || r.file === wf.file);
  const body = wfUI.view === 'runs'
    ? `<div class="lee-wf-runs">${runsFor.length ? runsFor.map(wfRunRow).join('')
        : `<div class="lee-git-empty-state"><strong>No runs</strong><span>${st.token ? 'This workflow has not run yet.' : 'Connect a token to see run history.'}</span></div>`}</div>`
    : wfUI.view === 'add'
    ? wfPickRows(wfUI.catalogue)
    : wfUI.view === 'build'
    ? renderBuilder()
    : wfUI.view === 'yaml'
    ? `<pre class="lee-wf-yaml">${esc(wfUI.preview || 'Generate to preview the workflow gheasy would write from .gheasy/config.json.')}</pre>`
    : wf ? wfGraph(wf, wfUI.runJobs) : '<div class="lee-git-empty-state"><strong>No workflows</strong><span>This project has no .github/workflows yet.</span></div>';
  host.innerHTML = wfStatusNote(st) +
    `<header class="lee-sc-branch"><div><strong>${esc(st.repo || d.root.split('/').pop())}</strong><span>${d.workflows.length} workflow${d.workflows.length === 1 ? '' : 's'}${d.config ? ' · gheasy config' : ''}</span></div></header>` +
    `<nav class="lee-git-nav" aria-label="Workflow views">${[['graph', 'Jobs'], ['add', 'Add'], ['build', 'Build'], ['runs', 'Runs'], ['env', 'Environment']].map(([id, label]) =>
      `<button data-wf-view="${id}" class="${wfUI.view === id ? 'active' : ''}">${label}</button>`).join('')}</nav>` +
    (wfUI.view === 'add' || wfUI.view === 'build'
      ? `<main class="lee-wf-body">${body}</main>`
      : wfUI.view === 'env'
      ? `<div class="lee-sc-actions"><button data-wf-env="refresh">refresh</button>` +
        `${st.gh_cli && !st.gh_auth ? '<button data-wf-env="auth">gh auth login…</button>' : ''}` +
        `<button data-wf-env="push" ${st.gh_auth ? '' : 'title="pushing uses the GitHub CLI"'}>push declared to GitHub</button>` +
        `<button data-wf-env="add">add key…</button></div>` +
        `<div class="lee-wf-envs">${wfEnvRows(wfUI.env?.entries, wfUI.env?.remote)}</div>`
      : `<div class="lee-wf-tabs">${tabs}</div>` +
        `<div class="lee-sc-actions">${wf?.dispatchable ? '<button data-wf-op="dispatch">run workflow</button>' : ''}` +
        `<button data-wf-op="open">open file</button><button data-wf-op="edit">edit in builder</button>` +
        `<button data-wf-op="generate">from gheasy config</button>` +
        `${d.config ? '<button data-wf-op="write">write gheasy.yml</button>' : ''}` +
        `<button data-wf-op="docker">Dockerfile…</button></div>` +
        `<main class="lee-wf-body">${body}</main>`);
  wireWorkflowsPanel(host, d, wf);
  if (wfUI.view === 'build') wireBuilder(host);
}
function wireWorkflowsPanel(host, d, wf) {
  host.querySelectorAll('[data-wf-view]').forEach(b => b.onclick = () => {
    wfUI.view = b.dataset.wfView; renderWorkflowsPanel();
    if (wfUI.view === 'runs' && !wfUI.runs) loadWorkflowRuns();
    if (wfUI.view === 'add' && !wfUI.catalogue) loadWorkflowCatalogue();
    if (wfUI.view === 'build' && !bldUI.vocab) loadBuilder(wfUI.open);
    if (wfUI.view === 'env' && !wfUI.env) loadWorkflowEnv();
  });
  host.querySelectorAll('[data-wf]').forEach(b => b.onclick = () => { wfUI.open = b.dataset.wf; wfUI.runJobs = null; renderWorkflowsPanel(); });
  host.querySelectorAll('[data-wf-op]').forEach(b => b.onclick = () => workflowOp(b.dataset.wfOp, wf));
  host.querySelector('[data-wf-op="edit"]')?.addEventListener('click', () => { wfUI.view = 'build'; loadBuilder(wf?.file); });
  host.querySelectorAll('.lee-wf-pick').forEach(row => {
    const id = row.dataset.pick;
    row.querySelector('[data-pick-preview]').onclick = () => pickWorkflow('preview', id);
    row.querySelector('[data-pick-add]')?.addEventListener('click', () => pickWorkflow('add', id));
  });
  host.querySelectorAll('[data-run]').forEach(b => b.onclick = async () => {
    try { wfUI.runJobs = {jobs: (await api('/workflows/jobs' + projectQuery({id: b.dataset.run}))).jobs};
          wfUI.view = 'graph'; renderWorkflowsPanel();
          status('run ' + b.dataset.run + ': job results are on the graph', 'ok'); }
    catch (e) { status(e.message || String(e), 'err'); }
  });
  host.querySelectorAll('[data-env]').forEach(row => {
    const key = row.dataset.env;
    row.querySelector('[data-env-set]').onclick = async () => {
      const entry = (wfUI.env?.entries || []).find(e => e.key === key) || {};
      const value = await inputDialog(`set ${key}`, entry.secret ? 'Value (stored in your keychain, never shown again)' : 'Value',
                                      entry.secret ? '' : (entry.value || ''), entry.secret ? 'paste the token' : 'value');
      if (value) envOp('set', {key, value, secret: !!entry.secret});
    };
    row.querySelector('[data-env-unset]')?.addEventListener('click', async () => {
      if (await confirmDialog('remove value', `Remove ${key} from the keychain and the env file?`, 'remove')) envOp('unset', {key});
    });
  });
  host.querySelectorAll('[data-wf-env]').forEach(b => b.onclick = async () => {
    const op = b.dataset.wfEnv;
    if (op === 'refresh') return loadWorkflowEnv(true);
    // Authenticating is a conversation with a browser and a one-time code, so the button opens
    // the real `gh auth login`.
    if (op === 'auth') { await openTerm('gh-auth'); return status('finish the login in the terminal, then refresh', 'ok'); }
    if (op === 'push') {
      if (await confirmDialog('push to GitHub', 'Send every declared value to this repository as a secret or a variable?', 'push')) envOp('push', {});
      return;
    }
    const key = await inputDialog('add key', 'Environment key', '', 'GITHUB_TOKEN');
    if (!key) return;
    const value = await inputDialog(`set ${key}`, 'Value (stored in your keychain)', '', 'paste the value');
    if (value) envOp('set', {key, value, secret: true});
  });
}
async function leeWorkflows() {
  try { wfUI.data = await api('/workflows' + projectQuery()); }
  catch (e) { const host = $('#workflowspanel'); if (host) host.innerHTML = `<div class="lee-git-empty-state"><strong>No project</strong><span>${esc(e.message || e)}</span></div>`; return; }
  renderWorkflowsPanel();
  if (wfUI.view === 'runs' && !wfUI.runs) loadWorkflowRuns();
  if (wfUI.view === 'add' && !wfUI.catalogue) loadWorkflowCatalogue();
  if (wfUI.view === 'env' && !wfUI.env) loadWorkflowEnv();
}
window.leeWorkflows = leeWorkflows;
async function loadWorkflowCatalogue() {
  try { wfUI.catalogue = await api('/workflows/catalogue' + projectQuery()); }
  catch (e) { status(e.message || String(e), 'err'); return; }
  renderWorkflowsPanel();
}
async function pickWorkflow(op, id) {
  try {
    const d = await post('/workflows/action', {op: op === 'add' ? 'add' : 'preview', repo: projectRepo(), workflow: id});
    if (d.yaml) { wfUI.preview = d.yaml; wfUI.view = 'yaml'; }
    if (d.path) { status(`wrote ${d.path}`, 'ok'); wfUI.catalogue = null; loadWorkflowCatalogue(); }
    if (d.workflows) wfUI.data = {...wfUI.data, workflows: d.workflows, status: d.status};
    renderWorkflowsPanel();
  } catch (e) { status(e.message || String(e), 'err'); }
}
async function loadWorkflowRuns() {
  if (!wfUI.data?.status?.token) { wfUI.runs = []; return renderWorkflowsPanel(); }
  try { wfUI.runs = (await api('/workflows/runs' + projectQuery({limit: 20}))).runs; }
  catch (e) { wfUI.runs = []; status(e.message || String(e), 'err'); }
  renderWorkflowsPanel();
}
async function loadWorkflowEnv(remote = false) {
  try { wfUI.env = await api('/workflows/env' + projectQuery(remote ? {remote: true} : {})); }
  catch (e) { status(e.message || String(e), 'err'); return; }
  renderWorkflowsPanel();
}
async function envOp(op, extra) {
  try {
    const d = await post('/workflows/env/action', {op, repo: projectRepo(), ...extra});
    wfUI.env = {...(wfUI.env || {}), entries: d.entries};
    // A push changes what GitHub has, so a listing already on screen is now wrong.
    if (op === 'push' && wfUI.env.remote) return loadWorkflowEnv(true);
    if (d.results) {
      const failed = d.results.filter(r => r.ok === false).length;
      status(`pushed ${d.results.filter(r => r.ok && !r.skipped).length} · skipped ${d.results.filter(r => r.skipped).length} · failed ${failed}`, failed ? 'err' : 'ok');
    } else if (op === 'set' && d.file && !d.keychain) status(`${extra.key} saved in ${d.file}, which only you can read: this computer has no keychain`, 'err');
    else status(`${extra.key} ${op === 'unset' ? 'removed' : 'saved'}`, 'ok');
    renderWorkflowsPanel();
  } catch (e) { status(e.message || String(e), 'err'); }
}
async function workflowOp(op, wf) {
  try {
    if (op === 'open') { if (wf) leeOpenFile(wf.path); return; }
    if (op === 'edit') return;                       // wired separately: it changes view, not state
    if (op === 'docker') {
      const d = await api('/workflows/docker' + projectQuery());
      if (d.why) return status(d.why, 'err');
      if (d.dockerfile) return status('this project already has a Dockerfile', 'ok');
      if (!await confirmDialog('write Dockerfile', `dockeasy detected:\n\n${d.base}\n\nWrite this Dockerfile?`, 'write')) return;
      op = 'dockerfile';
    }
    if (op === 'dispatch') {
      const ref = await inputDialog('run workflow', 'Branch or tag to run on', '', 'leave empty for the current branch');
      if (ref === null) return;
      const d = await post('/workflows/action', {op, repo: projectRepo(), workflow: wf.file, ref});
      wfUI.data = {...wfUI.data, workflows: d.workflows, status: d.status};
      status(`dispatched ${wf.file} on ${d.ref}`, 'ok');
      wfUI.view = 'runs'; setTimeout(loadWorkflowRuns, 1500);
      return renderWorkflowsPanel();
    }
    const d = await post('/workflows/action', {op, repo: projectRepo()});
    wfUI.data = {...wfUI.data, workflows: d.workflows, status: d.status};
    if (d.yaml) { wfUI.preview = d.yaml; wfUI.view = 'yaml'; }
    if (d.path) status(`wrote ${d.path}`, 'ok');
    renderWorkflowsPanel();
  } catch (e) { status(e.message || String(e), 'err'); }
}

// A form over gheasy's DSL. The vocabulary comes from the server as data, so a preset added in
// leela/wfbuild.py appears here without a line of frontend.
const bldUI = {vocab: null, spec: null, yaml: '', file: '', stale: false, timer: 0};
function blankSpec() {
  return {name: 'ci', file: 'ci.yml', on: {push: 'main', pull_request: 'main', workflow_dispatch: true},
          jobs: [{preset: 'uv_test', needs: []}]};
}
function bldTrigger(t, on) {
  const v = on[t.id];
  const checked = t.kind === 'flag' ? !!v : (v !== undefined && v !== false && v !== '');
  const field = t.kind === 'flag' ? '' :
    `<input class="lee-input" data-trigger-value="${t.id}" value="${esc(checked ? String(v ?? t.default) : t.default)}" ` +
    `placeholder="${esc(t.kind === 'cron' ? 'minute hour day month weekday' : 'main, release')}" ${checked ? '' : 'disabled'}>`;
  return `<article class="lee-bld-trigger"><label><input type="checkbox" data-trigger="${t.id}" ${checked ? 'checked' : ''}>` +
    `<strong>${esc(t.label)}</strong></label><small>${esc(t.doc)}</small>${field}</article>`;
}
function bldOption(o, job, i) {
  const value = (job.options || {})[o.key] ?? o.default;
  const field = o.type === 'flag'
    ? `<input type="checkbox" data-opt="${o.key}" data-job="${i}" ${value ? 'checked' : ''}>`
    : o.type === 'lines'
    ? `<textarea class="lee-keyedit" rows="3" data-opt="${o.key}" data-job="${i}">${esc(value)}</textarea>`
    : `<input class="lee-input" data-opt="${o.key}" data-job="${i}" value="${esc(value)}">`;
  return `<label class="lee-bld-opt"><span>${esc(o.label)}</span>${field}${o.doc ? `<small>${esc(o.doc)}</small>` : ''}</label>`;
}
function bldJob(job, i, presets, spec) {
  const preset = presets.find(p => p.id === job.preset) || presets[0];
  const others = spec.jobs.map((j, n) => n === i ? null : (j.id || (presets.find(p => p.id === j.preset) || {}).job))
                         .filter(Boolean);
  const needs = (job.needs || []).join(', ');
  return `<article class="lee-bld-job" data-job="${i}">` +
    `<header><select data-preset="${i}">${presets.map(p => `<option value="${p.id}" ${p.id === job.preset ? 'selected' : ''}>${esc(p.name)}</option>`).join('')}</select>` +
    `<button data-job-up="${i}" title="move earlier" ${i ? '' : 'disabled'}>↑</button>` +
    `<button data-job-del="${i}" title="remove" aria-label="remove job">×</button></header>` +
    `<small>${esc(preset.doc)}</small>` +
    (others.length ? `<label class="lee-bld-opt"><span>waits for</span>` +
      `<input class="lee-input" data-needs="${i}" value="${esc(needs)}" placeholder="${esc(others.join(', '))}"></label>` : '') +
    preset.options.map(o => bldOption(o, job, i)).join('') + `</article>`;
}
function renderBuilder() {
  const v = bldUI.vocab;
  if (!v) return '<div class="lee-git-loading"><span></span><span></span><span></span><small>reading the presets</small></div>';
  const spec = bldUI.spec || (bldUI.spec = blankSpec());
  return `<div class="lee-bld">` +
    `<div class="lee-bld-head"><label class="lee-bld-opt"><span>file</span><input class="lee-input" id="bldfile" value="${esc(spec.file || 'ci.yml')}"></label>` +
    `<label class="lee-bld-opt"><span>name</span><input class="lee-input" id="bldname" value="${esc(spec.name || 'ci')}"></label></div>` +
    `${bldUI.stale ? '<div class="lee-wf-note"><strong>The file has been edited</strong><span>Writing replaces those edits with what this form says.</span></div>' : ''}` +
    `<section class="lee-bld-section"><header>when it runs</header>${v.triggers.map(t => bldTrigger(t, spec.on || {})).join('')}</section>` +
    `<section class="lee-bld-section"><header>what it does<button id="bldaddjob">add job</button></header>` +
    `${spec.jobs.map((j, i) => bldJob(j, i, v.presets, spec)).join('')}</section>` +
    `<div class="lee-sc-actions"><button id="bldwrite">write ${esc(spec.file || 'ci.yml')}</button><button id="bldyaml">show YAML</button></div>` +
    `${bldUI.yaml ? `<pre class="lee-wf-yaml">${esc(bldUI.yaml)}</pre>` : ''}</div>`;
}
function wireBuilder(host) {
  const spec = bldUI.spec;
  const touch = () => { renderWorkflowsPanel(); scheduleBuild(); };
  host.querySelector('#bldfile')?.addEventListener('change', e => { spec.file = e.target.value.trim(); touch(); });
  host.querySelector('#bldname')?.addEventListener('change', e => { spec.name = e.target.value.trim(); touch(); });
  host.querySelectorAll('[data-trigger]').forEach(b => b.onchange = () => {
    const id = b.dataset.trigger, t = bldUI.vocab.triggers.find(x => x.id === id);
    spec.on = spec.on || {};
    if (!b.checked) delete spec.on[id];
    else spec.on[id] = t.kind === 'flag' ? true : t.default;
    touch();
  });
  host.querySelectorAll('[data-trigger-value]').forEach(i => i.onchange = () => {
    spec.on[i.dataset.triggerValue] = i.value.trim(); touch();
  });
  host.querySelector('#bldaddjob')?.addEventListener('click', () => { spec.jobs.push({preset: 'run', needs: []}); touch(); });
  host.querySelectorAll('[data-preset]').forEach(sel => sel.onchange = () => {
    const i = Number(sel.dataset.preset);
    spec.jobs[i] = {preset: sel.value, needs: spec.jobs[i].needs || []};
    touch();
  });
  host.querySelectorAll('[data-job-del]').forEach(b => b.onclick = () => { spec.jobs.splice(Number(b.dataset.jobDel), 1); touch(); });
  host.querySelectorAll('[data-job-up]').forEach(b => b.onclick = () => {
    const i = Number(b.dataset.jobUp); if (!i) return;
    [spec.jobs[i - 1], spec.jobs[i]] = [spec.jobs[i], spec.jobs[i - 1]]; touch();
  });
  host.querySelectorAll('[data-needs]').forEach(i => i.onchange = () => {
    spec.jobs[Number(i.dataset.needs)].needs = i.value.split(',').map(x => x.trim()).filter(Boolean);
    touch();
  });
  host.querySelectorAll('[data-opt]').forEach(el => el.onchange = () => {
    const job = spec.jobs[Number(el.dataset.job)];
    job.options = job.options || {};
    job.options[el.dataset.opt] = el.type === 'checkbox' ? el.checked : el.value;
    scheduleBuild();
  });
  host.querySelector('#bldyaml')?.addEventListener('click', () => buildYaml(true));
  host.querySelector('#bldwrite')?.addEventListener('click', async () => {
    try {
      const d = await post('/workflows/action', {op: 'write_spec', repo: projectRepo(), spec: bldUI.spec, file: bldUI.spec.file});
      status(`wrote ${d.path}`, 'ok');
      wfUI.data = {...wfUI.data, workflows: d.workflows, status: d.status};
      wfUI.catalogue = null; bldUI.stale = false; wfUI.view = 'graph';
      wfUI.open = bldUI.spec.file;
      renderWorkflowsPanel();
    } catch (e) { status(e.message || String(e), 'err'); }
  });
}
function scheduleBuild() { clearTimeout(bldUI.timer); bldUI.timer = setTimeout(() => buildYaml(false), 350); }
async function buildYaml(show) {
  try {
    const d = await post('/workflows/action', {op: 'build', repo: projectRepo(), spec: bldUI.spec});
    if (show || bldUI.yaml) { bldUI.yaml = d.yaml; renderWorkflowsPanel(); }
    else bldUI.yaml = '';
  } catch (e) { status(e.message || String(e), 'err'); }
}
async function loadBuilder(file = '') {
  if (!bldUI.vocab) { try { bldUI.vocab = await api('/workflows/presets'); } catch (e) { return status(e.message || String(e), 'err'); } }
  if (file) {
    try {
      const d = await api('/workflows/spec' + projectQuery({file}));
      if (d.spec) { bldUI.spec = d.spec; bldUI.stale = !!d.stale; }
    } catch (e) {}
  }
  if (!bldUI.spec) bldUI.spec = blankSpec();
  renderWorkflowsPanel();
}

const REL_MARK = {passed: '✓', failed: '✗', running: '•', skipped: '⤼', pending: '·'};
// The server rewrote the path to the checkout in this workspace, so "open" arrives in the
// repository rather than in a copy under .venv that the next sync overwrites.
function blameRow(b) {
  if (!b || !b.package) return '';
  const where = b.file ? `${b.package}/${b.file.split('/').slice(-1)[0]}:${b.line}` : b.package;
  return `<div class="lee-blame"><strong>${esc(b.package)}</strong>` +
    `<span>${esc(b.error || 'raised here')}</span>` +
    `<code>${esc(where)}${b.fn ? ' in ' + esc(b.fn) : ''}</code>` +
    `${b.checkout ? '<i>your checkout</i>' : '<i class="warn">installed copy</i>'}` +
    `${b.open ? `<button data-blame-open="${esc(b.open)}" data-blame-line="${b.line}">open</button>` : ''}</div>`;
}
function wireBlame(host) {
  host.querySelectorAll('[data-blame-open]').forEach(b => b.onclick = async () => {
    try { await leeOpenFile(b.dataset.blameOpen); } catch (e) { return status(e.message || String(e), 'err'); }
    // The line the traceback named, once the editor has actually mounted the file.
    const line = Number(b.dataset.blameLine) || 0;
    if (!line) return;
    setTimeout(() => {
      const view = lee.editors.get('file'); if (!view) return;
      const doc = view.state.doc, at = doc.line(Math.max(1, Math.min(line, doc.lines)));
      // `setCursor` deliberately does not scroll, so the move is dispatched with the scroll asked
      // for.
      view.dispatch({selection: {anchor: at.from}, scrollIntoView: true});
      LeeCM.focus?.(view);
    }, 350);
  });
}
function openProjectEnv() {
  leeLeft('workflows'); wfUI.view = 'env'; wfUI.env = null; return leeWorkflows();
}
// A finished pipeline refuses to start again server-side, because its end publishes or ships.
async function confirmRerun(d, what) {
  return !d.done || confirmDialog(`run ${what} again`,
    `Every step already ran. Forget that and run the whole ${what} again from the top?`, 'run again');
}
function relStepRow(s, d) {
  const busy = d.running && s.status !== 'running';
  return `<article class="lee-rel-step state-${s.status}" data-step="${esc(s.id)}">` +
    `<b>${REL_MARK[s.status] || '·'}</b>` +
    `<div><strong>${esc(s.label)}</strong><code>${esc(s.cmd)}</code>` +
    `<small>${esc(s.doc || '')}${s.code !== null && s.code !== undefined ? ` · exit ${s.code}` : ''}</small>` +
    `${s.missing.length ? `<i class="warn">needs ${s.missing.map(esc).join(', ')}</i>` : ''}</div>` +
    `<span class="lee-rel-actions">` +
    `${s.status === 'running' ? '<button data-rel="stop">stop</button>' :
      `<button data-rel="step" ${busy ? 'disabled' : ''} title="run only this step">run</button>` +
      `${s.status === 'failed' ? `<button data-rel="start" ${busy ? 'disabled' : ''} title="retry, then continue">retry</button><button data-rel="skip" title="mark done without running">skip</button>` : ''}`}` +
    `</span></article>`;
}
function renderReleasesPanel() {
  const host = $('#releasespanel'); if (!host) return;
  const d = relUI.data;
  if (!d) { host.innerHTML = '<div class="lee-git-loading"><span></span><span></span><span></span><small>reading the pipeline</small></div>'; return; }
  const done = d.steps.filter(s => s.status === 'passed').length;
  host.innerHTML =
    `<header class="lee-sc-branch"><div><strong>${esc(d.root.split('/').pop())}</strong>` +
    `<span>${d.flow || (d.nbdev ? 'nbdev' : 'plain')} project${d.app ? ' + desktop app' : ''} · ${done}/${d.steps.length} done${d.configured ? ' · .leela/release.json' : ' · default pipeline'}</span></div></header>` +
    `<div class="lee-sc-actions">` +
    `${d.running ? '<button data-rel-top="stop" class="warn">stop</button>' : `<button data-rel-top="start">${d.failed ? 'continue' : 'run release'}</button>`}` +
    `<button data-rel-top="terminal">terminal</button><button data-rel-top="env">environment</button><button data-rel-top="reset" ${d.running ? 'disabled' : ''}>reset</button>` +
    `<button data-rel-top="edit">edit steps</button>${d.configured ? '<button data-rel-top="defaults">defaults</button>' : ''}</div>` +
    `${d.failed ? `<div class="lee-wf-note"><strong>${esc(d.failed)} failed</strong><span>Its output is in the release terminal. Fix and retry, or skip it deliberately.</span></div>` : ''}` +
    blameRow(d.blame) +
    `<div class="lee-rel-steps">${d.steps.map(s => relStepRow(s, d)).join('')}</div>` +
    `${d.needs.length ? `<div class="lee-rel-needs"><strong>needs</strong>${d.needs.map(k => `<i>${esc(k)}</i>`).join('')}<button data-rel-top="env">environment…</button></div>` : ''}`;
  wireReleasesPanel(host, d);
  wireBlame(host);
  relPoll(d);
}
function wireReleasesPanel(host, d) {
  host.querySelectorAll('[data-rel-top]').forEach(b => b.onclick = () => releaseTop(b.dataset.relTop, d));
  host.querySelectorAll('.lee-rel-step').forEach(row => {
    const step = row.dataset.step;
    row.querySelectorAll('[data-rel]').forEach(b => b.onclick = () => releaseOp(b.dataset.rel, {step}));
  });
}
function relPoll(d) {
  clearTimeout(relUI.poll);
  // Steps finish on their own and start the next one, so the panel keeps asking while something
  // is running.
  if (d.running) relUI.poll = setTimeout(() => leeReleases(), 1200);
}
async function leeReleases() {
  try { relUI.data = await api('/releases' + projectQuery()); }
  catch (e) { const host = $('#releasespanel'); if (host) host.innerHTML = `<div class="lee-git-empty-state"><strong>No project</strong><span>${esc(e.message || e)}</span></div>`; return; }
  renderReleasesPanel();
}
window.leeReleases = leeReleases;
async function releaseOp(op, extra = {}) {
  try {
    relUI.data = await post('/releases/action', {op, repo: projectRepo(), ...extra});
    if (op === 'start' || op === 'step') await openReleaseTerm(relUI.data.root, 'release');
    renderReleasesPanel();
  } catch (e) { status(e.message || String(e), 'err'); }
}
async function releaseTop(op, d) {
  if (op === 'terminal') return openReleaseTerm(d.root, 'release');
  if (op === 'env') return openProjectEnv();
  if (op === 'defaults') return releaseOp('reset_plan');
  if (op === 'start') {
    const missing = d.steps.flatMap(s => s.missing);
    if (missing.length && !await confirmDialog('run release',
        `These steps are missing ${[...new Set(missing)].join(', ')}. Run anyway?`, 'run')) return;
    if (!await confirmRerun(d, 'release')) return;
    if (d.done) await releaseOp('reset');
    return releaseOp('start');
  }
  if (op === 'stop') { if (await confirmDialog('stop release', 'Stop the running step?', 'stop')) releaseOp('stop'); return; }
  if (op === 'reset') { if (await confirmDialog('reset', 'Forget what ran? The commands are unchanged.', 'reset')) releaseOp('reset'); return; }
  if (op === 'edit') {
    const text = await textDialog('release steps', 'One step per line: id | label | command',
                                  d.steps.map(s => `${s.id} | ${s.label} | ${s.cmd}`).join('\n'));
    if (text === null) return;
    const steps = text.split('\n').map(line => line.split('|').map(x => x.trim())).filter(p => p.length >= 3 && p[2])
      .map(([id, label, cmd]) => ({id, label, cmd}));
    releaseOp('save', {steps});
  }
}

// The non-nbdev half of the same front end: the fastship commands that are not release steps.
async function fastshipOp(op, extra = {}) {
  status(`fastship ${op}…`, 'busy');
  try {
    const r = await post('/project/fastship/action', {op, repo: projectRepo(), ...extra});
    status(`fastship ${op} · ${PathName(r.root)}`, 'ok');
    refreshFileTree(undefined, false).catch(() => {});
    if (relUI.data) leeReleases();
    return r;
  } catch (e) { status(String(e.message || e), 'err'); return null; }
}
async function leeFastship() {
  let d;
  try { d = await api('/project/fastship' + projectQuery()); }
  catch (e) { return status(String(e.message || e), 'err'); }
  const flow = `${d.flow || 'plain'} project`;
  const note = d.flow === 'nbdev'
    ? '<div class="lee-wf-note"><strong>This is an nbdev project</strong><span>nbdev prepare is its front end, and the release pipeline runs nbdev\'s commands. fastship still scaffolds a new package.</span></div>'
    : !d.installed ? `<div class="lee-wf-note"><strong>fastship is not installed here</strong><span>${esc(d.why)}</span><code>uv add --dev fastship</code></div>` : '';
  const rows = (d.ops || []).map(o => `<article class="lee-rel-step" data-fs="${esc(o.op)}">` +
    `<b>·</b><div><strong>${esc(o.op)}</strong><code>${esc(o.cmd)}</code><small>${esc(o.doc)}</small></div>` +
    `<span class="lee-rel-actions"><button data-fs-run ${d.flow === 'nbdev' || !d.installed ? 'disabled' : ''}>run</button></span></article>`).join('');
  const m = modal(`<div class="lee-mhead">fastship<span class="sub">${esc(PathName(d.root))} · ${esc(flow)}` +
    `${d.changelog ? ' · CHANGELOG.md' : ' · no CHANGELOG.md yet'}${d.app ? ' · packages a desktop app' : ''}</span></div>` +
    note + `<div class="lee-rel-steps">${rows}</div>` +
    `<div class="lee-mfoot"><button class="lee-btn" id="fsrelease">release pipeline…</button>` +
    `<button class="lee-btn go" id="fsnew">new package…</button></div>`);
  m.querySelectorAll('[data-fs]').forEach(row => row.querySelector('[data-fs-run]')?.addEventListener('click', async () => {
    m.remove();
    await fastshipOp(row.dataset.fs);
  }));
  m.querySelector('#fsrelease').onclick = () => { m.remove(); leeLeft('releases'); leeReleases(); };
  m.querySelector('#fsnew').onclick = async () => {
    const name = await inputDialog('new fastship package', 'package name', '', 'my-package');
    if (!name) return;
    m.remove();
    const r = await fastshipOp('new', {name});
    if (r) status(`fastship new · ${PathName(r.root)} · release.yml written`, 'ok');
  };
}
window.leeFastship = leeFastship;
// The same pipeline as a release, with a target above it, because a deploy that cannot say where it
// is going is the one nobody presses.
const depUI = {data: null, poll: 0, view: 'stages', infra: null, stack: null, zone: '', records: null};
function depTargetCard(t) {
  const files = [['deploy.py', t.script], ['setup.py', t.setup], ['Dockerfile', t.dockerfile],
                 ['docker-compose.yml', t.compose], ['Caddyfile', t.caddyfile]];
  return `<header class="lee-sc-branch"><div><strong>${esc(t.domain || t.app)}</strong>` +
    `<span>${esc(t.server || 'no server named')} · ${esc(t.user)}@:${esc(t.port)}</span></div></header>` +
    `<div class="lee-dep-files">${files.map(([n, has]) => `<i class="${has ? 'has' : ''}">${esc(n)}</i>`).join('')}</div>` +
    (t.missing.length ? `<div class="lee-wf-note"><strong>${t.missing.length} value${t.missing.length === 1 ? '' : 's'} not set</strong>` +
      `<span>${t.missing.map(esc).join(', ')}</span><code>set them in Workflows → Environment</code><button data-dep-env>environment</button></div>` : '');
}

function depInfraRows() {
  const d = depUI.infra;
  if (!d) return '<div class="lee-git-loading"><span></span><span></span><span></span><small>asking Hetzner and Cloudflare</small></div>';
  const st = d.status || {};
  const half = (title, part, render) => `<section class="lee-inf-group"><header>${title}</header>` +
    (part.error ? `<div class="lee-wf-note"><span>${esc(part.error)}</span></div>`
                : (part.rows.length ? part.rows.map(render).join('')
                                    : '<div class="lee-dim lee-git-empty">none</div>')) + '</section>';
  return `<div class="lee-inf-status">${['vpseasy', 'cfeasy'].map(k => `<i class="${st[k] ? 'has' : ''}">${k}</i>`).join('')}` +
    `<i class="${st.hcloud_token ? 'has' : ''}">HCLOUD_TOKEN</i><i class="${st.cf_token ? 'has' : ''}">CLOUDFLARE_API_TOKEN</i></div>` +
    half('servers', d.servers || {rows: [], error: ''}, s =>
      `<article class="lee-inf-row" data-server="${esc(s.name)}"><div><strong>${esc(s.name)}</strong><small>${esc(s.ip || '')} · ${esc(s.status || '')}</small></div>` +
      `<button data-server-del title="delete this server">delete</button></article>`) +
    half('tunnels', d.tunnels || {rows: [], error: ''}, t =>
      `<article class="lee-inf-row" data-tunnel="${esc(t.id)}"><div><strong>${esc(t.name)}</strong><small>${esc(t.status || '')} · ${t.connections} connection${t.connections === 1 ? '' : 's'}</small></div>` +
      `<button data-tunnel-del title="delete this tunnel">delete</button></article>`) +
    half('zones', d.zones || {rows: [], error: ''}, z =>
      `<article class="lee-inf-row" data-zone="${esc(z.name)}"><div><strong>${esc(z.name)}</strong><small>${esc(z.status || '')}</small></div>` +
      `<button data-zone-dns>records</button></article>`) +
    (depUI.records ? `<section class="lee-inf-group"><header>${esc(depUI.zone)}</header>` +
      depUI.records.map(r => `<article class="lee-inf-row"><div><strong>${esc(r.name)}</strong>` +
        `<small>${esc(r.type)} · ${esc(r.content)}${r.proxied ? ' · proxied' : ''}</small></div>` +
        `${r.tunnel ? '<i class="lee-inf-tag">tunnel</i>' : ''}</article>`).join('') + '</section>' : '');
}
function depStackRows() {
  const d = depUI.stack;
  if (!d) return '<div class="lee-git-loading"><span></span><span></span><span></span><small>reading the stack</small></div>';
  return `<div class="lee-inf-status"><i>${d.checkouts.length} checkouts open</i></div>` +
    `<div class="lee-pkgs">${d.packages.map(p => `<article class="lee-pkg${p.shadowed ? ' shadowed' : ''}">` +
      `<div><strong>${esc(p.name)}</strong><small>${p.installed ? esc(p.version || 'no version') + ' · ' + esc(p.source) : 'not installed'}</small>` +
      `${p.shadowed ? '<i class="warn">edits in your checkout are not what runs. Install it again as editable</i>' : ''}</div>` +
      `${p.checkout ? `<button data-pkg-open="${esc(p.checkout)}">open</button>` : ''}</article>`).join('')}</div>`;
}
async function loadInfra(force = false) {
  if (depUI.infra && !force) return renderDeployPanel();
  try { depUI.infra = await api('/infra'); } catch (e) { status(e.message || String(e), 'err'); return; }
  renderDeployPanel();
}
async function loadStack() {
  try { depUI.stack = await api('/stack' + projectQuery()); } catch (e) { status(e.message || String(e), 'err'); return; }
  renderDeployPanel();
}
async function infraOp(op, extra = {}) {
  try {
    depUI.infra = await post('/infra/action', {op, ...extra});
    status(`${op.replace('_', ' ')} done`, 'ok');
    renderDeployPanel();
  } catch (e) { status(e.message || String(e), 'err'); }
}
function wireInfra(host) {
  host.querySelectorAll('[data-server-del]').forEach(b => b.onclick = async () => {
    const name = b.closest('[data-server]').dataset.server;
    if (await confirmDialog('delete server', `Delete ${name}? The machine and everything on it goes.`, 'delete'))
      infraOp('delete_server', {name});
  });
  host.querySelectorAll('[data-tunnel-del]').forEach(b => b.onclick = async () => {
    const row = b.closest('[data-tunnel]');
    if (await confirmDialog('delete tunnel', `Delete this tunnel? Anything routed through it stops answering.`, 'delete'))
      infraOp('delete_tunnel', {id: row.dataset.tunnel});
  });
  host.querySelectorAll('[data-zone-dns]').forEach(b => b.onclick = async () => {
    const zone = b.closest('[data-zone]').dataset.zone;
    try { depUI.zone = zone; depUI.records = (await api('/infra/records?zone=' + encodeURIComponent(zone))).records; }
    catch (e) { return status(e.message || String(e), 'err'); }
    renderDeployPanel();
  });
  host.querySelectorAll('[data-pkg-open]').forEach(b => b.onclick = () => leeOpenFile(b.dataset.pkgOpen));
}
function renderDeployPanel() {
  const host = $('#deploypanel'); if (!host) return;
  const d = depUI.data;
  if (!d) { host.innerHTML = '<div class="lee-git-loading"><span></span><span></span><span></span><small>reading the deploy plan</small></div>'; return; }
  const t = d.target;
  const nav = `<nav class="lee-git-nav" aria-label="Deploy views">${[['stages', 'Stages'], ['infra', 'Servers'], ['stack', 'Stack']].map(([id, label]) =>
    `<button data-dep-view="${id}" class="${depUI.view === id ? 'active' : ''}">${label}</button>`).join('')}</nav>`;
  if (depUI.view !== 'stages') {
    host.innerHTML = depTargetCard(t) + nav +
      `<main class="lee-wf-body">${depUI.view === 'infra' ? depInfraRows() : depStackRows()}</main>`;
    host.querySelectorAll('[data-dep-view]').forEach(b => b.onclick = () => { depUI.view = b.dataset.depView; renderDeployPanel(); });
    wireInfra(host);
    if (depUI.view === 'infra' && !depUI.infra) loadInfra();
    if (depUI.view === 'stack' && !depUI.stack) loadStack();
    return;
  }
  host.innerHTML = depTargetCard(t) + nav +
    `<div class="lee-sc-actions">` +
    `${t.script ? (d.running ? '<button data-dep-top="stop" class="warn">stop</button>'
                             : `<button data-dep-top="start">${d.failed ? 'continue' : 'deploy'}</button>`)
                : '<button data-dep-top="scaffold">write deploy.py…</button>'}` +
    `<button data-dep-top="terminal">terminal</button><button data-dep-top="env">environment</button>` +
    `<button data-dep-top="reset" ${d.running ? 'disabled' : ''}>reset</button>` +
    `<button data-dep-top="edit">edit steps</button>` +
    `${t.script ? '<button data-dep-top="open">open deploy.py</button>' : ''}</div>` +
    `${d.failed ? `<div class="lee-wf-note"><strong>${esc(d.failed)} failed</strong><span>Its output is in the deploy terminal. You can run each stage again safely. Fix the problem and continue.</span></div>` : ''}` +
    blameRow(d.blame) +
    `<div class="lee-rel-steps">${d.steps.map(s => relStepRow(s, d)).join('')}</div>`;
  host.querySelectorAll('[data-dep-view]').forEach(b => b.onclick = () => { depUI.view = b.dataset.depView; renderDeployPanel(); });
  host.querySelectorAll('[data-dep-top]').forEach(b => b.onclick = () => deployTop(b.dataset.depTop, d));
  host.querySelector('[data-dep-env]')?.addEventListener('click', openProjectEnv);
  wireBlame(host);
  host.querySelectorAll('.lee-rel-step').forEach(row => {
    const step = row.dataset.step;
    row.querySelectorAll('[data-rel]').forEach(b => b.onclick = () => deployOp(b.dataset.rel, {step}));
  });
  clearTimeout(depUI.poll);
  if (d.running) depUI.poll = setTimeout(() => leeDeploys(), 1200);
}
async function leeDeploys() {
  try { depUI.data = await api('/deploys' + projectQuery()); }
  catch (e) { const host = $('#deploypanel'); if (host) host.innerHTML = `<div class="lee-git-empty-state"><strong>No project</strong><span>${esc(e.message || e)}</span></div>`; return; }
  renderDeployPanel();
}
window.leeDeploys = leeDeploys;
async function deployOp(op, extra = {}) {
  try {
    depUI.data = await post('/deploys/action', {op, repo: projectRepo(), ...extra});
    if (op === 'start' || op === 'step') await openReleaseTerm(depUI.data.root, 'deploy');
    renderDeployPanel();
  } catch (e) { status(e.message || String(e), 'err'); }
}
async function deployTop(op, d) {
  const t = d.target;
  if (op === 'terminal') return openReleaseTerm(d.root, 'deploy');
  if (op === 'env') return openProjectEnv();
  if (op === 'open') return leeOpenFile(d.root + '/deploy.py');
  if (op === 'reset') { if (await confirmDialog('reset', 'Forget what ran? The stages are unchanged.', 'reset')) deployOp('reset'); return; }
  if (op === 'stop') { if (await confirmDialog('stop deploy', 'Stop the running stage?', 'stop')) deployOp('stop'); return; }
  if (op === 'scaffold') {
    const domain = await inputDialog('write deploy.py', 'Domain this app answers on', t.domain || '', 'example.com');
    if (!domain) return;
    const sub = await inputDialog('write deploy.py', 'Subdomain, or empty for the apex', '', 'app');
    if (sub === null) return;
    const second = await inputDialog('write deploy.py', 'A second hostname on the same container, or empty',
                                     '', 'the apex, as lego serves it');
    if (second === null) return;
    const r = await post('/deploys/action', {op: 'scaffold', repo: projectRepo(), domain,
                                             subdomain: sub, second_host: second})
                    .catch(e => { status(e.message || String(e), 'err'); });
    if (!r) return;
    depUI.data = r.state;
    status(`wrote ${(r.written || []).map(p => p.split('/').pop()).join(', ')}`, 'ok');
    return renderDeployPanel();
  }
  if (op === 'start') {
    if (t.missing.length && !await confirmDialog('deploy',
        `These are not set: ${t.missing.join(', ')}. Deploy anyway?`, 'deploy')) return;
    if (!await confirmRerun(d, 'deploy')) return;
    if (d.done) await deployOp('reset');
    return deployOp('start');
  }
  if (op === 'edit') {
    const text = await textDialog('deploy stages', 'One stage per line: id | label | command',
                                  d.steps.map(s => `${s.id} | ${s.label} | ${s.cmd}`).join('\n'));
    if (text === null) return;
    const steps = text.split('\n').map(l => l.split('|').map(x => x.trim())).filter(p => p.length >= 3 && p[2])
      .map(([id, label, cmd]) => ({id, label, cmd}));
    deployOp('save', {steps});
  }
}

// The alternative to the deploy script, kept as its own panel so the two can be compared: same
// runner, same terminal, same blame on a failure, six library calls instead of three subcommands.
// The snippet is on screen because a button you cannot read is not a diagnostic.
const drvUI = {data: null, open: '', poll: 0};
function drvPart(s, d) {
  const m = s.meta || {}, busy = d.running && s.status !== 'running';
  const flow = [...(m.produces || []).map(f => `<i>writes ${esc(f)}</i>`),
                ...(m.writes || []).map(k => `<i class="writes">sets ${esc(k)}</i>`),
                ...(s.missing || []).map(k => `<i class="warn">needs ${esc(k)}</i>`)].join('');
  const open = drvUI.open === s.id;
  return `<article class="lee-drv-part state-${s.status}" data-part="${esc(s.id)}">` +
    `<b>${REL_MARK[s.status] || '·'}</b>` +
    `<div><strong><span class="lee-drv-pkg">${esc(m.package || '')}</span>${esc(m.title || s.label)}</strong>` +
    `<small>${esc(s.doc || '')}${s.code !== null && s.code !== undefined ? ` · exit ${s.code}` : ''}</small>` +
    `${flow ? `<div class="lee-drv-flow">${flow}</div>` : ''}` +
    `<details ${open ? 'open' : ''}><summary>${open ? 'hide' : 'show'} the call</summary>` +
    `<pre class="lee-drv-code">${esc(m.code || '')}</pre></details></div>` +
    `<span class="lee-drv-actions">` +
    `${s.status === 'running' ? '<button data-drv="stop">stop</button>'
                              : `<button data-drv="step" ${busy ? 'disabled' : ''}>run</button>`}` +
    `</span></article>`;
}
function renderDrivePanel() {
  const host = $('#drivepanel'); if (!host) return;
  const d = drvUI.data;
  if (!d) { host.innerHTML = '<div class="lee-git-loading"><span></span><span></span><span></span><small>reading the parts</small></div>'; return; }
  const c = d.context || {};
  const done = d.steps.filter(s => s.status === 'passed').length;
  host.innerHTML =
    `<header class="lee-sc-branch"><div><strong>${esc(c.host || c.app || '')}</strong>` +
    `<span>${esc(d.packages.join(' · '))} · ${done}/${d.steps.length} run</span></div></header>` +
    `<div class="lee-drv-ctx"><b>values</b><i>app ${esc(c.app || '')}</i>` +
    `${c.domain ? `<i>domain ${esc(c.domain)}</i>` : '<i class="warn">DOMAIN not set</i>'}` +
    `${c.subdomain ? `<i>sub ${esc(c.subdomain)}</i>` : ''}<i>tunnel ${esc(c.tunnel || '')}</i></div>` +
    `<div class="lee-sc-actions">` +
    `${d.running ? '<button data-drv-top="stop" class="warn">stop</button>'
                 : '<button data-drv-top="start">run all</button>'}` +
    `<button data-drv-top="terminal">terminal</button>` +
    `<button data-drv-top="reset" ${d.running ? 'disabled' : ''}>reset</button>` +
    `<button data-drv-top="values">environment</button></div>` +
    blameRow(d.blame) +
    `<div class="lee-rel-steps">${d.steps.map(s => drvPart(s, d)).join('')}</div>`;
  host.querySelectorAll('[data-drv-top]').forEach(b => b.onclick = () => driveTop(b.dataset.drvTop, d));
  host.querySelectorAll('.lee-drv-part').forEach(row => {
    const step = row.dataset.part;
    row.querySelectorAll('[data-drv]').forEach(b => b.onclick = () => driveOp(b.dataset.drv, {step}));
    row.querySelector('details')?.addEventListener('toggle', e => { drvUI.open = e.target.open ? step : ''; });
  });
  wireBlame(host);
  clearTimeout(drvUI.poll);
  if (d.running) drvUI.poll = setTimeout(() => leeDrive(), 1200);
}
async function leeDrive() {
  try { drvUI.data = await api('/drive' + projectQuery()); }
  catch (e) { const host = $('#drivepanel'); if (host) host.innerHTML = `<div class="lee-git-empty-state"><strong>No project</strong><span>${esc(e.message || e)}</span></div>`; return; }
  renderDrivePanel();
}
window.leeDrive = leeDrive;
async function driveOp(op, extra = {}) {
  try {
    drvUI.data = await post('/drive/action', {op, repo: projectRepo(), ...extra});
    if (op === 'step' || op === 'start') await openReleaseTerm(drvUI.data.root, 'drive');
    renderDrivePanel();
  } catch (e) { status(e.message || String(e), 'err'); }
}
async function driveTop(op, d) {
  if (op === 'terminal') return openReleaseTerm(d.root, 'drive');
  if (op === 'values') return openProjectEnv();
  if (op === 'stop') { if (await confirmDialog('stop', 'Stop the running call?', 'stop')) driveOp('stop'); return; }
  if (op === 'reset') { if (await confirmDialog('reset', 'Forget what ran? The calls are unchanged.', 'reset')) driveOp('reset'); return; }
  if (op === 'start') {
    const missing = [...new Set(d.steps.flatMap(s => s.missing))];
    if (missing.length && !await confirmDialog('run every call',
        `These are not set: ${missing.join(', ')}. Run anyway?`, 'run')) return;
    if (!await confirmRerun(d, 'run')) return;
    if (d.done) await driveOp('reset');
    return driveOp('start');
  }
}

async function renderGitPanel(snapshot = null) {
  const host = $('#gitpanel'); if (!host) return;
  host.dataset.features = 'Staged changes · Changes · Branches · Stashes · Remotes & tags · All repos · staged changes · working tree · fetch · pull · push · stash · tag · stage all · unstage all · fetch all · pull all · push all · clone';
  if (gitUI.tab === 'repos') {
    host.innerHTML = gitScope() + gitNav() + `<main class="lee-git-view">${gitReposView()}</main>`;
    wireGitPanel(host, gitUI.snapshot);
    if (!gitUI.repos) loadGitRepos();
    return;
  }
  if (!snapshot && !gitUI.snapshot) host.innerHTML = '<div class="lee-git-loading"><span></span><span></span><span></span><small>reading repository</small></div>';
  let d = snapshot || gitUI.snapshot;
  try { if (!d) d = await gitInfo(gitUrl('/git/info')); }
  catch (e) {
    // Still draw the nav: a workspace whose active folder is not a checkout can hold five other
    // repositories, and Repos is how you reach them.
    host.innerHTML = gitScope() + gitNav() +
      `<main class="lee-git-view"><div class="lee-git-empty-state"><strong>No Git repository</strong><span>${esc(e.message || e)}</span></div></main>`;
    // `null`, not `{}`: switching to another view from here must re-read the repository rather
    // than render a snapshot-shaped object with no fields in it.
    wireGitPanel(host, null);
    return;
  }
  // A key is `group:path`, so a file that was committed or moved between groups leaves a key that
  // renders as nothing and still gets posted by a bulk action. The selection only means anything
  // for the change list it was made against.
  const keys = new Set();
  for (const c of d.changes || []) {
    if (c.staged) keys.add(`staged:${c.path}`);
    if (c.unstaged) keys.add(`unstaged:${c.path}`);
  }
  gitAdopt(d.root);
  for (const key of [...gitUI.selectedChanges]) if (!keys.has(key)) gitUI.selectedChanges.delete(key);
  gitUI.snapshot = d; paintGitPill(d);
  const view = gitUI.tab === 'changes' ? gitChangesView(d) : gitUI.tab === 'review' ? gitReviewView(d) : gitUI.tab === 'branches' ? gitBranchesView(d) : gitUI.tab === 'history' ? gitHistoryView(d) : gitResourcesView(d);
  host.innerHTML = gitScope() + gitSummary(d) + gitNav() + `<main class="lee-git-view">${view}</main>`;
  wireGitPanel(host, d);
  if (gitUI.tab === 'history' && !gitUI.history.length) loadGitHistory();
  if (gitUI.tab === 'review' && !gitUI.review) loadGitReview();
  if (gitUI.tab === 'resources') loadGitResources();
}
async function loadGitReview() {
  if (!gitUI.reviewBase || !gitUI.reviewHead) return;
  const host = $('.lee-git-review-workspace');
  if (host) host.innerHTML = '<div class="lee-git-loading"><span></span><span></span><span></span><small>building review</small></div>';
  try {
    gitUI.review = await api(gitUrl('/git/review', {base: gitUI.reviewBase, head: gitUI.reviewHead, mode: gitUI.reviewMode}));
    gitUI.reviewFile = gitUI.review.files[0]?.path || ''; gitUI.reviewPatch = '';
    renderGitPanel(gitUI.snapshot);
  } catch (e) { leeFail('git', 'review', e); }
}
async function loadGitReviewFile(path, asTab = false) {
  if (!gitUI.review) return;
  gitUI.reviewFile = path;
  try {
    const d = noteHl(await api(gitUrl('/git/review/file', {base: gitUI.review.base, head: gitUI.review.head, mode: gitUI.review.mode, path})));
    gitUI.reviewPatch = d.patch || '';
    if (asTab) return openGitDiffTab({...d, path, kind: 'review', baseLabel: gitUI.review.base, headLabel: gitUI.review.head, absolutePath: gitUI.snapshot.root + '/' + path, root: gitUI.snapshot.root, worktreeBefore: d.worktree ?? null, reviewKey: gitReviewKey({...gitUI.review, root: gitUI.snapshot.root}, path), allowWrite: !!d.can_apply && !path.toLowerCase().endsWith('.ipynb')});
    renderGitPanel(gitUI.snapshot);
  } catch (e) { leeFail('git', 'review file', e); }
}
function moveGitReviewFile(delta) {
  const files = gitUI.review?.files || [], at = files.findIndex(f => f.path === gitUI.reviewFile);
  if (!files.length) return;
  loadGitReviewFile(files[(Math.max(0, at) + delta + files.length) % files.length].path);
}
async function loadGitHistory() {
  const rows = $('#githistoryrows');
  try {
    const ref = $('#githistoryref')?.value || '--all';
    const result = await api(gitUrl('/git/history', {limit: 150, query: gitUI.historyQuery, ref}));
    gitUI.history = result.commits || []; renderGitPanel(gitUI.snapshot);
  } catch (e) { if (rows) rows.innerHTML = `<div class="lee-err">${esc(e.message || e)}</div>`; }
}
async function loadGitResources() {
  try {
    const r = await api(gitUrl('/git/resources'));
    const worktrees = $('#gitworktrees');
    if (worktrees) worktrees.innerHTML = (r.worktrees || []).map(w => `<article class="lee-git-resource-row" data-worktree="${esc(w.path)}"><div><strong>${esc(w.branch || 'detached')}</strong><code>${esc(w.path)}</code></div>${w.path === gitUI.snapshot.root ? '<i>current</i>' : '<button data-remove-worktree class="warn">remove</button>'}</article>`).join('') || '<span class="lee-dim">No worktrees</span>';
    const submodules = $('#gitsubmodules');
    if (submodules) submodules.innerHTML = (r.submodules || []).map(s => `<article class="lee-git-resource-row"><div><strong>${esc(s.path)}</strong><code>${esc(s.oid)}</code></div><i>${s.state === ' ' ? 'clean' : s.state === '-' ? 'not initialized' : s.state === '+' ? 'different commit' : 'conflict'}</i></article>`).join('') || '<span class="lee-dim">No submodules</span>';
    worktrees?.querySelectorAll('[data-remove-worktree]').forEach(b => b.onclick = async () => {
      const path = b.closest('[data-worktree]').dataset.worktree;
      if (await confirmDialog('remove worktree', `Remove ${path}? Uncommitted work prevents removal.`, 'remove')) renderGitPanel(await gitDo('remove_worktree', {path}));
    });
  } catch (e) { leeFail('git', 'worktrees and submodules', e); }
}
function wireGitPanel(host, d) {
  host.querySelectorAll('[data-git-tab]').forEach(b => b.onclick = () => { gitUI.tab = b.dataset.gitTab; if (gitUI.tab !== 'history') gitUI.history = []; renderGitPanel(d); });
  host.querySelector('#gitscopeclear')?.addEventListener('click', () => gitPinRepo(''));
  host.querySelectorAll('[data-repos-op]').forEach(b => b.onclick = () => gitReposDo(b.dataset.reposOp));
  host.querySelectorAll('.lee-git-repo-row').forEach(row => {
    const root = row.dataset.repo;
    row.querySelector('[data-repo-open]').onclick = () => gitPinRepo(root === gitUI.repo ? '' : root);
    row.querySelector('[data-repo-fetch]').onclick = () => gitReposDo('fetch', {paths: [root]});
    row.querySelector('[data-repo-remove]').onclick = async () => {
      if (!await confirmDialog('remove repository', `Stop listing ${gitRepoName(root)} here? The checkout is left alone.`, 'remove')) return;
      if (gitUI.repo === root) gitUI.repo = '';
      gitReposDo('remove', {path: root});
    };
  });
  const expect = host.querySelector('#gitrepoexpect');
  if (expect) expect.onchange = () => { gitUI.expect = expect.value.trim(); loadGitRepos(); };
  host.querySelector('#gitrepoadd')?.addEventListener('click', async () => {
    const path = await inputDialog('add repository', 'Path to a Git checkout', '', '/home/you/code/project');
    if (path) gitReposDo('add', {path});
  });
  host.querySelector('#gitrepoclone')?.addEventListener('click', async () => {
    const spec = await inputDialog('clone repositories', 'URLs or owner/name, one per line', '', 'AnswerDotAI/fastws');
    if (spec) gitReposDo('clone', {urls: spec.split(/[\s,]+/).filter(Boolean)});
  });
  const act = async (op, extra = {}) => renderGitPanel(await gitDo(op, {repo: gitRepo(), ...extra}));
  host.querySelectorAll('[data-operation]').forEach(b => b.onclick = async () => {
    if (b.dataset.operation === 'abort' && !await confirmDialog('abort Git operation', `Abort the active ${d.operation.active}?`, 'abort')) return;
    act('operation_' + b.dataset.operation);
  });
  host.querySelectorAll('[data-git-undo]').forEach(b => b.onclick = async () => {
    const point = (d.safepoints || [])[0];
    if (!await confirmDialog('undo Git operation',
        `Put this repository back where it was before ${point?.describe || 'the last operation'}?` +
        `\n\nHEAD returns to ${point?.head || 'the recorded commit'}` +
        `${point?.dirty ? ` and ${point.dirty} uncommitted file(s) are restored` : ''}.`, 'undo')) return;
    act('undo', {token: b.dataset.gitUndo});
  });
  host.querySelectorAll('[data-top]').forEach(b => b.onclick = () => b.dataset.top === 'publish' ? act('push', {publish: true}) : act(b.dataset.top));
  host.querySelector('#scstageall')?.addEventListener('click', e => { e.preventDefault(); act('stage', {paths: d.changes.filter(x => x.unstaged).map(x => x.path)}); });
  host.querySelector('#scunstageall')?.addEventListener('click', e => { e.preventDefault(); act('unstage', {paths: d.changes.filter(x => x.staged).map(x => x.path)}); });
  host.querySelector('#scstash')?.addEventListener('click', async () => { const message = await inputDialog('stash changes', 'Optional message', '', 'work in progress'); if (message !== null) act('stash', {message}); });
  /* The panel re-renders on every save in the repository, not only on a click here, so a message
     being typed has to survive `innerHTML`. The branch filter already worked this way. */
  const commit = host.querySelector('#sccommit');
  if (commit) {
    const box = commit.querySelector('textarea');
    box.oninput = () => { gitUI.commitDraft = box.value; };
    commit.addEventListener('submit', e => {
      e.preventDefault();
      const message = box.value.trim();
      if (!message) return status('write a commit message first', 'err');
      gitUI.commitDraft = '';
      act('commit', {message, amend: commit.elements.amend.checked});
    });
  }
  host.querySelector('#screviewstaged')?.addEventListener('click', () => showStagedReview(d));
  host.querySelector('[data-conflict-center]')?.addEventListener('click', () => showConflictCenter());
  host.querySelectorAll('[data-selected-action]').forEach(b => b.onclick = async () => {
    const action = b.dataset.selectedAction;
    if (action === 'clear') { gitUI.selectedChanges.clear(); return renderGitPanel(d); }
    const selected = [...gitUI.selectedChanges].map(key => { const [group, ...parts] = key.split(':'); return {group, path: parts.join(':')}; });
    if (action === 'changelist') {
      const name = await inputDialog('move to changelist', 'Local changelist name', '', 'Focused change');
      if (name !== null) { for (const x of selected) { if (name) gitUI.changeLists[x.path] = name; else delete gitUI.changeLists[x.path]; } saveGitWorkflowState(); renderGitPanel(d); }
      return;
    }
    const paths = selected.filter(x => action === 'stage' ? x.group === 'unstaged' : x.group === 'staged').map(x => x.path);
    if (!paths.length) return status(`select ${action === 'stage' ? 'unstaged' : 'staged'} files`, 'err');
    gitUI.selectedChanges.clear(); act(action, {paths});
  });
  host.querySelectorAll('.lee-git-change').forEach(row => {
    const path = row.dataset.path, staged = row.dataset.group === 'staged';
    row.querySelector('[data-select-change]').onchange = e => { const key = `${row.dataset.group}:${path}`; if (e.target.checked) gitUI.selectedChanges.add(key); else gitUI.selectedChanges.delete(key); renderGitPanel(d); };
    row.querySelector('.lee-git-file').onclick = async () => { const patch = noteHl(await api(gitUrl('/git/diff', {path, staged}))); openGitDiffTab({kind: 'changes-' + row.dataset.group, path, absolutePath: d.root + '/' + path, base: staged ? 'HEAD' : 'index', head: staged ? 'index' : 'worktree', baseLabel: staged ? 'HEAD' : 'index', headLabel: staged ? 'staged' : 'working tree', left: patch.left || '', right: patch.right || '', patch: patch.content || patch.text || '', rawPatch: patch.text || '', notebook: !!patch.notebook, binary: !!patch.binary, lfs: patch.lfs || null, group: row.dataset.group, allowWrite: row.dataset.group === 'unstaged' && !patch.notebook && !patch.binary}); };
    row.querySelector('[data-open]').onclick = () => leeOpenFile(d.root + '/' + path);
    row.querySelector('[data-blame]')?.addEventListener('click', () => showGitBlame(d.root, path, null));
    row.querySelector('[data-resolve]')?.addEventListener('click', () => showGitConflict(path));
    row.querySelectorAll('[data-git]').forEach(b => b.onclick = async () => { const op = b.dataset.git; if (op === 'discard' && !await confirmDialog('discard changes', `Restore ${path} from the index? This cannot be undone.`, 'discard')) return; act(op, {paths: [path]}); });
  });
  host.querySelectorAll('[data-stash]').forEach(row => { const ref = row.dataset.stash; row.querySelector('[data-apply]').onclick = () => act('stash_apply', {ref}); row.querySelector('[data-pop]').onclick = () => act('stash_pop', {ref}); row.querySelector('[data-drop]').onclick = async () => { if (await confirmDialog('drop stash', `Delete ${ref}?`, 'drop')) act('stash_drop', {ref}); }; });
  const branchFilter = host.querySelector('#gitbranchfilter'); if (branchFilter) branchFilter.oninput = () => { gitUI.branchQuery = branchFilter.value; renderGitPanel(d); requestAnimationFrame(() => { const x = $('#gitbranchfilter'); x?.focus(); x?.setSelectionRange(x.value.length, x.value.length); }); };
  const branchScope = host.querySelector('#gitbranchscope'); if (branchScope) { branchScope.value = gitUI.branchScope; branchScope.onchange = () => { gitUI.branchScope = branchScope.value; renderGitPanel(d); }; }
  host.querySelector('#scbranch')?.addEventListener('click', async () => { const branch = await inputDialog('new branch', 'Branch name', '', 'feature/name'); if (branch) act('create', {branch}); });
  host.querySelectorAll('[data-branch]').forEach(row => { const branch = row.dataset.branch; row.querySelector('[data-switch]').onclick = () => act('checkout', {branch}); row.querySelector('[data-compare]')?.addEventListener('click', () => { gitUI.reviewBase = d.branch; gitUI.reviewHead = branch; gitUI.reviewMode = 'review'; gitUI.review = null; gitUI.tab = 'review'; renderGitPanel(d); }); const more = row.querySelector('[data-more]'); more?.addEventListener('click', () => gitBranchMenu(more, branch, d, act)); });
  host.querySelector('#sctag')?.addEventListener('click', async () => { const name = await inputDialog('create tag', 'Tag name', '', 'v1.0.0'); if (!name) return; const message = await inputDialog('annotated tag', 'Optional annotation', '', ''); if (message !== null) act('tag', {name, message}); });
  host.querySelectorAll('[data-delete-tag]').forEach(b => b.onclick = async () => { const name = b.closest('[data-tag]').dataset.tag; if (await confirmDialog('delete tag', `Delete local tag ${name}?`, 'delete')) act('delete_tag', {name}); });
  host.querySelector('#gitreviewmode') && (host.querySelector('#gitreviewmode').value = gitUI.reviewMode);
  const swapReviewDirection = () => { const base = $('#gitreviewbase')?.value.trim() || gitUI.reviewBase; gitUI.reviewBase = $('#gitreviewhead')?.value.trim() || gitUI.reviewHead; gitUI.reviewHead = base; gitUI.review = null; loadGitReview(); };
  host.querySelector('#gitreviewcontrolswap')?.addEventListener('click', swapReviewDirection);
  host.querySelector('#gitreviewswap')?.addEventListener('click', swapReviewDirection);
  host.querySelector('#gitreviewsnapshot')?.addEventListener('click', () => { gitUI.reviewMode = 'snapshot'; gitUI.review = null; loadGitReview(); });
  host.querySelector('#gitreviewload')?.addEventListener('click', () => { gitUI.reviewBase = $('#gitreviewbase').value.trim(); gitUI.reviewHead = $('#gitreviewhead').value.trim(); gitUI.reviewMode = $('#gitreviewmode').value; gitUI.review = null; loadGitReview(); });
  host.querySelectorAll('[data-review-path]').forEach(b => b.onclick = () => loadGitReviewFile(b.dataset.reviewPath, true));
  host.querySelector('#gitreviewprev')?.addEventListener('click', () => moveGitReviewFile(-1));
  host.querySelector('#gitreviewnext')?.addEventListener('click', () => moveGitReviewFile(1));
  host.querySelector('#gitreviewmark')?.addEventListener('click', () => { const key = gitReviewKey({...gitUI.review, root: d.root}, gitUI.reviewFile); gitUI.reviewed[key] = !gitUI.reviewed[key]; saveGitWorkflowState(); renderGitPanel(d); });
  host.querySelector('#gitreviewnote')?.addEventListener('click', async () => { const key = gitReviewKey({...gitUI.review, root: d.root}, gitUI.reviewFile), note = await inputDialog('review note', `Note for ${gitUI.reviewFile}`, gitUI.reviewNotes[key] || '', 'Question, risk, or follow-up'); if (note !== null) { if (note.trim()) gitUI.reviewNotes[key] = note.trim(); else delete gitUI.reviewNotes[key]; saveGitWorkflowState(); renderGitPanel(d); } });
  host.querySelector('#gitreviewcopynotes')?.addEventListener('click', async () => { const prefix = `${d.root}\0${gitUI.review.base}\0${gitUI.review.head}\0${gitUI.review.mode}\0`, rows = Object.entries(gitUI.reviewNotes).filter(([key]) => key.startsWith(prefix)).map(([key, note]) => `- **${key.slice(prefix.length)}**: ${note}`); if (!rows.length) return status('this review has no notes', 'err'); const text = `# Review: ${gitUI.review.head} → ${gitUI.review.base}\n\n${rows.join('\n')}\n`; try { await navigator.clipboard.writeText(text); status(`copied ${rows.length} review note${rows.length === 1 ? '' : 's'}`, 'ok'); } catch (_) { status('clipboard access failed', 'err'); } });
  host.querySelector('#gitreviewapply')?.addEventListener('click', () => showReviewHunkApply(d));
  host.querySelector('#githistorygo')?.addEventListener('click', () => { gitUI.historyQuery = $('#githistoryfilter').value.trim(); gitUI.history = []; gitUI.selectedCommit = null; loadGitHistory(); });
  host.querySelector('#githistoryfilter')?.addEventListener('keydown', e => { if (e.key === 'Enter') { gitUI.historyQuery = e.target.value.trim(); gitUI.history = []; gitUI.selectedCommit = null; loadGitHistory(); } });
  host.querySelector('#githistoryref')?.addEventListener('change', () => { gitUI.history = []; gitUI.selectedCommit = null; loadGitHistory(); });
  host.querySelector('#gitreflog')?.addEventListener('click', showGitReflog);
  host.querySelectorAll('[data-history-commit]').forEach(b => b.onclick = () => loadGitCommitInspector(b.dataset.historyCommit));
  host.querySelectorAll('[data-commit]').forEach(b => b.onclick = () => showGitCommit(b.dataset.commit, d.root));
  host.querySelectorAll('[data-commit-file]').forEach(b => b.onclick = () => openGitCommitFile(gitUI.selectedCommit.oid, b.dataset.commitFile));
  host.querySelector('[data-close-commit]')?.addEventListener('click', () => { gitUI.selectedCommit = null; renderGitPanel(d); });
  host.querySelector('.lee-git-commit-inspector [data-cherry]')?.addEventListener('click', () => act('cherry_pick', {ref: gitUI.selectedCommit.oid, repo: gitUI.selectedCommit.root}));
  host.querySelector('.lee-git-commit-inspector [data-revert]')?.addEventListener('click', async () => { if (await confirmDialog('revert commit', `Create a commit that reverses ${gitUI.selectedCommit.short}?`, 'revert')) act('revert', {ref: gitUI.selectedCommit.oid, repo: gitUI.selectedCommit.root}); });
  host.querySelector('.lee-git-commit-inspector [data-reset]')?.addEventListener('click', async () => { const c = gitUI.selectedCommit, mode = await inputDialog('reset branch', 'Mode: soft keeps index; mixed keeps files; hard discards changes', 'mixed', 'soft, mixed, or hard'); if (!['soft','mixed','hard'].includes(mode)) return status('reset mode must be soft, mixed, or hard', 'err'); if (mode === 'hard' && !await confirmDialog('hard reset', `Discard tracked changes and reset to ${c.short}? This cannot be undone.`, 'reset')) return; act('reset', {ref: c.oid, mode, repo: c.root}); });
  const rememberCompare = () => { gitUI.compareFrom = $('#gitcompareleft')?.value.trim() || ''; gitUI.compareTo = $('#gitcompareright')?.value.trim() || ''; };
  host.querySelector('#gitcompareleft')?.addEventListener('change', rememberCompare);
  host.querySelector('#gitcompareright')?.addEventListener('change', rememberCompare);
  host.querySelector('#gitcompareswap')?.addEventListener('click', () => { const left = $('#gitcompareleft'), right = $('#gitcompareright'), value = left.value; left.value = right.value; right.value = value; rememberCompare(); });
  host.querySelector('#gitcomparego')?.addEventListener('click', () => { rememberCompare(); showGitCompare(gitUI.compareFrom, gitUI.compareTo); });
  host.querySelector('[data-hosted-pr]')?.addEventListener('click', e => openExternal(e.currentTarget.dataset.url));
  host.querySelector('#gitaddremote')?.addEventListener('click', async () => { const name = await inputDialog('add remote', 'Remote name', '', 'origin'); if (!name) return; const url = await inputDialog('add remote', 'Fetch URL', '', 'https://github.com/owner/repository.git'); if (url) act('add_remote', {name, url}); });
  host.querySelectorAll('[data-remote]').forEach(row => { const remote = row.dataset.remote; row.querySelector('[data-open-remote]')?.addEventListener('click', b => openExternal(b.currentTarget.dataset.url)); row.querySelector('[data-fetch-remote]').onclick = () => act('fetch', {remote}); row.querySelector('[data-edit-remote]').onclick = async () => { const url = await inputDialog('edit remote', `${remote} fetch URL`, row.querySelector('code').textContent, 'https://github.com/owner/repository.git'); if (url) act('set_remote', {name: remote, url}); }; row.querySelector('[data-remove-remote]').onclick = async () => { if (await confirmDialog('remove remote', `Remove ${remote}? Local commits and branches remain.`, 'remove')) act('remove_remote', {name: remote}); }; });
  host.querySelector('#gitaddworktree')?.addEventListener('click', async () => { const path = await inputDialog('add worktree', 'Directory path', '', '../project-feature'); if (!path) return; const branch = await inputDialog('add worktree', 'Existing branch, or a new branch name', '', 'feature/name'); if (branch) act('add_worktree', {path, branch, create: !(d.branches || []).some(b => !b.remote && b.name === branch)}); });
}
async function showStagedReview(d) {
  const files = (d.changes || []).filter(c => c.staged);
  if (!files.length) return status('stage changes before reviewing them', 'err');
  const m = modal(`<div class="lee-mhead">Review staged changes<span class="sub">${files.length} file${files.length === 1 ? '' : 's'} will be committed</span><span class="lee-spacer"></span><button class="lee-btn" data-prev>previous</button><button class="lee-btn" data-next>next</button></div><div class="lee-git-full-review"><aside></aside><main class="lee-git-patch"></main></div><div class="lee-mfoot"><span class="lee-dim">Only the index is shown. Unstaged edits are not part of the commit.</span></div>`);
  m.classList.add('lee-git-review-expanded');
  let at = 0;
  const paint = async next => {
    at = (next + files.length) % files.length;
    const active = files[at];
    m.querySelector('aside').innerHTML = files.map((f, i) => `<button data-index="${i}" class="${i === at ? 'active' : ''}"><b>${esc(f.index)}</b><span>${esc(f.path)}</span></button>`).join('');
    m.querySelectorAll('[data-index]').forEach(b => b.onclick = () => paint(+b.dataset.index));
    const detail = noteHl(await api(gitUrl('/git/diff', {path: active.path, staged: true})));
    m.querySelector('main').innerHTML = gitPatchHtml(detail.content || detail.text || '');
  };
  m.querySelector('[data-prev]').onclick = () => paint(at - 1);
  m.querySelector('[data-next]').onclick = () => paint(at + 1);
  paint(0);
}
function showReviewHunkApply(d) {
  if (!gitUI.reviewPatch || !gitUI.review?.can_apply) return status('partial apply requires a clean current branch that is the review base', 'err');
  const parts = gitPatchParts(gitUI.reviewPatch);
  if (!parts.hunks.length) return status('this file has no text hunks to apply', 'err');
  const m = modal(`<div class="lee-mhead">Apply parts of ${esc(gitUI.reviewFile)}<span class="sub">from ${esc(gitUI.review.head)} into the current working tree</span></div><div class="lee-git-patch">${parts.hunks.map((h, i) => `<label class="lee-git-hunk"><input type="checkbox" data-hunk="${i}" checked><span>hunk ${i + 1}</span>${gitPatchHtml(h)}</label>`).join('')}</div><div class="lee-mfoot"><button class="lee-btn go" data-apply>apply selected hunks</button><span class="lee-dim">Changes remain uncommitted and can be reviewed before staging.</span></div>`);
  m.querySelector('[data-apply]').onclick = async () => {
    const selected = [...m.querySelectorAll('[data-hunk]:checked')].map(x => parts.hunks[+x.dataset.hunk]);
    if (!selected.length) return status('select at least one hunk', 'err');
    if (!await confirmDialog('apply branch hunks', `Apply ${selected.length} selected hunk${selected.length === 1 ? '' : 's'} from ${gitUI.review.head} to the working tree?`, 'apply')) return;
    try { const next = await gitDo('apply_patch', {patch: parts.header + selected.join(''), staged: false}); m.remove(); gitUI.review = null; gitUI.tab = 'changes'; renderGitPanel(next); }
    catch (e) { leeFail('git', 'apply hunks', e); }
  };
}
async function showMergePreview(branch, d, act) {
  try {
    const p = await api(gitUrl('/git/merge-preview', {incoming: branch}));
    const r = p.review, relation = {'fast-forward': 'Fast-forward available', 'already-merged': 'Already contained in current', 'identical': 'Branches are identical', 'diverged': 'Branches have diverged'}[p.relation] || p.relation;
    const conflict = p.conflict_likely ? `<div class="lee-git-merge-warning"><strong>Conflicts expected</strong><span>${p.conflicts.length ? p.conflicts.map(esc).join(' · ') : 'Git reports overlapping changes.'}</span></div>` : '<div class="lee-git-merge-ok"><strong>No conflicts found in merge rehearsal</strong><span>The working tree can still change before merge.</span></div>';
    // Untracked files are not dirt: git merges beside them and refuses only when the merge would
    // overwrite one, and then says so itself. Only tracked work blocks.
    const dirty = p.clean ? '' : `<div class="lee-git-merge-warning"><strong>Uncommitted changes to ${p.dirty.length} tracked file${p.dirty.length === 1 ? '' : 's'}</strong><span>${p.dirty.map(esc).join(' · ')}</span></div>`;
    const blocked = !p.clean ? `commit or stash ${p.dirty.length} changed file${p.dirty.length === 1 ? '' : 's'} first`
                  : p.relation === 'already-merged' ? `${p.current} already contains ${branch}`
                  : p.relation === 'identical' ? 'the two branches are identical' : '';
    const m = modal(`<div class="lee-mhead">Merge ${esc(branch)}<span class="sub">into ${esc(p.current)}</span></div><div class="lee-git-merge-preview"><header><strong>${esc(relation)}</strong><span>${r.head_only} commits · ${r.summary.files} files · +${r.summary.additions} −${r.summary.deletions}</span></header>${dirty}${conflict}<label>Strategy<select data-strategy><option value="merge">merge commit when needed</option><option value="squash">squash into working tree</option><option value="ff-only" ${p.relation === 'fast-forward' ? '' : 'disabled'}>fast-forward only</option></select></label><button class="lee-btn" data-review>review incoming files</button></div><div class="lee-mfoot"><button class="lee-btn go" data-merge>merge ${esc(branch)}</button><span class="lee-dim">${blocked ? esc(blocked) : 'Merge starts only after this preview.'}</span></div>`);
    m.querySelector('[data-review]').onclick = () => { m.remove(); gitUI.reviewBase = d.branch; gitUI.reviewHead = branch; gitUI.reviewMode = 'review'; gitUI.review = null; gitUI.tab = 'review'; renderGitPanel(d); };
    // Never a disabled button: one that cannot be pressed cannot say why.
    m.querySelector('[data-merge]').onclick = async () => {
      if (blocked) return status(`cannot merge: ${blocked}`, 'err');
      const strategy = m.querySelector('[data-strategy]').value;
      if (!await confirmDialog('merge branch', `Merge ${branch} into ${p.current} using ${strategy}?`, 'merge')) return;
      m.remove(); act('merge', {branch, strategy});
    };
  } catch (e) { leeFail('git', 'merge preview', e); }
}
async function showRebasePreview(branch, d, act) {
  try {
    const p = await api(gitUrl('/git/rebase-preview', {onto: branch})), r = p.review;
    const warning = p.conflict_likely ? `<div class="lee-git-merge-warning"><strong>Replaying these commits is likely to conflict</strong><span>${p.conflicts.length ? p.conflicts.map(esc).join(' · ') : 'Git reports overlapping changes.'}</span></div>` : '<div class="lee-git-merge-ok"><strong>No conflicts found in the tree rehearsal</strong><span>Rebase replays commits individually, so this remains a forecast.</span></div>';
    const rbDirty = p.clean ? '' : `<div class="lee-git-merge-warning"><strong>Uncommitted changes to ${p.dirty.length} tracked file${p.dirty.length === 1 ? '' : 's'}</strong><span>${p.dirty.map(esc).join(' · ')}</span></div>`;
    const rbBlocked = !p.clean ? `commit or stash ${p.dirty.length} changed file${p.dirty.length === 1 ? '' : 's'} first`
                    : p.already_based ? `${p.current} already contains ${branch}`
                    : !p.commits.length ? 'there is nothing to replay' : '';
    const m = modal(`<div class="lee-mhead">Rebase ${esc(p.current)}<span class="sub">onto ${esc(branch)}</span></div><div class="lee-git-merge-preview"><header><strong>${p.already_based ? 'Branch already contains the target history' : `${p.commits.length} commit${p.commits.length === 1 ? '' : 's'} will be replayed`}</strong><span>${r.summary.files} proposed files · +${r.summary.additions} −${r.summary.deletions}</span></header>${rbDirty}${warning}<div class="lee-git-rebase-commits">${p.commits.slice(0, 12).map(c => `<span><code>${esc(c.short)}</code>${esc(c.subject)}</span>`).join('')}</div><button class="lee-btn" data-review>review branch changes</button></div><div class="lee-mfoot"><button class="lee-btn go" data-rebase>start rebase</button><span class="lee-dim">The operation banner will offer continue, skip, and abort if Git pauses.</span></div>`);
    m.querySelector('[data-review]').onclick = () => { m.remove(); gitUI.reviewBase = branch; gitUI.reviewHead = d.branch; gitUI.reviewMode = 'review'; gitUI.review = null; gitUI.tab = 'review'; renderGitPanel(d); };
    m.querySelector('[data-rebase]').onclick = async () => {
      if (rbBlocked) return status(`cannot rebase: ${rbBlocked}`, 'err');
      if (!await confirmDialog('rebase branch', `Replay ${p.commits.length} commit${p.commits.length === 1 ? '' : 's'} from ${p.current} onto ${branch}?`, 'rebase')) return;
      m.remove(); act('rebase', {branch});
    };
  } catch (e) { leeFail('git', 'rebase preview', e); }
}
/* The branch row's `•••`, as a menu anchored to the button rather than a modal. Named for this
   panel because the branch pill in `branchbar.js` has its own, differently shaped menu, and the
   modules are concatenated into one scope, where two `function branchActions` meant the later file
   silently won. */
function gitBranchMenu(anchor, branch, d, act) {
  const current = branch === d.branch;
  const review = mode => {
    Object.assign(gitUI, {reviewBase: d.branch, reviewHead: branch, reviewMode: mode, review: null, tab: 'review'});
    renderGitPanel(d);
  };
  const rows = [
    {label: `Checkout ${branch}`, disabled: current, run: () => act('checkout', {branch})},
    {label: 'New branch from…', detail: branch, run: async () => {
      const name = await inputDialog('new branch', `Branch name, starting at ${branch}`, '', 'feature/name');
      if (name) act('create', {branch: name, start: branch});
    }},
    {separator: true},
    {label: `Review ${branch} into ${d.branch}`, detail: 'proposed changes', disabled: current,
     run: () => review('review')},
    {label: `Diff ${d.branch} … ${branch}`, detail: 'complete snapshots', disabled: current,
     run: () => review('snapshot')},
    {separator: true},
    {label: `Rebase ${d.branch} onto ${branch}`, disabled: current, run: () => showRebasePreview(branch, d, act)},
    {label: `Merge ${branch} into ${d.branch}`, disabled: current, run: () => showMergePreview(branch, d, act)},
    {separator: true},
    {label: 'Rename…', run: async () => {
      const name = await inputDialog('rename branch', 'New name', branch, 'feature/name');
      if (name) act('rename_branch', {branch, name});
    }},
    {label: 'Set upstream…', run: async () => {
      const upstream = await inputDialog('set upstream', 'Remote tracking branch', '', 'origin/' + branch);
      if (upstream) act('set_upstream', {branch, upstream});
    }},
  ];
  if (!current) rows.push({separator: true}, {label: `Delete ${branch}`, warn: true, run: async () => {
    if (await confirmDialog('delete branch', `Delete local branch ${branch}?`, 'delete')) act('delete', {branch});
  }});
  openChromeMenu(anchor, rows);
}
async function loadGitCommitInspector(ref, root = gitRepo()) {
  try { gitUI.selectedCommit = {...await api(gitUrl('/git/commit/review', {ref, repo: root})), root}; renderGitPanel(gitUI.snapshot); }
  catch (e) { leeFail('git', 'commit', e); }
}
async function openGitCommitFile(ref, path, c = gitUI.selectedCommit) {
  const root = c?.root || gitRepo();
  try {
    const d = noteHl(await api(gitUrl('/git/commit/file', {ref, path, repo: root})));
    return openGitDiffTab({...d, path, kind: 'commit', baseLabel: c?.parents?.[0]?.slice(0, 8) || 'empty tree', headLabel: c?.short || ref.slice(0, 8), absolutePath: root + '/' + path});
  } catch (e) { leeFail('git', 'commit file', e); }
}
async function showGitCommit(ref, root = gitRepo()) {
  try {
    const c = {...await api(gitUrl('/git/commit/review', {ref, repo: root})), root};
    const files = c.files.map(f => `<button class="lee-git-commit-file" data-path="${esc(f.path)}"><b>${esc(f.status)}</b><span>${esc(f.path)}</span><small>${f.binary ? 'binary' : `+${f.additions} −${f.deletions}`}</small></button>`).join('');
    const m = modal(`<div class="lee-mhead">${esc(c.short)}<span class="sub">${esc(c.author)} · ${new Date(c.timestamp * 1000).toLocaleString()}</span></div><article class="lee-git-commit-sheet"><h3>${esc(c.message)}</h3><section><b>${c.summary.files} files</b><span>+${c.summary.additions}</span><span>−${c.summary.deletions}</span></section><div>${files}</div></article>`);
    m.querySelectorAll('[data-path]').forEach(b => b.onclick = () => { m.remove(); openGitCommitFile(c.oid, b.dataset.path, c); });
  } catch (e) { leeFail('git', 'commit', e); }
}
async function showGitCompare(left, right) {
  if (!left || !right) return status('choose a base and target ref', 'err');
  gitUI.reviewBase = left; gitUI.reviewHead = right; gitUI.reviewMode = 'snapshot';
  gitUI.review = null; gitUI.reviewFile = ''; gitUI.reviewPatch = ''; gitUI.tab = 'review';
  await renderGitPanel(gitUI.snapshot);
}
async function showGitReflog() {
  try {
    const root = gitRepo(), d = await api(gitUrl('/git/reflog', {limit: 150, repo: root}));
    const m = modal(`<div class="lee-mhead">reflog<span class="sub">local recovery history · newest first</span></div><div class="lee-git-history">${(d.entries || []).map(x => `<button class="lee-git-commit-row" data-commit="${x.oid}"><span class="lee-git-graph">◆</span><span><strong>${esc(x.subject)}</strong><small>${esc(x.selector)} · ${esc(x.author)} · ${gitRelative(x.timestamp)} · ${esc(x.short)}</small></span></button>`).join('') || '<div class="lee-git-empty-state"><strong>No reflog entries</strong><span>This repository has no local movement history.</span></div>'}</div>`);
    m.querySelectorAll('[data-commit]').forEach(b => b.onclick = () => showGitCommit(b.dataset.commit, root));
  } catch (e) { leeFail('git', 'reflog', e); }
}
// Three-pane conflict resolution: ours, an editable result, and theirs.
//
// The conflicts are read from the markers Git already wrote into the working-tree file rather than
// diffed back out of the three versions. Git knows which lines it tried to merge and gave up on,
// and a re-diff only guesses at it.
//
// The result pane is that file, markers and all, re-scanned after every change. That is what lets
// the buttons and hand-editing coexist without either being a mode, and an edit that removes a
// marker block counts as resolving it.

const CONFLICT_OPEN = /^<{7}(?:\s|$)/, CONFLICT_MID = /^={7}(?:\s|$)/,
      CONFLICT_BASE = /^\|{7}(?:\s|$)/, CONFLICT_CLOSE = /^>{7}(?:\s|$)/;

function scanConflicts(text) {
  const lines = String(text ?? '').split('\n'), blocks = [];
  for (let i = 0; i < lines.length; i++) {
    if (!CONFLICT_OPEN.test(lines[i])) continue;
    const block = {start: i, end: -1, ours: [], theirs: [], base: []};
    let side = block.ours, j = i + 1;
    for (; j < lines.length; j++) {
      if (CONFLICT_BASE.test(lines[j])) { side = block.base; continue; }
      if (CONFLICT_MID.test(lines[j])) { side = block.theirs; continue; }
      if (CONFLICT_CLOSE.test(lines[j])) { block.end = j; break; }
      side.push(lines[j]);
    }
    // An opening marker with no close is a line of text that looks like one, in a file about
    // merge conflicts. Not a conflict, and not ours to rewrite.
    if (block.end < 0) continue;
    blocks.push(block); i = block.end;
  }
  return {lines, blocks};
}

// One whole side of a conflicted file, as it would read if every contested block went that
// way. `ranges` are the 1-based line spans of the contested parts, for marking them.
function conflictSide(scan, pick) {
  const out = [], ranges = [];
  let at = 0;
  for (const block of scan.blocks) {
    out.push(...scan.lines.slice(at, block.start));
    const from = out.length + 1;
    out.push(...(block[pick] || []));
    // A side that deleted these lines contributes none, so the marker goes on the seam.
    ranges.push(out.length >= from ? {from, to: out.length}
                                   : {from: Math.max(1, from - 1), to: Math.max(1, from - 1)});
    at = block.end + 1;
  }
  out.push(...scan.lines.slice(at));
  return {text: out.join('\n'), ranges};
}

function replaceConflict(scan, index, lines) {
  const block = scan.blocks[index];
  if (!block) return null;
  return [...scan.lines.slice(0, block.start), ...lines,
          ...scan.lines.slice(block.end + 1)].join('\n');
}

async function showGitConflict(path) {
  // A notebook is answered cell by cell, in `conflictcells.js`. The route says whether git holds
  // three readable notebooks; when it does not, the text panes are still the honest fallback.
  if (/\.ipynb$/i.test(path)) {
    let nb = null;
    try { nb = await api(gitUrl('/git/notebook/conflict', {path})); }
    catch (e) { status(`cell merge unavailable · ${e.message || e}`, 'err'); }
    if (nb && nb.notebook) return showNotebookConflict(path, nb);
    if (nb && nb.error) status(`${nb.error}; showing the text panes`, 'err');
  }
  try {
    const d = await api(gitUrl('/git/conflict', {path}));
    const original = scanConflicts(d.worktree || '');
    if (!original.blocks.length && (d.ours || d.theirs)) {
      // Add/add or delete/modify: there are no marked lines to work through, so the choice is
      // which whole side to keep.
      return showWholeSideConflict(path, d);
    }
    const lang = codeLang('', path);
    const pane = (key, label, note) =>
      `<section data-pane="${key}"${key === 'base' ? ' hidden' : ''}>` +
      `<header><strong>${label}</strong>${note ? `<small>${note}</small>` : ''}</header>` +
      `<div class="lee-merge3-editor" data-editor></div></section>`;
    const m = modal(
      `<div class="lee-mhead">resolve ${esc(path)}<span class="sub">ours · result · theirs</span></div>` +
      `<div class="lee-git-merge3">` +
      `<div class="lee-merge3-bar">` +
      `<span class="lee-merge3-count" data-count></span>` +
      `<button class="lee-btn" data-nav="prev" title="previous conflict">‹</button>` +
      `<button class="lee-btn" data-nav="next" title="next conflict">›</button>` +
      `<span class="lee-merge3-take">` +
      `<button class="lee-btn" data-take="ours">take ours</button>` +
      `<button class="lee-btn" data-take="theirs">take theirs</button>` +
      `<button class="lee-btn" data-take="both">both</button></span>` +
      `<button class="lee-btn" data-base-toggle>show base</button></div>` +
      `<div class="lee-merge3-panes">${pane('base', 'base', 'common ancestor')}` +
      `${pane('ours', 'ours', 'this branch')}` +
      `${pane('result', 'result', 'editable')}` +
      `${pane('theirs', 'theirs', 'incoming')}</div>` +
      `<div class="lee-merge3-foot"><span class="lee-dim" data-state></span>` +
      `<button class="lee-btn go" data-resolve>resolve &amp; stage</button></div></div>`,
      null, () => teardown(), {className: 'lee-modal-merge3', storageKey: 'git-conflict'});

    const views = {};
    const editorFor = key => m.querySelector(`[data-pane="${key}"] [data-editor]`);
    const teardown = () => Object.values(views).forEach(v => { try { LeeCM.destroy(v); } catch {} });
    let live = original, active = 0;

    const marks = (ranges, current) => ranges.map((r, i) =>
      ({...r, kind: i === current ? 'conflict-active' : 'conflict'}));

    for (const key of ['base', 'ours', 'theirs']) {
      const {text, ranges} = conflictSide(original, key);
      views[key] = createEditor(editorFor(key), {
        doc: text, lang, readOnly: true, lineNums: true, settings: lee.editorPrefs});
      views[key]._ranges = ranges;
      LeeCM.setChangedLines(views[key], marks(ranges, 0));
    }
    // `onChange` runs inside CodeMirror's own update, where dispatching again is not allowed, and
    // `refresh` dispatches marks. `programmatic` is why a button's own `setDoc` does not come back
    // round here and refresh a second time from stale text.
    let programmatic = false;
    views.result = createEditor(editorFor('result'), {
      doc: d.worktree || '', lang, lineNums: true, settings: lee.editorPrefs,
      onChange: text => { if (!programmatic) setTimeout(() => refresh(text, false), 0); }});

    // Which of the original blocks a remaining one is, matched on its contested text. Indices
    // cannot be used: resolving the second of three leaves two, and the sides still show three.
    // Two identical conflicts in one file align to the first, which is harmless.
    const originalIndex = block => original.blocks.findIndex(b =>
      b.ours.join('\n') === block.ours.join('\n') && b.theirs.join('\n') === block.theirs.join('\n'));

    // The side panes are read-only and CodeMirror only builds the lines it is showing, so there
    // is no element to scroll to for an off-screen conflict. Proportional scrolling gets close
    // enough to read.
    const align = () => {
      const block = live.blocks[active];
      const index = block ? originalIndex(block) : -1;
      for (const key of ['base', 'ours', 'theirs']) {
        const view = views[key], range = index >= 0 ? view._ranges[index] : null;
        LeeCM.setChangedLines(view, marks(view._ranges, index));
        const scroller = view.dom.querySelector('.cm-scroller');
        if (!range || !scroller) continue;
        const total = Math.max(1, LeeCM.lineCount(view));
        scroller.scrollTop = Math.max(0, (range.from - 1) / total * scroller.scrollHeight
                                         - scroller.clientHeight / 3);
      }
    };

    const refresh = (text, move = true) => {
      live = scanConflicts(text ?? LeeCM.getDoc(views.result));
      const total = live.blocks.length;
      active = Math.max(0, Math.min(active, total - 1));
      const done = original.blocks.length - total;
      m.querySelector('[data-count]').textContent = total
        ? `conflict ${active + 1} of ${total}` : 'no conflicts left';
      m.querySelector('[data-state]').textContent = total
        ? `${done} of ${original.blocks.length} resolved`
        : `all ${original.blocks.length} resolved. Stage the file to mark it merged.`;
      m.querySelectorAll('[data-take],[data-nav]').forEach(b => b.disabled = !total);
      m.querySelector('[data-resolve]').classList.toggle('go', !total);
      LeeCM.setChangedLines(views.result, marks(
        live.blocks.map(b => ({from: b.start + 1, to: b.end + 1})), active));
      if (move) align();
    };

    const jumpTo = index => {
      const total = live.blocks.length;
      if (!total) return;
      active = (index + total) % total;
      const block = live.blocks[active];
      const at = live.lines.slice(0, block.start).reduce((n, l) => n + l.length + 1, 0);
      refresh(null, true);
      LeeCM.setSelection(views.result, at, at);
    };

    const take = which => {
      const block = live.blocks[active];
      if (!block) return;
      const lines = which === 'both' ? [...block.ours, ...block.theirs] : block[which];
      const next = replaceConflict(live, active, lines);
      if (next == null) return;
      programmatic = true;
      try { LeeCM.setDoc(views.result, next); } finally { programmatic = false; }
      refresh(next, true);
      if (live.blocks.length) jumpTo(Math.min(active, live.blocks.length - 1));
    };

    m.querySelectorAll('[data-take]').forEach(b => b.onclick = () => take(b.dataset.take));
    m.querySelector('[data-nav="prev"]').onclick = () => jumpTo(active - 1);
    m.querySelector('[data-nav="next"]').onclick = () => jumpTo(active + 1);
    m.querySelector('[data-base-toggle]').onclick = e => {
      const section = m.querySelector('[data-pane="base"]');
      section.hidden = !section.hidden;
      e.currentTarget.textContent = section.hidden ? 'show base' : 'hide base';
      if (!section.hidden) align();
    };
    m.querySelector('[data-resolve]').onclick = async () => {
      const content = LeeCM.getDoc(views.result);
      const left = scanConflicts(content).blocks.length;
      if (left && !await confirmDialog('stage an unresolved file',
          `${left} conflict marker block${left === 1 ? '' : 's'} are still in ${path}. Stage it ` +
          `anyway, markers and all?`, 'stage anyway')) return;
      // What the panes were built from, so a change made on disk since then is refused
      // rather than overwritten.
      const next = await gitDo('resolve_conflict',
                               {path, choice: 'resolved', content, before: d.worktree});
      m.remove();
      afterConflictResolved(next, `${path} staged`);
    };
    refresh(d.worktree || '', true);
    jumpTo(0);
  } catch (e) { leeFail('git', 'resolve conflict', e); }
}

// Add/add and delete/modify conflicts have no contested lines, because one side has no file at
// all, so the only question is which side to keep.
async function showWholeSideConflict(path, d) {
  const side = (label, text, choice) =>
    `<section><header><strong>${label}</strong>` +
    `<button class="lee-btn" data-choice="${choice}">use ${label}</button></header>` +
    `<pre>${esc(text || 'This side does not have this file.')}</pre></section>`;
  const m = modal(
    `<div class="lee-mhead">resolve ${esc(path)}<span class="sub">one side has no file to merge</span></div>` +
    `<div class="lee-git-conflict">${side('ours', d.ours, 'ours')}${side('theirs', d.theirs, 'theirs')}` +
    `<details><summary>common base</summary><pre>${esc(d.base || 'No common base content.')}</pre></details></div>`,
    null, null, {storageKey: 'git-conflict-side'});
  m.querySelectorAll('[data-choice]').forEach(b => b.onclick = async () => {
    const choice = b.dataset.choice;
    if (!await confirmDialog('resolve conflict', `Use ${choice} for ${path} and stage it as resolved?`, 'resolve')) return;
    m.remove();
    // A checkout overwrites the working file, so it is gated on the same before-image the
    // three-pane resolution is, rather than on the server still remembering these panes.
    afterConflictResolved(await gitDo('resolve_conflict', {path, choice, before: d.worktree}),
                          `${path} staged`);
  });
}

// Blame, reachable from wherever you are rather than only from a changed-file row. A text file
// blames the lines you have selected, and the whole-file answer is one button away. A notebook
// blames its cells, because blaming its JSON tells you about `"source": [` and nothing about the
// code.
function blameRelative(root, path) {
  const p = String(path || '');
  if (!root) return p;
  return p.startsWith(root + '/') ? p.slice(root.length + 1) : p;
}
function blameSelectionRange() {
  const view = curEditor(); if (!view || lee.kind === 'notebook') return null;
  const sel = view.state.selection.main;
  if (sel.empty) return null;
  const doc = view.state.doc;
  return {start: doc.lineAt(sel.from).number, end: doc.lineAt(sel.to).number};
}
async function leeBlame() {
  if (!lee.path) return status('open a file to blame it', 'err');
  let root = gitUI.snapshot?.root;
  if (root && !lee.path.startsWith(root + '/')) root = gitUI.repo && lee.path.startsWith(gitUI.repo + '/') ? gitUI.repo : '';
  if (!root) { try { root = (await gitInfo(gitUrl('/git/info', {repo: ''}))).root; } catch (e) { return leeFail('git', 'blame', e); } }
  showGitBlame(root, blameRelative(root, lee.path), blameSelectionRange());
}
window.leeBlame = leeBlame;
function blameHue(oid, commits) {
  // Colour by commit, so a cell made of three commits reads as three bands. Position in the
  // recency-sorted legend rather than a hash, because the newest change is what is looked for.
  const i = commits.findIndex(c => c.oid === oid);
  return i < 0 ? 'var(--lee-fg4)' : `hsl(${(i * 47) % 360} 55% 55%)`;
}
function blameLineRows(lines, commits, showN) {
  return lines.map(l => `<button class="lee-blame-line${l.uncommitted ? ' uncommitted' : ''}" data-commit="${esc(l.oid)}" ` +
    `title="${esc(l.author)} · ${esc(l.summary || '')}">` +
    `<i style="background:${blameHue(l.oid, commits)}"></i>` +
    `<code>${l.uncommitted ? 'working' : esc(l.oid.slice(0, 8))}</code>` +
    `<span class="lee-blame-who">${esc(l.author || '')}</span>` +
    `<small>${l.timestamp ? gitRelative(l.timestamp) : ''}</small>` +
    `<em>${showN ? l.n : l.line}</em><pre>${esc(l.text)}</pre></button>`).join('');
}
function blameCells(d) {
  const commits = d.commits || [];
  const legend = commits.length ? `<div class="lee-blame-legend">${commits.map(c =>
    `<i style="border-color:${blameHue(c.oid, commits)}">${c.uncommitted ? 'working tree' : esc(c.oid.slice(0, 8))} · ${esc(c.author || '')}</i>`).join('')}</div>` : '';
  const cells = d.cells.map(c => {
    const t = c.touched || {};
    const made = c.commits.length;
    return `<details class="lee-blame-cell" data-cell="${c.index}">` +
      `<summary><b>${c.index}</b><span class="lee-blame-kind">${esc(c.kind)}</span>` +
      `<strong>${esc(t.author || 'never committed')}</strong>` +
      `<small>${t.timestamp ? gitRelative(t.timestamp) : ''}${made > 1 ? ` · ${made} commits` : ''}` +
      `${c.mapped ? '' : ' · lines not located'}</small>` +
      `<span class="lee-blame-bar">${c.commits.map(x =>
        `<i style="background:${blameHue(x.oid, commits)};flex:${x.lines}"></i>`).join('')}</span></summary>` +
      `<div class="lee-git-blame">${blameLineRows(c.lines, commits, true)}</div></details>`;
  }).join('');
  return legend + `<div class="lee-blame-cells">${cells}</div>`;
}
async function showGitBlame(root, path, range = null) {
  try {
    const params = {path, repo: root, ...(range ? {start: range.start, end: range.end} : {})};
    const d = await api(gitUrl('/git/blame', params));
    const scope = d.notebook ? `${d.cells.length} cells`
                             : range ? `lines ${range.start}–${range.end}` : 'whole file';
    const commits = d.commits || [];
    const body = d.notebook ? blameCells(d)
      : `<div class="lee-git-blame">${blameLineRows((d.lines || []).map(x => ({...x, uncommitted: /^0+$/.test(x.oid)})), commits, false)}</div>`;
    const m = modal(`<div class="lee-mhead">${esc(path)}<span class="sub">who wrote this · ${esc(scope)}</span></div>` +
      `${d.error ? `<div class="lee-dialogcopy">${esc(d.error)}</div>` : ''}${body}` +
      `${range ? '<div class="lee-mfoot"><button class="lee-btn" id="blameall">blame the whole file</button></div>' : ''}`);
    m.querySelectorAll('[data-commit]').forEach(b => b.onclick = () => showGitCommit(b.dataset.commit, root));
    m.querySelector('#blameall')?.addEventListener('click', () => { m.remove(); showGitBlame(root, path, null); });
  } catch (e) { leeFail('git', 'blame', e); }
}
function leeGit() { leeLeft('git'); }
function leeGitRefresh() { gitUI.snapshot = null; gitUI.history = []; renderGitPanel(); refreshProjectPills(); }
window.leeGit = leeGit; window.leeGitRefresh = leeGitRefresh;

async function leeNbdevPrepare() {
  status('nbdev prepare…', 'busy');
  try {
    const r = await post('/project/nbdev_prepare', {});
    status(`nbdev prepare · ${PathName(r.root)}${r.nbs_path ? ' · ' + r.nbs_path : ''}`, 'ok');
    refreshFileTree(undefined, false).catch(() => {});
  } catch (e) { status(String(e.message || e), 'err'); }
}
function PathName(path) { return String(path || '').split('/').pop() || path || ''; }
window.leeNbdevPrepare = leeNbdevPrepare;

function researchDomain(url) {
  try { return new URL(url).hostname.replace(/^www\./, ''); } catch (_) { return 'source'; }
}
async function saveDoc(doc, kind) {
  doc = doc || lee.lastDoc; if (!doc) return status('nothing fetched yet', 'err');
  if (kind === 'notebook' && !doc.url) return status('a research digest can be saved as markdown; source pages can become notebooks', 'err');
  if (!doc.text && doc.url && kind !== 'notebook') {
    status('reading source before saving…');
    const fetched = await api('/research/read?url=' + encodeURIComponent(doc.url));
    if (!fetched.doc) return status(fetched.note, 'err');
    doc = fetched.doc;
  }
  const r = await post('/research/save', {kind: kind === 'notebook' ? 'notebook' : 'md',
                                          url: doc.url, title: doc.title, text: doc.text});
  status('saved ' + r.entry.path, 'ok');
  leeOpenFile(r.entry.path);
}
function researchWorkspace(mode = 'search', value = '') {
  let activeMode = mode, docs = [], activeDoc = null, digest = '', query = value;
  const m = modal(`<div class="lee-mhead lee-research-head"><span>Research</span>` +
    `<span class="sub">search, read, and keep sources with the project</span></div>` +
    `<form class="lee-research-command"><div class="lee-segbar" aria-label="research mode">` +
    `<button type="button" class="lee-seg" data-mode="search">Search</button>` +
    `<button type="button" class="lee-seg" data-mode="read">Read URL</button>` +
    `<button type="button" class="lee-seg" data-mode="research">Research</button>` +
    `<button type="button" class="lee-seg" data-mode="vault">Vault</button></div>` +
    `<input class="lee-input" id="researchquery" autocomplete="off">` +
    `<label class="lee-research-remember" title="Store fetched sources in durable memory"><input type="checkbox" id="researchremember" checked> remember</label>` +
    `<button class="lee-btn go" type="submit">Go</button></form>` +
    `<div class="lee-research-body"><aside class="lee-research-sources">` +
    `<div class="lee-research-section-label">Sources</div><div id="researchsources" class="lee-research-source-list">` +
    `<div class="lee-research-empty">Search the web or enter a URL to begin.</div></div></aside>` +
    `<main class="lee-research-reader"><div class="lee-research-reader-head"><div>` +
    `<strong id="researchtitle">Research workspace</strong><span id="researchmeta">Current sources stay visible while you read.</span></div>` +
    `<div class="lee-research-actions"><button class="lee-btn" data-new-thought>New note</button>` +
    `<button class="lee-btn" data-open disabled>Open webpage</button>` +
    `<button class="lee-btn" data-save disabled>Save Markdown</button><button class="lee-btn" data-notebook disabled>Make notebook</button>` +
    `<button class="lee-btn" data-memory-note disabled>Add to agent memory</button>` +
    `<button class="lee-btn" data-forget disabled>Forget</button><button class="lee-btn" data-ask disabled>Ask with sources</button></div></div>` +
    `<article id="researchreader" class="lee-research-content"><div class="lee-research-hero">` +
    `<span class="lee-research-mark">R</span><strong>Keep evidence close to the work.</strong>` +
    `<p>Read a source cleanly, save it into the project, or carry cited results into the assistant.</p></div></article></main></div>`);
  m.classList.add('lee-research-modal');
  const input = $('#researchquery', m), list = $('#researchsources', m), reader = $('#researchreader', m);
  const title = $('#researchtitle', m), meta = $('#researchmeta', m);
  /* Vault mode puts what you have already kept in the same column as what you are about to find.
     The sources list becomes the vault tree, and the reader stays the reader. */
  const showVault = async () => {
    list.innerHTML = '<div class="lee-research-empty">Reading the vault…</div>';
    // `elid`, because the vault panel can be open behind this modal with a fragment of its own,
    // and two elements sharing an id would send every folder toggle to whichever came first.
    try {
      await htmx.ajax('GET', '/vault/browse?elid=researchvault', {target: '#researchsources', swap: 'innerHTML'});
      list.insertAdjacentHTML('afterbegin', '<button class="lee-btn" data-open-vault>open in Vault</button>');
      $('[data-open-vault]', list).onclick = () => { m.remove(); leeVaultWorkbench('library'); };
    }
    catch (e) { list.innerHTML = `<div class="lee-research-error">${esc(e.message || e)}</div>`; }
  };
  const setMode = next => {
    activeMode = next;
    $$('[data-mode]', m).forEach(b => b.classList.toggle('active', b.dataset.mode === next));
    input.placeholder = next === 'read' ? 'https://example.com/article' :
      next === 'research' ? 'Research a question across several sources…' :
      next === 'vault' ? 'Search what you have already kept…' : 'Search the web…';
    m.classList.toggle('research-vault', next === 'vault');
    if (next === 'vault') showVault();
    input.focus();
  };
  const setBusy = text => {
    reader.innerHTML = `<div class="lee-research-loading"><span></span><span></span><span></span><p>${esc(text)}</p></div>`;
  };
  const setActions = doc => {
    $('[data-open]', m).disabled = !doc?.url;
    $('[data-save]', m).disabled = !doc;
    $('[data-notebook]', m).disabled = !doc?.url;
    $('[data-memory-note]', m).disabled = !doc?.text;
    $('[data-forget]', m).disabled = !doc?.memory_id;
    $('[data-ask]', m).disabled = !(docs.length || doc);
  };
  const showDoc = async doc => {
    activeDoc = doc; lee.lastDoc = doc;
    title.textContent = doc.title || doc.url || 'Source'; meta.textContent = doc.url || 'research digest';
    setActions(doc);
    if (!doc.text && doc.url) {
      setBusy('Reading and cleaning the source…');
      try {
        const remember = $('#researchremember', m)?.checked !== false;
        const result = await api('/research/read?url=' + encodeURIComponent(doc.url) + '&remember=' + remember);
        if (!result.doc) throw new Error(result.note || 'No readable content');
        Object.assign(doc, result.doc); activeDoc = doc; lee.lastDoc = doc; setActions(doc);
      } catch (e) { reader.innerHTML = `<div class="lee-research-error"><strong>Could not read this source</strong><p>${esc(e.message || e)}</p>` +
        `<button class="lee-btn" data-open-fallback>Open the original webpage</button></div>`;
        $('[data-open-fallback]', reader).onclick = () => openExternal(doc.url); return; }
    }
    reader.innerHTML = '';
    if ((doc.sections || []).length > 1) {
      const collection = document.createElement('div'); collection.className = 'lee-research-collection';
      doc.sections.forEach((section, i) => {
        const article = document.createElement('article'); article.className = 'lee-research-article';
        article.innerHTML = `<header><span>${String(i + 1).padStart(2, '0')}</span>` +
          `<strong>${esc(section.title || `Article ${i + 1}`)}</strong></header>`;
        const body = document.createElement('div'); body.className = 'lee-research-markdown';
        article.appendChild(body); collection.appendChild(article); renderMarkdown(body, section.text || '');
      });
      reader.appendChild(collection);
      meta.textContent = `${researchDomain(doc.url)} · ${doc.sections.length} articles · ` +
        `${doc.sections.reduce((n, x) => n + (x.text || '').length, 0).toLocaleString()} characters`;
    } else {
      const md = document.createElement('div'); md.className = 'lee-research-markdown'; reader.appendChild(md);
      renderMarkdown(md, doc.text || 'No readable content was returned.');
      meta.textContent = `${researchDomain(doc.url)} · ${(doc.text || '').length.toLocaleString()} characters`;
    }
  };
  const paintSources = () => {
    list.innerHTML = docs.length ? docs.map((doc, i) => `<button class="lee-research-source${doc === activeDoc ? ' active' : ''}" data-source="${i}">` +
      `<span class="lee-research-source-index">${String(i + 1).padStart(2, '0')}</span><span><strong>${esc(doc.title || doc.url)}</strong>` +
      `<small>${esc(researchDomain(doc.url))}</small></span></button>`).join('') :
      '<div class="lee-research-empty">No sources yet.</div>';
  };
  const run = async () => {
    query = input.value.trim();
    // The vault is searched where it is shown, and an empty box puts the tree back, the same
    // two-views-of-one-panel rule the vault panel follows.
    if (activeMode === 'vault')
      return htmx.ajax('GET', '/vault/browse?' + new URLSearchParams({q: query, elid: 'researchvault'}),
                       {target: '#researchsources', swap: 'innerHTML'});
    if (!query) return;
    setBusy(activeMode === 'research' ? 'Reading and comparing the strongest sources…' : activeMode === 'read' ? 'Fetching the page…' : 'Searching the web…');
    try {
      if (activeMode === 'read') {
        const remember = $('#researchremember', m)?.checked !== false;
        const result = await api('/research/read?url=' + encodeURIComponent(query) + '&remember=' + remember);
        if (!result.doc) throw new Error(result.note || 'No readable content');
        docs = [result.doc]; paintSources(); await showDoc(result.doc); paintSources();
      } else if (activeMode === 'research') {
        const remember = $('#researchremember', m)?.checked !== false;
        const result = await api('/research/dig?q=' + encodeURIComponent(query) + '&remember=' + remember);
        docs = result.docs || []; digest = result.digest || '';
        const brief = {title: query, url: '', text: digest, kind: 'research'};
        paintSources(); await showDoc(brief); status(result.note, docs.length ? 'ok' : 'err');
      } else {
        const result = await api('/research/search?q=' + encodeURIComponent(query));
        docs = result.docs || []; activeDoc = null; paintSources();
        title.textContent = `${docs.length} results`; meta.textContent = result.note || query; setActions(null);
        reader.innerHTML = docs.length ? '<div class="lee-research-empty">Choose a source to open it in the reader.</div>' :
          '<div class="lee-research-error"><strong>No sources found</strong><p>Try a more specific query or switch to Research.</p></div>';
        status(result.note, docs.length ? 'ok' : 'err');
      }
    } catch (e) { reader.innerHTML = `<div class="lee-research-error"><strong>Research stopped</strong><p>${esc(e.message || e)}</p></div>`; status(e.message || String(e), 'err'); }
  };
  m.querySelector('.lee-research-command').onsubmit = e => { e.preventDefault(); run(); };
  m.querySelector('.lee-segbar').onclick = e => { const b = e.target.closest('[data-mode]'); if (b) setMode(b.dataset.mode); };
  list.onclick = e => { const b = e.target.closest('[data-source]'); if (!b) return; const doc = docs[+b.dataset.source]; showDoc(doc).then(paintSources); };
  $('[data-new-thought]', m).onclick = () => {
    activeDoc = {title: 'Research notes', url: '', text: '', kind: 'note'}; lee.lastDoc = activeDoc;
    title.textContent = 'New research note'; meta.textContent = 'Your Markdown scratchpad · save to the project or agent memory';
    reader.innerHTML = `<section class="lee-research-note-editor"><label>Title<input class="lee-input" data-thought-title value="Research notes"></label>` +
      `<div class="lee-research-note-cm"></div></section>`;
    const noteEditor = createEditor($('.lee-research-note-cm', reader), {doc: '# Notes\n\n', lang: 'markdown', lineNums: true,
      placeholder: 'Write observations, decisions, open questions, and links…', onChange: text => {
        activeDoc.text = text; setActions(activeDoc);
      }});
    activeDoc.text = LeeCM.getDoc(noteEditor); setActions(activeDoc);
    $('[data-thought-title]', reader).oninput = e => { activeDoc.title = e.target.value || 'Research notes'; };
    $('[data-thought-title]', reader).focus();
  };
  $('[data-open]', m).onclick = () => openExternal(activeDoc?.url);
  $('[data-save]', m).onclick = () => activeDoc && saveDoc(activeDoc, 'markdown');
  $('[data-notebook]', m).onclick = () => activeDoc && saveDoc(activeDoc, 'notebook');
  $('[data-memory-note]', m).onclick = () => {
    if (!activeDoc?.text) return;
    const source = activeDoc.url ? `\n\nSource: ${activeDoc.url}` : '';
    const text = String(activeDoc.text || '').slice(0, 30_000) + source;
    m.remove(); leeNewMemoryNote({title: activeDoc.title || query || 'Research note', text});
    status('research added to a new memory note; edit and choose model routing before saving', 'ok');
  };
  $('[data-forget]', m).onclick = async () => {
    if (!activeDoc?.memory_id) return;
    if (!await confirmDialog('forget research source', `Remove ${activeDoc.title || activeDoc.url} from durable memory?`, 'forget')) return;
    await post('/memory/forget', {id: activeDoc.memory_id}); activeDoc.memory_id = '';
    setActions(activeDoc); lee.memoryLoaded = false; status('source removed from memory', 'ok');
  };
  $('[data-ask]', m).onclick = () => {
    const sources = docs.filter(d => d.url).map((d, i) => `[${i + 1}] ${d.title}: ${d.url}`).join('\n');
    const prompt = $('#agentprompt'); if (!prompt) return;
    prompt.value = `Research this question using these sources and cite them in the answer:\n\n${query || activeDoc?.title || ''}\n\n${sources}`;
    m.remove(); leePane('right', true); leeRight('agent'); prompt.focus(); status(`${docs.length} research sources added to the prompt`, 'ok');
  };
  setMode(mode); input.value = value;
  if (value) queueMicrotask(run);
  return m;
}
function webSearch() { return researchWorkspace('search'); }
function readUrl(url = '') { return researchWorkspace('read', url); }
function researchQ() { return researchWorkspace('research'); }


// Clip a file, a folder or the open tab into the workspace vault shelf.
function clipTarget() {
  // Which menu opened decides the target. A tab names its path in `title`, so an inactive tab
  // read straight after right-clicking it does not have to wait for the select.
  const s = lee.menuSurface;
  if (s === 'file' || s === 'folder') return treeSel()?.dataset.path || '';
  if (s === 'tab') return $(`.lee-tab[data-i="${lee.menuTab}"]`)?.title || '';
  return treeSel()?.dataset.path || lee.path || '';
}
window.clipTarget = clipTarget;
function modalViewport() {
  const v = window.visualViewport;
  return {left: v?.offsetLeft || 0, top: v?.offsetTop || 0, width: v?.width || innerWidth, height: v?.height || innerHeight};
}
function fitModal(m) {
  const box = $('.lee-modalbox', m), v = modalViewport(), gap = 8; if (!box) return;
  box.style.maxWidth = Math.max(0, v.width - gap * 2) + 'px';
  // Below where the box starts, not the whole viewport: a box 5vh down with a full-height cap ran off the bottom.
  const top = m.classList.contains('lee-modal-moved') ? gap : Math.max(gap, box.getBoundingClientRect().top - v.top);
  box.style.maxHeight = Math.max(0, v.height - top - gap) + 'px';
  if (!m.classList.contains('lee-modal-moved')) return;
  const r = box.getBoundingClientRect();
  box.style.left = Math.max(v.left, Math.min(r.left, v.left + v.width - Math.min(r.width, v.width) - gap)) + 'px';
  box.style.top = Math.max(v.top, Math.min(r.top, v.top + v.height - Math.min(r.height, v.height) - gap)) + 'px';
}
function modal(inner, onKey, onClose, options = {}) {
  const previousFocus = document.activeElement;
  const m = document.createElement('div');
  m.className = `lee-modal${options.className ? ' ' + options.className : ''}`;
  m.innerHTML = `<div class="lee-modalbox lee-modal-resizable" role="dialog" aria-modal="true" tabindex="-1">` +
                `<div class="lee-modal-grip" aria-hidden="true"></div>${inner}` +
                `<button class="lee-modal-expand" type="button" aria-label="expand dialog" title="expand dialog">↗</button>` +
                `<button class="lee-modal-close" type="button" aria-label="close dialog">×</button></div>`;
  const box = m.querySelector('.lee-modalbox');
  const heading = box.querySelector('.lee-mhead');
  if (heading) box.setAttribute('aria-label', heading.textContent.trim());
  const storageKey = options.storageKey ? `lee-modal-size:${options.storageKey}` : '';
  const viewport = modalViewport();
  if (storageKey) {
    try {
      const saved = JSON.parse(localStorage.getItem(storageKey) || 'null');
      if (saved?.width) box.style.width = Math.min(saved.width, viewport.width - 16) + 'px';
      if (saved?.height) box.style.height = Math.min(saved.height, viewport.height - 16) + 'px';
      if (Number.isFinite(saved?.left) && Number.isFinite(saved?.top)) {
        m.classList.add('lee-modal-moved');
        box.style.left = Math.max(viewport.left, Math.min(saved.left, viewport.left + viewport.width - 80)) + 'px';
        box.style.top = Math.max(viewport.top, Math.min(saved.top, viewport.top + viewport.height - 48)) + 'px';
      }
    } catch (_) {}
  }
  // Result rows are true keyboard targets, not divs that only a mouse can activate.
  const prepareRows = root => $$('.lee-mrow', root).forEach(row => {
    row.tabIndex = row.dataset.off ? -1 : 0; row.setAttribute('role', 'option');
    row.setAttribute('aria-selected', String(row.classList.contains('sel')));
    const list = row.closest('.lee-modallist'); if (list && !list.hasAttribute('role')) list.setAttribute('role', 'listbox');
  });
  prepareRows(m);
  const observer = new MutationObserver(records => records.forEach(r => r.addedNodes.forEach(n => {
    if (n instanceof Element) { if (n.matches('.lee-mrow')) prepareRows(n.parentElement); else prepareRows(n); }
  })));
  observer.observe(box, {childList: true, subtree: true});
  let closed = false;
  const onViewport = () => fitModal(m);
  const nativeRemove = m.remove.bind(m);
  const focusables = () => $$('button:not([disabled]), input:not([disabled]), textarea:not([disabled]), select:not([disabled]), [href], [tabindex]:not([tabindex="-1"])', box)
    .filter(el => !el.hidden && el.getClientRects().length);
  const requestClose = async () => {
    if (m.beforeClose && !await m.beforeClose()) return false;
    m.remove(); return true;
  };
  m.requestClose = requestClose;
  const key = (e) => {
    // Nested dialogs form a stack, and only the top one owns keys, or one Escape closes every
    // layer at once.
    if ($$('.lee-modal').at(-1) !== m) return;
    // The dialog's own keys come first. A dialog that means something by Tab says so by preventing
    // the default; the trap below then never sees it. Handling Tab here first made that branch
    // unreachable, and a dialog that bound it looked like it had no binding at all.
    if (onKey) onKey(e, m);
    if (e.defaultPrevented) return;
    if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); requestClose(); return; }
    if (e.key === 'Tab') {
      const items = focusables(); if (!items.length) { e.preventDefault(); box.focus(); return; }
      const at = items.indexOf(document.activeElement);
      if (e.shiftKey && at <= 0) { e.preventDefault(); items.at(-1).focus(); }
      else if (!e.shiftKey && (at < 0 || at === items.length - 1)) { e.preventDefault(); items[0].focus(); }
      return;
    }
    const rows = $$('.lee-mrow:not([data-off])', m), at = rows.indexOf(document.activeElement);
    if (rows.length && (e.key === 'ArrowDown' || e.key === 'ArrowUp')) {
      e.preventDefault(); e.stopPropagation();
      const step = e.key === 'ArrowDown' ? 1 : -1;
      const next = rows[(Math.max(0, at) + step + rows.length) % rows.length];
      rows.forEach(r => { const selected = r === next; r.classList.toggle('sel', selected); r.setAttribute('aria-selected', String(selected)); });
      next.focus(); next.scrollIntoView({block: 'nearest'});
    } else if (at >= 0 && (e.key === 'Enter' || e.key === ' ')) {
      e.preventDefault(); e.stopPropagation(); rows[at].click();
    }
  };
  m.remove = () => {
    if (closed) return;
    closed = true; observer.disconnect(); document.removeEventListener('keydown', key, true);
    window.removeEventListener('resize', onViewport); window.visualViewport?.removeEventListener('resize', onViewport); nativeRemove();
    if (!$$('.lee-modal').length) { document.body.style.overflow = document.body.dataset.leeModalOverflow || ''; delete document.body.dataset.leeModalOverflow; }
    if (previousFocus instanceof HTMLElement && previousFocus.isConnected) previousFocus.focus({preventScroll: true});
    if (onClose) onClose();
  };
  const dragHandle = heading || m.querySelector('.lee-modal-grip');
  let drag = null;
  dragHandle.addEventListener('pointerdown', e => {
    if (e.button !== 0 || e.target.closest('button, input, textarea, select, a') || m.classList.contains('lee-modal-expanded')) return;
    const r = box.getBoundingClientRect();
    m.classList.add('lee-modal-moved', 'lee-modal-dragging');
    box.style.left = r.left + 'px'; box.style.top = r.top + 'px';
    drag = {x: e.clientX, y: e.clientY, left: r.left, top: r.top, dx: 0, dy: 0};
    dragHandle.setPointerCapture(e.pointerId); e.preventDefault();
  });
  dragHandle.addEventListener('pointermove', e => {
    if (!drag) return;
    const r = box.getBoundingClientRect(), v = modalViewport(), width = r.width, height = r.height;
    const maxX = v.left + Math.max(0, v.width - width) - drag.left;
    const maxY = v.top + Math.max(0, v.height - height) - drag.top;
    drag.dx = Math.max(v.left - drag.left, Math.min(e.clientX - drag.x, maxX));
    drag.dy = Math.max(v.top - drag.top, Math.min(e.clientY - drag.y, maxY));
    box.style.transform = `translate3d(${drag.dx}px, ${drag.dy}px, 0)`;
    e.preventDefault();
  });
  const endDrag = e => {
    if (!drag) return;
    const v = modalViewport();
    box.style.left = Math.max(v.left, drag.left + drag.dx) + 'px'; box.style.top = Math.max(v.top, drag.top + drag.dy) + 'px';
    box.style.transform = ''; drag = null; m.classList.remove('lee-modal-dragging');
    try { dragHandle.releasePointerCapture(e.pointerId); } catch (_) {}
  };
  dragHandle.addEventListener('pointerup', endDrag); dragHandle.addEventListener('pointercancel', endDrag);
  const toggleExpanded = () => {
    const expanding = !m.classList.contains('lee-modal-expanded');
    if (expanding) {
      box._leeRestorePosition = m.classList.contains('lee-modal-moved')
        ? {left: box.style.left, top: box.style.top} : null;
      m.classList.remove('lee-modal-moved'); box.style.left = box.style.top = box.style.transform = '';
      m.classList.add('lee-modal-expanded');
    } else {
      m.classList.remove('lee-modal-expanded');
      if (box._leeRestorePosition) {
        m.classList.add('lee-modal-moved'); box.style.left = box._leeRestorePosition.left; box.style.top = box._leeRestorePosition.top;
      }
    }
    const expanded = m.classList.contains('lee-modal-expanded');
    m.querySelector('.lee-modal-expand').textContent = expanded ? '↙' : '↗';
    m.querySelector('.lee-modal-expand').setAttribute('aria-label', expanded ? 'restore dialog' : 'expand dialog');
  };
  m.querySelector('.lee-modal-expand').onclick = toggleExpanded;
  heading?.addEventListener('dblclick', e => { if (!e.target.closest('button, input, select')) toggleExpanded(); });
  if (storageKey && 'ResizeObserver' in window) {
    const sizeObserver = new ResizeObserver(() => {
      if (m.classList.contains('lee-modal-expanded')) return;
      const r = box.getBoundingClientRect();
      if (r.width > 0 && r.height > 0) localStorage.setItem(storageKey, JSON.stringify({width: Math.round(r.width), height: Math.round(r.height), left: Math.round(r.left), top: Math.round(r.top)}));
    });
    sizeObserver.observe(box);
    const oldRemove = m.remove;
    m.remove = () => { sizeObserver.disconnect(); oldRemove(); };
  }
  m.querySelector('.lee-modal-close').onclick = requestClose;
  m.addEventListener('mousedown', e => { if (e.target === m) requestClose(); });
  document.addEventListener('keydown', key, true);
  window.addEventListener('resize', onViewport); window.visualViewport?.addEventListener('resize', onViewport);
  if (!$$('.lee-modal').length) { document.body.dataset.leeModalOverflow = document.body.style.overflow; document.body.style.overflow = 'hidden'; }
  document.body.appendChild(m);
  requestAnimationFrame(() => {
    fitModal(m);
    const target = box.querySelector('[autofocus]') || box.querySelector('.lee-mrow.sel:not([data-off])') ||
                   box.querySelector('.lee-mrow:not([data-off])') || box.querySelector('input, textarea, select') ||
                   box.querySelector('button:not(.lee-modal-close):not([disabled])') || box;
    target.focus({preventScroll: true});
    if (target.classList.contains('lee-mrow')) target.scrollIntoView({block: 'nearest'});
  });
  return m;
}

function inputDialog(title, label, value = '', placeholder = '') {
  return new Promise(resolve => {
    let settled = false;
    const done = value => { if (settled) return; settled = true; m.remove(); resolve(value); };
    const m = modal(
      `<form class="lee-dialogform"><div class="lee-mhead">${esc(title)}</div>` +
      `<label class="lee-fieldlabel">${esc(label)}<input class="lee-input" id="dialoginput" ` +
      `placeholder="${esc(placeholder)}" autocomplete="off"></label>` +
      `<div class="lee-mfoot"><button class="lee-btn go" type="submit">confirm</button>` +
      `<button class="lee-btn" type="button" id="dialogcancel">cancel</button></div></form>`,
      null, () => { if (!settled) { settled = true; resolve(null); } });
    const input = m.querySelector('#dialoginput'); input.value = value;
    m.querySelector('form').onsubmit = e => { e.preventDefault(); done(input.value.trim()); };
    m.querySelector('#dialogcancel').onclick = () => done(null);
    setTimeout(() => { input.focus(); input.select(); }, 0);
  });
}

function textDialog(title, label, value = '') {
  return new Promise(resolve => {
    let settled = false;
    const done = value => { if (settled) return; settled = true; m.remove(); resolve(value); };
    const m = modal(
      `<form class="lee-dialogform"><div class="lee-mhead">${esc(title)}</div>` +
      `<label class="lee-fieldlabel">${esc(label)}<textarea class="lee-keyedit" id="dialogtext" rows="12" spellcheck="false"></textarea></label>` +
      `<div class="lee-mfoot"><button class="lee-btn go" type="submit">retry</button>` +
      `<button class="lee-btn" type="button" id="dialogcancel">cancel</button></div></form>`,
      null, () => { if (!settled) { settled = true; resolve(null); } });
    const input = m.querySelector('#dialogtext'); input.value = value;
    m.querySelector('form').onsubmit = e => { e.preventDefault(); done(input.value.trim()); };
    m.querySelector('#dialogcancel').onclick = () => done(null);
    setTimeout(() => { input.focus(); input.select(); }, 0);
  });
}

/* `alt` offers a second way to say yes. It resolves `'alt'`, and cancel stays falsy so every
   caller that asked a yes/no question is unchanged. */
function confirmDialog(title, detail, action = 'confirm', alt = '') {
  return new Promise(resolve => {
    let settled = false;
    const done = value => { if (settled) return; settled = true; m.remove(); resolve(value); };
    const second = alt ? `<button class="lee-btn" id="dialogalt">${esc(alt)}</button>` : '';
    const m = modal(`<div class="lee-mhead">${esc(title)}</div><div class="lee-dialogcopy">${esc(detail)}</div>` +
      `<div class="lee-mfoot"><button class="lee-btn warn" id="dialogyes">${esc(action)}</button>${second}` +
      `<button class="lee-btn" id="dialogno" autofocus>cancel</button></div>`, null,
      () => { if (!settled) { settled = true; resolve(false); } });
    m.querySelector('#dialogyes').onclick = () => done(true);
    m.querySelector('#dialogalt')?.addEventListener('click', () => done('alt'));
    m.querySelector('#dialogno').onclick = () => done(false);
  });
}

/* One menu renderer for every contextual surface. Labels and effective chords come from
 * `leela.blocks.keys.menus` and `leela.core.keys`. The browser positions rows and dispatches. */
function closeMenu() {
  $('.lee-ctxmenu')?.remove();
  if (lee.menuAnchor?.hasAttribute('aria-haspopup')) lee.menuAnchor.setAttribute('aria-expanded', 'false');
  lee.menuAnchor = null;
}
function openMenu(surface, x, y) {
  closeMenu();
  lee.menuSurface = surface;   // an action can act on what was right-clicked, not on the focus
  const rows = lee.menus?.[surface] || [];
  if (!rows.length) return;
  const menu = document.createElement('div');
  menu.className = 'lee-ctxmenu'; menu.setAttribute('role', 'menu'); menu.tabIndex = -1;
  menu.innerHTML = rows.map(r => r.separator ? '<div class="lee-menusep" role="separator"></div>' :
    `<button class="lee-menuitem ${esc(r.kind)}" role="${r.check ? 'menuitemcheckbox' : 'menuitem'}"` +
    `${r.check ? ` aria-checked="${!!lee.menuChecks?.[r.action]?.()}"` : ''}${lee.menuOff?.[r.action]?.() ? ' disabled' : ''} data-action="${esc(r.action)}">` +
    `<span>${esc(sentence(r.label))}</span>${r.chord && r.chord !== '–' ? `<kbd>${esc(displayChord(r.chord))}</kbd>` : ''}</button>`).join('');
  document.body.appendChild(menu);
  const rect = menu.getBoundingClientRect();
  menu.style.left = Math.max(4, Math.min(x, innerWidth - rect.width - 4)) + 'px';
  menu.style.top = Math.max(4, Math.min(y, innerHeight - rect.height - 4)) + 'px';
  menu.onclick = e => {
    const item = e.target.closest('.lee-menuitem'); if (!item || item.disabled) return;
    if (item.getAttribute('role') !== 'menuitemcheckbox') { closeMenu(); return leeAct(item.dataset.action); }
    const sync = () => item.setAttribute('aria-checked', String(!!lee.menuChecks?.[item.dataset.action]?.()));
    Promise.resolve(leeAct(item.dataset.action)).then(sync, sync); sync();
  };
  menu.onkeydown = e => {
    const items = $$('.lee-menuitem:not(:disabled)', menu), at = items.indexOf(document.activeElement);
    if (e.key === 'Escape') { e.preventDefault(); const back = lee.menuAnchor; closeMenu(); back?.focus(); }
    else if (e.key === 'ArrowDown') { e.preventDefault(); items[(at + 1 + items.length) % items.length]?.focus(); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); items[(at - 1 + items.length) % items.length]?.focus(); }
    else if (e.key === 'Home') { e.preventDefault(); items[0]?.focus(); }
    else if (e.key === 'End') { e.preventDefault(); items.at(-1)?.focus(); }
  };
  menu.focus();
}
function leeMenuAt(surface, anchor) {
  const r = anchor.getBoundingClientRect(); openMenu(surface, r.right - 4, r.bottom + 3);
  if (!$('.lee-ctxmenu')) return;
  lee.menuAnchor = anchor; if (anchor.hasAttribute('aria-haspopup')) anchor.setAttribute('aria-expanded', 'true');
}
window.leeMenuAt = leeMenuAt;

function openChromeMenu(anchor, rows) {
  closeMenu();
  const menu = document.createElement('div'); menu.className = 'lee-ctxmenu'; menu.setAttribute('role', 'menu');
  menu.innerHTML = rows.map((r, i) => r.separator ? '<div class="lee-menusep" role="separator"></div>' :
    `<button class="lee-menuitem${r.warn ? ' warn' : ''}" role="menuitem" data-i="${i}" ${r.disabled ? 'disabled' : ''}>` +
    `<span>${esc(sentence(r.label))}</span>${r.detail ? `<small title="${esc(r.detail)}">${esc(r.detail)}</small>` : ''}</button>`).join('');
  document.body.appendChild(menu);
  const a = anchor.getBoundingClientRect(), rect = menu.getBoundingClientRect();
  menu.style.left = Math.max(4, Math.min(a.left, innerWidth - rect.width - 4)) + 'px';
  menu.style.top = Math.max(4, Math.min(a.bottom + 3, innerHeight - rect.height - 4)) + 'px';
  menu.onclick = e => { const b = e.target.closest('[data-i]'); if (!b || b.disabled) return; closeMenu(); rows[+b.dataset.i].run?.(); };
  menu.tabIndex = -1; menu.focus();
}

// Choosing a folder is choosing a project: source control, releases, deploys and the branch pill
// all follow it. Selecting the folder in the tree is not choosing it; this route is.
async function activateRoot(path) {
  try { await post('/workspace/activate', {path}); }
  catch (e) { return status(e.message || String(e), 'err'); }
  leeLeft('files');
  const node = $$('.lee-root').find(n => n.dataset.path === path);
  if (node) { selectTreeNode(node); await loadTreeDir(node); node.scrollIntoView({block: 'nearest'}); }
  gitUI.repo = '';                  // the panels follow the workspace again, not a pinned repo
  refreshProjectPills();
  projectChanged();
  status(`project · ${path.split('/').pop() || path}`);
}
window.leeActivateRoot = activateRoot;

async function leeWorkspaceMenu(anchor) {
  const d = await api('/workspace/info');
  const sites = d.workspaces || [];
  const home = p => lee.home && (p === lee.home || String(p).startsWith(lee.home + '/')) ? '~' + String(p).slice(lee.home.length) : p;
  const rows = sites.map(site => ({label: site.name, detail: home(site.root), run: () => {
    if (site.url && site.url !== location.href) location.href = site.url;
  }}));
  if (sites.length && (d.roots || []).length) rows.push({separator: true});
  rows.push(...(d.roots || []).map(root => ({label: sites.length ? `Folder: ${root.name}` : root.name,
    detail: home(root.path), run: () => activateRoot(root.path)})));
  if (rows.length) rows.push({separator: true});
  rows.push({label: 'Add folder…', detail: 'to this workspace', run: addRoot});
  openChromeMenu(anchor, rows);
}
window.leeWorkspaceMenu = leeWorkspaceMenu;

/* The branch pill's own popup is `branchbar.js`. It is a searchable list rather than a menu, so it
   does not fit `openChromeMenu`. */

async function operationHistory() {
  const d = await api('/history/operations');
  const m = modal(`<div class="lee-mhead">workspace history<span class="sub">saved file checkpoints · newest first</span></div>` +
    // An empty `data-history` still matches `[data-history]`, so the attribute is omitted rather
    // than blanked. A spent operation must not be clickable at all.
    `<div class="lee-modallist">${(d.operations || []).map(op => `<button class="lee-mrow" data-op="${esc(op.id)}"${op.reversible ? ' data-history="undo"' : op.redoable ? ' data-history="redo"' : ' data-off="1"'}>` +
      `<strong>${esc(op.label)}</strong><span class="sub">${op.redoable ? 'undone · redo available · ' : ''}${new Date(op.at * 1000).toLocaleString()} · ${esc((op.paths || []).join(', '))}</span></button>`).join('') || '<div class="lee-dim">No saved operations yet.</div>'}</div>` +
    `<div class="lee-mfoot"><span class="lee-dim">Undo and redo refuse files changed after the checkpoint.</span></div>`);
  $$('[data-history]', m).forEach(row => row.onclick = async () => {
    const redo = row.dataset.history === 'redo', verb = redo ? 'Redo' : 'Undo';
    if (!await confirmDialog(`${verb} workspace operation`, `${verb} ${row.textContent.trim()}?`, verb.toLowerCase())) return;
    try { const r = await post('/history/' + (redo ? 'redo' : 'undo'), {id: row.dataset.op}); m.remove();
      await afterHistory(r.operation, `workspace operation ${redo ? 'redone' : 'undone'}`, !redo);
    } catch (e) { status(e.message || String(e), 'err'); }
  });
}

function leeToolsMenu(anchor) {
  openChromeMenu(anchor, [
    {label: 'Command palette', detail: displayChord('mod+shift+p'), run: () => leeAct('palette')},
    {label: 'Recent files', detail: displayChord('mod+e'), run: () => leeAct('recent_tabs')},
    {separator: true},
    {label: 'The vault…', detail: 'browse, search, and put things in', run: () => leeVaultWorkbench()},
    {label: 'Research workspace…', run: () => leeAct('research')},
    {label: 'Read webpage…', run: () => leeAct('read_url')},
    {label: 'Browse a page…', detail: displayChord('alt+shift+o'), run: () => leeAct('browse_url')},
    {label: 'Pages open in the browser…', run: () => leeAct('browse_tabs')},
    {label: 'Kernel and interpreter…', run: () => leeAct('pick_kernel')},
    {label: 'Working directory…', run: leeCwd},
    {label: 'nbdev prepare…', detail: 'uv + settings.ini', run: leeNbdevPrepare},
    {label: 'fastship…', detail: 'releases for a package that is not nbdev', run: leeFastship},
    {label: 'Models and updates…', detail: 'set one up, or pull a newer backend', run: () => leeSetupModal()},
    {separator: true},
    {label: 'Settings…', detail: displayChord(shownChord(lee.keys.find(k => k.action === 'settings')) || 'mod+,'), run: editorSettings},
    {label: 'Workspace history…', detail: 'conflict-safe undo', run: operationHistory},
    {label: 'Inline completions…', detail: 'what you asked, and what you kept', run: () => showCompletions()},
    {label: 'Keybindings…', run: () => leeAct('edit_keys')},
    {label: 'Terminal', run: () => leeAct('terminal')},
  ]);
}
window.leeToolsMenu = leeToolsMenu;

function leeEditorMenu(anchor) {
  const rows = [
    {label: 'Run selection', detail: displayChord(shownChord(lee.keys.find(k => k.action === 'run_selection')) || ''), run: () => leeAct('run_selection')},
    {label: 'Run all cells', detail: displayChord(shownChord(lee.keys.find(k => k.action === 'run_all')) || ''), run: () => leeAct('run_all')},
    {label: 'Restart and run all', run: () => leeAct('restart_run_all')},
    {separator: true},
    {label: 'Save', detail: displayChord(shownChord(lee.keys.find(k => k.action === 'save')) || ''), run: () => leeAct('save')},
    {label: 'Show unsaved changes', run: () => leeAct('show_diff')},
    {label: 'Rename symbol…', run: () => leeAct('rename_symbol')},
    {label: 'Replace in workspace…', run: () => leeAct('replace_workspace')},
    {separator: true},
    {label: 'Insert cell below', run: () => leeAct('cell_below')},
    {label: 'Change cell type', run: () => leeAct('cell_type')},
    {label: 'Clear all outputs', run: () => leeAct('clear_all_outputs')},
    {separator: true},
    {label: 'All commands…', detail: displayChord(shownChord(lee.keys.find(k => k.action === 'palette')) || ''), run: () => leeAct('palette')},
  ];
  openChromeMenu(anchor, rows);
}
window.leeEditorMenu = leeEditorMenu;

function leeDebugMenu(anchor) {
  openChromeMenu(anchor, [
    {label:'Debug current Python file',detail:'debugpy',disabled:lee.kind!=='text'||curLang()!=='python',run:()=>startDirectDebug({name:lee.path?.split('/').pop()||'Python',program:lee.path,debug:true})},
    {label:'Run or debug configuration…',run:()=>leeAct('run_app')},
    {label:'Edit configurations…',run:editRuns},
    {separator:true},
    {label:'Continue',disabled:!lee.debugState,run:()=>leeDebugControl('continue')},
    {label:'Step over',disabled:!lee.debugState,run:()=>leeDebugControl('next')},
    {label:'Step into',disabled:!lee.debugState,run:()=>leeDebugControl('stepIn')},
    {label:'Step out',disabled:!lee.debugState,run:()=>leeDebugControl('stepOut')},
    {label:'Stop debugger',warn:true,disabled:!lee.debugCell&&!lee.directDebug,run:leeDebugStop},
    {separator:true},
    {label:'Interrupt kernel',warn:true,run:()=>leeAct('interrupt')},
    {label:'Restart kernel',warn:true,run:()=>leeAct('restart')},
  ]);
}
window.leeDebugMenu = leeDebugMenu;

document.addEventListener('pointerdown', e => { if (!e.target.closest('.lee-ctxmenu, .lee-more, [aria-haspopup="menu"]')) closeMenu(); }, true);
window.addEventListener('blur', closeMenu);
window.addEventListener('resize', () => { closeMenu(); layoutTabs(); });
window.addEventListener('scroll', e => { if (!e.target.closest?.('.lee-ctxmenu, #agentlog')) closeMenu(); }, true);

function showHelp() {
  const scopes = Object.entries(lee.help).sort(([a], [b]) =>
    a === lee.scope ? -1 : b === lee.scope ? 1 : a === 'global' ? -1 : b === 'global' ? 1 : 0);
  const body = scopes.map(([scope, rows]) =>
    `<section class="lee-help-scope${scope === lee.scope ? ' active' : ''}"><h4>${esc(scope)}` +
    `${scope === lee.scope ? '<span>current</span>' : ''}</h4>` +
    (scope === 'present' ? '<p class="lee-dim lee-help-note">These keys work only during a presentation. They cannot be rebound. Laser and blank have no button.</p>' : '') +
    (scope === 'editor' ? '<p class="lee-dim lee-help-note">In a notebook, a single letter works only when you do not edit a cell. Press Escape to stop editing. Press D two times to delete a cell.</p>' : '') + rows.map(([k, l]) =>
      `<div class="lee-krow"><kbd>${esc(displayChord(k))}</kbd><span>${esc(l)}</span></div>`).join('') + '</section>').join('');
  const m = modal(
    `<div class="lee-mhead">keys<span class="sub">${esc(lee.keyPath || '')}</span></div>` +
    (lee.keyNotes || []).map(n => `<div class="lee-err">${esc(n)}</div>`).join('') +
    `<div class="lee-dim">Every key outside the present section can be rebound. Each of those keys also has a button.</div>` +
    `<div class="lee-help">${body}</div>` +
    `<div class="lee-mfoot"><button class="lee-btn" id="gokeys">edit keybindings</button></div>`);
  m.querySelector('#gokeys').onclick = () => { m.remove(); editKeys(); };
}

async function quickOpen(searchMode, q = '') {
  let hits = [], sel = 0, seq = 0, timer = null, ctl = null, shown = null, cut = false;
  const m = modal(
    `<input class="lee-input" id="qo" placeholder="${searchMode ? 'search files…' : 'open file…'}" aria-label="Go to file" autofocus>
     <label><input type="checkbox" id="qoall"> include .venv and dot folders</label>
     <div class="sub" id="qonote" hidden></div>
     <div class="lee-modallist" id="qolist"></div>`,
    (e) => {
      if (e.key === 'ArrowDown') { e.preventDefault(); sel = Math.max(0, Math.min(sel + 1, hits.length - 1)); paint(); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); sel = Math.max(sel - 1, 0); paint(); }
      else if (e.key === 'Enter') { e.preventDefault(); go(); }
    }, () => { clearTimeout(timer); ctl?.abort(); });
  const list = m.querySelector('#qolist'), input = m.querySelector('#qo'), all = m.querySelector('#qoall'), note = m.querySelector('#qonote');
  input.value = q;
  const paint = () => {
    list.innerHTML = hits.length ? hits.slice(0, 300).map((h, i) =>
      `<div class="lee-mrow${i === sel ? ' sel' : ''}" data-i="${i}" title="${esc(h.path)}">${esc(h.name)}<span class="sub">${h.hidden ? 'hidden · ' : ''}${esc(shownPath(h.path))}</span></div>`).join('')
      : shown != null && input.value.trim() ? '<div class="lee-dim lee-qo-none">No file matches.</div>' : '';
    list.querySelector('.sel')?.scrollIntoView({block: 'nearest'});
  };
  const go = () => { const h = hits[sel]; if (h) { m.remove(); leeOpenFile(h.path); } };
  list.addEventListener('click', e => { const r = e.target.closest('.lee-mrow'); if (r) { sel = +r.dataset.i; go(); } });
  // Hidden folders and environments take seconds to walk, so they follow the project's files and
  // only once typing pauses. Aborting a hidden batch stops its walk on the server; `seq` drops an
  // answer already on its way.
  const live = mine => mine === seq && m.isConnected;
  const stop = () => { seq++; ctl?.abort(); };
  const search = async () => {
    stop();
    const mine = seq, q = input.value.trim(), signal = (ctl = new AbortController()).signal;
    const find = extra => api('/fs/find?' + extra + 'q=' + encodeURIComponent(q), {signal});
    let found;
    const say = text => { note.textContent = text; note.hidden = !text; };
    if (q === shown) { hits = hits.filter(h => !h.hidden); sel = Math.min(sel, Math.max(0, hits.length - 1)); paint(); }
    else {
      try { found = await find(''); } catch (e) { if (live(mine)) status(e.message, 'err'); return; }
      if (!live(mine)) return;
      cut = !!found.partial; hits = found.hits; shown = q; sel = 0; paint();
    }
    const CUT = 'this folder has too many files to list them all, so some files are not in this list';
    say(cut ? CUT : '');
    if (!all.checked || !q) return;
    await new Promise(r => setTimeout(r, 300));
    if (!live(mine)) return;
    try { found = await find('more=1&'); } catch (e) { if (live(mine)) status(e.message, 'err'); return; }
    if (!live(mine)) return;
    say(cut ? CUT : found.partial ? 'hidden folders took over 10 seconds, so this list is incomplete' : '');
    hits = hits.concat(found.hits.map(h => ({...h, hidden: true}))); paint();
  };
  input.addEventListener('input', () => { stop(); clearTimeout(timer); timer = setTimeout(search, 120); });
  all.addEventListener('change', () => { clearTimeout(timer); input.focus(); search(); });
  search(); setTimeout(() => input.focus(), 0);
}

// The modes, in the order Tab walks them. `all` leads and ranks every backend together. A rail
// rather than a row, because each mode carries a count.
const SEARCH_MODES = [
  ['all', 'all', 'rank ripgrep, symbols, FTS and semantic results together'],
  ['rg', 'rg', 'ripgrep: literal search over current files, fastest'],
  ['context', 'context', 'Kosha composed retrieval across repository code and installed packages'],
  ['repo', 'repo', 'Kosha repository code store'],
  ['env', 'packages', 'Kosha installed-package environment store'],
  ['symbols', 'symbols', 'Kosha symbols: repository and indexed packages'],
  ['ann', 'ANN', 'Kosha embedding ANN'],
];

/* What a search was asked, what it showed, and what was worth opening. Queued and posted in
   batches: a keystroke never waits on a write, and a failed write never fails a search. */
function searchSignals(session) {
  const queue = [];
  let queryId = '', askedAt = 0, timer = null, shown = new Map(), previewKey = '', previewAt = 0, opened = 0;
  let context = {};
  const key = h => `${h.path || ''}:${h.line || 0}:${h.package || ''}`;
  const flush = doc => {
    clearTimeout(timer); timer = null;
    const events = queue.splice(0, queue.length);
    if (!events.length && !doc) return;
    post('/search/events', {events, session: doc || null}).catch(() => {});
  };
  const push = (kind, row = {}) => {
    queue.push({session, query_id: queryId, kind, at: Date.now() / 1000, ...row});
    if (!timer) timer = setTimeout(() => flush(), 4000);
  };
  const closePreview = () => {
    if (!previewKey) return;
    const row = shown.get(previewKey);
    push('preview', {key: previewKey, rank: row?.rank ?? 0, dwell: Math.round(performance.now() - previewAt)});
    previewKey = '';
  };
  const doc = () => ({session, query_id: queryId, ...context, opened, shown_n: shown.size,
                      shown: [...shown.values()].sort((a, b) => a.rank - b.rank)});
  return {
    // A query typed over one that had already answered is the strongest negative signal there is.
    query(q, mode, scope, exts) {
      closePreview();
      if (queryId && shown.size) push('refine', {q});
      queryId = `${session}:${Date.now().toString(36)}`;
      askedAt = performance.now(); shown = new Map(); opened = 0;
      context = {q, mode, scope, exts};
      push('query', context);
    },
    leg(leg, ms, n) { push('leg', {leg, ms: Math.round(ms), n}); },
    impression(rows) {
      shown = new Map(rows.map((h, rank) => [key(h), {rank, path: h.path, line: h.line,
        symbol: h.symbol || '', package: h.package || '', sources: h.sources || [h.kind],
        previewed: false, opened: false}]));
      push('impression', {n: rows.length, ms: Math.round(performance.now() - askedAt)});
    },
    preview(hit, rank) {
      if (!hit) return;
      const k = key(hit); if (k === previewKey) return;
      closePreview();
      previewKey = k; previewAt = performance.now();
      const row = shown.get(k); if (row) row.previewed = true;
      if (!row) shown.set(k, {rank, path: hit.path, line: hit.line, symbol: hit.symbol || '',
        sources: hit.sources || [hit.kind], previewed: true, opened: false});
    },
    open(hit, rank) {
      if (!hit) return;
      closePreview(); opened += 1;
      const row = shown.get(key(hit)); if (row) row.opened = true;
      push('open', {key: key(hit), rank, path: hit.path, line: hit.line, symbol: hit.symbol || '',
        sources: hit.sources || [hit.kind], why: hit.why || null, score: hit.score || 0,
        ms: Math.round(performance.now() - askedAt), ...context});
    },
    mode(next) { push('mode', {mode: next}); },
    close() {
      closePreview();
      if (queryId && !opened) push('abandon', {n: shown.size});
      flush(queryId ? doc() : null);
    },
  };
}

/* Every slider in plain words: what the number buys, and what it is paying for. The settings keys
   are named for the scorer's own fields, which say nothing to somebody who has not read it. */
const WEIGHT_LABELS = {
  legFiles: ['a matching filename', 'a file whose name contains what you typed'],
  legSymbols: ['a matching name in the code', 'a function or class the code index knows'],
  legRg: ['the words, found in a file', 'a line containing exactly what you typed'],
  legFts: ['a keyword match', 'the search index found your words in a file'],
  legAnn: ['a match by meaning', 'code that does something similar, in different words'],
  legRank: ['being near the top of its own list', 'how much to respect the order each search came back in'],
  symbolExact: ['the name is exactly what you typed', 'searching `merge` and finding `def merge`'],
  symbolPart: ['the name contains what you typed', 'searching `merge` and finding `merge_dicts`'],
  queryInText: ['your words in the matching line', 'the line itself contains what you typed'],
  queryInFilename: ['your words in the filename', 'the file is called something like what you typed'],
  demoteNoise: ['pushing junk down', 'points taken off `node_modules`, `dist`, `build`, `vendor` and minified files'],
};

/* One hit's score from one set of weights, the arithmetic `Weights.score` does on the server. The
   panel re-ranks with it rather than asking again, so a slider moves the list as it is dragged. */
function weighHit(hit, weights, keys) {
  const why = hit.why; if (!why) return Number(hit.score || 0);
  let out = 0;
  for (const [name, field] of Object.entries(keys || {})) {
    if (field === why.leg) { out += Number(weights[name] || 0); continue; }
    if (field !== 'leg' && field in why) out += Number(weights[name] || 0) * Number(why[field] || 0);
  }
  return out;
}

/* What the dialog was last set to, kept where a moving port cannot lose it. The three legacy keys
   are adopted before anything is read, so the dialog opens on the same choices it closed on. Once
   a page: `origins` still says `default` until the settings are read again, so adopting on every
   open would put the old keys back over a choice made since. */
let searchAdopted = false;
async function adoptSearchPrefs() {
  if (searchAdopted) return;
  searchAdopted = true;
  await prefAdopt('search', 'lastMode', 'lee-search-mode');
  await prefAdopt('search', 'lastScope', 'lee-search-scope');
  await prefAdopt('search', 'lastExts', 'lee-search-exts');
}

async function codeSearch() {
  await adoptSearchPrefs();
  const session = crypto.randomUUID?.() || String(Math.random()).slice(2);
  const signals = searchSignals(session);
  let hits = [], sel = 0, backend = '', previewView = null, searchSeq = 0;
  // Two zones, one selection. Tab walks the rail and switches as it goes; Enter on the rail steps
  // into the results, and Enter in the results opens. Arrows are always the results.
  let zone = 'list', tuned = false, weights = {}, weightKeys = {}, weightDefaults = {};
  let mode = prefGet('search', 'lastMode', 'all');
  if (!SEARCH_MODES.some(([id]) => id === mode)) mode = 'all';
  const counts = {};
  const m = modal(
    `<div class="lee-searchbar"><input class="lee-input" id="cs" placeholder="search code, symbols and meaning…" autofocus
            role="combobox" aria-expanded="true" aria-controls="cslist" aria-autocomplete="list">
     <button class="lee-btn" id="cstune" type="button" aria-pressed="false">weights</button>
     <button class="lee-btn" id="cslog" type="button" aria-pressed="false">log</button>
     <button class="lee-btn" id="kosharefresh" type="button">sync</button></div>` +
    // A workspace holds several checkouts, so "this project" is the default and "everything
    // open" is the deliberate widening.
    `<div class="lee-searchfilters">
       <label>in<select id="csscope">
         <option value="project">this project</option>
         <option value="workspace">every open folder</option></select></label>
       <label>files<input class="lee-input" id="csexts" placeholder="py, ts · empty for all"
              aria-label="restrict to file extensions"></label>
       <span class="lee-dim" id="csscopenote"></span></div>` +
    `<div class="lee-search-weights" id="csweights" hidden></div>` +
    `<div class="lee-kosha-status" id="koshastatus"><span>Opening Kosha…</span></div>
     <div class="lee-code-search-body">
       <nav class="lee-searchrail" id="csrail" aria-label="search mode">${SEARCH_MODES.map(([id, label, tip]) =>
         `<button class="lee-searchrail-mode" data-mode="${id}" tabindex="-1" title="${esc(tip)}">` +
         `<span>${esc(label)}</span><b data-count-for="${id}"></b></button>`).join('')}
         <span class="lee-dim lee-searchrail-hint">tab / shift+tab</span></nav>
       <div class="lee-modallist" id="cslist" role="listbox" aria-label="search results"><div class="lee-dim">type to search repository + environment context</div></div>
       <aside class="lee-search-preview"><header><div><strong id="cspreviewtitle">Code preview</strong>` +
       `<span id="cspreviewmeta">Select a result</span></div>` +
       `<div class="lee-search-actions"><button class="lee-btn" id="cspkg" hidden>Package API</button>` +
       `<button class="lee-btn go" id="csopen" disabled>Open file</button></div></header>` +
       `<div id="cspreview"><div class="lee-search-preview-empty">Matches open here with syntax highlighting.</div></div>` +
       `<div class="lee-search-relations" id="csrelations"></div></aside></div>` +
       `<div class="lee-search-hints"><kbd>tab</kbd> changes the kind of search` +
       `<kbd>enter</kbd> goes into the results, then opens one<kbd>↑↓</kbd> moves` +
       `<span class="lee-dim lee-search-hint-click">click previews, clicking it again opens it</span>` +
       `<span class="lee-spacer"></span><span class="lee-dim" id="cssignals"></span></div>`,
    (e) => {
      // The panel owns its own keyboard: a slider needs its arrows, and Tab has to reach the next
      // control in it rather than the next search mode.
      if (e.target?.closest?.('.lee-search-weights')) return;
      if (e.key === 'ArrowDown') { e.preventDefault(); zone = 'list'; select(sel + 1); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); zone = 'list'; select(sel - 1); }
      else if (e.key === 'Enter') {
        e.preventDefault();
        if (zone === 'rail') { zone = 'list'; paintRail(); select(sel); input.focus(); }
        else go();
      }
      else if (e.key === 'Tab') { e.preventDefault(); cycleMode(e.shiftKey ? -1 : 1); }
    }, () => {
      if (previewView) LeeCM.destroy(previewView);
      clearTimeout(previewTimer);
      if (extsTimer) { clearTimeout(extsTimer); prefSet('search', 'lastExts', extsEl.value.trim()); }
      // Closing the dialog must stop the search, or four backends work on for nothing.
      if (liveStream) { try { liveStream.close(); } catch {} liveStream = null; }
      signals.close();
    });
  m.classList.add('lee-code-search-modal');
  const list = $('#cslist', m), input = $('#cs', m), preview = $('#cspreview', m), open = $('#csopen', m);
  const pkgBtn = $('#cspkg', m), panel = $('#csweights', m);
  const scopeEl = $('#csscope', m), extsEl = $('#csexts', m);
  // Remembered, so somebody who works in Python does not retype `py` every time.
  scopeEl.value = prefGet('search', 'lastScope', 'project');
  if (!scopeEl.value) scopeEl.value = 'project';
  extsEl.value = prefGet('search', 'lastExts', '');
  const paintRail = () => {
    $$('.lee-searchrail-mode', m).forEach(b => {
      b.classList.toggle('active', b.dataset.mode === mode);
      b.classList.toggle('cursor', zone === 'rail' && b.dataset.mode === mode);
      b.setAttribute('aria-pressed', String(b.dataset.mode === mode));
    });
    // A count means something only once that mode has run. Blank is "not asked yet", which must
    // not look like nought.
    SEARCH_MODES.forEach(([id]) => {
      const el = $(`[data-count-for="${id}"]`, m); if (!el) return;
      el.textContent = counts[id] == null ? '' : counts[id];
      el.classList.toggle('zero', counts[id] === 0);
    });
  };
  const setMode = (next, from = 'click') => {
    if (!next || next === mode) return;
    mode = next; prefSet('search', 'lastMode', mode);
    zone = from === 'tab' ? 'rail' : 'list';
    signals.mode(mode);
    paintRail();
    if (input.value.trim()) search(); else paint();
    input.focus();
  };
  // Tab switches as it walks: the mode you are on is the mode that answered, so there is never a
  // pending choice to lose track of. The searches it fires are debounced by `search`.
  const cycleMode = step => {
    const at = SEARCH_MODES.findIndex(([id]) => id === mode);
    setMode(SEARCH_MODES[(at + step + SEARCH_MODES.length) % SEARCH_MODES.length][0], 'tab');
  };
  const rowId = i => `cshit${i}`;
  const select = (next, withPreview = true) => {
    if (!hits.length) return;
    sel = Math.max(0, Math.min(next, hits.length - 1));
    $$('.lee-search-result', list).forEach((row, i) => {
      const on = i === sel;
      row.classList.toggle('sel', on); row.setAttribute('aria-selected', String(on));
      if (on) row.scrollIntoView({block: 'nearest'});
    });
    input.setAttribute('aria-activedescendant', rowId(sel));
    if (withPreview) showPreview();
  };
  let previewTimer = null;
  const showPreview = () => {
    // Debounced: a held arrow key would otherwise mount and tear down one editor per row.
    clearTimeout(previewTimer);
    previewTimer = setTimeout(paintPreview, 70);
  };
  const paintPreview = () => {
    if (previewView) { LeeCM.destroy(previewView); previewView = null; }
    const h = hits[sel];
    if (!h) {
      preview.innerHTML = '<div class="lee-search-preview-empty">No result selected.</div>';
      // The header named the last hit, which a mode with no matches of its own does not have.
      $('#cspreviewtitle', m).textContent = 'Code preview';
      $('#cspreviewmeta', m).textContent = 'Select a result';
      open.disabled = true; pkgBtn.hidden = true; return;
    }
    const filename = h.path.split('/').pop() || h.package || 'indexed source';
    $('#cspreviewtitle', m).textContent = h.symbol || filename;
    $('#cspreviewmeta', m).textContent = `${h.package ? h.package + ' · ' : ''}${filename}:${h.line} · ${(h.sources || [h.kind]).join(' + ')}`;
    // A package is a file like any other once the path is one this project can open. Its API
    // listing is the second question, so it gets its own button.
    const environment = h.kind.startsWith('env-');
    open.disabled = !h.path && !(environment && h.package) && h.kind !== 'vault';
    open.textContent = h.kind === 'vault' ? 'Open in vault' : h.path ? 'Open file' : environment && h.package ? 'Package API' : 'Indexed package';
    pkgBtn.hidden = !(environment && h.package && h.path);
    preview.innerHTML = '<div class="lee-search-preview-editor"></div>';
    previewView = mountCodeSurface($('.lee-search-preview-editor', preview), h.text || '(no indexed preview)',
                                   codeLang('', h.path), false);
    signals.preview(h, sel);
    const relations = $('#csrelations', m), callers = h.callers || [];
    relations.innerHTML = callers.length ? `<span>called by</span>` + callers.map(name =>
      `<button data-symbol="${esc(name)}">${esc(name.split('.').pop())}</button>`).join('') : '';
    // Following a caller is a graph question, so it switches to the mode that answers one.
    $$('[data-symbol]', relations).forEach(button => button.onclick = () => {
      input.value = button.dataset.symbol;
      if (mode === 'context') search(); else setMode('context');
    });
  };
  // Only once a weight has been moved: until then the streamed leg order is the order, and a list
  // that re-sorted under the cursor while it filled would be unreadable.
  const ranked = () => tuned ? [...hits].sort((a, b) =>
    weighHit(b, weights, weightKeys) - weighHit(a, weights, weightKeys) ||
    a.path.localeCompare(b.path) || a.line - b.line) : hits;
  const paint = () => {
    if (!hits.length) {
      list.innerHTML = `<div class="lee-dim">${backend ? 'no matches · ' + esc(backend) : 'type to search'}</div>`;
      input.removeAttribute('aria-activedescendant');
      showPreview(); return;
    }
    hits = ranked();
    list.innerHTML = hits.map((h, i) => {
      const f = h.path.split('/').pop() || h.package || 'environment';
      const foundBy = (h.sources || [h.kind]).join(' + ');
      return `<button class="lee-search-result${i === sel ? ' sel' : ''}" id="${rowId(i)}" role="option" ` +
        `tabindex="-1" aria-selected="${i === sel}" data-i="${i}">` +
        `<span class="lee-search-result-kind">${esc(h.kind === 'vault' ? 'VAULT' : h.kind.startsWith('env-') ? 'PKG' : h.kind === 'file' ? 'FILE' : h.symbol ? 'SYM' : 'TXT')}</span>` +
        `<span><strong>${esc(h.symbol || h.text.split('\n')[0].slice(0, 90))}</strong>` +
        `<small>${h.kind === 'vault' ? `vault · ${esc(h.shelf || 'main')}${h.page == null ? '' : ' · p. ' + (h.page + 1)}`
                                      : `${esc(h.package ? h.package + ' · ' : '')}${esc(f)}:${h.line}`}</small></span>` +
        `<em>${esc(foundBy)}</em></button>`;
    }).join('');
    select(sel);
  };
  /* A name Kosha knows the file for opens it; one it does not still answers the other question. */
  const packageApi = async h => {
    const d = await api('/code/package-api?package=' + encodeURIComponent(h.package));
    const box = modal(`<div class="lee-mhead">${esc(h.package)}<span class="sub">public API from Kosha</span></div>` +
      `<div class="lee-package-api"></div>`);
    const body = $('.lee-package-api', box), symbols = d.symbols || [];
    body.innerHTML = symbols.length ? symbols.map((row, i) => `<button data-api="${i}">` +
      `<strong>${esc(row.mod_name || '')}</strong><span>${esc(row.docstring || '')}</span>` +
      `<small>${esc(row.path ? compactPath(row.path) + ':' + row.line : 'no indexed file')}</small></button>`).join('') :
      '<div class="lee-dim">No exported API metadata found.</div>';
    $$('[data-api]', body).forEach(el => el.onclick = () => {
      const row = symbols[+el.dataset.api]; box.remove();
      if (row.path) { m.remove(); return openLocation({path: row.path, line: row.line || 1}); }
      input.value = row.mod_name || ''; search();
    });
  };
  const go = async () => {
    const h = hits[sel]; if (!h) return;
    signals.open(h, sel);
    if (h.kind === 'vault') { m.remove(); return leeOpenVaultDoc(h.doc, h.shelf, h.vault, h.symbol, {page: h.page, quote: h.text.slice(0, 80)}); }
    if (h.path) { m.remove(); return openLocation(h); }
    if (!h.package) return status('package source is indexed read-only', 'info');
    await packageApi(h);
  };
  /* A click selects and previews. A click on the row already in the preview is what opens it, so a
     mouse can read a result before committing to it, exactly as the arrow keys can.

     Against `sel`, not against the last row the mouse hit. Those differ wherever the selection
     moved without the mouse: the first result is selected and previewed the moment the results
     land, so opening the row on screen took two clicks, and a row reached with the arrow keys was
     previewed and then ignored the click that meant open. */
  list.onclick = e => {
    const row = e.target.closest('[data-i]'); if (!row) return;
    const at = +row.dataset.i;
    zone = 'list';
    if (at === sel) return go();
    select(at, false); clearTimeout(previewTimer); paintPreview();
  };
  open.onclick = go;
  pkgBtn.onclick = () => { const h = hits[sel]; if (h?.package) packageApi(h); };
  // `all` streamed: one section per backend, in the server's best-first leg order. Slots are
  // stable because rg answers in tens of milliseconds and the embedding leg in seconds, and a
  // list that re-ranked on every arrival would reshuffle under the cursor while it was read. A
  // hit a later leg finds again adds its name to the existing row rather than a second one.
  const streamAll = (q, seq) => new Promise(resolve => {
    const slots = new Map(), seen = new Map();
    const started = performance.now();
    let notes = [];
    const es = new EventSource('/search/stream?q=' + encodeURIComponent(q) +
                               '&scope=' + encodeURIComponent(scopeEl.value) +
                               '&exts=' + encodeURIComponent(extsEl.value.trim()));
    // Held so the next keystroke can close it. A stream left open keeps four backends working,
    // and the server only notices when it next tries to write, seconds away for the slow legs.
    liveStream = es;
    const stop = () => { try { es.close(); } catch {} if (liveStream === es) liveStream = null; resolve(); };
    const recount = () => {
      hits = [];
      for (const leg of slots.keys()) hits.push(...slots.get(leg));
      counts.all = hits.length; paintRail();
    };
    es.addEventListener('start', e => {
      const d = JSON.parse(e.data);
      for (const leg of d.legs || []) slots.set(leg, []);      // fixes the order once
      if (d.weights) setWeights(d.weights);
      const where = (d.searched || []).map(p => p.split('/').pop()).join(', ');
      $('#csscopenote', m).textContent = where ? `searched ${where}` : '';
    });
    es.addEventListener('leg', e => {
      if (seq !== searchSeq) return stop();
      const d = JSON.parse(e.data);
      if (d.note) notes.push(d.note);
      const kept = [];
      for (const h of d.hits || []) {
        const key = `${h.path}:${h.line}:${h.package || ''}`;
        const already = seen.get(key);
        if (already) { already.sources = [...new Set([...(already.sources || []), d.leg])]; continue; }
        seen.set(key, h); kept.push(h);
      }
      slots.set(d.leg, kept);
      signals.leg(d.leg, performance.now() - started, (d.hits || []).length);
      recount();
      backend = `all · ${[...slots.keys()].filter(k => slots.get(k).length).join(' + ') || 'searching'}`;
      // The list grew at the end, so the selection still points at its row.
      if (sel >= hits.length) sel = Math.max(0, hits.length - 1);
      paint();
    });
    // the vault answers after the code legs, in a section of its own at the end: at most five sections
    es.addEventListener('vault', e => {
      if (seq !== searchSeq) return stop();
      const d = JSON.parse(e.data);
      slots.set('vault', (d.hits || []).map(v => ({kind: 'vault', path: '', line: v.page == null ? 0 : v.page + 1, text: v.snippet || '',
        symbol: v.title || v.doc, doc: v.doc, shelf: v.shelf, vault: d.vault || '', page: v.page, sources: ['vault']})));
      recount(); paint();
    });
    es.addEventListener('done', e => {
      if (notes.length) backend += ' · ' + notes.slice(0, 2).join('; ');
      paint(); signals.impression(hits); stop();
    });
    es.onerror = () => { backend = backend || 'search stream failed'; paint(); stop(); };
  });

  let timer, liveStream = null;
  const search = () => {
    clearTimeout(timer); const seq = ++searchSeq;
    if (liveStream) { try { liveStream.close(); } catch {} liveStream = null; }
    timer = setTimeout(async () => {
      const q = input.value.trim();
      if (!q) { hits = []; backend = ''; paint(); return; }
      signals.query(q, mode, scopeEl.value, extsEl.value.trim());
      if (mode === 'all') {
        hits = []; sel = 0; backend = 'all · searching';
        list.innerHTML = `<div class="lee-search-progress"><span></span>every backend, fastest first…</div>`;
        return streamAll(q, seq);
      }
      list.innerHTML = `<div class="lee-search-progress"><span></span>searching ${esc(mode === 'context' ? 'Kosha repo + environment context' : mode === 'all' ? 'rg, symbols, FTS and ANN' : mode)}…</div>`;
      try {
        const d = await api('/search?q=' + encodeURIComponent(q) + '&mode=' + mode +
                            '&scope=' + encodeURIComponent(scopeEl.value) +
                            '&exts=' + encodeURIComponent(extsEl.value.trim()));
        if (seq !== searchSeq) return;
        hits = d.hits || []; backend = d.backend + (d.note ? ' · ' + d.note : ''); sel = 0;
        if (d.weights) setWeights(d.weights);
        // Which folders were walked, because "no matches" and "no matches here" are different
        // answers.
        const where = (d.searched || []).map(p => p.split('/').pop()).join(', ');
        $('#csscopenote', m).textContent = where ? `searched ${where}` : '';
        counts[mode] = hits.length; paintRail();
        paint(); signals.impression(hits); status(`search: ${d.backend}${d.note ? ' · ' + d.note : ''}`);
      } catch (e) {
        if (seq !== searchSeq) return;
        hits = []; backend = e.message || String(e); paint(); status(backend, 'err');
      }
    }, mode === 'rg' ? 120 : mode === 'all' || mode === 'context' ? 360 : 280);
  };
  input.addEventListener('input', search);
  scopeEl.addEventListener('change', () => {
    prefSet('search', 'lastScope', scopeEl.value);
    if (input.value.trim()) search();
  });
  // Settled, not per keystroke: this one is a POST and a file write, where the old key was neither.
  let extsTimer = 0;
  extsEl.addEventListener('input', () => {
    clearTimeout(extsTimer);
    extsTimer = setTimeout(() => prefSet('search', 'lastExts', extsEl.value.trim()), 400);
    if (input.value.trim()) search();
  });
  const setWeights = values => { weights = {...weights, ...values}; };
  /* Every weight `all` pays, with the list re-ranking as one is dragged. Ranking you cannot see
     is ranking you cannot tune, so each hit carries the features it scored on and the panel does
     the same arithmetic the server did. */
  let view = 'weights';
  const paintPanel = d => {
    held = d;
    weightKeys = d.keys || {}; weightDefaults = d.defaults || {}; setWeights(d.weights || {});
    const s = d.summary || {};
    const slider = name => {
      const [label, help] = WEIGHT_LABELS[name] || [name.replace(/([A-Z])/g, ' $1').toLowerCase(), ''];
      return `<label class="lee-weight" title="${esc(help)}"><span>${esc(label)}<small>${esc(help)}</small></span>` +
        `<input type="range" min="0" max="500" step="1" data-weight="${esc(name)}" value="${Number(weights[name] || 0)}" aria-label="${esc(label)}">` +
        `<input class="lee-input" type="number" min="0" max="500" data-weight-value="${esc(name)}" value="${Number(weights[name] || 0)}"></label>`;
    };
    const legs = Object.entries(s.legs || {}).map(([leg, row]) =>
      `${esc(leg)} ${row.won || 0}/${row.found || 0}`).join(' · ');
    panel.innerHTML =
      `<section data-panel="weights">` +
      `<p class="lee-weight-lead">Every result gets a score, and the highest score goes to the top. ` +
      `These are the points each thing is worth. Drag one and the list below re-sorts as you go.</p>` +
      `<div class="lee-weight-group"><h4>Points for how a result was found</h4><div class="lee-weight-grid">` +
      Object.keys(d.keys || {}).filter(k => k.startsWith('leg')).map(slider).join('') + `</div></div>` +
      `<div class="lee-weight-group"><h4>Points for how well it matches</h4><div class="lee-weight-grid">` +
      Object.keys(d.keys || {}).filter(k => !k.startsWith('leg')).map(slider).join('') + `</div></div>` +
      `<div class="lee-weight-actions"><button class="lee-btn" data-weights-reset type="button">defaults</button>` +
      `<span class="lee-spacer"></span><button class="lee-btn go" data-weights-save type="button">save weights</button></div></section>` +
      `<section data-panel="log"><div class="lee-weight-group"><h4>What Leela keeps about your searches</h4><div class="lee-weight-row">` +
      `<label>keep<select class="lee-select" data-signal="telemetry">` +
      ['off', 'local', 'vault'].map(v => `<option value="${v}"${v === d.telemetry ? ' selected' : ''}>${v}</option>`).join('') +
      `</select></label>` +
      `<label class="lee-settings-toggle"><input type="checkbox" data-signal="snippets"${d.snippets ? ' checked' : ''}><span>keep matched text</span></label>` +
      `<button class="lee-btn" data-signals-purge type="button">purge log</button></div>` +
      `<div class="lee-dim lee-weight-note">${esc(plural(s.searches || 0, 'search', 'searches'))} · ${esc(s.opens || 0)} opened · ` +
      `MRR ${esc(s.mrr || 0)} · abandoned ${Math.round((s.abandon_rate || 0) * 100)}% · retyped ${Math.round((s.refine_rate || 0) * 100)}%` +
      `${legs ? ' · won/found ' + esc(legs) : ''}<br>${esc(d.dir || '')}${d.telemetry === 'vault' ? ' · vault ' + esc(d.vault || '') : ''}</div></div>` +
      // What was recorded, not just how much of it: a log you cannot read is a log you cannot
      // trust, and the rank a search was opened at is the number the weights are answering to.
      `<div class="lee-weight-group"><h4>Your recent searches</h4><div class="lee-search-log">` +
      ((s.recent || []).map(r => `<button data-recall="${esc(r.q)}" data-recall-mode="${esc(r.mode || 'all')}">` +
        `<strong>${esc(r.q)}</strong><span>${esc(r.mode || 'all')} · ${esc(r.n || 0)} shown` +
        `${r.ms ? ' · ' + esc(r.ms) + 'ms' : ''}${r.previewed ? ' · ' + esc(r.previewed) + ' previewed' : ''}</span>` +
        `<em>${r.opened.length ? 'opened #' + (r.opened[0].rank + 1) + ' ' + esc((r.opened[0].path || '').split('/').pop() || r.opened[0].symbol)
             : r.abandoned ? 'abandoned' : 'no open'}</em></button>`).join('') ||
        '<div class="lee-dim">nothing recorded yet</div>') + `</div></div>` +
      `<div class="lee-dim lee-weight-note">Click a row to run that search again. Leela keeps what you ` +
      `searched for, what it showed you, what you looked at and what you opened${d.telemetry === 'vault' ?
      ', and files one note per search in a vault of its own' : ''}. None of it leaves this machine.</div>` +
      `</div></section>`;
    $$('[data-panel]', panel).forEach(el => el.hidden = el.dataset.panel !== view);
    const retune = () => { tuned = true; paint(); };
    $$('[data-weight]', panel).forEach(el => el.oninput = () => {
      weights[el.dataset.weight] = Number(el.value);
      $(`[data-weight-value="${el.dataset.weight}"]`, panel).value = el.value;
      retune();
    });
    $$('[data-weight-value]', panel).forEach(el => el.oninput = () => {
      weights[el.dataset.weightValue] = Number(el.value);
      $(`[data-weight="${el.dataset.weightValue}"]`, panel).value = el.value;
      retune();
    });
    $('[data-weights-reset]', panel).onclick = () => {
      setWeights(weightDefaults);
      $$('[data-weight]', panel).forEach(el => el.value = weights[el.dataset.weight]);
      $$('[data-weight-value]', panel).forEach(el => el.value = weights[el.dataset.weightValue]);
      retune();
    };
    $('[data-weights-save]', panel).onclick = async () => {
      try {
        await post('/settings/save', {scope: 'user', section: 'search', values: weights});
        status('search weights saved', 'ok');
        if (input.value.trim()) { tuned = false; search(); }
      } catch (e) { status(e.message || String(e), 'err'); }
    };
    $$('[data-signal]', panel).forEach(el => el.onchange = async () => {
      const value = el.type === 'checkbox' ? el.checked : el.value;
      try { await post('/settings/save', {scope: 'user', section: 'search', values: {[el.dataset.signal]: value}}); }
      catch (e) { status(e.message || String(e), 'err'); }
    });
    // A recorded search is a search you can run again, which is what makes the log worth reading.
    $$('[data-recall]', panel).forEach(el => el.onclick = () => {
      input.value = el.dataset.recall;
      panel.hidden = true; $('#cstune', m).setAttribute('aria-pressed', 'false');
      if (el.dataset.recallMode !== mode) setMode(el.dataset.recallMode); else search();
      input.focus();
    });
    $('[data-signals-purge]', panel).onclick = async () => {
      if (!await confirmDialog('Purge the search log', 'Delete every recorded search event? The vault documents are not touched.', 'purge')) return;
      const out = await post('/search/signals/purge', {});
      status(`removed ${out.removed} search event file${out.removed === 1 ? '' : 's'}`, 'ok');
      loadPanel();
    };
  };
  let held = null;
  const loadPanel = async (force = false) => {
    if (held && !force) return paintPanel(held);
    try { paintPanel(await api('/search/signals')); }
    catch (e) { panel.innerHTML = `<div class="lee-err">${esc(e.message || e)}</div>`; }
  };
  // Two questions, one panel: what the ranking pays for, and what it has recorded so far. Each
  // button shows its own; pressing the one already showing puts the results back.
  const showPanel = next => {
    panel.hidden = !panel.hidden && view === next;
    view = next;
    ['cstune', 'cslog'].forEach(id =>
      $(`#${id}`, m).setAttribute('aria-pressed', String(!panel.hidden && view === (id === 'cstune' ? 'weights' : 'log'))));
    if (!panel.hidden) loadPanel(view === 'log'); else input.focus();
  };
  $('#cstune', m).onclick = () => showPanel('weights');
  $('#cslog', m).onclick = () => showPanel('log');
  paintKoshaStatus($('#koshastatus', m));
  api('/search/signals?days=30').then(d => {
    weightKeys = d.keys || {}; weightDefaults = d.defaults || {}; setWeights(d.weights || {});
    const s = d.summary || {}, el = $('#cssignals', m);
    if (el && s.searches) el.textContent = `${plural(s.searches, 'search', 'searches')} recorded · ${Math.round((s.open_rate || 0) * 100)}% opened`;
  }).catch(() => {});
  $('#kosharefresh', m).onclick = async () => {
    const button = $('#kosharefresh', m); button.disabled = true; button.textContent = 'syncing…';
    try {
      const {err} = await runKoshaSync();
      if (err) { button.textContent = 'retry sync'; status(err, 'err'); }
      else { button.textContent = 'synced'; status('Kosha code, notebooks and graph synced', 'ok'); if (input.value.trim()) search(); }
    } finally { button.disabled = false; }
  };
  $('#csrail', m).onclick = e => {
    const b = e.target.closest('[data-mode]'); if (!b) return;
    e.preventDefault(); setMode(b.dataset.mode);
  };
  paintRail();
  setTimeout(() => input.focus(), 0);
}

function cursorWord() {
  const v = curEditor(); return v ? LeeCM.wordAtCursor(v) : '';
}
async function findDefinition(name = cursorWord()) {
  if (!name) return status('put the cursor on a symbol first', 'err');
  status(`finding ${name}…`);
  const d = await api('/code/definition?name=' + encodeURIComponent(name) + '&path=' + encodeURIComponent(lee.path || ''));
  if (!(d.hits || []).length) return status(`no definition found for ${name}`, 'err');
  if (d.hits.length === 1) return openLocation(d.hits[0]);
  hitList(d.hits, `${d.backend} · ${d.note}`, `definitions of ${name}`, openLocation);
}
async function findUsages(name = cursorWord()) {
  if (!name) return status('put the cursor on a symbol first', 'err');
  const d = await api('/code/usages?name=' + encodeURIComponent(name));
  hitList(d.hits || [], `${d.backend} · ${d.note}`, `usages of ${name}`, openLocation);
}
/* The dotted chain the cursor ends, so `fastcore.test` reaches the server whole: the last name
   alone found whichever package had a `def test`. Leftwards only, so on `fastcore` the answer is
   the package. */
function dottedAtCursor(view) {
  const word = LeeCM.wordAtCursor(view); if (!word) return '';
  const line = view.state.doc.lineAt(LeeCM.cursor(view)), text = line.text;
  let i = LeeCM.cursor(view) - line.from;
  while (i > 0 && /\w/.test(text[i - 1])) i--;
  let j = i;
  while (j > 1 && text[j - 1] === '.' && /\w/.test(text[j - 2])) {
    j--; while (j > 0 && /\w/.test(text[j - 1])) j--;
  }
  return text.slice(j, i) + word;
}
/* Where the cursor is, in the coordinates a symbol lookup can use. A notebook cursor is a cell
   and a line inside it: the file line is a line of JSON and matches no declaration. */
function editorPlace(view = curEditor()) {
  const path = lee.path || '';
  if (!view) return {path, line: 0, cellIndex: -1, dotted: ''};
  const line = view.state.doc.lineAt(LeeCM.cursor(view)).number;
  const cellIndex = lee.kind === 'notebook'
    ? lee.cells.findIndex(c => lee.editors.get(c.id) === view) : -1;
  return {path, line, cellIndex, dotted: dottedAtCursor(view)};
}
/* One key, both directions. On a usage it goes to the declaration, on the declaration it lists
   who uses it. The server decides which, since it knows where the declaration is. */
async function gotoDeclaration(name = cursorWord(), place = editorPlace()) {
  if (!name) return status('put the cursor on a symbol first', 'err');
  status(`finding ${name}…`);
  let d;
  try {
    d = await api('/code/jump?name=' + encodeURIComponent(name) +
      '&path=' + encodeURIComponent(place.path) + '&line=' + place.line + '&cell_index=' + place.cellIndex +
      '&dotted=' + encodeURIComponent(place.dotted || ''));
  } catch (e) { return status(String(e.message || e), 'err'); }
  const hits = d.hits || [];
  if (!hits.length) return status(`nothing found for ${name}`, 'err');
  if (d.kind === 'definition' && hits.length === 1) return openLocation(hits[0]);
  const word = d.kind === 'usages' ? 'usage' : 'definition';
  hitList(hits, `${d.backend} · ${d.note}`, `${word}s of ${name}`, openLocation);
  // `finding…` is a busy toast and waits to be clicked, so the answer has to replace it.
  status(`${plural(hits.length, word)} of ${name}`, 'ok');
}
/* The mouse saying what mod+b says. CodeMirror owns the click, so this takes the event in the
   capture phase: letting it through would move the caret and select a word.

   Either modifier counts, because platform detection is not reliable enough to gate it. In a
   webview that reported no platform, ctrl+click looked up the symbol and, being a right-click on
   macOS, opened the cell menu on top of the result. The paired `contextmenu` is claimed too. */
function bindModClick() {
  document.addEventListener('contextmenu', e => {
    if (e.shiftKey || !(e.metaKey || e.ctrlKey) || !e.target?.closest?.('.cm-content')) return;
    e.preventDefault(); e.stopPropagation();
  }, true);
  document.addEventListener('mousedown', e => {
    if (e.button !== 0 || e.altKey || e.shiftKey || !(e.metaKey || e.ctrlKey)) return;
    if (!e.target?.closest?.('.cm-content')) return;
    const view = [...lee.editors.values()].find(v => v?.contentDOM?.contains(e.target));
    const pos = view ? view.posAtCoords({x: e.clientX, y: e.clientY}) : null;
    if (pos == null) return;
    e.preventDefault(); e.stopPropagation();
    LeeCM.setCursor(view, pos);
    const word = LeeCM.wordAtCursor(view);
    if (!word) return status('nothing to look up there', 'err');
    gotoDeclaration(word, editorPlace(view));
  }, true);
}
window.gotoDeclaration = gotoDeclaration; window.bindModClick = bindModClick;
window.dottedAtCursor = dottedAtCursor;

async function renameSymbol() {
  const name=cursorWord(),view=curEditor();
  if(!name||!view||!lee.path||curLang()!=='python')return status('put the cursor on a Python symbol first','err');
  const next=await inputDialog('rename symbol','New name',name,'valid Python identifier');
  if(!next||next===name)return;
  const pos=LeeCM.cursor(view),line=view.state.doc.lineAt(pos),character=pos-line.from;
  try{
    const preview=await post('/lsp/rename',{path:lee.path,text:LeeCM.getDoc(view),line:line.number-1,character,newName:next});
    if(!preview.files?.length)return status('Pyright found no rename edits','err');
    const summary=preview.files.map(f=>`${f.path.split('/').pop()} · ${f.edits} edit${f.edits===1?'':'s'}`).join('\n');
    if(!await confirmDialog('Rename across workspace',`${name} → ${next}\n\n${summary}`,'rename'))return;
    await post('/lsp/rename',{path:lee.path,text:LeeCM.getDoc(view),line:line.number-1,character,newName:next,apply:true});
    const at=lee.path;await post('/tab/reload',{path:at});await mountTab(at);refreshFileTree(undefined,false);status(`renamed ${name} to ${next}`,'ok');
  }catch(e){status(e.message||String(e),'err');}
}

/* The Kosha header, repainted from `/code/status`; `err` is a failed sync, shown beside it. */
async function paintKoshaStatus(el, err = '') {
  if (!el) return;
  let d; try { d = await api('/code/status'); } catch (e) { d = {ok: false, note: e.message || String(e)}; }
  el.innerHTML = (d.ok ? `<span class="ok">Kosha connected</span><span>${plural(Number(d.files || 0).toLocaleString(), 'file')}</span>` +
    `<span>${plural(Number(d.packages || 0).toLocaleString(), 'package')}</span><span>${plural(Number(d.graph_nodes || 0).toLocaleString(), 'graph node')}</span>` +
    `${d.stale_files ? `<span class="warn">${esc(plural(d.stale_files, 'stale file'))}</span>` : ''}` : `<span class="warn">${esc(d.note || 'Kosha unavailable')}</span>`) +
    (err ? `<span class="warn">${esc(err)}</span>` : '');
}
/* Every Kosha sync: `err` is why it failed, and the header is repainted either way. */
async function runKoshaSync() {
  let d; try { d = await post('/code/sync'); } catch (e) { d = {ok: false, note: e.message || String(e)}; }
  const err = d.ok === false ? d.note || d.error || 'Kosha sync failed' : '';
  await paintKoshaStatus($('#koshastatus'), err);
  return {...d, err};
}
async function syncCodeIndex() {
  status('syncing Kosha index, notebooks and call graph…');
  const d = await runKoshaSync(); status(d.err || d.note || 'Kosha index synced', d.err ? 'err' : 'ok');
}

async function leeSymbols() {
  const host = $('#symbols'), label = $('#symbolfile'); if (!host) return;
  const path = lee.path, name = compactPath(path || ''); if (label) label.textContent = name ? '· ' + name : '';
  // Notebooks are included, read out of the cells rather than the JSON. The outline is of the
  // file on disk, so a def typed and not yet saved appears once autosave has run.
  if (!lee.path || (lee.kind !== 'text' && lee.kind !== 'notebook')) {
    host.innerHTML = '<div class="lee-dim">Open a source file or notebook to see its symbols.</div>'; return;
  }
  host.innerHTML = '<div class="lee-symbol-loading">Reading structure…</div>';
  try {
    const d = await api('/outline?path=' + encodeURIComponent(path));
    if (path !== lee.path) return;
    const rows = d.symbols || [];
    host.innerHTML = rows.length ? rows.map((s, i) => {
      const depth = Math.max(0, Math.floor(Number(s.score || 0) / 4));
      const kind = /^class\s/.test(s.text || '') ? 'class' : 'function';
      // A notebook symbol is addressed by cell. The JSON line it also carries would be a
      // meaningless number to show.
      const cellLine = Number(s.cell_line || 0), cellIndex = Number(s.cell_index ?? -1);
      const where = cellLine > 0 ? `${cellIndex + 1}:${cellLine}` : String(Number(s.line || 1));
      return `<button class="lee-symbol-row" role="treeitem" style="--depth:${depth}" ` +
        `data-line="${Number(s.line || 1)}" data-column="${Number(s.column || 0)}" data-cell="${esc(s.cell || '')}" ` +
        `data-cell-index="${cellIndex}" data-cell-line="${cellLine}">` +
        `<span class="lee-symbol-kind">${kind === 'class' ? 'C' : 'ƒ'}</span>` +
        `<span>${esc(s.symbol)}</span><small>${esc(where)}</small></button>`;
    }).join('') : '<div class="lee-dim">No functions or classes in this file.</div>';
    $$('.lee-symbol-row', host).forEach(row => row.onclick = () => {
      openLocation({path: path, line: +row.dataset.line, column: +row.dataset.column, cell: row.dataset.cell,
                    cell_index: +row.dataset.cellIndex, cell_line: +row.dataset.cellLine});
      if (matchMedia('(max-width: 1100px)').matches) leePane('left', false);
    });
  } catch (e) { if (e.name !== 'AbortError' && path === lee.path) host.innerHTML = `<div class="lee-err">${esc(e.message || e)}</div>`; }
}
window.leeSymbols = leeSymbols;

/* One find pane for both shapes of document. CodeMirror's own panel searches the one cell it
   belongs to, which is never what is asked of a notebook, and it offered no regex or replace where
   the cell bar did. This is the single mod+f: regex, case, whole word and replace, over a file or
   over every cell. */

const FIND_FLAGS = 'lee-find-flags';
const MAX_FIND_HITS = 5000;

const cellText = i => {
  const c = lee.cells[i]; if (!c) return '';
  const v = lee.editors.get(c.id);
  return v ? LeeCM.getDoc(v) : String(c.source || '');
};

function findFlags() {
  if (!lee.findFlags) {
    try { lee.findFlags = JSON.parse(localStorage.getItem(FIND_FLAGS)) || {}; }
    catch (_) { lee.findFlags = {}; }
  }
  return lee.findFlags;
}

function findRe(q) {
  const f = findFlags();
  let body = f.regex ? q : q.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  if (f.word) body = `\\b(?:${body})\\b`;
  return new RegExp(body, 'g' + (f.case ? '' : 'i'));
}

/* `-1` is the open file; anything else is a cell index. Whichever the tab holds, the pane
   walks the live text rather than what was last saved. */
const findDocs = () => lee.kind === 'notebook' ? lee.cells.map((_, i) => i) : (curEditor() ? [-1] : []);
const findText = i => i < 0 ? (curEditor() ? LeeCM.getDoc(curEditor()) : '') : cellText(i);
const findView = i => i < 0 ? curEditor() : ensureCellMounted(i);

/* Null means the pattern itself is broken, which is a different thing to say than "no matches". */
function findMatches(q) {
  if (!q) return [];
  let re;
  try { re = findRe(q); } catch (_) { return null; }
  const out = [];
  for (const i of findDocs()) {
    const text = findText(i);
    re.lastIndex = 0;
    for (let m; (m = re.exec(text));) {
      out.push({doc: i, from: m.index, to: m.index + m[0].length});
      if (!m[0].length) re.lastIndex++;
      if (out.length >= MAX_FIND_HITS) return out;
    }
  }
  return out;
}

function findPaint() {
  const bar = $('#leefind'); if (!bar) return;
  const q = $('#leefindq', bar).value, hits = findMatches(q), at = lee.find?.at ?? -1;
  lee.find = {q, hits: hits || [], at: hits && at < hits.length ? at : -1, bad: hits === null};
  $('#leefindcount', bar).textContent = !q ? '' : hits === null ? 'bad pattern'
    : !hits.length ? 'no matches' : `${(lee.find.at < 0 ? 0 : lee.find.at) + 1} of ${hits.length}`;
  bar.classList.toggle('empty', !!q && !lee.find.hits.length);
  $$('[data-find-flag]', bar).forEach(b => b.classList.toggle('on', !!findFlags()[b.dataset.findFlag]));
}

function findStep(direction) {
  const bar = $('#leefind'), state = lee.find;
  if (!bar || !state?.hits.length) return;
  const n = state.hits.length;
  state.at = ((state.at + direction) % n + n) % n;
  const hit = state.hits[state.at];
  if (hit.doc >= 0) focusCell(hit.doc);
  const view = findView(hit.doc);
  if (view) LeeCM.setSelection(view, hit.from, hit.to);
  $('#leefindcount', bar).textContent = `${state.at + 1} of ${n}`;
  // `focusCell` and `setSelection` both take the focus, a frame apart, so the query claims it
  // back after both have had their turn.
  requestAnimationFrame(() => requestAnimationFrame(() => $('#leefindq', bar)?.focus()));
}

function findReplaceOne() {
  const state = lee.find; if (!state?.hits.length) return findPaint();
  if (state.at < 0) return findStep(1);
  const hit = state.hits[state.at], view = findView(hit.doc);
  if (!view) return;
  const text = findText(hit.doc).slice(hit.from, hit.to);
  LeeCM.replaceRange(view, hit.from, hit.to, text.replace(findRe(state.q), $('#leefindr').value));
  const was = state.at;
  findPaint();
  lee.find.at = Math.min(was, lee.find.hits.length - 1) - 1;
  findStep(1);
}

function findReplaceAll() {
  const state = lee.find; if (!state?.hits.length) return findPaint();
  const to = $('#leefindr').value, done = new Set(state.hits.map(h => h.doc));
  let n = 0;
  for (const i of done) {
    const view = findView(i); if (!view) continue;
    const before = findText(i), after = before.replace(findRe(state.q), to);
    if (after === before) continue;
    n += state.hits.filter(h => h.doc === i).length;
    LeeCM.setDoc(view, after);
  }
  lee.find = null; findPaint();
  status(`replaced ${n} match${n === 1 ? '' : 'es'}`, 'ok');
}

/* Every hit in one editor becomes a cursor: the current hit's cell, else the selected cell, or the file. */
function findSelectAll() {
  if (!lee.find) findPaint();
  const state = lee.find, doc = state.at >= 0 ? state.hits[state.at].doc : lee.kind === 'notebook' ? lee.sel : -1;
  const hits = state.hits.filter(h => h.doc === doc && h.to > h.from);
  if (!hits.length) return status('no matches in this editor', 'err');
  if (doc >= 0 && doc !== lee.sel) focusCell(doc);
  const view = findView(doc); if (!view) return;
  LeeCM.setSelections(view, hits.map(h => [h.from, h.to]));
  status(`${hits.length} match${hits.length === 1 ? '' : 'es'} selected`, 'ok');
}

function findClose() {
  const bar = $('#leefind'); if (bar) bar.hidden = true;
  lee.find = null;
  const v = curEditor(); if (v) LeeCM.focus(v);
}

function findMake() {
  const bar = document.createElement('div');
  bar.id = 'leefind'; bar.className = 'lee-find-bar'; bar.setAttribute('role', 'search');
  bar.innerHTML =
    `<input class="lee-input" id="leefindq" spellcheck="false" placeholder="find" aria-label="find">` +
    `<div class="lee-find-tools">` +
      `<button type="button" data-find-flag="regex" title="regular expression" aria-label="regular expression">.*</button>` +
      `<button type="button" data-find-flag="case" title="match case" aria-label="match case">Aa</button>` +
      `<button type="button" data-find-flag="word" title="whole word" aria-label="whole word">|ab|</button>` +
      `<span class="lee-find-count" id="leefindcount" aria-live="polite"></span>` +
      `<button type="button" data-find="prev" title="previous match (shift+enter)">&#8593;</button>` +
      `<button type="button" data-find="next" title="next match (enter)">&#8595;</button>` +
      `<button type="button" data-find="select" title="select every match in this editor" aria-label="select every match in this editor">sel</button>` +
      `<button type="button" data-find="close" title="close (esc)">&#10005;</button>` +
    `</div>` +
    `<input class="lee-input" id="leefindr" spellcheck="false" placeholder="replace" aria-label="replace">` +
    `<div class="lee-find-tools">` +
      `<button type="button" class="lee-btn" data-find="one" title="replace this match">replace</button>` +
      `<button type="button" class="lee-btn" data-find="all" title="replace every match">all</button>` +
    `</div>`;
  document.body.appendChild(bar);
  bar.addEventListener('click', e => {
    const flag = e.target.closest('[data-find-flag]');
    if (flag) {
      const f = findFlags();
      f[flag.dataset.findFlag] = !f[flag.dataset.findFlag];
      try { localStorage.setItem(FIND_FLAGS, JSON.stringify(f)); } catch (_) {}
      lee.find = null; findPaint(); $('#leefindq', bar).focus();
      return;
    }
    const b = e.target.closest('[data-find]'); if (!b) return;
    if (b.dataset.find === 'close') return findClose();
    if (b.dataset.find === 'one') return findReplaceOne();
    if (b.dataset.find === 'all') return findReplaceAll();
    if (b.dataset.find === 'select') return findSelectAll();
    findStep(b.dataset.find === 'next' ? 1 : -1);
  });
  const step = e => {
    if (e.key === 'Escape') { e.preventDefault(); return findClose(); }
    if (e.key !== 'Enter') return;
    e.preventDefault();
    if (!lee.find?.hits.length) findPaint();
    findStep(e.shiftKey ? -1 : 1);
  };
  $('#leefindq', bar).addEventListener('input', findPaint);
  $('#leefindq', bar).addEventListener('keydown', step);
  $('#leefindr', bar).addEventListener('keydown', e => {
    if (e.key === 'Escape') { e.preventDefault(); return findClose(); }
    if (e.key === 'Enter') { e.preventDefault(); findReplaceOne(); }
  });
  return bar;
}

function leeFind() {
  if (!findDocs().length) return status('open a file to search it', 'err');
  const bar = $('#leefind') || findMake();
  bar.hidden = false;
  const input = $('#leefindq', bar), view = curEditor(), held = view ? LeeCM.selection(view) : null;
  if (held && held.from !== held.to && !held.text.includes('\n')) input.value = held.text;
  lee.find = null;
  findPaint();
  input.focus(); input.select();
}
function cursorLine() {
  if (lee.kind === 'notebook') {
    const c = lee.cells[lee.sel], v = c && lee.editors.get(c.id);
    return v ? LeeCM.lineOf(v) : 1;
  }
  const v = lee.editors.get('file');
  return v ? LeeCM.lineOf(v) : 1;
}

/* Where a hit is, said well enough to choose between two of them. A package hit is its dotted
   module, because `document.py` is offered by chonkie and by prompt_toolkit, and every package
   offers an `__init__.py`. A project hit is its basename until two hits share one, and then as
   many parent folders as it takes to tell them apart. */
function hitWhere(h, hits) {
  if (h.module) return h.module;
  const parts = String(h.path || '').split('/').filter(Boolean);
  const clash = hits.filter(o => o !== h && !o.module && String(o.path || '').split('/').pop() === parts.at(-1));
  if (!clash.length) return parts.at(-1) || h.path;
  const others = clash.map(o => String(o.path || '').split('/').filter(Boolean));
  for (let take = 2; take <= parts.length; take++) {
    const mine = parts.slice(-take).join('/');
    if (others.every(o => o.slice(-take).join('/') !== mine)) return mine;
  }
  return parts.join('/');
}

function hitList(hits, note, title, onPick) {
  let sel = 0;
  const m = modal(
    `<div class="lee-mhead">${esc(title)}<span class="sub">${esc(note || '')}</span></div>
     <div class="lee-modallist" id="hl"></div>`,
    (e) => {
      if (e.key === 'ArrowDown') { e.preventDefault(); sel = Math.min(sel + 1, hits.length - 1); paint(); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); sel = Math.max(sel - 1, 0); paint(); }
      else if (e.key === 'Enter') { e.preventDefault(); go(); }
    });
  const list = m.querySelector('#hl');
  const paint = () => {
    list.innerHTML = hits.length ? hits.map((h, i) =>
      `<div class="lee-mrow${i === sel ? ' sel' : ''}" data-i="${i}">` +
      `<span>${esc(h.symbol || h.text.slice(0, 60))}</span>` +
      `<span class="sub">${esc(hitWhere(h, hits))}:${h.line}` +
      `${h.score ? ' · d=' + h.score.toFixed(3) : ''}</span></div>`).join('')
      : '<div class="lee-dim">nothing found</div>';
    list.querySelector('.sel')?.scrollIntoView({block: 'nearest'});
  };
  const go = () => { const h = hits[sel]; if (h) { m.remove(); onPick(h); } };
  list.addEventListener('click', e => { const r = e.target.closest('.lee-mrow'); if (r) { sel = +r.dataset.i; go(); } });
  paint();
  return m;
}

const openHit = openLocation;

async function findSimilar() {
  if (!lee.path) return status('open a file first', 'err');
  status('finding similar code…');
  const d = await api(`/similar?path=${encodeURIComponent(lee.path)}&line=${cursorLine()}&mode=cluster`);
  status(`${d.hits.length} similar · ${d.backend} · ${d.note}`, d.hits.length ? 'ok' : null);
  hitList(d.hits, `${d.backend} · ${d.note}`, 'code like this', openHit);
}

async function codeMap() {
  status('clustering the codebase…');
  const d = await api('/clusters');
  if (!d.clusters.length) return status(d.note || 'no clusters', 'err');
  status(`${d.clusters.length} clusters · ${d.note}`, 'ok');
  // one row per cluster; picking one drills into its members
  const rows = d.clusters.map(c => ({
    symbol: `${c.label}  (${c.size})`, text: '', path: c.files[0] || '', line: 1,
    score: 0, _cluster: c,
  }));
  hitList(rows, d.note, 'code map: clusters of similar code', (r) => {
    const c = r._cluster;
    hitList(c.members, `${c.size} members across ${c.files.length} files`, `cluster: ${c.label}`, openHit);
  });
}

/* Start a run configuration in a process leela puts an inspector into. That is the difference
 * between this and the same command in a terminal: the inspector is inside it, so the variable
 * panel can watch the app's own module while it serves. A process started anywhere else has to opt
 * in with `dhrishti.serving.serve()`, and the picker says so.
 *
 * The picker and Run on an open file both come here, or there are two kinds of running script
 * again. */
async function startRun(r) {
  if (r.debug) return startDirectDebug(r);
  status(`starting ${r.name || (r.cmd || '').split('/').pop()}…`);
  let s;
  try { s = await withPython(() => post('/dev/start?name=' + encodeURIComponent(r.name || '') + '&path=' + encodeURIComponent(r.cmd))); }
  catch (e) { return status(String(e.message || e), 'err'); }
  if (!s.ok) return status(s.error || 'failed to start', 'err');
  agentLog(`<div class="lee-runline"><span class="sub">▶ ${esc(s.label)}: ${esc(s.cmd)}</span></div>` +
           `<div class="lee-runline"><span class="res">${esc((s.log || []).join('\n'))}</span></div>`);
  // A dev server's output is the thing you watch, so open the terminal it is on rather than
  // leaving it to be found under a dock tab and a filter.
  leeRunTerm(s.script || r.cmd, s.label, s.pid).catch(e => status(String(e.message || e), 'err'));
  if (s.base) {
    // Running is an explicit choice of runtime, so connect the variable panel rather than making
    // the user repeat that choice in "env…".
    await post('/envs/watch', {base: s.base});
    paintEnv(s.label);
  }
  status(`${s.label} running · app ${s.app_url || '?'} · ` +
         (s.base ? 'variables connected' : 'inspector pending'), 'ok');
  pollRunLogs(); leeVars();
}
window.startRun = startRun;

async function runApp() {
  const d = await api('/runs');
  const opts = (d.runs || []).concat(d.here ? [d.here] : []);
  if (!opts.length) {
    editRuns();
    return status('no run configurations yet. This is the file for them', 'err');
  }
  const start = startRun;
  if (opts.length === 1) return start(opts[0]);
  const m = modal(
    `<div class="lee-mhead">run<span class="sub">${esc(d.path || 'no project folder')}</span></div>` +
    `<div class="lee-modallist">${opts.map((r, i) =>
      `<div class="lee-mrow" data-i="${i}">${esc(r.name)}<span class="sub">${esc(r.cmd)}</span></div>`).join('')}</div>` +
    `<div class="lee-mfoot"><button class="lee-btn" id="editruns">edit configurations</button></div>`);
  m.addEventListener('click', (e) => {
    const r = e.target.closest('.lee-mrow'); if (!r) return;
    m.remove(); start(opts[+r.dataset.i]);
  });
  m.querySelector('#editruns').onclick = () => { m.remove(); editRuns(); };
}

// The menu bar reaches this from `evaluate_js`, which runs in global scope and cannot see a
// module-scope name. Same arguments the Debug chrome menu passes.
window.leeDebugFile = () => startDirectDebug(
  {name: lee.path?.split('/').pop() || 'Python', program: lee.path, debug: true});

async function startDirectDebug(run={}) {
  let capabilities;
  try{capabilities=await withPython(()=>api('/debug/capabilities'));}catch(e){return status(String(e.message||e),'err');}
  if(!capabilities.debugpy){
    const ok=await confirmDialog('Install debugpy',`Install debugpy into ${capabilities.python}?`,'install');
    if(!ok)return;
    status('installing debugpy…');await post('/debug/install',{python:capabilities.python});
  }
  const path=run.program||lee.path||'', lines=path?detailedBreakpoints(path):[];
  status(`starting debugger: ${run.name||path.split('/').pop()||'Python'}…`);
  const config={...lee.debugPrefs,...run,program:run.program||path,breakpoints:path?{[path]:lines}:{}};
  try{await withPython(()=>post('/debug/start',config));}catch(e){return status(String(e.message||e),'err');}
  lee.directDebug=true;
  status('debugger running','ok');
  postEvents('/debug/events',{},(event,data)=>{
    if(event==='stopped'){lee.debugThread=data.thread_id;paintDebugger(data);status(`paused at line ${data.frames?.[0]?.line||'?'}`,'ok');}
    else if(event==='continued'){$('#debugger')?.classList.add('running');}
    else if(event==='output'){const text=data.output||'';if(text)agentLog(`<div class="lee-runline"><span class="res">${esc(text)}</span></div>`);}
    else if(event==='error')status(data.message||'debugger failed','err');
    else if(event==='terminated'||event==='exited'){leeDebugStop();status('debug session finished','ok');}
  }).catch(e=>status(e.message||String(e),'err'));
}
window.leeStartDebug=startDirectDebug;

/* Which live namespace the variable panel shows. Every process that registered an inspector is
 * here: a notebook kernel, an app leela started, or something you launched yourself that called
 * `dhrishti.serving.serve()`. Nothing else has anything to read. */
function paintEnv(name) {
  lee.env = name || '';
  const t = $('#envtag'); if (!t) return;
  t.textContent = name ? '▶ ' + name : '';
  t.style.display = name ? '' : 'none';
  t.title = name ? 'Run and the variable panel are connected to this runtime' : '';
}

async function pickEnv() {
  const d = await api('/envs');
  const rows = [{name: 'the tab’s own kernel', base: null, kind: 'kernel', current: !d.watching}]
    .concat(d.envs || []);
  const m = modal(
    `<div class="lee-mhead">runtime<span class="sub">Run + variables · ${(d.envs || []).length} live env(s)</span></div>` +
    `<div class="lee-modallist">${rows.map((e, i) =>
      `<div class="lee-mrow${e.current ? ' sel' : ''}" data-i="${i}">${e.current ? '● ' : '○ '}` +
      `${esc(e.name)}<span class="sub">${esc(e.kind)}${e.pid ? ' · pid ' + e.pid : ''}</span></div>`).join('')}</div>` +
    `<div class="lee-dim">a process shows here only when it has an inspector in it. ` +
    `<code>${esc(d.hint)}</code> puts one in yours.</div>`);
  m.addEventListener('click', async (e) => {
    const r = e.target.closest('.lee-mrow'); if (!r) return;
    const pick = rows[+r.dataset.i];
    m.remove();
    await post('/envs/watch', {base: pick.base});
    paintEnv(pick.base ? pick.name : '');
    status(pick.base ? 'watching ' + pick.name : 'back on the tab’s kernel', 'ok');
    leeVars();
  });
}

/* The configurations themselves, editable in place for the same reason the keymap is. */
async function editRuns() {
  const d = await api('/runs/file');
  let data;
  try { data = JSON.parse(d.text); } catch (_) { data = {runs: []}; }
  let runs = Array.isArray(data) ? data : (data.runs || []);
  const m = modal(`<div class="lee-mhead">run configurations<span class="sub">${esc(d.path || 'open a folder first')}</span></div>` +
    `<div class="lee-runtime-workbench"><header><div><strong>Project runtime</strong><span>Commands, working directories, and environment sources</span></div>` +
    `<button class="lee-btn" data-add-run>Add configuration</button></header><div data-run-list></div>` +
    `<details class="lee-run-json"><summary>Advanced JSON</summary><textarea class="lee-keyedit" spellcheck="false"></textarea></details></div>` +
    `<div class="lee-mfoot"><span class="lee-dim">Secret values belong in an ignored .env.local file, not runs.json.</span><span class="lee-spacer"></span>` +
    `<button class="lee-btn" data-cancel>cancel</button><button class="lee-btn go" data-save>save configurations</button></div>`,
    null, null, {className: 'lee-runtime-modal', storageKey: 'runs'});
  const list = $('[data-run-list]', m), json = $('.lee-run-json textarea', m);
  const normal = r => ({name:r.name||'run',cmd:r.cmd||'',cwd:r.cwd||'',watch:r.watch||'',inspect:r.inspect!==false,
    env_file:r.env_file||'',env:{...(r.env||{})},debug:!!r.debug,request:r.request||'launch',program:r.program||'',module:r.module||'',
    args:Array.isArray(r.args)?r.args:[],justMyCode:r.justMyCode!==false,stopOnEntry:!!r.stopOnEntry,subProcess:r.subProcess!==false,
    host:r.host||'127.0.0.1',port:Number(r.port)||5678,django:!!r.django,jinja:!!r.jinja,gevent:!!r.gevent,pathMappings:r.pathMappings||[]});
  runs = runs.map(normal);
  const collect = () => $$('.lee-run-card', list).map(card => {
    const env = {}; $$('.lee-env-row', card).forEach(row => { const key = $('[data-env-key]', row).value.trim(); if (key) env[key] = $('[data-env-value]', row).value; });
    return {name:$('[data-run-name]',card).value.trim()||'run',cmd:$('[data-run-cmd]',card).value.trim(),cwd:$('[data-run-cwd]',card).value.trim(),
      watch:$('[data-run-watch]',card).value.trim(),env_file:$('[data-run-env-file]',card).value.trim(),inspect:$('[data-run-inspect]',card).checked,env,
      debug:$('[data-run-debug]',card).checked,request:$('[data-debug-request]',card).value,program:$('[data-debug-program]',card).value.trim(),
      module:$('[data-debug-module]',card).value.trim(),args:$('[data-debug-args]',card).value.trim().split(/\s+/).filter(Boolean),
      justMyCode:$('[data-debug-mycode]',card).checked,stopOnEntry:$('[data-debug-entry]',card).checked,subProcess:$('[data-debug-subprocess]',card).checked,
      host:$('[data-debug-host]',card).value.trim()||'127.0.0.1',port:Number($('[data-debug-port]',card).value)||5678,
      django:$('[data-debug-django]',card).checked,jinja:$('[data-debug-jinja]',card).checked,gevent:$('[data-debug-gevent]',card).checked,
      pathMappings:(()=>{try{return JSON.parse($('[data-debug-paths]',card).value||'[]');}catch(_){return [];}})()};
  });
  const envRow = (key = '', value = '') => `<div class="lee-env-row"><input class="lee-input" data-env-key placeholder="NAME" value="${esc(key)}">` +
    `<input class="lee-input" data-env-value placeholder="value" value="${esc(value)}"><button class="lee-icon" data-remove-env aria-label="remove variable">×</button></div>`;
  const paint = () => {
    list.innerHTML = runs.map((r, i) => `<section class="lee-run-card" data-i="${i}"><header><strong>${esc(r.name)}</strong>` +
      `<button class="lee-btn warn" data-remove-run>remove</button></header><div class="lee-run-fields">` +
      `<label>Name<input class="lee-input" data-run-name value="${esc(r.name)}"></label><label>Command<input class="lee-input" data-run-cmd value="${esc(r.cmd)}" placeholder="uv run python app.py"></label>` +
      `<label>Working directory<input class="lee-input" data-run-cwd value="${esc(r.cwd)}" placeholder="project root"></label><label>Watch module<input class="lee-input" data-run-watch value="${esc(r.watch)}" placeholder="infer from command"></label>` +
      `<label>Environment file<input class="lee-input" data-run-env-file value="${esc(r.env_file)}" placeholder=".env.local"></label><label class="lee-run-check"><input type="checkbox" data-run-inspect${r.inspect?' checked':''}> Attach live inspector</label></div>` +
      `<details class="lee-debug-config"${r.debug?' open':''}><summary><label class="lee-run-check"><input type="checkbox" data-run-debug${r.debug?' checked':''}> Debug with debugpy</label></summary><div class="lee-run-fields">` +
      `<label>Request<select class="lee-select" data-debug-request><option value="launch"${r.request==='launch'?' selected':''}>Launch</option><option value="attach"${r.request==='attach'?' selected':''}>Attach</option></select></label>` +
      `<label>Program<input class="lee-input" data-debug-program value="${esc(r.program)}" placeholder="active Python file"></label><label>Module<input class="lee-input" data-debug-module value="${esc(r.module)}" placeholder="pytest"></label>` +
      `<label>Arguments<input class="lee-input" data-debug-args value="${esc(r.args.join(' '))}" placeholder="-x tests"></label><label>Attach host<input class="lee-input" data-debug-host value="${esc(r.host)}"></label><label>Attach port<input class="lee-input" data-debug-port type="number" value="${r.port}"></label>` +
      `<label>Path mappings<input class="lee-input" data-debug-paths value="${esc(JSON.stringify(r.pathMappings||[]))}" placeholder='[{"localRoot":".","remoteRoot":"/app"}]'></label>` +
      `<label class="lee-run-check"><input type="checkbox" data-debug-mycode${r.justMyCode?' checked':''}> Just my code</label><label class="lee-run-check"><input type="checkbox" data-debug-entry${r.stopOnEntry?' checked':''}> Stop on entry</label><label class="lee-run-check"><input type="checkbox" data-debug-subprocess${r.subProcess?' checked':''}> Subprocesses</label>` +
      `<label class="lee-run-check"><input type="checkbox" data-debug-django${r.django?' checked':''}> Django</label><label class="lee-run-check"><input type="checkbox" data-debug-jinja${r.jinja?' checked':''}> Jinja templates</label><label class="lee-run-check"><input type="checkbox" data-debug-gevent${r.gevent?' checked':''}> gevent</label></div></details>` +
      `<div class="lee-env-head"><strong>Environment variables</strong><button class="lee-btn" data-add-env>Add variable</button></div><div data-env-list>${Object.entries(r.env).map(([k,v])=>envRow(k,v)).join('')}</div></section>`).join('') ||
      `<div class="lee-empty"><strong>No run configurations</strong><p>Add how this project starts, then attach its live namespace to Variables.</p></div>`;
    $$('.lee-run-card', list).forEach(card => {
      $('[data-remove-run]', card).onclick = () => { runs = collect(); runs.splice(+card.dataset.i, 1); paint(); };
      $('[data-add-env]', card).onclick = () => { $('[data-env-list]', card).insertAdjacentHTML('beforeend', envRow()); $('.lee-env-row:last-child [data-env-key]', card).focus(); };
      card.onclick = e => { const b = e.target.closest('[data-remove-env]'); if (b) b.closest('.lee-env-row').remove(); };
    });
  };
  paint();
  $('[data-add-run]', m).onclick = () => { runs = collect(); runs.push(normal({name: `run ${runs.length + 1}`})); paint(); $$('.lee-run-card', list).at(-1)?.scrollIntoView({block:'center'}); };
  $('.lee-run-json', m).ontoggle = e => { if (e.target.open) json.value = JSON.stringify({runs: collect()}, null, 2); };
  json.addEventListener('change', () => { try { runs = (JSON.parse(json.value).runs || []).map(normal); paint(); } catch (e) { status('invalid run configuration JSON: ' + e.message, 'err'); } });
  $('[data-cancel]', m).onclick = () => m.remove();
  $('[data-save]', m).onclick = async () => {
    try {
      runs = collect();
      const r = await post('/runs/save', {text: JSON.stringify({runs}, null, 2) + '\n'});
      status(r.note || `saved ${r.runs.length} configuration(s)`, r.note ? 'err' : 'ok'); m.remove();
    } catch (e) { status(String(e.message || e), 'err'); }
  };
}

function palette() {
  const picked = String(getSelection?.() ?? '').trim();
  const lessonCommands = [{name: "Lesson: I don't get…", scope: 'editor', run: () => lessonGuideSelected(picked)}];
  const agentCommands = [
    {name: 'Agent: autopilot mode', scope: 'agent', run: () => leeAgentControl('autopilot')},
    {name: 'Agent: guided mode', scope: 'agent', run: () => leeAgentControl('guided')},
    {name: 'Agent: directed mode', scope: 'agent', run: () => leeAgentControl('directed')},
    {name: 'Agent: pause after current call', scope: 'agent', run: pauseAgentAfterCurrent},
    {name: 'Agent: run until next write', scope: 'agent', run: () => post('/agent/run-policy', {policy: 'until_write'})},
    {name: 'Agent: run read-only calls', scope: 'agent', run: () => post('/agent/run-policy', {policy: 'reads'})},
    {name: 'Agent: edit starting state', scope: 'agent', run: leeAgentState},
    {name: 'Agent: steer after current call', scope: 'agent', run: () => $('#agentprompt')?.focus()},
    {name: 'Agent: sub-agents', scope: 'agent', run: () => leeSubagents()},
    {name: 'Agent: sub-agent model', scope: 'agent', run: () => leeOpenSetting('#jobmodels [data-job="subagent"]')},
    {name: 'Agent: sub-agent effort', scope: 'agent', run: () => leeOpenSetting('#subeffort')},
    {name: 'Agent: sub-agent tool calls native or text', scope: 'agent', run: () => leeOpenSetting('#subtools')},
    {name: 'Agent: tool calls native or text', scope: 'agent', run: () => leeOpenSetting('#toolmode')},
    {name: 'Agent: conversation branches', scope: 'agent', run: () => leeAgentBranches()},
    {name: 'Agent: shape what the model remembers', scope: 'agent', run: () => leeAgentShape()},
    {name: 'Inline completions: what was asked and taken', scope: 'global', run: () => showCompletions()},
  ];
  const cmds = lee.keys.filter(k => k.label).map(k => ({name: k.label, scope: k.scope, action: k.action, key: shownChord(k)})).concat(agentCommands, lessonCommands);
  let hits = cmds, sel = 0;
  const m = modal(`<input class="lee-input" id="cp" placeholder="command…" aria-label="Command palette" role="combobox" aria-controls="cplist" aria-expanded="true" autofocus>
                   <div class="lee-modallist" id="cplist" role="listbox" aria-label="Commands"></div>`,
    (e) => {
      if (e.key === 'ArrowDown') { e.preventDefault(); sel = Math.min(sel + 1, hits.length - 1); paint(); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); sel = Math.max(sel - 1, 0); paint(); }
      else if (e.key === 'Enter') { e.preventDefault(); go(); }
    });
  const list = m.querySelector('#cplist'), input = m.querySelector('#cp');
  const paint = () => {
    list.innerHTML = hits.slice(0, 200).map((h, i) =>
      `<div class="lee-mrow${i === sel ? ' sel' : ''}" data-i="${i}">${esc(sentence(h.name))}${h.scope && h.scope !== 'global' ? `<span class="sub">${esc(h.scope)}</span>` : ''}` +
      `${h.key ? `<kbd>${esc(displayChord(h.key))}</kbd>` : ''}</div>`).join('');
    list.querySelector('.sel')?.scrollIntoView({block: 'nearest'});
  };
  const go = () => {
    const h = hits[sel]; if (!h) return;
    m.remove();
    h.run ? h.run() : leeAct(h.action);
  };
  list.addEventListener('click', e => { const r = e.target.closest('.lee-mrow'); if (r) { sel = +r.dataset.i; go(); } });
  // Files are ⌘P's: one row hands the query over rather than twenty crowding the commands.
  input.addEventListener('input', () => {
    const q = input.value.toLowerCase(), raw = input.value.trim();
    hits = cmds.filter(c => c.name.toLowerCase().includes(q) || (c.action || '').includes(q));
    if (raw) hits = hits.concat({name: `Go to file matching “${raw}”…`, scope: 'files', key: shownChord(lee.keys.find(k => k.action === 'quick_open')),
                                 run: () => quickOpen(false, raw)});
    sel = 0; paint();
  });
  paint(); setTimeout(() => input.focus(), 0);
}

const treeSel = () => $('.lee-node.sel');
/* One click is one selection; meta adds and removes, shift takes the run between. `.sel` stays the
   caret, so the arrows and every single-target action keep working unchanged, and `treePaths` is
   what an operation acts on: the marked set when there is one, otherwise the caret alone. */
const treeMarked = () => $$('.lee-node.marked');
const treePaths = () => {
  const marked = treeMarked().map(n => n.dataset.path);
  const sel = treeSel()?.dataset.path;
  return marked.length ? marked : sel ? [sel] : [];
};
function markTreeNode(n, on) {
  if (!n) return;
  n.classList.toggle('marked', on);
  n.setAttribute('aria-multiselectable', 'true');
}
function clearTreeMarks() { treeMarked().forEach(n => n.classList.remove('marked')); }
/* A file row opens on click and stops there, so the document listener never sees it. Held
   modifiers have to mean "select" rather than "open", and both readings live here. */
function leeTreeClick(e, path) {
  e.preventDefault(); e.stopPropagation();
  const n = e.target.closest('.lee-node');
  setScope('files');
  // Only what was clicked. Folding the caret in would put whichever row happened to be highlighted
  // on load into a cut or a delete nobody chose it for; `treePaths` already falls back to the caret
  // when nothing is marked at all.
  if (e.metaKey || e.ctrlKey) {
    markTreeNode(n, !n.classList.contains('marked'));
    return selectTreeNode(n, true);
  }
  if (e.shiftKey) { markTreeRange(n); return; }
  selectTreeNode(n);
  leeOpenFile(path);
}
window.leeTreeClick = leeTreeClick;
function markTreeStep(d) {
  const nodes = visibleTreeNodes(), at = nodes.indexOf(treeSel());
  const next = nodes[Math.max(0, Math.min(nodes.length - 1, at + d))];
  if (!treeMarked().length) markTreeNode(treeSel(), true);
  markTreeNode(next, true);
  selectTreeNode(next, true);
}
function markTreeRange(to) {
  const nodes = visibleTreeNodes(), from = treeSel();
  const a = nodes.indexOf(from), b = nodes.indexOf(to);
  if (a < 0 || b < 0) return markTreeNode(to, true);
  for (const n of nodes.slice(Math.min(a, b), Math.max(a, b) + 1)) markTreeNode(n, true);
}
const visibleTreeNodes = () => $$('.lee-node').filter(n => n.getClientRects().length);
function selectTreeNode(n, keepMarks = false) {
  if (!n) return;
  if (!keepMarks) clearTreeMarks();
  $$('.lee-node').forEach(x => { x.classList.remove('sel'); x.setAttribute('aria-selected', 'false'); });
  n.classList.add('sel'); n.setAttribute('aria-selected', 'true');
  n.scrollIntoView({block: 'nearest'});
}
window.selectTreeNode = selectTreeNode;
function highlightTree() { if (!treeSel()) selectTreeNode(visibleTreeNodes()[0]); }
function moveTreeSelection(d) {
  const nodes = visibleTreeNodes(); if (!nodes.length) return;
  const at = Math.max(0, nodes.indexOf(treeSel()));
  selectTreeNode(nodes[Math.max(0, Math.min(nodes.length - 1, at + d))]);
}
/* Dotfiles are off by default and on by choice, because `.gitignore`, `.github` and `.env` are
   files you edit. The server's skip list drops `.venv` and `node_modules` whatever the toggle
   says. */
function treeHidden() { return prefGet('workbench', 'showHiddenFiles', false) === true; }
function treeQuery(sep = '?') { return treeHidden() ? sep + 'hidden=1' : ''; }
/* `lee-tree-hidden` was per origin, and the port moves between launches, so the toggle came back
   off at a port nobody chose. The tree is painted before the adoption can answer, so it is painted
   again when the answer changes it. */
let hiddenAdopted = false;
async function adoptTreeHidden() {
  if (hiddenAdopted) return;
  hiddenAdopted = true;
  const was = treeHidden();
  await prefAdopt('workbench', 'showHiddenFiles', 'lee-tree-hidden', v => v === '1');
  if (treeHidden() === was) return;
  paintHiddenBtn();
  if (fsEvents) watchFiles();
  await refreshFileTree(undefined, false);
}
function paintHiddenBtn() {
  adoptTreeHidden().catch(() => {});
  $$('[data-action="show_hidden"]').forEach(b => {
    b.classList.toggle('on', treeHidden());
    b.setAttribute('aria-pressed', String(treeHidden()));
  });
}
async function toggleHidden() {
  await prefSet('workbench', 'showHiddenFiles', !treeHidden());
  if (fsEvents) watchFiles();
  await refreshFileTree(undefined, false);
  status(treeHidden() ? 'showing dotfiles' : 'hiding dotfiles', 'ok');
}
window.treeHidden = treeHidden; window.toggleHidden = toggleHidden; window.paintHiddenBtn = paintHiddenBtn;
async function loadTreeDir(n) {
  if (!n?.classList.contains('lee-dir')) return;
  const kids = n.querySelector(':scope > .lee-kids');
  n.open = true; n.setAttribute('aria-expanded', 'true');
  if (kids && !kids.children.length) {
    kids.innerHTML = await fetch('/tree?path=' + encodeURIComponent(n.dataset.path) + treeQuery('&'),
                                 {headers: {'HX-Request': 'true'}}).then(r => r.text());
    htmx.process(kids); paintTreeGit($$('.lee-node', kids));
  }
}
async function treeActivate() {
  const n = treeSel(); if (!n) return highlightTree();
  if (n.classList.contains('lee-dir')) {
    if (n.open) { n.open = false; n.setAttribute('aria-expanded', 'false'); }
    else await loadTreeDir(n);
    return;
  }
  leeOpenFile(n.dataset.path);
}
async function treeExpand() {
  const n = treeSel(); if (!n) return highlightTree();
  if (!n.classList.contains('lee-dir')) return treeActivate();
  if (!n.open) await loadTreeDir(n);
  else selectTreeNode(visibleTreeNodes()[visibleTreeNodes().indexOf(n) + 1] || n);
}
function treeCollapse() {
  const n = treeSel(); if (!n) return highlightTree();
  if (n.classList.contains('lee-dir') && n.open) {
    n.open = false; return;
  }
  selectTreeNode(n.parentElement?.closest('.lee-node.lee-dir') || n);
}
/* The open folders go up with the request and come back drawn: one round trip, not one each. */
async function refreshFileTree(selectPath = treeSel()?.dataset.path, focus = true) {
  const old = $('.lee-files'); if (!old) return;
  const open = $$('.lee-dir[open]', old).map(n => n.dataset.path);
  const scrollTop = $('#filetree')?.scrollTop || 0;
  const q = new URLSearchParams();
  if (treeHidden()) q.set('hidden', '1');
  if (open.length) q.set('open', open.join('\n'));
  const html = await fetch('/files/panel?' + q).then(r => { if (!r.ok) throw new Error(r.statusText); return r.text(); });
  const doc = new DOMParser().parseFromString(html, 'text/html'), fresh = doc.querySelector('.lee-files');
  if (!fresh) throw new Error('file tree refresh returned no panel');
  old.replaceWith(fresh); htmx.process(fresh); paintHiddenBtn(); paintTreeGit();
  const wanted = $$('.lee-node').find(n => n.dataset.path === selectPath) || visibleTreeNodes()[0];
  selectTreeNode(wanted); if ($('#filetree')) $('#filetree').scrollTop = scrollTop;
  if (focus) setScope('files');
  status('files refreshed', 'ok');
}

/* Pushed, not polled. A push reconciles the folders that changed and leaves every other row, its
   expansion and the scroll alone. */
const selfWrites = new Map();
const SELF_WRITE_MS = 4000;
function noteSelfWrite(...paths) { for (const p of paths) if (p) selfWrites.set(p, performance.now()); }
function notMine(paths) {
  const now = performance.now();
  for (const [p, at] of selfWrites) if (now - at > SELF_WRITE_MS) selfWrites.delete(p);
  return paths.filter(p => !selfWrites.has(p));
}
window.noteSelfWrite = noteSelfWrite;

/* Rows are drawn with the marks the server last saw and never wait on git, which in the packaged
   app can take seconds. This asks for every row's mark and paints it: one request at a time, and
   the rows asked for meanwhile go in the one after it. */
const GIT_MARKS = ['git-ignored', 'git-staged', 'git-modified', 'git-untracked', 'git-conflict'], TREE_GIT_BATCH = 2000;
let treeGitBusy = null, treeGitAgain = new Set();
function paintTreeRow(row, state) {
  row.classList.remove(...GIT_MARKS);
  const own = row.classList.contains('lee-dir') ? row.querySelector(':scope > summary') : row;
  own?.querySelectorAll(':scope > .lee-tree-git').forEach(b => b.remove());
  if (!state || !own) return;
  row.classList.add('git-' + state);
  const badge = document.createElement('span'); badge.className = 'lee-tree-git'; badge.textContent = state[0].toUpperCase();
  const name = own.querySelector(':scope > .lee-fname');
  name ? name.after(badge) : own.appendChild(badge);
}
function paintTreeGit(rows = $$('#filetree .lee-node')) {
  rows.forEach(r => r.dataset.path && treeGitAgain.add(r));
  if (treeGitBusy) return treeGitBusy;
  treeGitBusy = (async () => {
    try {
      while (treeGitAgain.size) {
        const now = [...treeGitAgain].filter(r => r.isConnected); treeGitAgain = new Set();
        for (let i = 0; i < now.length; i += TREE_GIT_BATCH) {
          const part = now.slice(i, i + TREE_GIT_BATCH);
          const d = await post('/tree/git', {paths: part.map(r => r.dataset.path)});
          part.forEach(r => { if (r.isConnected && r.dataset.path in d.states) paintTreeRow(r, d.states[r.dataset.path]); });
        }
      }
    } catch (e) { console.warn('Leela tree git marks:', e); }
    finally { treeGitBusy = null; }
  })();
  return treeGitBusy;
}
window.paintTreeGit = paintTreeGit;
document.addEventListener('htmx:afterSwap', e => { if (e.target.closest?.('#filetree')) paintTreeGit($$('.lee-node', e.target)); });
// Rows that are still there stay where they are, with whatever they had open inside them.
async function patchTreeDir(dir) {
  const kids = dir.querySelector(':scope > .lee-kids'); if (!kids) return;
  const html = await fetch('/tree?path=' + encodeURIComponent(dir.dataset.path) + treeQuery('&'),
                           {headers: {'HX-Request': 'true'}}).then(r => r.text());
  const box = document.createElement('div'); box.innerHTML = html;
  const have = new Map([...kids.children].map(n => [n.dataset.path, n]));
  [...box.children].forEach((fresh, i) => {
    const row = have.get(fresh.dataset.path) || fresh;
    have.delete(fresh.dataset.path);
    if (kids.children[i] !== row) kids.insertBefore(row, kids.children[i] || null);
  });
  have.forEach(n => n.remove());
  htmx.process(kids); paintTreeGit($$('.lee-node', kids));
}
/* A new folder's own path is open nowhere. Redraw the nearest open ancestor, but only when the
   change can alter its names: a direct child came or went, or a deeper write names a row it does
   not have. A file written deep inside a closed folder that is already listed changes nothing it
   shows, and redrawing for it was a `/tree`, and git in every repository, per batch. */
function patchTargets(paths) {
  const open = $$('.lee-dir[open]'), want = new Set();
  for (const p of paths) {
    let best = null;
    for (const n of open) {
      const d = n.dataset.path;
      if ((p === d || p.startsWith(d + '/')) && (!best || d.length > best.dataset.path.length)) best = n;
    }
    if (!best) continue;
    const d = best.dataset.path, rest = p.slice(d.length + 1);
    if (p === d || !rest.includes('/')) { want.add(best); continue; }
    const name = rest.split('/')[0];
    if (name.startsWith('.') && !treeHidden()) continue;
    const kids = best.querySelector(':scope > .lee-kids');
    if (kids && ![...kids.children].some(n => n.dataset.path === d + '/' + name)) want.add(best);
  }
  return want;
}
/* One redraw at a time, and the paths that arrive meanwhile are carried into the next one, as
   `refreshGitTreeMarks` does for the marks. */
let patchBusy = null, patchAgain = new Set();
async function patchTree(paths) {
  paths.forEach(p => patchAgain.add(p));
  if (patchBusy) return patchBusy;
  patchBusy = (async () => {
    try {
      while (patchAgain.size) {
        const now = [...patchAgain]; patchAgain = new Set();
        await Promise.all([...patchTargets(now)].map(n => patchTreeDir(n).catch(() => {})));
      }
    } finally { patchBusy = null; }
  })();
  return patchBusy;
}
/* A change git can see repaints every row's mark, through `paintTreeGit`, which runs one request at
   a time and folds the rest into the next. A build writing without pause costs two walks of the
   repository, not one per batch. */
function refreshGitTreeMarks() { return paintTreeGit(); }

let fsWatchTimer = null, fsWatchSeen = [], fsWatchSince = 0;
const FS_DEBOUNCE = 250, FS_MAX_WAIT = 1000, FS_MAX_SEEN = 2000;
// Too many changes to name, so nothing is named: redraw rather than patch.
function resyncFiles() {
  clearTimeout(fsWatchTimer); fsWatchSeen = []; fsWatchSince = 0;
  refreshFileTree(undefined, false).catch(() => {});
  noticeGitDisk(); refreshGitTreeMarks(); watchOpenFile();
}
/* The server drops what the tree cannot show, dotfiles among them unless they are shown, so the
   stream is reopened when that toggle changes. `git` is whether any change is one git can see. */
let fsEvents = null, fsWatchGit = false;
function watchFiles() {
  fsEvents?.close();
  const es = fsEvents = new EventSource('/fs/events' + treeQuery());
  es.addEventListener('changed', e => {
    let d; try { d = JSON.parse(e.data); } catch (_) { return; }
    if (d.resync) return resyncFiles();
    if (d.git !== false) fsWatchGit = true;
    fsWatchSeen.push(...d.paths);
    // A build writes without pause. A timer that only resets never fires.
    if (fsWatchSeen.length > FS_MAX_SEEN) fsWatchSeen = fsWatchSeen.slice(-FS_MAX_SEEN);
    if (!fsWatchSince) fsWatchSince = performance.now();
    clearTimeout(fsWatchTimer);
    const wait = Math.max(0, Math.min(FS_DEBOUNCE, fsWatchSince + FS_MAX_WAIT - performance.now()));
    fsWatchTimer = setTimeout(async () => {
      const all = fsWatchSeen, git = fsWatchGit; fsWatchSeen = []; fsWatchSince = 0; fsWatchGit = false;
      const theirs = notMine(all);
      // Our own save changed no filenames, only what git thinks of one.
      if (theirs.length) await patchTree(theirs).catch(() => {});
      if (git) { noticeGitDisk(); await refreshGitTreeMarks(); }
      if (theirs.some(p => p === lee.path)) { refreshOpenGitMarks(); watchOpenFile(); }
    }, wait);
  });
  // Opened by the desktop shell (Finder, Open With), not by this page: show it without a reload.
  es.addEventListener('opened', e => {
    let d; try { d = JSON.parse(e.data); } catch (_) { return; }
    if (d.path) leeOpenFile(d.path).catch(err => leeFail('open', d.path, err));
  });
  // The keymap file changed on disk: Sanketa, an Undo, a hand edit.
  es.addEventListener('keys', e => {
    let d; try { d = JSON.parse(e.data); } catch (_) { return; }
    const chords = ks => JSON.stringify((ks || []).map(k => [k.action, k.chords]));
    const rebound = chords(lee.keys) !== chords(d.keys);
    loadKeys(d).catch(() => {});
    if (rebound) { remountEditors(); if (!lee.keyNotes.length) status('keys changed on disk and are live', 'ok'); }
  });
  es.onerror = () => { es.close(); if (fsEvents === es) setTimeout(watchFiles, 3000); };
  return es;
}
window.watchFiles = watchFiles;

async function treeGitAction(op) {
  const node = treeSel();
  if (!node || node.classList.contains('lee-root')) return status('select a file or folder first', 'err');
  const directory = node.classList.contains('lee-dir'), name = node.dataset.path.split('/').pop();
  // `git restore --worktree`, so the index is what comes back, not HEAD. Saying HEAD sent people
  // to a version they had already staged past.
  if (op === 'discard' && !await confirmDialog(`discard changes in ${name}`, 'This restores the selected file from the index, losing unstaged changes. It cannot be undone.', 'discard')) return;
  if (op === 'ignore' && !await confirmDialog(`ignore ${name}`, `Add ${name}${directory ? '/' : ''} to this repository's .gitignore.`, 'ignore')) return;
  try {
    const d = await post('/git/tree/action', {op, path: node.dataset.path, directory});
    gitUI.snapshot = d; paintGitPill(d);
    if (op === 'ignore' && d.outcome?.path) await leeOpenFile(d.outcome.path);
    await refreshFileTree(node.dataset.path, false);
  } catch (e) { leeFail('git', op, e); }
}

async function treeBlame() {
  const node = treeSel();
  if (!node || node.classList.contains('lee-dir')) return status('select a file to blame', 'err');
  await leeOpenFile(node.dataset.path); await leeBlame();
}

async function treeDiff() {
  const node = treeSel();
  if (!node || node.classList.contains('lee-dir')) return status('select a file to compare', 'err');
  await leeOpenFile(node.dataset.path); showDiff();
}

async function newEntry(kind) {
  // ⌘N from anywhere: the folder selected in the tree, else the open file's, else the first root.
  const sel = treeSel() || (lee.path && $$('.lee-node').find(n => n.dataset.path === lee.path)) || $('.lee-node.lee-root');
  const parent = sel ? (sel.classList.contains('lee-dir') || sel.classList.contains('lee-root') ? sel.dataset.path
                                                        : sel.dataset.path.replace(/\/[^/]+$/, '')) : '';
  if (!parent) return status('open a folder first', 'err');
  const name = await inputDialog(kind === 'dir' ? 'new folder' : 'new file', 'name', '',
                                 kind === 'dir' ? 'folder name' : 'filename.py');
  if (!name) return;
  const r = await post('/fs/new', {parent, name, kind});
  noteSelfWrite(r.entry.path);
  status('created ' + name, 'ok');
  await refreshFileTree(r.entry.path);
  if (kind === 'file') leeOpenFile(r.entry.path);
}
async function renameEntry() {
  const sel = treeSel(); if (!sel) return status('select a file or folder first');
  const old = sel.dataset.path.split('/').pop();
  const name = await inputDialog('rename', 'name', old);
  if (!name || name === old) return;
  const r = await post('/fs/rename', {path: sel.dataset.path, name});
  noteSelfWrite(sel.dataset.path, r.entry.path);
  await refreshFileTree(r.entry.path);
}
async function deleteEntry() {
  const paths = treePaths(); if (!paths.length) return status('select a file or folder first');
  const sel = treeSel();
  const name = paths.length > 1 ? `${paths.length} items` : paths[0].split('/').pop();
  const folder = paths.some(p => $(`.lee-node[data-path="${p}"]`)?.classList.contains('lee-dir'));
  // Recoverable, and it says so: a delete now moves the file or the whole folder into the trash,
  // and `workspace undo` puts it back where it was.
  const warning = (folder ? 'Folders go too, with everything inside them. ' : '') +
    'Deleted from disk, and recoverable with undo until the trash is cleared.';
  if (lee.filePrefs.confirmDelete !== false && !await confirmDialog('delete ' + name + ' from disk', warning, 'delete')) return;
  const parent = sel?.parentElement?.closest('.lee-node.lee-dir')?.dataset.path;
  const failed = [];
  for (const path of paths) {
    noteSelfWrite(path);
    try { await post('/fs/delete', {path}); } catch (e) { failed.push(path.split('/').pop()); }
  }
  clearTreeMarks();
  await refreshTabStrip();
  await refreshFileTree(parent);
  status(failed.length ? `could not delete ${failed.join(', ')}` : `deleted ${name}`,
         failed.length ? 'err' : 'ok');
}

/* Cut and copy mark what to act on; paste is where. A cut is not a move until the paste, so
   nothing has happened to the tree while the clipboard is full and Escape is enough to abandon it. */
function fileClipboard(cut) {
  const paths = treePaths(); if (!paths.length) return status('select a file or folder first');
  lee.fileClip = {paths, cut};
  $$('.lee-node.cut').forEach(n => n.classList.remove('cut'));
  if (cut) paths.forEach(p => $(`.lee-node[data-path="${p}"]`)?.classList.add('cut'));
  status(`${cut ? 'cut' : 'copied'} ${paths.length > 1 ? paths.length + ' items' : paths[0].split('/').pop()}`, 'ok');
}
const treeDir = n => n?.classList.contains('lee-dir') ? n.dataset.path
                   : n?.parentElement?.closest('.lee-node.lee-dir')?.dataset.path;
async function pasteEntries() {
  const clip = lee.fileClip;
  if (!clip?.paths?.length) return status('nothing on the clipboard');
  const dest = treeDir(treeSel());
  if (!dest) return status('select the folder to paste into', 'err');
  const r = await post(clip.cut ? '/fs/move' : '/fs/copy', {paths: clip.paths, dest});
  (clip.cut ? clip.paths : []).forEach(noteSelfWrite);
  (r.moved || r.created || []).forEach(noteSelfWrite);
  if (clip.cut) { lee.fileClip = null; $$('.lee-node.cut').forEach(n => n.classList.remove('cut')); }
  clearTreeMarks();
  await refreshFileTree(dest);
  const done = (r.moved || r.created || []).length;
  status(r.ok ? `${clip.cut ? 'moved' : 'copied'} ${done} into ${dest.split('/').pop()}`
             : `${done} done, ${r.failed.map(f => f.path.split('/').pop()).join(', ')} refused`,
         r.ok ? 'ok' : 'err');
}
async function duplicateEntries() {
  const paths = treePaths(); if (!paths.length) return status('select a file or folder first');
  const r = await post('/fs/copy', {paths, duplicate: true});
  (r.created || []).forEach(noteSelfWrite);
  clearTreeMarks();
  await refreshFileTree(r.created?.[0]);
  status(r.ok ? `duplicated ${paths.length > 1 ? paths.length + ' items' : paths[0].split('/').pop()}`
             : `${(r.created || []).length} done, ${r.failed.length} refused`, r.ok ? 'ok' : 'err');
}
/* The server closed tabs we did not ask it to close. The strip is index-addressed, so a stale one
   makes the next click land on a different document. */
async function refreshTabStrip() {
  try {
    const r = await fetch('/tab/bar'); if (!r.ok) return;
    const fresh = new DOMParser().parseFromString(await r.text(), 'text/html').querySelector('#tabbar'), bar = $('#tabbar');
    if (!fresh || !bar) return;
    bar.replaceWith(fresh); htmx.process(fresh);
  } catch (_) {}
}
async function removeRoot() {
  const sel = treeSel();
  if (!sel?.classList.contains('lee-root')) return status('select an open project root first', 'err');
  const name = sel.dataset.path.split('/').pop();
  if (!await confirmDialog('remove ' + name + ' from workspace', 'Files stay on disk. Open tabs inside it will close.', 'remove')) return;
  await post('/fs/remove-root', {path: sel.dataset.path});
  await refreshTabStrip();
  await refreshFileTree();
  // The header names the folder the project surfaces are about, and that folder has just gone.
  refreshProjectPills();
  projectChanged();
  status(name + ' removed from the workspace; files were not deleted', 'ok');
}
/* `find` opens the same dialog with the repository filter focused. Browsing and searching are
   the two ways people actually find a checkout, and they want the same confirm button. */
async function findRepo() { return addRoot(true); }

/* One box, the way a shell has one.

   Typing completes folders under what is already typed, Tab takes the completion, and Enter
   opens. Repositories deeper down answer to a bare name, because a directory of checkouts is more
   than one level deep. */
async function addRoot(find = false) {
  const m = modal(`<div class="lee-mhead">open folder<span class="sub">type a path · Tab completes · Enter opens</span></div>
    <input class="lee-input lee-pathinput" id="folderpath" autocomplete="off" spellcheck="false"
      aria-label="folder path" aria-autocomplete="list" aria-controls="folderlist"
      placeholder="~/code/  ·  or the name of a repository below it">
    <div class="lee-modallist lee-folderlist" id="folderlist" role="listbox"></div>
    <div class="lee-mfoot"><button class="lee-btn go" id="folderopen">open this folder</button>
    <button class="lee-btn" id="folderbrowse" hidden>browse…</button>
    <span class="lee-dim" id="folderhint"></span></div>`);
  const input = m.querySelector('#folderpath'), list = m.querySelector('#folderlist');
  const hint = m.querySelector('#folderhint'), openBtn = m.querySelector('#folderopen');
  // In the packaged app the platform's own chooser is the only way to find a folder without
  // knowing its path. In a browser tab there is none. Wired now and shown when the bridge
  // arrives, which is not always by the time this opens.
  const browse = m.querySelector('#folderbrowse');
  browse.onclick = async () => {
    const picked = await nativeFolder();
    if (picked) { m.remove(); openFolder(picked); }
  };
  shellReady().then(ok => { if (ok) browse.hidden = false; });
  let base = '', dirs = [], rows = [], sel = 0, lastDir = null, seq = 0, timer = null;

  const dirOf = v => { const i = v.lastIndexOf('/'); return i < 0 ? '' : v.slice(0, i + 1); };
  const fragOf = v => { const i = v.lastIndexOf('/'); return i < 0 ? v : v.slice(i + 1); };
  const row = (r, i) =>
    `<button class="lee-folderrow${i === sel ? ' sel' : ''}" role="option" aria-selected="${i === sel}" ` +
    `data-path="${esc(r.path)}"><span class="lee-folderglyph">▸</span>${esc(r.name)}` +
    (r.where ? `<span class="lee-dim lee-folderwhere">${esc(r.where)}</span>` : '') + `</button>`;
  const paint = (extra = '') => {
    list.innerHTML = rows.map(row).join('') + extra ||
      '<div class="lee-dim">No folder matches. Enter opens what you typed, if it exists.</div>';
    list.querySelector('.sel')?.scrollIntoView({block: 'nearest'});
    hint.textContent = base ? `in ${base}` : '';
  };
  // Prefix matches first: completing `pe` should offer `personal` before `home/spec`.
  const rank = frag => {
    const f = frag.toLowerCase();
    const starts = dirs.filter(x => x.name.toLowerCase().startsWith(f));
    return starts.concat(dirs.filter(x => !starts.includes(x) && x.name.toLowerCase().includes(f)));
  };
  const repos = async frag => {
    const mine = ++seq;
    try {
      const r = await api(`/git/find?base=${encodeURIComponent(base)}&q=${encodeURIComponent(frag)}`);
      if (mine !== seq) return;                        // a later keystroke already answered
      const found = (r.repos || []).filter(x => !rows.some(n => n.path === x.path));
      if (!found.length) return paint();
      rows = rows.concat(found.map(x => ({name: x.name, path: x.path, where: x.parent})));
      paint();
    } catch (_) { paint(); }
  };
  const draw = async () => {
    const v = input.value, dir = dirOf(v), frag = fragOf(v);
    if (dir !== lastDir) {
      lastDir = dir;
      try {
        const d = await api('/fs/browse?path=' + encodeURIComponent(dir || v));
        base = d.path; dirs = d.dirs || [];
      } catch (_) { dirs = []; base = ''; }
    }
    rows = rank(frag); sel = 0;
    clearTimeout(timer);
    if (frag.length < 2) return paint();
    // The search below walks a tree, so it is debounced: a five-letter name is one search.
    paint(`<div class="lee-searching"><span class="lee-spin"></span>searching ${esc(base)} for repositories…</div>`);
    timer = setTimeout(() => repos(frag), 200);
  };
  const complete = () => {
    const r = rows[sel]; if (!r) return false;
    // The caret is placed, not left where assigning `value` puts it: WebKit puts it at 0.
    input.value = r.path + '/'; input.setSelectionRange(input.value.length, input.value.length);
    draw(); return true;
  };
  const open = async path => {
    const target = path || input.value.trim(); if (!target) return;
    m.remove();
    try {
      await post('/fs/add-root', {path: target});
      // The tree is redrawn before the folder is activated, because activating selects the new
      // root's node and a tree that has not been rebuilt does not have one yet.
      await refreshFileTree(target);
      await activateRoot(target);           // the folder you just opened is the one you mean
    } catch (e) { status(String(e.message || e), e.body?.declined ? '' : 'err'); }
  };
  input.oninput = draw;
  input.onkeydown = e => {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault(); if (!rows.length) return;
      sel = (sel + (e.key === 'ArrowDown' ? 1 : -1) + rows.length) % rows.length; paint();
    } else if (e.key === 'Tab') { e.preventDefault(); complete(); }
    else if (e.key === 'Enter') {
      e.preventDefault();
      const v = input.value.trim(), frag = fragOf(v);
      // A path that names a folder is a folder to open. Anything else is half-typed, so the
      // first Enter completes it and the second opens it.
      if (v && (!frag || dirs.some(x => x.path === v.replace(/\/$/, '')))) return open(v);
      if (!complete()) if (v) open(v);
    } else if (e.key === 'Escape') { e.preventDefault(); m.remove(); }
  };
  list.onclick = e => {
    const r = e.target.closest('.lee-folderrow'); if (!r) return;
    input.value = r.dataset.path + '/'; input.focus();
    input.setSelectionRange(input.value.length, input.value.length); draw();
  };
  openBtn.onclick = () => open();
  input.value = find ? '' : (await api('/fs/browse?path=').catch(() => ({path: ''}))).path + '/';
  input.focus(); input.setSelectionRange(input.value.length, input.value.length);
  await draw();
}

document.addEventListener('keydown', e => {
  const tab = e.target.closest?.('.lee-tab'); if (!tab) return;
  const tabs = $$('.lee-tab'), at = tabs.indexOf(tab);
  if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
    e.preventDefault(); const step = e.key === 'ArrowRight' ? 1 : -1;
    const next = tabs[(at + step + tabs.length) % tabs.length]; next?.focus(); next?.click();
  } else if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); tab.click(); }
  else if (e.key === 'Delete' || e.key === 'Backspace') { e.preventDefault(); tab.querySelector('.lee-tab-x')?.click(); }
});

document.addEventListener('click', (e) => {
  const n = e.target.closest('.lee-node');
  if (n && (e.metaKey || e.ctrlKey)) {
    setScope('files');
    markTreeNode(n, !n.classList.contains('marked'));
    return selectTreeNode(n, true);
  }
  if (n && e.shiftKey) { setScope('files'); markTreeRange(n); return; }
  if (n) { selectTreeNode(n); setScope('files'); }
  if (e.target.closest('.lee-vars')) setScope('vars');
});
document.addEventListener('toggle', e => {
  if (e.target.matches?.('.lee-dir')) e.target.setAttribute('aria-expanded', e.target.open ? 'true' : 'false');
}, true);

// Middle-click closes a tab. Delegated because both strips are re-rendered whole, the document
// strip by htmx and the terminal strip by `paintTermTabs`.
document.addEventListener('auxclick', e => {
  if (e.button !== 1) return;
  const term = e.target.closest?.('.lee-termtab');
  if (term) { e.preventDefault(); return closeTerm(term.dataset.term); }
  const tab = e.target.closest?.('.lee-tab');
  if (!tab) return;
  e.preventDefault();                     // some platforms paste or autoscroll on button 1
  if (tab.dataset.gitDiff) return closeGitDiffTab(tab.dataset.gitDiff);
  closeTab(+tab.dataset.i);
});

// Drag to reorder. The drop is posted rather than kept in the browser, so it survives a reload
// like the tabs do.
document.addEventListener('dragstart', e => {
  const tab = e.target.closest?.('.lee-tab');
  if (!tab || tab.dataset.gitDiff) return;
  lee.dragTab = +tab.dataset.i;
  e.dataTransfer.effectAllowed = 'move';
  try { e.dataTransfer.setData('text/plain', tab.dataset.i); } catch (_) {}
});
document.addEventListener('dragover', e => {
  if (lee.dragTab == null) return;
  const tab = e.target.closest?.('.lee-tab');
  if (!tab || tab.dataset.gitDiff) return;
  e.preventDefault(); e.dataTransfer.dropEffect = 'move';
  $$('.lee-tab').forEach(t => t.classList.toggle('drop', t === tab));
});
document.addEventListener('drop', e => {
  if (lee.dragTab == null) return;
  const tab = e.target.closest?.('.lee-tab');
  $$('.lee-tab').forEach(t => t.classList.remove('drop'));
  if (tab && !tab.dataset.gitDiff) { e.preventDefault(); moveTab(lee.dragTab, +tab.dataset.i); }
  lee.dragTab = null;
});
document.addEventListener('dragend', () => {
  lee.dragTab = null; $$('.lee-tab').forEach(t => t.classList.remove('drop'));
});

/* Naming a file for somebody else. Relative is against the open folder holding it, so it is what
   a colleague pastes into the same repository. Absolute is what a shell here needs. Only the
   server knows which folder a path is under. */
async function copyFilePath(which) {
  const target = clipTarget();
  if (!target) return status('select a file, a folder or a tab first', 'err');
  let d;
  try { d = await api('/fs/paths?path=' + encodeURIComponent(target)); }
  catch (e) { return status(String(e.message || e), 'err'); }
  const text = which === 'relative' ? (d.relative || d.absolute) : d.absolute;
  if (!text) return status('that path has no name to copy', 'err');
  try { await navigator.clipboard.writeText(text); }
  catch (_) { return status('clipboard access failed', 'err'); }
  // A path under no open folder has no relative form, and silently copying the absolute one
  // would read as the button being wrong rather than the file being outside.
  status(which === 'relative' && !d.relative ? `outside the open folders · copied ${text}`
                                             : `copied ${text}`, 'ok');
}
window.copyFilePath = copyFilePath;

document.addEventListener('contextmenu', e => {
  // Shift+right-click remains the browser's native copy/paste/spellcheck menu.
  if (e.shiftKey) return;
  const node = e.target.closest('.lee-node');
  if (node) {
    e.preventDefault(); $$('.lee-node').forEach(x => x.classList.remove('sel')); node.classList.add('sel');
    const surface = node.classList.contains('lee-root') ? 'root' : node.classList.contains('lee-dir') ? 'folder' : 'file';
    setScope('files'); openMenu(surface, e.clientX, e.clientY); return;
  }
  if (e.target.closest('#filetree')) {
    e.preventDefault(); setScope('files'); openMenu('files', e.clientX, e.clientY); return;
  }
  const variable = e.target.closest('.lee-vrow');
  if (variable) {
    e.preventDefault(); selectVar(variable); setScope('vars'); openMenu('variable', e.clientX, e.clientY); return;
  }
  const cell = e.target.closest('.lee-cell');
  if (cell) {
    e.preventDefault(); selectCell(+cell.dataset.i); setScope('editor'); openMenu('cell', e.clientX, e.clientY); return;
  }
  const tab = e.target.closest('.lee-tab');
  if (tab) {
    e.preventDefault(); lee.menuTab = +tab.dataset.i;
    if (!tab.classList.contains('active')) htmxPost('/tab/select?i=' + tab.dataset.i);
    openMenu('tab', e.clientX, e.clientY); return;
  }
  if (e.target.closest('#kpill')) { e.preventDefault(); openMenu('kernel', e.clientX, e.clientY); return; }
  if (e.target.closest('.lee-exec')) { e.preventDefault(); setScope('exec'); openMenu('exec', e.clientX, e.clientY); return; }
  if (e.target.closest('#editor')) { e.preventDefault(); setScope('editor'); openMenu('editor', e.clientX, e.clientY); }
});

/* Staging a folder is `git add`, which honours .gitignore -- and a folder you have just made does
   not have one. This writes the rules its project kinds need before it stages, so the build output
   of a language you are meeting for the first time never has to be recognised file by file. */
async function treeAddFolder() {
  const n = treeSel() || $('.lee-node.lee-dir');
  const path = n?.dataset.path;
  if (!path) return status('select a folder in the tree first', 'err');
  if (!n.classList.contains('lee-dir')) return status('that is a file; pick its folder', 'err');
  try {
    const d = await post('/git/tree/prepare', {path});
    const p = d.prepared || {};
    const kinds = (p.kinds || []).join(' + ');
    status(p.added?.length ? `staged ${path.split('/').pop()}, and taught .gitignore about ${kinds}`
                           : `staged ${path.split('/').pop()}`, 'ok');
    gitUI.snapshot = d; paintGitPill(d);
    await refreshFileTree(path, false);
  } catch (e) { leeFail('git', 'add folder', e); }
}
/* A Word, PowerPoint or Excel file, read-only. On macOS the tab shows Quick Look's own preview in a
   frame that runs no script. The simple view is the server's cleaned HTML, with the sheet buttons and
   the row pager. Nothing here writes the file. */
const officeQ = (path, more = '') => '?path=' + encodeURIComponent(path) + more;
const OFFICE_VIEW = 'lee-office-view';   // 'simple' once a person picks the simple view
async function mountOffice(host, st) {
  host.innerHTML =
    `<div class="lee-doc lee-office"><div class="lee-doc-head"><span>${esc(compactPath(st.path))}</span>` +
    `<span class="lee-dim">read-only</span><span class="lee-spacer"></span>` +
    `<button class="lee-btn" data-office-view hidden></button>` +
    `<button class="lee-btn" data-office-open>open in default app</button>` +
    `<button class="lee-btn" data-office-copy>copy as text</button></div>` +
    `<div class="lee-doc-body lee-office-body"><div class="lee-dim">Loading…</div></div></div>`;
  const body = $('.lee-office-body', host), path = st.path, view = $('[data-office-view]', host);
  $('[data-office-open]', host).onclick = () => post('/office/open' + officeQ(path))
    .then(() => status('opened in the default app', 'ok')).catch(e => status(String(e.message || e), 'err'));
  $('[data-office-copy]', host).onclick = async () => {
    try { await navigator.clipboard.writeText((await api('/office/text' + officeQ(path))).text); status('document text copied', 'ok'); }
    catch (e) { status(String(e.message || e), 'err'); }
  };
  const show = async faithful => {
    view.hidden = true; body.className = 'lee-doc-body lee-office-body'; body.innerHTML = '<div class="lee-dim">Loading…</div>';
    let ql = null;
    if (faithful) {
      try { ql = await api('/office/quicklook' + officeQ(path)); }
      catch (e) {
        if (e.body?.kind === 'no-quicklook') return officeSimple(body, path);
        status(`${String(e.message || e)}. The simple view is shown.`, 'err');
      }
    }
    if (ql) officeQuickLook(body, ql); else await officeSimple(body, path);
    view.textContent = ql ? 'simple view' : 'Quick Look view'; view.hidden = false;
    view.onclick = () => { localStorage.setItem(OFFICE_VIEW, ql ? 'simple' : 'quicklook'); show(!ql); };
  };
  await show(localStorage.getItem(OFFICE_VIEW) !== 'simple');
}
//: Quick Look's pages in a frame with no script and no links; a workbook gets one button for each sheet.
function officeQuickLook(body, ql) {
  body.className = 'lee-doc-body lee-office-ql';
  const src = pg => `/office/ql/${encodeURIComponent(ql.token)}/${encodeURIComponent(pg.src)}`;
  const note = document.createElement('div'), frame = document.createElement('iframe');
  note.className = 'lee-dim lee-office-clip';
  note.textContent = 'Quick Look shows only the first 4096 rows of a sheet. The simple view shows all rows.';
  frame.className = 'lee-office-frame'; frame.setAttribute('sandbox', 'allow-same-origin'); frame.title = 'Quick Look preview';
  const pick = i => {
    frame.src = src(ql.pages[i]); note.hidden = !ql.pages[i].clipped;
    for (const [j, x] of $$('[data-sheet-tab]', body).entries()) x.setAttribute('aria-selected', String(j === i));
  };
  body.replaceChildren();
  if (ql.pages.length > 1) {
    const bar = document.createElement('div');
    bar.className = 'lee-sheet-tabs'; bar.setAttribute('role', 'tablist');
    ql.pages.forEach((pg, i) => {
      const b = document.createElement('button');
      b.className = 'lee-btn'; b.setAttribute('role', 'tab'); b.dataset.sheetTab = i;
      b.textContent = pg.name || `Sheet ${i + 1}`; b.onclick = () => pick(i);
      bar.append(b);
    });
    body.append(bar);
  }
  // Quick Look draws slides at their size in points; scale them to the tab's width, never above it.
  const fit = () => {
    const d = frame.contentDocument, s = d?.querySelector('div.slide');
    if (s) d.body.style.zoom = String(Math.min(1, (frame.clientWidth - 32) / (s.offsetWidth + 16)));
  };
  frame.onload = fit; new ResizeObserver(fit).observe(frame);
  body.append(note, frame); pick(0);
}
async function officeSimple(body, path) {
  try { body.innerHTML = (await api('/office/view' + officeQ(path))).html; }
  catch (e) { body.innerHTML = `<div class="lee-err">${esc(String(e.message || e))}</div>`; return; }
  // A link in a document never replaces the IDE page.
  for (const a of $$('a[href]', body)) { a.target = '_blank'; a.rel = 'noopener noreferrer'; }
  officeSheets(body, path);
}
function officeSheets(body, path) {
  const sheets = $$('.lee-sheet', body);
  if (!sheets.length) return;
  const bar = document.createElement('div');
  bar.className = 'lee-sheet-tabs'; bar.setAttribute('role', 'tablist');
  sheets.forEach((s, i) => {
    const b = document.createElement('button');
    b.className = 'lee-btn'; b.setAttribute('role', 'tab'); b.dataset.sheetTab = i;
    b.textContent = $('.lee-sheet-name', s)?.textContent || `Sheet ${i + 1}`;
    b.onclick = () => { sheets.forEach((x, j) => x.hidden = j !== i); $$('[data-sheet-tab]', bar).forEach((x, j) => x.setAttribute('aria-selected', String(j === i))); };
    bar.append(b);
  });
  body.prepend(bar);
  bar.firstChild.setAttribute('aria-selected', 'true');
  for (const more of $$('.lee-sheet-more', body)) {
    const b = document.createElement('button');
    b.className = 'lee-btn'; b.textContent = 'show more rows';
    b.onclick = async () => {
      const s = more.closest('.lee-sheet'); b.disabled = true;
      try {
        const d = await api('/office/rows' + officeQ(path, `&sheet=${s.dataset.sheet}&start=${more.dataset.next}`));
        $('.lee-sheet-table tbody', s).insertAdjacentHTML('beforeend', d.html);
        more.dataset.next = String(+more.dataset.next + d.count);
        $('span', more).textContent = `Showing the first ${more.dataset.next} rows.`;
        if (!d.more) more.remove(); else b.disabled = false;
      } catch (e) { b.disabled = false; status(String(e.message || e), 'err'); }
    };
    more.append(b);
  }
}
function initSplits() {
  const savedLeft = localStorage.getItem('lee-left-view');
  // Every panel is saved on switch, so every panel is restorable.
  leeLeft(['git', 'symbols', 'workflows', 'releases', 'deploys', 'drive'].includes(savedLeft) ? savedLeft : 'files');
  // Read before the views: `leeDock` opens the bottom pane to show its tab and persists that,
  // which would erase a pane the last session had minimised.
  const closed = ['left', 'right', 'bottom'].filter(p => localStorage.getItem('lee-pane-' + p) === 'hidden');
  const savedRight = localStorage.getItem('lee-right-view');
  if (['agent', 'vars', 'memory', 'learn'].includes(savedRight)) leeRight(savedRight);
  const savedDock = localStorage.getItem('lee-dock-view');
  if (['exec', 'term', 'logs'].includes(savedDock)) leeDock(savedDock);
  for (const pane of closed) leePane(pane, false);
  // The pin buttons are rendered pinned; a saved unpin has to reach them before the first click.
  for (const pane of ['left', 'right']) leeSyncPin(pane);
  if (matchMedia('(max-width: 1100px)').matches) {
    leePane('left', false); leePane('right', false);
  }
  $$('.lee-split').forEach(sp => {
    sp.onpointerdown = (e) => {
      e.preventDefault(); sp.classList.add('drag'); sp.setPointerCapture(e.pointerId);
      const side = sp.dataset.split;
      // `localStorage` is synchronous and disk-backed, and a drag fires this at pointer rate. The
      // width a person let go at is the only one worth keeping, so it is written once, at the end.
      const move = (ev) => {
        const w = side === 'left' ? ev.clientX : window.innerWidth - ev.clientX;
        const v = Math.max(140, Math.min(window.innerWidth - 300, w));
        document.documentElement.style.setProperty(`--lee-${side}-w`, v + 'px');
      };
      const up = () => {
        sp.classList.remove('drag'); sp.onpointermove = null; sp.onpointerup = null;
        const now = getComputedStyle(document.documentElement).getPropertyValue(`--lee-${side}-w`).trim();
        if (now) localStorage.setItem(`lee-${side}-w`, now);
      };
      sp.onpointermove = move; sp.onpointerup = up;
    };
  });
  initEditorSplitter();
  const centreHeight = () => $('.lee-centre')?.clientHeight || window.innerHeight;
  // The dock can occupy most of the workspace. The editor keeps its own 140px floor.
  const limit = () => Math.min(900, Math.max(110, centreHeight() - 240));
  const dockSplit = $('.lee-dock-split');
  if (dockSplit) dockSplit.onpointerdown = (e) => {
    e.preventDefault(); dockSplit.classList.add('drag'); dockSplit.setPointerCapture(e.pointerId);
    const bottom = $('#bottomdock')?.getBoundingClientRect().bottom || window.innerHeight;
    const move = (ev) => {
      const v = Math.max(110, Math.min(limit(), bottom - ev.clientY));
      document.documentElement.style.setProperty('--lee-dock-h', v + 'px');
      requestAnimationFrame(() => lee.term?.refit());
    };
    dockSplit.onpointermove = move;
    dockSplit.onpointerup = () => {
      dockSplit.classList.remove('drag'); dockSplit.onpointermove = null;
      const now = getComputedStyle(document.documentElement).getPropertyValue('--lee-dock-h').trim();
      if (!now) return;
      localStorage.setItem('lee-dock-h', now);
      localStorage.setItem('lee-agent-h', now);   // the previous name for this preference
    };
  };
  ['left-w', 'right-w'].forEach(k => {
    const v = localStorage.getItem('lee-' + k);
    if (v) document.documentElement.style.setProperty('--lee-' + k, v);
  });
  // Legacy names remain readable so an upgrade preserves the user's lower-panel height.
  const legacyPanelFloors = [['exec-h', 80], ['agent-h', 110]];
  void legacyPanelFloors;
  for (const [k, floor] of [['dock-h', 110]]) {
    const raw = parseFloat(localStorage.getItem('lee-' + k) || localStorage.getItem('lee-agent-h'));
    if (!Number.isFinite(raw)) continue;
    const value = Math.max(floor, Math.min(limit(), raw));
    document.documentElement.style.setProperty('--lee-' + k, value + 'px');
    localStorage.setItem('lee-' + k, value + 'px');
  }
  // The retired boolean is read once and rewritten as the slot and mode it meant.
  if (localStorage.getItem('lee-agent-expanded') === '1' && !localStorage.getItem('lee-expand'))
    localStorage.setItem('lee-expand', 'right:wide');
  localStorage.removeItem('lee-agent-expanded');
  leeSyncExpand();
}

const SPLIT_SIZE = 'lee-editor-split-size';   //: the first pane's share in percent; its own key, as each side page rewrites `lee-editor-split`
//: The share of the first pane of the editor split, clamped to 20-80; `keep` saves it for the next split and the next session.
function setSplitSize(v, keep = false) {
  const stage = $('#editorstage'), bar = $('.lee-editor-splitter'); if (!stage || !bar) return;
  v = Math.round(Math.max(20, Math.min(80, Number(v) || 50)));
  stage.style.setProperty('--lee-split', v + '%'); bar.setAttribute('aria-valuenow', v);
  bar.setAttribute('aria-orientation', stage.classList.contains('split-horizontal') ? 'horizontal' : 'vertical');
  if (keep) localStorage.setItem(SPLIT_SIZE, v);
}
const splitSize = () => parseFloat($('#editorstage')?.style.getPropertyValue('--lee-split')) || 50;
function initEditorSplitter() {
  const stage = $('#editorstage'), bar = $('.lee-editor-splitter'); if (!stage || !bar) return;
  Object.assign(bar, {tabIndex: 0, title: 'Drag, or use the arrow keys, to resize the split'});
  bar.setAttribute('role', 'separator'); bar.setAttribute('aria-label', 'Resize the split'); bar.setAttribute('aria-valuemin', 20); bar.setAttribute('aria-valuemax', 80);
  const across = () => stage.classList.contains('split-horizontal');
  bar.onpointerdown = e => {
    e.preventDefault(); bar.classList.add('drag'); stage.classList.add('split-dragging'); bar.setPointerCapture(e.pointerId);
    const r = stage.getBoundingClientRect();
    bar.onpointermove = ev => setSplitSize(across() ? (ev.clientY - r.top) / r.height * 100 : (ev.clientX - r.left) / r.width * 100);
    // a cancelled drag (a system gesture, a context menu) ends as a finished one, or the frames stay deaf to the pointer
    bar.onpointerup = bar.onpointercancel = bar.onlostpointercapture = () => {
      bar.classList.remove('drag'); stage.classList.remove('split-dragging');
      bar.onpointermove = bar.onpointerup = bar.onpointercancel = bar.onlostpointercapture = null; setSplitSize(splitSize(), true);
    };
  };
  bar.onkeydown = e => {
    const step = (across() ? {ArrowUp: -5, ArrowDown: 5} : {ArrowLeft: -5, ArrowRight: 5})[e.key];
    if (!step) return;
    e.preventDefault(); e.stopPropagation(); setSplitSize(splitSize() + step, true);
  };
}

async function refreshKernelPill() {
  try {
    const d = await api('/kernel/info');
    const pill = $('#kpill'); if (!pill) return;
    pill.className = 'lee-pill ' + (d.api_error || d.boot_error || d.notice ? 'lee-pill-warn' : d.alive ? 'lee-pill-on' : 'lee-pill-err');
    pill.textContent = (d.api_error || d.notice ? '⚠ ' : d.alive ? '⏺ ' : '○ ') + (d.key || '').split('/').pop();
    pill.title = (d.base || 'no inspector') + (d.cwd ? ' · cwd ' + d.cwd : '') +
                 (d.boot_error ? ' · ' + d.boot_error : '') + (d.api_error ? ' · inspector: ' + d.api_error : '') +
                 (d.notice ? ' · ' + d.notice.message : '');
    if (d.evicted) status(`closed ${d.evicted.name} runtime to make room; its in-memory variables were cleared`);
    paintVenvNotice(d.no_venv);
    (d.tabs || []).forEach((state, i) => {
      const tab = $(`.lee-tab[data-i="${i}"]`); if (!tab) return;
      let run = tab.querySelector('.lee-tab-run');
      if (state.running && !run) { run = document.createElement('span'); run.className = 'lee-tab-run'; tab.prepend(run); }
      if (run) { run.hidden = !state.running; run.title = `${state.running} cell(s) running`; }
      const wasDirty = tab.classList.contains('dirty');
      tab.classList.toggle('dirty', !!state.dirty);
      if (state.dirty && !wasDirty) setTabSaveState(tab, 'pending');
      else if (!state.dirty && wasDirty && tab.dataset.saveState !== 'error') setTabSaveState(tab, 'saved');
    });
  } catch (e) {}
}

/* A project with Python in it and nowhere to run it says so above the editor until it is answered.
   "Not now" holds for this window's session; the server, not the page, decides when it is answered. */
function paintVenvNotice(v) {
  let bar = $('#venvnotice');
  if (!v || lee.observer || sessionStorage.getItem('lee-venv-later:' + v.root)) return bar?.remove();
  if (bar?.dataset.root === v.root) return;
  bar?.remove();
  bar = document.createElement('div');
  Object.assign(bar, {id: 'venvnotice', className: 'lee-venv-notice', role: 'status'});
  bar.dataset.root = v.root;
  bar.innerHTML = `<span>No Python environment for ${esc(v.name)}.</span>` +
    `<button class="lee-btn go" data-venv="setup">Set up .venv</button>` +
    `<button class="lee-btn" data-venv="pick">Choose interpreter…</button>` +
    `<button class="lee-btn" data-venv="later">Not now</button>`;
  $('#editorstage')?.before(bar);
  bar.addEventListener('click', async e => {
    const act = e.target.closest('[data-venv]')?.dataset.venv;
    if (act === 'later') { sessionStorage.setItem('lee-venv-later:' + v.root, '1'); bar.remove(); }
    else if (act === 'pick') { if (await pickKernel()) refreshKernelPill(); }
    else if (act === 'setup') {
      bar.querySelectorAll('button').forEach(b => b.disabled = true);
      bar.classList.add('busy'); bar.firstChild.textContent = `Setting up .venv for ${v.name}…`;
      if (!await setUpVenv(v.root, v.name)) { bar.remove(); refreshKernelPill(); }
    }
  });
}

async function checkProjectRuntime() {
  if (lee.observer) return;
  let d;
  try { d = await api('/runtime/info'); } catch (_) { return; }
  /* A folder with no environment gets the notice above the editor, from `refreshKernelPill`, and
     never a venv it did not ask for. */
  if ((!d.needs_support && !d.needs_upgrade && !d.needs_inspector) || sessionStorage.getItem('lee-runtime-asked:' + d.root)) return;
  sessionStorage.setItem('lee-runtime-asked:' + d.root, '1');
  /* Two separate lacks, one dialog: the runtime cannot run notebook code without the launchers,
     and the variables panel cannot read the namespace without what dhrishti imports. A folder
     missing both should be asked once. */
  const pkgs = (d.inspector_packages || []).map(p => `<code>${esc(p)}</code>`).join(' and ');
  const wants = [d.needs_support ? '<code>ipykernel</code> and <code>ipymini</code> to run notebook code' : '',
                 d.needs_upgrade && !d.needs_support ? `<code>ipykernel</code> 7.4 or later (${esc(d.notice.message)})` : '',
                 d.needs_inspector ? `${pkgs} to read live variables` : ''].filter(Boolean);
  const m = modal(`<div class="lee-mhead">enable project runtime<span class="sub">${esc(d.python)}</span></div>` +
    `<div class="lee-dialogcopy">Leela found this folder’s environment, but it needs ` +
    `${wants.join(', and ')}. ` +
    `Leela installs them into this project environment with uv; the IDE remains separate.</div>` +
    `<div class="lee-mfoot"><button class="lee-btn go" id="runtimeenable">install kernel support</button>` +
    `<button class="lee-btn" id="runtimelater">not now</button></div>`);
  m.querySelector('#runtimeenable').onclick = async () => {
    m.querySelector('#runtimeenable').disabled = true; status('installing project kernel support…');
    try {
      if (d.needs_support || d.needs_upgrade) await post('/runtime/support', {python: d.python});
      if (d.needs_inspector) await post('/runtime/inspector', {python: d.python});
      m.remove();
      status('project runtime ready', 'ok');
      refreshKernelPill(); if (window.leeVars) leeVars();
    }
    catch (e) { status(String(e.message || e), 'err'); m.querySelector('#runtimeenable').disabled = false; }
  };
  m.querySelector('#runtimelater').onclick = () => m.remove();
}

/* CodeMirror measures its width once and caches it, and nothing was telling it when that width
   changed. Toggling a pane, unpinning one so it auto-closes, opening a split, switching the
   markdown view or resizing the window all move the editor's right edge without a keystroke, so
   the cached measurement outlived the layout.

   Visible as a vertical band cutting through the text: the overview stripe is pinned to the
   *editor's* right edge, so it stays where the edge used to be while the text runs on past it.
   Intermittent only because it takes a resize that happens to miss a re-measure.

   `requestMeasure` is plain EditorView API, so no new `LeeCM` export and no vendored rebuild. */
/* An editor skipped by the sweep above still holds the width the pane used to have, which is the
   band cutting through the text this whole observer exists to prevent. It is measured the moment it
   is scrolled to instead, so the cost is paid for the editors a person actually looks at. */
function measureWhenSeen(views) {
  if (!views.length || !('IntersectionObserver' in window)) return;
  const io = new IntersectionObserver(entries => {
    for (const e of entries) if (e.isIntersecting) {
      io.unobserve(e.target);
      try { e.target._leeMeasure?.requestMeasure(); } catch (_) { /* torn down while off screen */ }
    }
  }, {rootMargin: '200px 0px'});
  for (const v of views) { try { v.dom._leeMeasure = v; io.observe(v.dom); } catch (_) {} }
}

function observeEditorWidth() {
  if (!('ResizeObserver' in window)) return;
  let frame = 0;
  const remeasure = () => {
    cancelAnimationFrame(frame);
    // Coalesced: a drag on the splitter fires this per frame, and each measure is a layout read.
    //
    // Spread, because a notebook that has been scrolled through holds 156 editors and measuring all
    // of them lands in one frame: 128ms in the engine the packaged app runs, which is what opening
    // the agent pane felt like. A slice per frame costs the same total and blocks nothing.
    const views = [...lee.editors.values(), lee.gitMergeView?.a, lee.gitMergeView?.b].filter(Boolean);
    /* A measure is only worth paying for on an editor somebody can see. A notebook scrolled end to
       end holds a view per cell and re-measured every one of them on every splitter drag; the ones
       off screen are marked instead and measured when they scroll back in, which is what
       `observeNotebookCells` already does for building them. */
    const tall = window.innerHeight || 900;
    const onScreen = v => {
      try { const r = v.dom.getBoundingClientRect(); return r.bottom > -tall && r.top < tall * 2; }
      catch (_) { return false; }
    };
    const later = [];
    const slice = () => {
      for (const v of views.splice(0, 12)) {
        try { onScreen(v) ? v.requestMeasure() : later.push(v); } catch (_) { /* torn down */ }
      }
      if (views.length) frame = requestAnimationFrame(slice);
      else measureWhenSeen(later.splice(0));
    };
    frame = requestAnimationFrame(slice);
  };
  const observer = new ResizeObserver(remeasure);
  for (const sel of ['#editor', '#shell', '#bottomdock']) { const el = $(sel); if (el) observer.observe(el); }
}

/* One step of boot, which costs itself and nothing after it when it fails.

   `boot` was a single sequence of awaits, so one throw anywhere in it took every step below with
   it: the branch and kernel pills kept the text the page was rendered with, the file watcher and
   the polls never started, and nothing said why. */
async function bootStep(name, fn) {
  try { return await fn(); }
  catch (e) { console.error('boot: ' + name, e); status(`${name} did not start: ${e.message || e}`, 'err'); }
}

/* ------------------------------------------------------------------ boot */
async function boot() {
  await bootStep('settings', () => Promise.all([loadKeys(), loadSettings()]));
  // Model discovery can probe CLIs and registries; it must not hold the editor's first paint.
  loadAgentModels().catch(e => status(String(e.message || e), 'err'));
  refreshAgentThreads().catch(e => status(String(e.message || e), 'err'));
  bootStep('panes', initSplits);
  bootStep('click bindings', bindModClick);
  bootStep('exec strip', mountExec);
  bootStep('agent composer', initAgentComposer);
  // The agent pane is client-owned, so a reload starts it blank; the turns are on disk.
  bootStep('agent pane', rehydrateAgentLive);
  // `/?cell=N`: a hand-off from abhyasa (`/learn`) opens the notebook at that cell; the address drops it, so a reload keeps the place.
  const handCell = new URLSearchParams(location.search).get('cell');
  if (handCell !== null && /^\d{1,5}$/.test(handCell)) { lee.pendingLocation = {cellIndex: +handCell, line: 1}; history.replaceState(null, '', location.pathname); }
  await bootStep('editor', mountTab);
  bootStep('tab strip', layoutTabs);
  bootStep('header layout', () => new ResizeObserver(layoutTabs).observe($('#header')));
  bootStep('editor width', observeEditorWidth);
  bootStep('project runtime', checkProjectRuntime);
  bootStep('variables', leeVars);
  bootStep('lesson reviews', refreshLessonDue);
  setInterval(whenVisible(refreshLessonDue), 600000);
  setInterval(whenVisible(leeVars), 2500);   // the kernel's own inspector is the source of truth
  setInterval(watchOpenFile, 10000);   // a backstop: /fs/events is what actually reports a write
  bootStep('approvals', approvalLoop);                       // catches Rishi approvals raised outside an agent SSE stream
  bootStep('theme', () => applyTheme(readTheme()));   // also rewrites a pre-family value into `family:mode`
  // after the theme, so a theme set at boot is not a look move; a reload of the presenting tab comes back from the server's state
  bootStep('presentation', presentResume);
  // The first paint is server-rendered, so the welcome screen is already on the page when
  // Leela opens on no folder; only its recent list needs filling in.
  if ($('#leerecent')) bootStep('recent folders', paintRecent);
  // Beside it, and only in a packaged app with nothing set up: `/agent/setup` decides, not this.
  if ($('#leesetup')) bootStep('setup pane', leeSetupPane);
  // A network check, so it waits until the page is at work; it fails silent.
  setTimeout(() => leeUpdateNotice().catch(() => {}), 5000);
  setInterval(() => leeUpdateNotice().catch(() => {}), 3600e3);
  // The first paint is server-rendered without the preference, so it is only wrong when set.
  bootStep('file tree', paintHiddenBtn); if (treeHidden()) refreshFileTree(undefined, false).catch(() => {});
  /* The agent's log is one append-only file and grows without bound; reading it the first time
     costs seconds on a large one, and it is cached after that. Paying it here, once the page is
     interactive, means the first click on History does not. */
  // `typeof`, because a bare reference to a global that does not exist is a ReferenceError, not a
  // falsy value. WebKit has never shipped `requestIdleCallback`, so this line threw in the packaged
  // app and took every step below it: both pills, the polls, the run log and the file watcher.
  typeof requestIdleCallback === 'function' ? requestIdleCallback(warmAgentHistory, {timeout: 4000})
                                            : setTimeout(warmAgentHistory, 2000);
  /* 286kb, fetched on the first terminal action with the person waiting on it. Fetching it while
     nothing is waiting spends the same time where nobody is watching. `requestIdleCallback` again:
     WebKit, which is the packaged app, has never shipped it. */
  const warmTerm = () => loadTermBundle().catch(() => {});
  typeof requestIdleCallback === 'function' ? requestIdleCallback(warmTerm, {timeout: 8000})
                                            : setTimeout(warmTerm, 3000);
  bootStep('project pills', refreshProjectPills);
  setInterval(whenVisible(refreshKernelPill), 5000);
  // The pills change only when a root or the cwd does, and every one of those already calls
  // `refreshProjectPills`. Polling them was 24 requests a minute saying nothing.
  bootStep('run log', runLogLoop);
  bootStep('file watcher', watchFiles);
  bootStep('file tree marks', () => { paintTreeGit(); });
  status('ready', 'ok');
}

// A window nobody is looking at asks for nothing.
const whenVisible = fn => () => { if (!document.hidden) fn(); };

document.addEventListener('DOMContentLoaded', boot);

document.addEventListener('htmx:beforeRequest', e => {
  if (/^\/tab\/(select|close)\b/.test(e.detail.pathInfo?.requestPath || '')) dropTabReads();
});

// The pills describe the folder the active tab is in, so a switch inside one folder has nothing new to say.
let pillsFolder = null;
function refreshPillsForTab() {
  const folder = ($('.lee-tab.active')?.title || '').replace(/\/[^/]*$/, '');
  if (folder === pillsFolder) return;
  pillsFolder = folder; refreshProjectPills();
}

document.addEventListener('htmx:afterSwap', (e) => {
  const id = e.target.id || '';
  // A tab change swaps only the tab bar; re-mount the editor for whatever is now active.
  if (id === 'tabbar') { mountTab().then(leeVars); refreshPillsForTab(); requestAnimationFrame(layoutTabs); }
  // Adding a folder rebuilds the whole shell, so everything the client owns is remounted.
  else if (id === 'shell') { paintTreeGit(); lee.editors.clear(); loadAgentModels(); initSplits(); mountExec(); initAgentComposer(); rehydrateAgentLive(); mountTab().then(leeVars); refreshProjectPills(); refreshLessonDue(); requestAnimationFrame(layoutTabs); }
});
function refactorRows(files, selected) {
  return files.map((file, i) => `<label class="lee-mrow"><input type="checkbox" data-refactor-path="${esc(file.path)}"${selected.has(file.path) ? ' checked' : ''}>` +
    `<strong>${esc(compactPath(file.path))}</strong><span class="sub">${file.edits} replacement${file.edits === 1 ? '' : 's'}</span></label>`).join('');
}

async function replaceWorkspace() {
  const m = modal(`<div class="lee-mhead">Replace in workspace<span class="sub">preview before changing files</span></div>` +
    `<label>Find<input class="lee-input" data-refactor-find autofocus></label>` +
    `<label>Replace<input class="lee-input" data-refactor-replace></label>` +
    `<label><input type="checkbox" data-refactor-regex> regular expression</label>` +
    `<label><input type="checkbox" data-refactor-case> match case</label>` +
    `<label><input type="checkbox" data-refactor-word> whole word</label>` +
    `<div class="lee-mfoot"><button class="lee-btn go" data-refactor-preview>Preview</button><button class="lee-btn" data-refactor-cancel>Cancel</button></div>`);
  const find = $('[data-refactor-find]', m), replace = $('[data-refactor-replace]', m);
  $('[data-refactor-cancel]', m).onclick = () => m.remove();
  $('[data-refactor-preview]', m).onclick = async () => {
    const button = $('[data-refactor-preview]', m); button.disabled = true;
    try {
      const data = await post('/replace/preview', {find: find.value, replace: replace.value,
        regex: $('[data-refactor-regex]', m).checked, case: $('[data-refactor-case]', m).checked,
        word: $('[data-refactor-word]', m).checked});
      if (!data.summary.files) return status('no matches in editable workspace files', 'err');
      const selected = new Set(data.files.map(x => x.path));
      m.querySelector('.lee-modalbox').innerHTML = `<div class="lee-mhead">Replace preview<span class="sub">${data.summary.edits} replacements in ${data.summary.files} files${data.summary.partial ? `, in the first ${data.summary.searched} files only: the folder has more` : ''}</span></div>` +
        `<div class="lee-modallist" data-refactor-files>${refactorRows(data.files, selected)}</div>` +
        `<div class="lee-mfoot"><button class="lee-btn go" data-refactor-apply>Apply</button><button class="lee-btn" data-refactor-cancel>Cancel</button></div>`;
      $('[data-refactor-cancel]', m).onclick = () => m.remove();
      $('[data-refactor-apply]', m).onclick = async () => {
        const paths = $$('[data-refactor-path]:checked', m).map(x => x.dataset.refactorPath);
        if (!paths.length) return status('select at least one file', 'err');
        if (!await confirmDialog('Replace in workspace', `Change ${paths.length} file${paths.length === 1 ? '' : 's'}?`, 'apply')) return;
        try {
          const result = await post('/replace/apply', {token: data.token, paths}); m.remove();
          if (paths.includes(lee.path)) await takeDiskVersion(lee.path);
          refreshFileTree(undefined, false); status(`replaced text in ${result.paths.length} file${result.paths.length === 1 ? '' : 's'}`, 'ok');
        } catch (e) { status(e.message || String(e), 'err'); }
      };
    } catch (e) { status(e.message || String(e), 'err'); }
    finally { button.disabled = false; }
  };
}

/* Which lines differ, as one span from the first difference to the last. Not a real diff: the point
   is to put the change on screen and under a selection, and a span does that for every edit an undo
   can produce. */
function changedSpan(now, other) {
  const A = String(now || '').split('\n'), B = String(other || '').split('\n');
  let s = 0;
  while (s < A.length && s < B.length && A[s] === B[s]) s++;
  let a = A.length - 1, b = B.length - 1;
  while (a >= s && b >= s && A[a] === B[b]) { a--; b--; }
  return {from: s + 1, to: Math.max(s + 1, a + 1)};
}

/* An undo that changes a file you cannot see has happened to you rather than been done by you, so
   select what moved and centre it. */
function showChangedSpan(now, other, note) {
  const v = curEditor();
  if (!v) return status(note, 'ok');
  const doc = v.state.doc, {from, to} = changedSpan(now, other);
  const head = doc.line(Math.min(to, doc.lines)).to, anchor = doc.line(Math.min(from, doc.lines)).from;
  v.dispatch({selection: {anchor, head}, scrollIntoView: true});
  requestAnimationFrame(() => centreOnPos(v, anchor));
  v.focus();
  status(`${note} · line${to > from ? `s ${from}–${to}` : ` ${from}`}`, 'ok');
}

/* `undone` says which way round the texts are: after an undo the file holds `before`, after a
   redo it holds `after`, and the other one is what it was. */
async function afterHistory(operation, note, undone) {
  const rows = operation.resources || [], paths = rows.map(x => x.path);
  refreshFileTree(undefined, false);
  const row = rows.find(x => x.path === lee.path);
  if (!row) return status(`${note} · ${paths.length} file${paths.length === 1 ? '' : 's'}`, 'ok');
  await takeDiskVersion(lee.path);
  showChangedSpan(undone ? row.before : row.after, undone ? row.after : row.before, note);
}

async function workspaceHistoryRedo() {
  try {
    const result = await post('/history/redo', {});
    await afterHistory(result.operation, 'workspace operation redone', false);
  } catch (e) { status(e.message || String(e), 'err'); }
}

/* Extraction and inlining run against the file on disk: the endpoints read it themselves and
   address it by character offset, so an unsaved buffer would be rewritten from text the server
   never saw. Both refuse rather than save on the user's behalf. */
function refactorTarget() {
  if (lee.kind !== 'text' || !(lee.path || '').endsWith('.py')) {
    status('open a Python file to refactor', 'err'); return null;
  }
  if (lee.dirtyBuffers.has(lee.path)) { status('save the file before refactoring', 'err'); return null; }
  return curEditor();
}

async function runRefactor(url, body, note) {
  const data = await post(url, {path: lee.path, ...body}), edits = data.summary.edits;
  if (!await confirmDialog('Refactor', `Change ${edits} place${edits === 1 ? '' : 's'} in this file?`, 'apply')) return;
  await post('/refactor/apply', {token: data.token});
  await takeDiskVersion(lee.path); refreshFileTree(undefined, false); status(note, 'ok');
}

/* Whether the block the selection sits in is a class body, which is what decides between a
   method taking `self` and a plain function. The nearest header at a smaller indent wins. */
function inClassBody(view, pos) {
  const doc = view.state.doc, indent = t => t.match(/^[ \t]*/)[0].length;
  const want = indent(doc.lineAt(pos).text);
  for (let n = doc.lineAt(pos).number - 1; n >= 1; n--) {
    const t = doc.line(n).text;
    if (t.trim() && indent(t) < want) return /^\s*class\s/.test(t);
  }
  return false;
}

async function extractRefactor(kind) {
  const view = refactorTarget(); if (!view) return;
  const sel = LeeCM.selection(view);
  if (!sel || sel.from === sel.to) return status('select the code to extract first', 'err');
  if (kind === 'method' && !inClassBody(view, sel.from)) kind = 'function';
  const name = await inputDialog(`extract ${kind}`, 'Name', '', 'valid Python identifier');
  if (!name) return;
  try {
    await runRefactor('/refactor/preview', {start: sel.from, end: sel.to, kind, name}, `extracted ${kind} ${name}`);
  } catch (e) { status(e.message || String(e), 'err'); }
}

async function inlineVariable() {
  const view = refactorTarget(); if (!view) return;
  try {
    await runRefactor('/refactor/inline', {pos: LeeCM.cursor(view)}, 'variable inlined');
  } catch (e) { status(e.message || String(e), 'err'); }
}

/* Whole lines within one buffer, where `cell_move_up` and `cell_move_down` move whole cells.
   Written against the CodeMirror state directly rather than through a new `LeeCM` export, because
   the vendored bundle is committed and rebuilding it needs node. */
function moveLines(dir) {
  const view = curEditor(); if (!view) return;
  const doc = view.state.doc, sel = view.state.selection.main;
  const first = doc.lineAt(sel.from), last = doc.lineAt(sel.to);
  const n = dir < 0 ? first.number - 1 : last.number + 1;
  if (n < 1 || n > doc.lines) return;
  const swap = doc.line(n), block = doc.sliceString(first.from, last.to);
  const shift = dir * (swap.text.length + 1);
  view.dispatch({
    changes: {from: Math.min(first.from, swap.from), to: Math.max(last.to, swap.to),
              insert: dir < 0 ? block + '\n' + swap.text : swap.text + '\n' + block},
    selection: {anchor: sel.anchor + shift, head: sel.head + shift}, scrollIntoView: true});
  view.focus();
}

ACTIONS.replace_workspace = replaceWorkspace;
ACTIONS.workspace_undo = () => operationHistory();
ACTIONS.workspace_redo = workspaceHistoryRedo;
ACTIONS.extract_variable = () => extractRefactor('variable');
ACTIONS.extract_constant = () => extractRefactor('constant');
ACTIONS.extract_method = () => extractRefactor('method');
ACTIONS.inline_variable = inlineVariable;
ACTIONS.move_line_up = () => moveLines(-1);
ACTIONS.move_line_down = () => moveLines(1);
/* Lift whole functions and classes into another file. Unlike extract and inline this changes
   several files at once, so it previews before it writes and every file it would touch is its own
   row. */

function moveSymbolAt(symbols, pos) {
  const here = symbols.find(s => pos >= s.start && pos <= s.end);
  return here ? [here.name] : [];
}

function moveRows(files, keep, selected) {
  return files.map((f, i) => {
    const fixed = keep.includes(f.path);
    const note = f.before === null ? 'new file' : `${f.edits} change${f.edits === 1 ? '' : 's'}`;
    return `<details class="lee-moverow" data-move-file="${i}">` +
      `<summary><input type="checkbox" data-move-path="${esc(f.path)}"${selected.has(f.path) ? ' checked' : ''}` +
      `${fixed ? ' disabled title="the move needs this file"' : ''}>` +
      `<strong>${esc(compactPath(f.path))}</strong><span class="sub">${note}</span></summary>` +
      `<div class="lee-movediff" data-move-diff="${i}"></div></details>`;
  }).join('');
}

/* The diff is built when its row is opened, not when the list is drawn, or a move across a dozen
   call sites would mount a dozen merge views nobody asked to see. */
function moveDiffs(m, files) {
  const built = [];
  $$('[data-move-file]', m).forEach(row => row.addEventListener('toggle', () => {
    const i = +row.dataset.moveFile;
    if (!row.open || built[i]) return;
    const f = files[i];
    built[i] = createMerge($(`[data-move-diff="${i}"]`, row), {
      left: f.before || '', right: f.after, lang: codeLang('', f.path),
      settings: lee.editorPrefs, readOnlyRight: true, revertControls: false});
  }));
  return () => built.forEach(v => v && LeeCM.destroyMerge(v));
}

async function movePreview(m, body, opened) {
  let data;
  try { data = await post('/refactor/move', body); }
  catch (e) { return status(e.message || String(e), 'err'); }
  const keep = [body.path, body.dest], selected = new Set(data.files.map(f => f.path));
  const notes = (data.notes || []).map(n => `<div class="lee-movenote">${esc(n)}</div>`).join('');
  m.querySelector('.lee-modalbox').innerHTML =
    `<div class="lee-mhead">Move preview<span class="sub">${data.summary.files} file${data.summary.files === 1 ? '' : 's'}</span></div>` +
    notes + `<div class="lee-modallist">${moveRows(data.files, keep, selected)}</div>` +
    `<div class="lee-mfoot"><button class="lee-btn go" data-move-apply>Apply</button>` +
    `<button class="lee-btn" data-move-cancel>Cancel</button></div>`;
  const drop = moveDiffs(m, data.files);
  const close = () => { drop(); m.remove(); };
  $('[data-move-cancel]', m).onclick = close;
  $('[data-move-apply]', m).onclick = async () => {
    const paths = $$('[data-move-path]:checked', m).map(x => x.dataset.movePath);
    try {
      const r = await post('/refactor/apply', {token: data.token, paths});
      close();
      if (opened && paths.concat(keep).includes(lee.path)) await takeDiskVersion(lee.path);
      refreshFileTree(undefined, false);
      status(`moved into ${compactPath(body.dest)} · ${r.paths.length} file${r.paths.length === 1 ? '' : 's'}`, 'ok');
    } catch (e) { status(e.message || String(e), 'err'); }
  };
}

async function moveSymbol() {
  const view = refactorTarget(); if (!view) return;
  let found;
  try { found = await post('/refactor/symbols', {path: lee.path}); }
  catch (e) { return status(e.message || String(e), 'err'); }
  if (!found.symbols.length) return status('no top-level function or class to move', 'err');
  const chosen = new Set(moveSymbolAt(found.symbols, LeeCM.cursor(view)));
  const files = (await api('/fs/find')).hits.filter(h => h.path.endsWith('.py') && h.path !== lee.path);
  const m = modal(`<div class="lee-mhead">Move to file<span class="sub">${esc(found.module)}</span></div>` +
    `<div class="lee-modallist lee-movepick">${found.symbols.map(s =>
      `<label class="lee-mrow"><input type="checkbox" data-move-name="${esc(s.name)}"${chosen.has(s.name) ? ' checked' : ''}>` +
      `<strong>${esc(s.name)}</strong><span class="sub">${s.kind} · line ${s.line}</span></label>`).join('')}</div>` +
    `<label>Into<input class="lee-input lee-movedest" data-move-dest list="lee-move-files" placeholder="path/to/module.py" autofocus></label>` +
    `<datalist id="lee-move-files">${files.slice(0, 500).map(h => `<option value="${esc(h.path)}">`).join('')}</datalist>` +
    `<label><input type="checkbox" data-move-shim checked> keep a re-export in ${esc(compactPath(lee.path))}</label>` +
    `<div class="lee-mfoot"><button class="lee-btn go" data-move-go>Preview</button>` +
    `<button class="lee-btn" data-move-cancel>Cancel</button></div>`);
  $('[data-move-cancel]', m).onclick = () => m.remove();
  $('[data-move-go]', m).onclick = async () => {
    const go = $('[data-move-go]', m); go.disabled = true;
    const names = $$('[data-move-name]:checked', m).map(x => x.dataset.moveName);
    const dest = $('[data-move-dest]', m).value.trim();
    if (!names.length) { go.disabled = false; return status('choose what to move', 'err'); }
    if (!dest) { go.disabled = false; return status('name the file to move it into', 'err'); }
    await movePreview(m, {path: lee.path, names, dest, shim: $('[data-move-shim]', m).checked}, true);
    go.disabled = false;
  };
}

ACTIONS.move_symbol = moveSymbol;
async function showConflictCenter() {
  try {
    const d = await api(gitUrl('/git/conflicts')), files = d.files || [], s = d.summary || {};
    if (!files.length) return status('no unresolved Git conflicts', 'ok');
    const rows = files.map(f => `<button class="lee-mrow" data-conflict-path="${esc(f.path)}"><strong>${esc(f.path)}</strong>` +
      `<span class="sub">${f.kind} · ${f.blocks || 0} conflict${f.blocks === 1 ? '' : 's'} · ${f.safe ? `${f.safe} safe` : f.reason}</span></button>`).join('');
    const m = modal(`<div class="lee-mhead">Resolve conflicts<span class="sub">${esc(d.operation.active || 'Git operation')} paused · ${s.files} files · ${s.blocks} blocks</span></div>` +
      `<div class="lee-git-merge-preview"><header><strong>${s.safe || 0} safe resolution${s.safe === 1 ? '' : 's'} available</strong><span>Automatic changes are limited to identical sides.</span></header></div>` +
      `<div class="lee-modallist">${rows}</div><div class="lee-mfoot"><button class="lee-btn go" data-safe${s.safe ? '' : ' disabled'}>Resolve safe changes</button><button class="lee-btn" data-close>Close</button></div>`);
    $('[data-close]', m).onclick = () => m.remove();
    $$('[data-conflict-path]', m).forEach(b => b.onclick = () => { m.remove(); showGitConflict(b.dataset.conflictPath); });
    $('[data-safe]', m).onclick = async () => {
      if (!await confirmDialog('Resolve safe conflicts', `Stage ${s.safe} deterministic resolution${s.safe === 1 ? '' : 's'}?`, 'resolve')) return;
      const next = await gitDo('resolve_safe_conflicts', {paths: files.filter(f => f.safe).map(f => f.path)});
      m.remove(); afterConflictResolved(next, `${s.safe} resolved`);
    };
  } catch (e) { leeFail('git', 'resolve conflicts', e); }
}
window.showConflictCenter = showConflictCenter;

// Step to the next file, and finish the operation when none remain.
async function afterConflictResolved(d, done = '') {
  renderGitPanel(d);
  const left = (d.changes || []).filter(x => x.conflicted).map(x => x.path);
  if (left.length) {
    status(`${done}${done ? ' · ' : ''}${left.length} file${left.length === 1 ? '' : 's'} still conflicted`, 'ok');
    return showGitConflict(left[0]);
  }
  const op = (d.operation || {}).active;
  if (!op) return status(done || 'every conflict is resolved', 'ok');
  if (!await confirmDialog(`continue the ${op}`, 'Every conflict is resolved and staged.', 'continue')) return;
  renderGitPanel(await gitDo('operation_continue'));
}
window.afterConflictResolved = afterConflictResolved;
// A conflicted notebook, answered cell by cell.
//
// The worktree file is JSON with conflict markers through it: not a notebook, and not text anybody
// can read a merge out of. Git keeps all three sides in the index as whole notebooks, so the server
// lines them up into rows and this draws them. A person answers about cells, and the only answers
// are the four the server takes.

//: The states that owe an answer. The rest are context and resolve themselves.
const NB_OWED = new Set(['both', 'added', 'deleted']);
const NB_OWED_SAYS = {both: 'both sides changed this cell', added: 'one side added this cell',
                      deleted: 'one side deleted this cell'};
const NB_CONTEXT_SAYS = {same: 'both sides agree', ours: 'only ours changed it',
                         theirs: 'only theirs changed it'};

function nbCellSource(cell) {
  const s = (cell || {}).source;
  return Array.isArray(s) ? s.join('') : String(s || '');
}

// The same read-only cell the split pane draws, so a merge and a side-by-side read look alike.
function nbMergeCell(cell, label) {
  if (!cell) return `<div class="lee-nbmerge-absent">${esc(label)} does not have this cell</div>`;
  const kind = String(cell.cell_type || 'code');
  return `<article class="lee-split-cell ${esc(kind)}"><header>${esc(label)} · ${esc(kind)}</header>` +
         `<pre>${esc(nbCellSource(cell))}</pre></article>`;
}

// What a row can be answered with. An added or deleted cell exists on one side only, so the
// question is whether to keep it, and `side` is the side that has it to keep.
function nbTakes(row) {
  if (row.state === 'both') return [['ours', 'take ours'], ['theirs', 'take theirs'], ['both', 'take both']];
  return [[row.side === 'theirs' ? 'theirs' : 'ours', 'keep'], ['drop', 'drop']];
}

function nbContextCell(row) {
  return nbMergeCell(row.state === 'theirs' ? row.theirs : (row.ours || row.theirs),
                     NB_CONTEXT_SAYS[row.state] || row.state);
}

function nbOwedRow(row) {
  const takes = nbTakes(row).map(([choice, label]) =>
    `<button class="lee-btn" data-key="${esc(row.key)}" data-choice="${choice}">${esc(label)}</button>`).join('');
  return `<section class="lee-nbmerge-row" data-row="${esc(row.key)}">` +
    `<header><strong>${esc(NB_OWED_SAYS[row.state] || row.state)}</strong>` +
    `<span class="lee-dim">${esc(row.id ? 'cell ' + row.id : row.key)}</span>` +
    `<span class="lee-spacer"></span>${takes}<span class="lee-nbmerge-chose" data-chose></span></header>` +
    `<div class="lee-nbmerge-sides">${nbMergeCell(row.ours, 'ours')}${nbMergeCell(row.theirs, 'theirs')}</div>` +
    `</section>`;
}

// Rows in document order, with each run of self-resolving ones folded into one count. Order is what
// says where a contested cell sits in the notebook, so the context is not moved out of the way.
function nbMergeBody(rows) {
  const out = [];
  let context = [];
  const flush = () => {
    if (!context.length) return;
    out.push(`<details class="lee-nbmerge-context"><summary>${context.length} settled cell` +
             `${context.length === 1 ? '' : 's'}, nothing to answer</summary>` +
             context.map(nbContextCell).join('') + '</details>');
    context = [];
  };
  for (const row of rows) {
    if (NB_OWED.has(row.state)) { flush(); out.push(nbOwedRow(row)); }
    else context.push(row);
  }
  flush();
  return out.join('') || '<div class="lee-dim">this notebook has no cells to merge</div>';
}

async function showNotebookConflict(path, d) {
  const rows = d.rows || [], owed = rows.filter(r => NB_OWED.has(r.state)), choices = {};
  const m = modal(
    `<div class="lee-mhead">merge ${esc(path)}` +
    `<span class="sub">cell by cell · ours is this branch, theirs is incoming</span></div>` +
    `<div class="lee-nbmerge"><div class="lee-nbmerge-rows">${nbMergeBody(rows)}</div>` +
    `<div class="lee-nbmerge-foot"><span class="lee-dim" data-nb-left></span>` +
    `<span class="lee-nbmerge-why" data-nb-why></span>` +
    `<button class="lee-btn go" data-nb-apply>apply &amp; stage</button></div></div>`,
    null, null, {className: 'lee-modal-nbmerge', storageKey: 'git-notebook-conflict'});

  const left = () => owed.filter(r => !choices[r.key]).length;
  const refresh = () => {
    const n = left();
    m.querySelector('[data-nb-left]').textContent = owed.length
      ? (n ? `${n} of ${owed.length} contested cell${owed.length === 1 ? '' : 's'} still undecided`
           : `all ${owed.length} contested cell${owed.length === 1 ? '' : 's'} decided`)
      : 'nothing here needs an answer';
    m.querySelector('[data-nb-apply]').disabled = n > 0;
    m.querySelectorAll('[data-row]').forEach(sec => {
      const pick = choices[sec.dataset.row] || '';
      sec.classList.toggle('decided', !!pick);
      sec.querySelector('[data-chose]').textContent = pick ? `taking ${pick}` : '';
      sec.querySelectorAll('[data-choice]').forEach(b => b.classList.toggle('on', b.dataset.choice === pick));
    });
  };
  m.querySelectorAll('[data-choice]').forEach(b => b.onclick = () => {
    const key = b.dataset.key;
    if (choices[key] === b.dataset.choice) delete choices[key];
    else choices[key] = b.dataset.choice;
    refresh();
  });
  m.querySelector('[data-nb-apply]').onclick = async () => {
    if (left()) return;
    const why = m.querySelector('[data-nb-why]');
    why.textContent = '';
    try { await post('/git/notebook/conflict/resolve', {path, choices}); }
    catch (e) {
      // The server checks the same thing again, over the rows it re-reads. Its sentence is the one
      // that is true about the file, so it is shown rather than translated.
      why.textContent = e.message || String(e);
      return status(`notebook merge refused · ${e.message || e}`, 'err');
    }
    m.remove();
    const info = await api(gitUrl('/git/info'));
    gitUI.snapshot = info; paintGitPill(info);
    noteGitSignature(info); gitChanged();
    afterConflictResolved(info, `${path} staged`);
  };
  refresh();
}
window.showNotebookConflict = showNotebookConflict;
/* ---- the Vault tab: its home, the add box, and the Read sheet ---- */

async function mountVaultWorkbench(host, st) {
  host.innerHTML = '<div class="lee-git-loading"><span></span><span></span><span></span><small>opening the vault</small></div>';
  try {
    // a Find scoped from the document view arrives with its scope, in one load
    const scoped = (st.view || '') === 'find' && lee.vaultFindNext ? '&' + new URLSearchParams(lee.vaultFindNext) : '';
    lee.vaultFindNext = null;
    await htmx.ajax('GET', '/vault/workbench?view=' + encodeURIComponent(st.view || 'library') + scoped,
                    {target: host, swap: 'innerHTML'});
  } catch (e) { host.innerHTML = `<div class="lee-err">${esc(e.message || e)}</div>`; }
}
window.mountVaultWorkbench = mountVaultWorkbench;

async function leeVaultWorkbench(view = 'library') {
  await htmx.ajax('POST', '/vault/workbench/open?view=' + encodeURIComponent(view),
                  {target: '#tabbar', swap: 'outerHTML'});
  return mountTab();
}
window.leeVaultWorkbench = leeVaultWorkbench;

function leeVaultFilter(input) {
  const want = input.value.trim().toLowerCase(), wrap = input.closest('.lee-wb-main');
  let shown = 0;
  $$('.lee-vault-docrow', wrap).forEach(row => {
    const hit = !want || row.textContent.toLowerCase().includes(want);
    row.hidden = !hit; if (hit) shown++;
  });
  const count = $('.lee-wb-count', wrap);
  if (count) count.textContent = `${shown} shown`;
}
window.leeVaultFilter = leeVaultFilter;

function attachVaultRef({vault = '', shelf = '', doc = '', title = ''}) {
  if (!doc) return null;
  lee.vaultRefs.set(`${vault}|${shelf}|${doc}`, {kind: 'vault', vault, shelf, doc, title: title || doc});
  return title || doc;
}
window.attachVaultRef = attachVaultRef;

function leeVaultAsk(btn) {
  const name = attachVaultRef(btn.dataset);
  if (!name) return;
  paintAgentAttachments();
  leeRight('agent');
  $('#agentprompt')?.focus();
  status(`${name} is attached to the next question`, 'ok');
}
window.leeVaultAsk = leeVaultAsk;

function leeVaultAskAll(btn) {
  const rows = $$('.lee-wb-hit .lee-vault-ask', btn.closest('.lee-wb-find'));
  rows.forEach(b => attachVaultRef(b.dataset));
  paintAgentAttachments();
  leeRight('agent');
  status(`${rows.length} section${rows.length === 1 ? '' : 's'} attached`, 'ok');
}
window.leeVaultAskAll = leeVaultAskAll;

/* A vault route answers `{ok: false, error, kind}` with an error status, and the screen needs the
   kind, so this reads the body whatever the status. A job card comes back as HTML. */
async function vaultCall(url, data) {
  const r = await fetch(url, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data || {})});
  const ct = r.headers.get('content-type') || '';
  return ct.includes('json') ? r.json() : {ok: r.ok, html: await r.text()};
}
window.vaultCall = vaultCall;

const VAULT_PAGED = /\.(pdf|png|jpe?g|tiff?|webp)$/i;
const VAULT_LEVELS = [['open', 'Open'], ['personal', 'Personal'], ['local', 'Local only']];
const VAULT_VERSES = ['sanskrit', 'tamil'];

/* A finished book opens on its chapters. */
const vaultBookDone = m => j => {
  m.remove();
  const r = j.result;
  status(`${r.chapters} chapter${r.chapters === 1 ? '' : 's'}, ${r.verses} verses · ${r.problems} problem${r.problems === 1 ? '' : 's'} to check`, 'ok');
  lee.vaultChapters = r.doc_id;
  return leeOpenVaultDoc(r.doc_id, r.shelf || '', r.vault || '', r.title || '');
};
window.vaultBookDone = vaultBookDone;

function leeVaultAdd(form) {
  const src = form.elements.src.value.trim();
  if (!src) return;
  if (VAULT_PAGED.test(src) && !/^https?:/.test(src)) return leeVaultReadSheet(src);
  const into = $('#vaultwbjobs') ? '#vaultwbjobs' : null;
  if (/^https?:|^\d{4}\.\d{4,5}|^github\.com\//.test(src))
    return into ? htmx.ajax('POST', '/vault/acquire?' + new URLSearchParams({target: src}), {target: into, swap: 'afterbegin'}) : null;
  return into ? htmx.ajax('POST', '/clip?' + new URLSearchParams({target: src, kind: 'clip', origin: 'library'}),
                          {target: into, swap: 'afterbegin'}) : null;
}
window.leeVaultAdd = leeVaultAdd;

async function vaultModels() {
  try { return (await api('/agent/models')).models || []; } catch { return []; }
}
const seesImages = m => /\bimage\b/.test(String(m.modalities || '').split(/out:|→/)[0]);

/* The Read sheet. It estimates first, says where every page would go, and remembers what was
   chosen for the folder, so a second file from the same place is one Enter. */
async function leeVaultReadSheet(src, {vault = '', shelf = ''} = {}) {
  if (!src) return status('choose a PDF or a page image to read', 'err');
  const est = await vaultCall('/vault/read', {src, estimate: true, vault, shelf});
  if (!est.ok) return status(est.error || 'could not read that file', 'err');
  const mem = est.remembered || {}, name = src.split('/').pop();
  // a type the words settle picks the preset; an unsure guess leaves the folder's choice alone
  const typed = (est.type?.decisive || est.type?.sensitive) && est.type.preset !== 'generic' ? est.type.preset : '';
  const preset0 = typed || mem.preset || est.type?.preset || 'generic';
  const opts = (xs, cur) => xs.map(([v, l]) => `<option value="${esc(v)}"${v === cur ? ' selected' : ''}>${esc(l)}</option>`).join('');
  const m = modal(`<div class="lee-mhead"><span>Read into the vault</span><span class="sub">${esc(name)}</span></div>` +
    `<form class="lee-vault-sheet" data-vault-sheet>` +
    `<div class="lee-vault-est" data-est></div>` +
    `<label>parse<select class="lee-input" name="parse">${opts(est.parses.map(p => [p, {auto: 'auto: keep a sound text layer', text: 'text layer only', ocr: 'OCR every page', llm: 'model reads every page'}[p] || p]), mem.parse || 'auto')}</select></label>` +
    `<label>preset<select class="lee-input" name="preset">${opts(est.presets.map(p => [p, p]), preset0)}</select></label>` +
    `<label class="lee-vault-allow" data-book hidden><input type="checkbox" name="book"${mem.book ? ' checked' : ''}> book of verses: every page by the model, gathered into chapters</label>` +
    `<label data-counts hidden>verses per chapter<input class="lee-input" name="counts" autocomplete="off" placeholder="optional, like 47,72,43"></label>` +
    `<label>model<select class="lee-input" name="model" id="vaultreadmodel" aria-label="the model that reads page images">` +
    `<option value="">no model: nothing leaves this machine</option></select></label>` +
    `<label>hint<input class="lee-input" name="hint" autocomplete="off" value="${esc(mem.hint || '')}" placeholder="what the pages are, for the model"></label>` +
    `<label>pages<input class="lee-input" name="pages" autocomplete="off" placeholder="all, or 1-3,7"></label>` +
    `<label>privacy<select class="lee-input" name="level">${opts(VAULT_LEVELS, est.level)}</select></label>` +
    `<div class="lee-vault-sendline" data-send role="status"></div>` +
    `<label class="lee-vault-allow" data-allow hidden><input type="checkbox" name="allow"> allow once: send the Personal pages whole, this read only</label>` +
    `<div class="lee-vault-sheetfoot"><span class="lee-spacer"></span><button class="lee-btn go" type="submit" data-read>Read</button></div>` +
    `<div class="lee-vault-jobs" data-job></div></form>`, null, null, {storageKey: 'vault-read'});
  const f = $('[data-vault-sheet]', m), sel = $('#vaultreadmodel', m);
  const local = est.type.vision === 'local';
  const models = (await vaultModels()).filter(r => seesImages(r) && (!local || r.local));
  for (const r of models) {
    const o = document.createElement('option');
    o.value = r.value; o.textContent = `${r.label} · ${r.local ? 'on this Mac' : 'hosted: ' + (r.provider || 'remote')}`;
    sel.appendChild(o);
  }
  if ([...sel.options].some(o => o.value === mem.model)) sel.value = mem.model;
  attachModelPicker(sel);
  const pickedModel = () => sel.value;
  let last = est;
  const paint = d => {
    last = d;
    const need = d.need?.length || 0, kind = d.type?.doctype;
    $('[data-est]', m).innerHTML = `<strong>${d.pages} page${d.pages === 1 ? '' : 's'}</strong>` +
      ` · ${need ? `up to ${need} need${need === 1 ? 's' : ''} the model` : 'none needs a model'}` +
      (Object.keys(d.flags || {}).length ? ` · ${Object.keys(d.flags).length} flagged` : '') +
      (kind ? ` · looks like ${esc(kind.replace(/_/g, ' '))}` : '') +
      (typed ? ` · preset ${esc(typed)} suggested for it` : '') +
      (d.type?.level === 'local' ? '<br><span class="warn">this kind of document is Local only: only models on this Mac are offered</span>' : '');
    const line = $('[data-send]', m), blocked = d.check_ok === false || d.ok === false;
    line.textContent = d.why || '';
    line.className = 'lee-vault-sendline' + (blocked ? ' blocked' : '');
    line.dataset.kind = d.kind || '';
    $('[data-allow]', m).hidden = d.kind !== 'pii_blocked' && !f.elements.allow.checked;
    $('[data-read]', m).textContent = d.kind === 'model_unavailable' ? 'pick another model'
      : blocked ? 'Read, keeping withheld pages as text' : 'Read';
  };
  const verses = () => VAULT_VERSES.includes(f.elements.preset.value);
  const book = () => verses() && f.elements.book.checked;
  const fields = () => ({src, vault, shelf, parse: book() ? 'llm' : f.elements.parse.value, preset: f.elements.preset.value,
    model: pickedModel(), hint: f.elements.hint.value, pages: f.elements.pages.value, level: f.elements.level.value,
    allow: f.elements.allow.checked});
  const check = async () => {
    $('[data-book]', m).hidden = !verses(); $('[data-counts]', m).hidden = !book();
    f.elements.parse.disabled = book();
    const d = await vaultCall('/vault/send-check', fields());
    paint(d.ok ? d : {...last, check_ok: false, kind: d.kind, why: d.error});
  };
  paint(est);
  $('[data-book]', m).hidden = !verses(); $('[data-counts]', m).hidden = !book();
  if (est.kind || pickedModel() !== '' || book()) check();
  f.addEventListener('change', check);
  f.addEventListener('submit', async e => {
    e.preventDefault();
    if (last.kind === 'model_unavailable') return $('[data-model-pick]', m)?.click();
    const asBook = book();
    const r = await vaultCall(asBook ? '/vault/book' : '/vault/read', {...fields(), partial: last.check_ok === false, counts: f.elements.counts.value});
    const jobs = $('[data-job]', m);
    if (r.html) {
      jobs.insertAdjacentHTML('afterbegin', r.html);
      htmx.process(jobs);
      const id = (r.html.match(/id="job-([^"]+)"/) || [])[1];
      if (id) asBook ? vaultFollow(id, m, 'book', vaultBookDone(m)) : vaultFollow(id, m);
      return;
    }
    jobs.insertAdjacentHTML('afterbegin', `<div class="lee-job error" data-kind="${esc(r.kind || '')}">` +
      `<span class="lee-job-error">${esc(r.error || 'the read did not start')}</span></div>`);
    if (r.kind === 'busy' && r.job) $(`#job-${CSS.escape(r.job)}`)?.scrollIntoView({block: 'nearest'});
  });
  if (mem.parse) setTimeout(() => $('[data-read]', m)?.focus(), 0);
  return m;
}
window.leeVaultReadSheet = leeVaultReadSheet;

/* The card polls itself; this waits on the same job to open what it read. */
async function vaultFollow(id, m, kind = 'read', done = null) {
  for (let i = 0; i < 1800 && m.isConnected; i++) {
    await new Promise(res => setTimeout(res, 700));
    let j;
    try { j = (await api(`/jobs?kind=${kind}&limit=20`)).jobs.find(x => x.id === id); } catch { continue; }
    if (!j || j.active) continue;
    if (j.status !== 'complete' || !j.result?.doc_id && kind === 'read') return;
    if (done) return done(j);
    m.remove();
    const r = j.result;
    status(r.blocked?.length ? `${r.blocked.length} page(s) kept their text layer: not sent` : 'read into the vault', r.blocked?.length ? 'err' : 'ok');
    return leeOpenVaultDoc(r.doc_id, r.shelf || '', r.vault || '', r.title || j.target.split('/').pop());
  }
}

/* Clipping a PDF or a scan is a read; anything else is clipped as text. Either way it lands in the Vault tab. */
async function leeClipToVault() {
  const target = clipTarget();
  if (!target) return status('select a file, a folder or a tab to clip', 'err');
  if (VAULT_PAGED.test(target)) return leeVaultReadSheet(target);
  await leeVaultWorkbench('library');
  const into = $('#vaultwbjobs');
  if (!into) return status('the Vault tab did not open', 'err');
  await htmx.ajax('POST', '/clip?' + new URLSearchParams({target, kind: 'clip', origin: 'menu'}), {target: into, swap: 'afterbegin'});
  into.closest('details')?.setAttribute('open', '');
  status(`clipping ${target.split('/').pop() || target} into the vault…`);
}
window.leeClipToVault = leeClipToVault;

function leeVaultRead() {
  const target = clipTarget();
  if (target && VAULT_PAGED.test(target)) return leeVaultReadSheet(target);
  return leeVaultWorkbench('library').then(() => $('[data-vault-add] input')?.focus());
}
window.leeVaultRead = leeVaultRead;

/* ---- Find: one box, a scope chip, hits to open and an answer that cites them ---- */

const findForm = el => el.closest('[data-vault-find]');
const findScope = f => {
  const scope = f.elements.scope?.value || 'vault';
  return {doc: scope === 'vault' ? '' : f.elements.doc.value, pages: scope === 'pages' ? f.elements.pages.value : '',
          shelf: f.elements.shelf.value, vault: f.elements.vault.value, model: f.elements.model?.value || ''};
};

function leeVaultScope(sel) {
  const f = findForm(sel); if (!f) return;
  f.elements.pages.hidden = sel.value !== 'pages';
  if (sel.value === 'pages') f.elements.pages.focus();
  vaultFindLine(f);
}
window.leeVaultScope = leeVaultScope;

/* Where an answer's sections may go, said before anything is asked, by the route every send line uses. */
async function vaultFindLine(f) {
  const line = $('[data-send]', f.closest('.lee-wb-find'));
  if (!line) return;
  const d = await vaultCall('/vault/send-check', {ask: true, ...findScope(f)});
  line.hidden = false;
  line.textContent = d.ok ? d.why : d.error;
  line.className = 'lee-vault-sendline' + (d.ok && d.check_ok !== false ? '' : ' blocked');
  line.dataset.kind = d.kind || '';
}

async function mountVaultFind(f) {
  f.dataset.mounted = '1';
  const sel = document.createElement('select');
  sel.name = 'model'; sel.className = 'lee-input'; sel.id = 'vaultaskmodel'; sel.setAttribute('aria-label', 'the model that answers');
  sel.add(new Option('the conversation model', ''));
  for (const r of await vaultModels()) sel.add(new Option(`${r.label} · ${r.local ? 'on this Mac' : 'hosted: ' + (r.provider || 'remote')}`, r.value));
  $('[data-find-ask]', f).before(sel);
  attachModelPicker(sel);
  sel.addEventListener('change', () => vaultFindLine(f));
  f.elements.pages.addEventListener('input', () => { clearTimeout(f.__t); f.__t = setTimeout(() => vaultFindLine(f), 300); });
  vaultFindLine(f);
}
const mountVaultFinds = () => $$('[data-vault-find]:not([data-mounted])').forEach(mountVaultFind);
document.addEventListener('htmx:afterSettle', mountVaultFinds);

async function leeVaultAskFind(btn) {
  const f = findForm(btn), q = f?.elements.q.value.trim();
  if (!q) return status('type a question to ask', 'err');
  const box = f.closest('.lee-wb-find'), out = $('[data-answer]', box), line = $('[data-send]', box), sc = findScope(f);
  out.hidden = false; out.className = 'lee-wb-answer asking'; out.dataset.kind = '';
  out.innerHTML = '<div class="lee-wb-answertext" data-answer-text>asking…</div><div class="lee-wb-cites" data-cites></div>';
  const text = $('[data-answer-text]', out), cites = $('[data-cites]', out);
  const fail = (msg, kind) => { out.className = 'lee-wb-answer failed'; out.dataset.kind = kind || ''; text.textContent = msg; };
  const said = (why, ok) => { line.hidden = false; line.textContent = why; line.className = 'lee-vault-sendline' + (ok === false ? ' blocked' : ''); };
  try {
    await postEvents('/vault/ask', {q, ...sc}, (ev, d) => {
      if (ev === 'send') said(d.why, d.check_ok);
      else if (ev === 'reset') text.textContent = '';
      else if (ev === 'chunk') text.textContent = d.text;
      else if (ev === 'error') fail(d.error, d.kind);
      else if (ev === 'answer') {
        out.className = 'lee-wb-answer' + (d.refused ? ' failed' : '');
        renderMarkdown(text, d.answer || '*no answer*');
        if (d.send?.why) said(d.send.why, d.send.ok);
        cites.innerHTML = (d.cited || []).map(c => `<button class="lee-wb-cite" data-cite="${c.n}">` +
          `<b>[${c.n}]</b> ${esc(c.title)}${c.page == null ? '' : ` · p. ${pageNo(c.page)}`}</button>`).join('');
        $$('[data-cite]', cites).forEach(b => b.onclick = () => {
          const c = d.cited.find(x => x.n === +b.dataset.cite);
          leeOpenVaultDoc(c.doc, c.shelf, sc.vault, c.title, {page: c.page, quote: c.quote});
        });
      }
    });
  } catch (e) {
    let body = {}; try { body = JSON.parse(e.message); } catch {}
    fail(body.error || e.message || String(e), body.kind);
  }
}
window.leeVaultAskFind = leeVaultAskFind;

/* Find scoped to the document in the view, or to its current page. */
async function leeVaultFindIn(st, page = null) {
  lee.vaultFindNext = {doc: st.doc, shelf: st.shelf || '', vault: st.vault || '', title: st.title || st.doc, scope: page == null ? 'doc' : 'pages',
                       ...(page == null ? {} : {pages: String(pageNo(page))})};
  await leeVaultWorkbench('find');
  $('[data-vault-find] [name=q]')?.focus();
  if (page != null) status(`ask about page ${pageNo(page)}: type the question, then ask`, 'ok');
}
window.leeVaultFindIn = leeVaultFindIn;

async function leeVaultGuessTypes(btn) {
  const d = await vaultCall('/vault/types/guess', {vault: btn.dataset.vault || ''});
  status(d.ok ? `${d.typed} typed, ${d.proposed} to decide under Review > Types` : d.error, d.ok ? 'ok' : 'err');
}
window.leeVaultGuessTypes = leeVaultGuessTypes;

/* A vault attached, created, detached, activated or re-permissioned: Settings and the picker re-render. A refusal keeps what was typed. */
function leeVaultSettled(ev) {
  const x = ev.detail.xhr;
  if (!ev.detail.successful) {
    let e; try { e = JSON.parse(x.responseText).error; } catch { e = x.statusText || 'the vault did not answer'; }
    return status(e, 'err');
  }
  htmx.ajax('GET', '/vault/workbench?view=settings', {target: '#vaultwb', swap: 'outerHTML'});
}
window.leeVaultSettled = leeVaultSettled;

/* The vault's floor: the level no document in it goes below. Lowering it is said out loud first. */
async function leeVaultFloor(sel) {
  const was = sel.dataset.was, rank = v => VAULT_LEVELS.findIndex(([k]) => k === v);
  if (rank(sel.value) < rank(was) && !await confirmDialog('lower the floor',
      `Documents in this vault were kept at least ${VAULT_LEVELS[rank(was)][1]}. Lower the floor to ${VAULT_LEVELS[rank(sel.value)][1]}?`, 'lower')) {
    sel.value = was; return;
  }
  const r = await vaultCall('/vault/access', {name: $('.lee-wb-vault')?.value || '', privacy: sel.value});
  if (!r.ok) { sel.value = was; return status(r.error, 'err'); }
  sel.dataset.was = r.floor;
  status(`floor: ${VAULT_LEVELS[rank(r.floor)][1]}`, 'ok');
}
window.leeVaultFloor = leeVaultFloor;

/* What left this machine: every send to a hosted model, newest first, for the vault or one document. */
async function leeVaultSends({doc = '', shelf = '', vault = ''} = {}) {
  const d = await api('/vault/sends?' + new URLSearchParams({doc, shelf, vault: vault || $('.lee-wb-vault')?.value || ''})).catch(e => ({ok: false, error: e.message}));
  if (!d.ok) return status(d.error, 'err');
  const when = t => new Date(t * 1000).toLocaleString();
  const rows = d.sends.map(r => `<tr><td>${esc(when(r.at))}</td><td><button class="lee-vault-doc" data-send-doc="${esc(r.doc_id)}" data-shelf="${esc(r.shelf || '')}">${esc(r.title || r.doc_id)}</button></td>` +
    `<td>${esc(r.pages.map(pageNo).join(', ') || 'sections')}</td><td>${esc(r.model)}</td><td>${esc(r.runtime || '')}</td><td>${esc(r.policy || '')}</td>` +
    `<td>${esc(Object.entries(r.kinds || {}).map(([k, n]) => `${k}×${n}`).join(', '))}</td></tr>`).join('');
  const m = modal(`<div class="lee-mhead">What left this machine<span class="sub">${doc ? 'this document' : 'the whole vault'} · ${d.sends.length}</span></div>` +
    `<div class="lee-vault-sends" data-vault-sends>${d.sends.length ? `<table><thead><tr><th>when</th><th>document</th><th>pages</th><th>model</th><th>runtime</th><th>policy</th><th>kinds</th></tr></thead>` +
    `<tbody>${rows}</tbody></table>` : '<div class="lee-wb-empty"><strong>Nothing was sent to a hosted model</strong></div>'}` +
    `<small class="lee-dim">Reads, re-reads, proofreads, answers and field reads by a hosted model. Sends to a model on this Mac are not listed. Prompt-bar attachments are not listed yet.</small></div>`,
    null, null, {storageKey: 'vault-sends'});
  $$('[data-send-doc]', m).forEach(b => b.onclick = () => { m.remove(); leeOpenVaultDoc(b.dataset.sendDoc, b.dataset.shelf, vault, b.textContent); });
  return m;
}
window.leeVaultSends = leeVaultSends;
/* ---- a vault document as a tab: page strip, page image and page text, or its sections ---- */

/* Pages are 0-based on the wire and 1-based on the screen. This is the one place that says so. */
const pageNo = i => i + 1;

function vaultSectionRows(sections, active) {
  if (!sections.length) return '<div class="lee-dim">No section structure was extracted.</div>';
  return sections.map(s => `<button class="lee-vault-section${s.node_id === active ? ' active' : ''}" ` +
    `data-node="${esc(s.node_id)}" style="padding-left:${6 + s.depth * 10}px">` +
    `<strong>${esc(s.title)}</strong>${s.page ? `<small>p. ${s.page}</small>` : ''}</button>`).join('');
}

function vaultPrivacy(d) {
  const p = d.privacy || {};
  const kinds = Object.entries(p.kinds || {}).map(([k, n]) => `${k}×${n}`).join(', ');
  const cleared = p.override === 'clear', forced = p.override === 'force';
  if (!p.has_pii && !p.detected && !forced) {
    return `<div class="lee-vault-privacy"><strong>No pattern found</strong>` +
      `<span class="lee-pii clear" title="${esc(d.covers || '')}">no pattern found</span>` +
      `<button data-vault-pii="1">mark personal</button></div>`;
  }
  const head = cleared ? 'Marked not personal' : forced ? 'Marked personal' : 'Personal information found';
  return `<div class="lee-vault-privacy${cleared ? '' : ' sensitive'}">` +
    `<strong>${head}</strong>` +
    `<span class="lee-pii ${cleared ? 'clear' : 'found'}" title="${esc(d.covers || '')}">${esc(kinds || 'no kinds')}</span>` +
    (d.evidence?.length ? `<div class="lee-vault-evidence">${d.evidence.slice(0, 40).map(e =>
      `<span title="${esc(e.kind)}, page ${e.page}"><mark>${esc(e.value)}</mark><small>p. ${e.page}</small></span>`).join('')}</div>` : '') +
    (forced ? `<button data-vault-pii="0">restore detection</button>`
            : `<button data-vault-notpii="${cleared ? '0' : '1'}">${cleared ? 'restore detection' : 'mark not personal'}</button>`) +
    `</div>`;
}

/* The level chip: what a hosted model may have of this document, and a person's way to change it. */
function vaultLevelChip(lv, writable) {
  const opts = VAULT_LEVELS.map(([v, l]) => `<option value="${v}"${v === lv.level ? ' selected' : ''}>${l}</option>`).join('');
  const why = [lv.override ? `marked ${lv.override}` : `detected ${lv.detected}`, lv.floor !== 'open' ? `floor ${lv.floor}` : '',
               lv.doctype ? `type ${lv.doctype}` : '', Object.keys(lv.kinds || {}).join(', ')].filter(Boolean).join(' · ');
  return `<span class="lee-vault-level ${esc(lv.level)}" title="${esc(why)}">` +
    `<select class="lee-input" data-vault-level aria-label="privacy level"${writable ? '' : ' disabled title="this vault is attached read-only"'}>${opts}</select>` +
    (lv.override ? `<button class="lee-btn" data-vault-level-reset title="let detection decide again">auto</button>` : '') + `</span>`;
}

function wireVaultLevel(host, st, repaint) {
  const set = async level => {
    const r = await vaultCall('/vault/privacy', {doc: st.doc, shelf: st.shelf || '', vault: st.vault || '', level});
    if (!r.ok) return status(r.error, 'err');
    status(`now ${VAULT_LEVELS.find(([v]) => v === r.privacy.level)?.[1] || r.privacy.level}`, 'ok');
    repaint(r.privacy);
  };
  const sel = $('[data-vault-level]', host);
  if (sel) sel.onchange = () => set(sel.value);
  const reset = $('[data-vault-level-reset]', host);
  if (reset) reset.onclick = () => set('');
}

async function mountVault(host, st) {
  host.innerHTML = '<div class="lee-git-loading"><span></span><span></span><span></span><small>reading the vault</small></div>';
  const q = new URLSearchParams({doc: st.doc, shelf: st.shelf || '', vault: st.vault || ''});
  let d;
  try { d = await api('/vault/doc?' + q); }
  catch (e) { host.innerHTML = `<div class="lee-err">${esc(e.message || e)}</div>`; return; }
  return d.paged ? mountVaultPages(host, st, d, q) : mountVaultSections(host, st, d);
}
window.mountVault = mountVault;

function vaultHead(st, d) {
  const doc = d.doc || {}, src = String(doc.source || '');
  return `<header class="lee-vault-dochead"><span class="lee-ptitle">${esc(doc.title || st.title)}</span>` +
    `<span class="lee-keyscope">${esc(doc.kind || 'document')} · ${esc(st.shelf || 'store')}</span>` +
    `<span data-level-slot>${vaultLevelChip(d.level || {level: 'open'}, d.writable)}</span>${vaultTypeChip(doc.meta || {})}<span class="lee-spacer"></span>` +
    (d.paged ? `<button class="lee-btn" data-vault-act="reread" title="r">re-read</button>` +
      `<button class="lee-btn" data-vault-act="history" title="h">history</button>` +
      `<button class="lee-btn" data-vault-act="proofread" title="p">proofread</button>` +
      `<button class="lee-btn" data-vault-act="review">review</button>` +
      `<button class="lee-btn" data-vault-act="sent" title="m: what a hosted model receives">as sent</button>` +
      `<button class="lee-btn" data-vault-act="find" title="/: find in this document">find</button>` +
      `<button class="lee-btn" data-vault-act="fields" title="the fields read out of it, each with its page">fields</button>` +
      (doc.meta?.book ? `<button class="lee-btn" data-vault-act="chapters" title="its chapters and verse numbers, and the problems to check">chapters</button>`
                      : `<button class="lee-btn" data-vault-act="book" title="read every page by a model as a book of verses">read as a book</button>`) : '') +
    `<button class="lee-btn" data-vault-sent-log title="what of it went to a hosted model, and when">sent</button>` +
    (VAULT_PAGED.test(src) ? `<button class="lee-btn" data-vault-reread>${d.paged ? 'read the file again' : 'read it page by page'}</button>` : '') +
    (src.startsWith('/') ? `<button class="lee-btn" data-vault-file>open file</button>` : '') + `</header>`;
}

function vaultTypeChip(m) {
  const dt = m.doctype || m.doctype_proposed;
  return dt ? `<span class="lee-vault-type${m.doctype ? '' : ' proposed'}" title="${m.doctype ? 'type' : 'proposed type: decide it under Review > Types'}">` +
    `${esc(dt.replace(/_/g, ' '))}</span>` : '';
}

function wireVaultHead(host, st, d) {
  const src = String(d.doc?.source || '');
  const rr = $('[data-vault-reread]', host); if (rr) rr.onclick = () => leeVaultReadSheet(src, {vault: st.vault || '', shelf: st.shelf || ''});
  const of = $('[data-vault-file]', host); if (of) of.onclick = () => leeOpenVaultFile(st.doc, st.shelf || '', st.vault || '');
  const sl = $('[data-vault-sent-log]', host); if (sl) sl.onclick = () => leeVaultSends({doc: st.doc, shelf: st.shelf || '', vault: st.vault || ''});
  const repaint = lv => { $('[data-level-slot]', host).innerHTML = vaultLevelChip(lv, d.writable); wireVaultLevel(host, st, repaint); };
  wireVaultLevel(host, st, repaint);
}

function vaultBlocks(blocks) {
  return blocks.map((b, i) => {
    const body = b.rows?.length ? `<table>${b.rows.map(r => `<tr>${r.map(c => `<td>${esc(c)}</td>`).join('')}</tr>`).join('')}</table>`
      : esc(b.text || '').replace(/\n/g, '<br>');
    return `<div class="lee-vault-block ${esc(b.kind || 'prose')}" data-block="${i}" tabindex="-1">` +
      (b.n != null ? `<small>${esc(b.n)}</small>` : '') + body + `</div>`;
  }).join('');
}

async function mountVaultPages(host, st, d, q) {
  let pages;
  try { pages = (await api('/vault/pages?' + q)).pages; }
  catch (e) { host.innerHTML = `<div class="lee-err">${esc(e.message || e)}</div>`; return; }
  const routes = [...new Set(pages.map(p => p.route))];
  const secs = (d.sections || []).filter(s => s.page);
  host.innerHTML = `<div class="lee-vault-docview" tabindex="0" data-doc="${esc(st.doc)}">${vaultHead(st, d)}` +
    `<div class="lee-vault-docbody"><aside class="lee-vault-strip">` +
    `<select class="lee-input" data-strip-filter aria-label="show pages"><option value="">every page</option>` +
    `<option value="flagged">flagged</option>${routes.map(r => `<option value="route:${esc(r)}">${esc(r)}</option>`).join('')}</select>` +
    (secs.length ? `<select class="lee-input" data-sections aria-label="sections"><option value="">sections…</option>` +
      secs.map(s => `<option value="${s.page - 1}">${esc(s.title)} · p. ${s.page}</option>`).join('') + `</select>` : '') +
    `<div class="lee-vault-thumbs">${pages.map(p => `<button class="lee-vault-thumb" data-page="${p.page}" data-route="${esc(p.route)}"` +
      ` data-flagged="${p.flags.length ? 1 : 0}" title="page ${pageNo(p.page)} · ${esc(p.route)}${p.flags.length ? ' · ' + esc(p.flags.join(', ')) : ''}">` +
      `<img loading="lazy" alt="" src="/vault/page/img?${q}&page=${p.page}&w=120">` +
      `<span class="lee-vault-pno">${pageNo(p.page)}</span><span class="lee-vault-route ${esc(p.route)}">${esc(p.route)}</span>` +
      `${p.flags.map(f => `<i class="lee-vault-flag" title="${esc(f)}"></i>`).join('')}</button>`).join('')}</div></aside>` +
    `<figure class="lee-vault-pageimg"><img data-pageimg alt=""><figcaption data-imgerr hidden></figcaption></figure>` +
    `<article class="lee-vault-pagetext" data-pagetext></article><aside class="lee-vault-fields" data-fields hidden></aside>` +
    `<aside class="lee-vault-fields lee-vault-chapters" data-chapters hidden></aside></div></div>`;
  const view = $('.lee-vault-docview', host), img = $('[data-pageimg]', host), text = $('[data-pagetext]', host);
  let at = -1, seq = 0;
  const show = async i => { const tok = ++seq;
    if (i < 0 || i >= pages.length) return;
    at = i;
    const p = pages[i];
    view.dataset.page = String(p.page);
    $$('.lee-vault-thumb', host).forEach(b => b.classList.toggle('active', +b.dataset.page === p.page));
    $(`.lee-vault-thumb[data-page="${p.page}"]`, host)?.scrollIntoView({block: 'nearest'});
    const err = $('[data-imgerr]', host); err.hidden = true; img.hidden = false;
    img.src = `/vault/page/img?${q}&page=${p.page}&w=900`;
    img.onerror = async () => {
      let why = 'the page image did not render';
      try { why = (await (await fetch(img.src)).json()).error || why; } catch {}
      img.hidden = true; err.hidden = false; err.textContent = why;
    };
    try {
      if (st.sent) {
        const s = await api(`/vault/page?${q}&page=${p.page}&view=sent`);
        if (tok !== seq) return;
        text.innerHTML = `<div class="lee-vault-pagehead lee-vault-senthead ${esc(s.how)}">as sent to a hosted model · page ${pageNo(p.page)} · ` +
          `${esc(s.how)} · ${esc(s.level)}${Object.keys(s.kinds || {}).length ? ' · ' + esc(Object.keys(s.kinds).join(', ')) : ''}` +
          `<small>a page image cannot be masked: a re-read or a proofread withholds a Personal page from a hosted model</small></div>` +
          `<pre class="lee-vault-sent" data-sent>${esc(s.text || '')}</pre>`;
        return;
      }
      const r = await api(`/vault/page?${q}&page=${p.page}`);
      if (tok !== seq) return;
      text.innerHTML = `<div class="lee-vault-pagehead">page ${pageNo(p.page)} · ${esc(r.route)}${r.model ? ' · ' + esc(r.model) : ''}` +
        ` · <button class="lee-vault-vchip" data-vault-act="history" title="h: versions of this page">v${r.version}</button>` +
        `${r.flags.length ? ` · <span class="warn">${esc(r.flags.join(', '))}</span>` : ''}</div>`;
      if (r.blocks?.length) text.insertAdjacentHTML('beforeend', vaultBlocks(r.blocks));
      else {
        // rendered on the server: a jump marks a block only once the text is on the page
        const a = document.createElement('div'); text.appendChild(a);
        await new Promise(res => { a.addEventListener('lee-markdown-rendered', res, {once: true}); setTimeout(res, 3000);
                                   renderMarkdown(a, r.text || '*no text on this page*'); });
      }
    } catch (e) { text.textContent = e.message || String(e); }
  };
  const cur = () => pages[at]?.page ?? 0;
  const go = async (page, hl) => { await show(Math.max(0, pages.findIndex(p => p.page === page))); vaultMark(text, hl); };
  const acts = {
    reread: () => vaultPageSheet('reparse', st, {pages: String(pageNo(cur())), done: () => mountVault(host, {...st, at: cur()})}),
    proofread: () => vaultPageSheet('proof', st, {pages: ''}),
    history: () => vaultHistory(st, q, cur(), () => mountVault(host, {...st, at: cur()})),
    review: () => leeVaultReview(st.doc, st.shelf || '', st.vault || ''),
    find: () => leeVaultFindIn(st),
    ask: () => leeVaultFindIn(st, cur()),
    fields: () => { $('[data-chapters]', host).hidden = true; vaultFields(st, $('[data-fields]', host), go); },
    chapters: () => { $('[data-fields]', host).hidden = true; vaultChapters(st, $('[data-chapters]', host), go); },
    book: () => vaultPageSheet('book', st, {done: () => { lee.vaultChapters = st.doc; mountVault(host, {...st, at: cur()}); }}),
    sent: () => { st.sent = !st.sent; view.classList.toggle('sent', !!st.sent); $$('[data-vault-act="sent"]', host).forEach(b => b.classList.toggle('active', !!st.sent)); show(at); },
  };
  view.addEventListener('click', e => { const b = e.target.closest('[data-vault-act]'); if (b && acts[b.dataset.vaultAct]) acts[b.dataset.vaultAct](); });
  const visible = () => $$('.lee-vault-thumb', host).filter(b => !b.hidden).map(b => pages.findIndex(p => p.page === +b.dataset.page));
  view.__vault = {
    ...acts,
    step: n => { const v = visible(), k = v.indexOf(at); show(v[Math.max(0, Math.min(v.length - 1, (k < 0 ? 0 : k + n)))]); },
    flag: n => {
      const f = pages.map((p, i) => p.flags.length ? i : -1).filter(i => i >= 0);
      if (!f.length) return status('no page is flagged', 'ok');
      show(n > 0 ? (f.find(i => i > at) ?? f[0]) : (f.slice().reverse().find(i => i < at) ?? f.at(-1)));
    }};
  $$('.lee-vault-thumb', host).forEach(b => b.onclick = () => show(pages.findIndex(p => p.page === +b.dataset.page)));
  text.addEventListener('click', e => {
    const b = e.target.closest('.lee-vault-block'); if (!b) return;
    $$('.lee-vault-block.active', text).forEach(x => x.classList.remove('active')); b.classList.add('active');
  });
  $('[data-strip-filter]', host).onchange = e => {
    const v = e.target.value;
    $$('.lee-vault-thumb', host).forEach(b => b.hidden = v === 'flagged' ? b.dataset.flagged !== '1'
      : v.startsWith('route:') ? b.dataset.route !== v.slice(6) : false);
  };
  const sec = $('[data-sections]', host); if (sec) sec.onchange = () => sec.value && show(pages.findIndex(p => p.page === +sec.value));
  view.addEventListener('mousedown', e => { if (!e.target.closest('select, input, button, a')) setTimeout(() => view.focus({preventScroll: true}), 0); });
  wireVaultHead(host, st, d);
  if (st.sent) { view.classList.add('sent'); $$('[data-vault-act="sent"]', host).forEach(b => b.classList.add('active')); }
  const jump = lee.vaultJump?.doc === st.doc ? lee.vaultJump : null;
  lee.vaultJump = null;
  await go(jump?.page ?? st.at, jump);
  if (lee.vaultChapters === st.doc && d.doc?.meta?.book) { lee.vaultChapters = null; acts.chapters(); }
  view.focus({preventScroll: true});
}

function leeVaultPage(n) { $('.lee-vault-docview')?.__vault?.step(n); }
function leeVaultFlag(n) { $('.lee-vault-docview')?.__vault?.flag(n); }
function leeVaultDoc(act) {
  const v = $('.lee-vault-docview');
  if (!v?.__vault) return status('open a read vault document first', 'err');
  v.__vault[act]?.();
}
window.leeVaultPage = leeVaultPage; window.leeVaultFlag = leeVaultFlag; window.leeVaultDoc = leeVaultDoc;

/* Versions of one page: pick any two and see what changed between them. */
async function vaultHistory(st, q, page, done = null) {
  let rows;
  try { rows = (await api(`/vault/pages?${q}&history=1`)).pages.filter(p => p.page === page); }
  catch (e) { return status(e.message || String(e), 'err'); }
  if (!rows.length) return status('this page has no versions yet', 'err');
  const when = t => t ? new Date(t * 1000).toLocaleString() : '';
  const opt = (sel) => rows.map(r => `<option value="${r.version}"${r.version === sel ? ' selected' : ''}>v${r.version} · ${esc(r.route)}` +
    `${r.model ? ' · ' + esc(r.model) : ''} · ${esc(when(r.at))}</option>`).join('');
  const last = rows.at(-1).version, prev = rows.length > 1 ? rows.at(-2).version : last;
  const m = modal(`<div class="lee-mhead">Page ${pageNo(page)} versions<span class="sub">${rows.length} version${rows.length === 1 ? '' : 's'}</span></div>` +
    `<div class="lee-vault-history" data-vault-history><div class="lee-vault-histpick">` +
    `<select class="lee-input" data-a aria-label="from version">${opt(prev)}</select><span>→</span>` +
    `<select class="lee-input" data-b aria-label="to version">${opt(last)}</select><span class="lee-spacer"></span>` +
    `<button class="lee-btn" data-restore title="file the from version again as the newest; no version is lost">restore the from version</button></div>` +
    `<div class="lee-diff" data-diff></div></div>`, null, null, {storageKey: 'vault-history'});
  const paint = async () => {
    const a = $('[data-a]', m).value, b = $('[data-b]', m).value, out = $('[data-diff]', m);
    try {
      const d = await api(`/vault/page/diff?${q}&page=${page}&a=${a}&b=${b}`);
      out.innerHTML = d.rows.length ? diffHtml(d.rows) : '<div class="lee-dim">these two versions read the same</div>';
    } catch (e) { out.textContent = e.message || String(e); }
  };
  m.addEventListener('change', paint);
  $('[data-restore]', m).onclick = async () => {
    const v = +$('[data-a]', m).value;
    if (v === last) return status(`v${v} is already the newest`, 'err');
    const r = await vaultCall('/vault/page/revert', {doc: st.doc, shelf: st.shelf || '', vault: st.vault || '', page, version: v});
    if (!r.ok) return status(r.error, 'err');
    m.remove(); status(`page ${pageNo(page)}: v${v} restored as v${r.version}`, 'ok'); done?.();
  };
  await paint();
  return m;
}

/* The Re-read and Proofread sheets: which pages, which models, and the send line above the button. */
async function vaultPageSheet(kind, st, {pages = '', done = null} = {}) {
  const proof = kind === 'proof', isBook = kind === 'book', base = {doc: st.doc, shelf: st.shelf || '', vault: st.vault || ''};
  const est = proof ? await vaultCall('/vault/proofread', {...base, estimate: true}) : {};
  const mem = est.remembered || {};
  const pick = i => `<label>${proof ? `reader ${i + 1}` : 'model'}<select class="lee-input" name="model${i}" aria-label="${proof ? 'proofreader' : 'the model that reads the pages again'}">` +
    `<option value="">${proof && i ? 'none' : 'choose a model'}</option></select></label>`;
  const title = proof ? 'Proofread' : isBook ? 'Read as a book of verses' : 'Re-read pages', goLabel = proof ? 'Proofread' : isBook ? 'Read as a book' : 'Read again';
  const m = modal(`<div class="lee-mhead"><span>${title}</span><span class="sub">${esc(st.title || st.doc)}</span></div>` +
    `<form class="lee-vault-sheet" data-vault-pagesheet="${kind}">` +
    `<label>pages<input class="lee-input" name="pages" autocomplete="off" value="${esc(pages)}" placeholder="all, or 3-9"></label>` +
    pick(0) + (proof ? pick(1) + `<label>agree<input class="lee-input" name="agree" type="number" min="1" max="2" value="${esc(mem.agree || 2)}"></label>`
      : `<label>preset<select class="lee-input" name="preset">${isBook ? '' : '<option value="">as first read</option>'}` +
        (isBook ? VAULT_VERSES : ['generic', 'sanskrit', 'tamil', 'tables']).map(p => `<option>${p}</option>`).join('') + `</select></label>` +
        (isBook ? `<label>verses per chapter<input class="lee-input" name="counts" autocomplete="off" placeholder="optional, like 47,72,43"></label>` : '') +
        `<label>hint<input class="lee-input" name="hint" autocomplete="off" placeholder="what the pages are, for the model"></label>`) +
    `<div class="lee-vault-sendline" data-send role="status">choose a model to see where the pages go</div>` +
    `<label class="lee-vault-allow" data-allow hidden><input type="checkbox" name="allow"> allow once: send the Personal pages, this run only</label>` +
    `<div class="lee-vault-sheetfoot"><span class="lee-spacer"></span><button class="lee-btn go" type="submit" data-go>${goLabel}</button></div>` +
    `<div class="lee-vault-jobs" data-job></div></form>`, null, null, {storageKey: 'vault-pages'});
  const f = $('[data-vault-pagesheet]', m), sels = $$('select[name^="model"]', f);
  const models = (await vaultModels()).filter(seesImages);
  sels.forEach((sel, i) => {
    for (const r of models) {
      const o = document.createElement('option');
      o.value = r.value; o.textContent = `${r.label} · ${r.local ? 'on this Mac' : 'hosted: ' + (r.provider || 'remote')}`;
      sel.appendChild(o);
    }
    const want = (mem.readers || [])[i];
    if (want && ![...sel.options].some(o => o.value === want)) sel.add(new Option(want, want));
    if (want) sel.value = want;
    attachModelPicker(sel);
  });
  let last = {};
  const names = () => sels.map(s => s.value).filter(Boolean).join(',');
  const fields = () => ({...base, pages: f.elements.pages.value, allow: f.elements.allow.checked,
    ...(proof ? {readers: names(), agree: +f.elements.agree.value || 2}
              : {model: names(), preset: f.elements.preset.value, hint: f.elements.hint.value, ...(isBook ? {counts: f.elements.counts.value} : {})})});
  const check = async () => {
    const line = $('[data-send]', m), go = $('[data-go]', m);
    if (!names()) { last = {}; line.className = 'lee-vault-sendline'; line.textContent = 'choose a model to see where the pages go'; return; }
    const d = await vaultCall('/vault/send-check', {...base, pages: f.elements.pages.value, model: names(), allow: f.elements.allow.checked});
    last = d.ok ? d : {check_ok: false, kind: d.kind, why: d.error};
    const blocked = last.check_ok === false;
    line.textContent = last.why || '';
    line.className = 'lee-vault-sendline' + (blocked ? ' blocked' : '');
    line.dataset.kind = last.kind || '';
    $('[data-allow]', m).hidden = last.kind !== 'pii_blocked' && !f.elements.allow.checked;
    go.textContent = last.kind === 'model_unavailable' ? 'pick another model'
      : blocked ? `${goLabel}, skipping withheld pages` : goLabel;
  };
  f.addEventListener('change', check);
  f.elements.pages.addEventListener('input', () => { clearTimeout(f.__t); f.__t = setTimeout(check, 300); });
  f.addEventListener('submit', async e => {
    e.preventDefault();
    if (!names()) return status('choose a model', 'err');
    const r = await vaultCall(proof ? '/vault/proofread' : isBook ? '/vault/book' : '/vault/reparse', {...fields(), partial: last.check_ok === false});
    const jobs = $('[data-job]', m);
    if (r.html) {
      jobs.insertAdjacentHTML('afterbegin', r.html);
      htmx.process(jobs);
      const id = (r.html.match(/id="job-([^"]+)"/) || [])[1];
      if (id) vaultFollow(id, m, kind, j => {
        m.remove();
        if (proof) return leeVaultReview(st.doc, st.shelf || '', st.vault || '');
        status(j.result?.blocked?.length ? `${j.result.blocked.length} page(s) not sent`
          : isBook ? `${j.result.chapters} chapter(s), ${j.result.verses} verses · ${j.result.problems} problem(s) to check` : 'read again: a new version of each page',
          j.result?.blocked?.length ? 'err' : 'ok');
        done?.(j);
      });
      return;
    }
    jobs.insertAdjacentHTML('afterbegin', `<div class="lee-job error" data-kind="${esc(r.kind || '')}">` +
      `<span class="lee-job-error">${esc(r.error || 'it did not start')}</span></div>`);
  });
  if (names()) check();
  setTimeout(() => (names() ? $('[data-go]', m) : sels[0])?.focus(), 0);
  return m;
}
window.vaultPageSheet = vaultPageSheet;

function mountVaultSections(host, st, d) {
  const doc = d.doc || {}, sections = d.sections || [];
  const src = String(doc.source || '');
  const mdBase = /^(https?:|memory:|pointer:)/.test(src) || !src ? '' : src.slice(0, src.lastIndexOf('/'));
  host.innerHTML = `<div class="lee-vault-reader-wrap">${vaultHead(st, d)}<div class="lee-vault-reader">` +
    `<aside class="lee-vault-toc"><div class="lee-vault-sections">${vaultSectionRows(sections, '')}</div></aside>` +
    `<div class="lee-vault-body"${mdBase ? ` data-md-base="${esc(mdBase)}"` : ''}>${vaultPrivacy(d)}` +
    `<article class="lee-vault-text" data-markdown=""></article></div></div></div>`;
  wireVaultHead(host, st, d);
  const body = $('.lee-vault-text', host);
  const show = async node => {
    $$('.lee-vault-section', host).forEach(b => b.classList.toggle('active', b.dataset.node === node));
    try {
      const s = await api('/vault/section?' + new URLSearchParams({node, shelf: st.shelf || '', vault: st.vault || ''}));
      renderMarkdown(body, s.section?.text || '');
    } catch (e) { body.textContent = e.message || String(e); }
  };
  $$('.lee-vault-section', host).forEach(b => b.onclick = () => show(b.dataset.node));
  if (sections.length) show(sections[0].node_id);
  const notpii = $('[data-vault-notpii]', host);
  if (notpii) notpii.onclick = async e => {
    try {
      await post('/vault/not-pii', {doc: st.doc, shelf: st.shelf || '', vault: st.vault || '',
                                    clear: e.target.dataset.vaultNotpii === '1'});
      mountVault(host, st);
    } catch (err) { status(err.message || String(err), 'err'); }
  };
  const forcepii = $('[data-vault-pii]', host);
  if (forcepii) forcepii.onclick = async e => {
    try {
      await post('/vault/pii/mark', {doc: st.doc, shelf: st.shelf || '', vault: st.vault || '',
                                     force: e.target.dataset.vaultPii === '1'});
      mountVault(host, st);
    } catch (err) { status(err.message || String(err), 'err'); }
  };
}

/* The document in the vault is a copy; this opens the thing it was copied from. */
async function leeOpenVaultFile(doc, shelf = '', vault = '') {
  let d;
  try { d = await api('/vault/source?' + new URLSearchParams({doc, shelf, vault})); }
  catch (e) { return status(e.message || String(e), 'err'); }
  if (d.kind === 'url') return status('this was clipped from the web, not from a file', 'err');
  if (d.kind !== 'file') return status('this document was never a file', 'err');
  if (!d.exists) return status(`${d.path} is no longer there`, 'err');
  // The fs sandbox refuses paths outside an open folder. The server asks before it adds one, so there is one question.
  if (!d.inside_workspace) {
    try { await post('/fs/add-root', {path: d.parent}); await refreshFileTree(d.parent); }
    catch (e) { return status(e.message || String(e), e.body?.declined ? '' : 'err'); }
  }
  return leeOpenFile(d.path);
}
window.leeOpenVaultFile = leeOpenVaultFile;

/* Mark the block a citation or a field came from: the one holding its quote, else the one locate named. A masked quote finds nothing, so the index stands. */
function vaultMark(text, hl) {
  if (!hl || (!hl.quote && hl.block == null)) return null;
  const norm = t => String(t || '').replace(/\s+/g, ' ').trim().toLowerCase();
  const blocks = $$('.lee-vault-block, p, li, td', text), want = norm(hl.quote).slice(0, 40);
  const b = (want && blocks.find(x => norm(x.textContent).includes(want))) || (hl.block != null ? $$('.lee-vault-block', text)[hl.block] || blocks[hl.block] : null);
  $$('.lee-vault-marked', text).forEach(x => x.classList.remove('lee-vault-marked', 'active'));
  b?.classList.add('lee-vault-marked', 'active');
  b?.scrollIntoView({block: 'center'});
  return b;
}

/* The Fields drawer: each field with its page, quote and warnings; a click opens its page. */
async function vaultFields(st, box, go) {
  box.hidden = !box.hidden;
  if (box.hidden) return;
  const base = {doc: st.doc, shelf: st.shelf || '', vault: st.vault || ''};
  box.innerHTML = '<div class="lee-dim">reading the fields…</div>';
  let d;
  try { d = await api('/vault/fields?' + new URLSearchParams(base)); }
  catch (e) { box.textContent = e.message || String(e); return; }
  const shown = v => v == null || v === '' || (Array.isArray(v) && !v.length) ? '–' : typeof v === 'object' ? JSON.stringify(v) : String(v);
  box.innerHTML = `<div class="lee-vault-fieldshead"><strong>Fields</strong>` +
    `<small>${d.extracted ? `${esc(d.schema || '')}${d.model ? ' · ' + esc(d.model) : ''}` : 'nothing extracted yet'}</small></div>` +
    (d.fields || []).map((f, i) => `<button class="lee-vault-field${f.errors.length ? ' warn' : ''}${shown(f.value) === '–' ? ' empty' : ''}" data-field="${i}"` +
      `${f.page == null ? ' disabled' : ''}><strong>${esc(f.field.replace(/_/g, ' '))}</strong><span>${esc(shown(f.value))}</span>` +
      `${f.page == null ? '' : `<small>p. ${pageNo(f.page)}</small>`}${f.quote ? `<q>${esc(f.quote)}</q>` : ''}` +
      f.errors.map(w => `<span class="warn" data-field-warn>⚠ ${esc(w)}</span>`).join('') +
      `${f.stale ? '<span class="lee-dim">page read again since</span>' : ''}</button>`).join('') +
    `<form class="lee-vault-fieldsform" data-extract><select class="lee-input" name="model" id="vaultextractmodel" aria-label="the model that reads the fields">` +
    `<option value="">the conversation model</option></select><div class="lee-vault-sendline" data-send role="status"></div>` +
    `<button class="lee-btn go" type="submit">${d.extracted ? 're-extract' : 'extract'}</button><div class="lee-vault-jobs" data-job></div></form>`;
  $$('[data-field]', box).forEach(b => b.onclick = () => {
    const f = d.fields[+b.dataset.field];
    if (f.page != null) go(f.page, {quote: f.quote || shown(f.value), block: f.block});
  });
  const form = $('[data-extract]', box), sel = form.elements.model;
  for (const r of await vaultModels()) sel.add(new Option(`${r.label} · ${r.local ? 'on this Mac' : 'hosted: ' + (r.provider || 'remote')}`, r.value));
  attachModelPicker(sel);
  const check = async () => {
    const c = await vaultCall('/vault/send-check', {refs: st.doc, shelf: base.shelf, vault: base.vault, model: sel.value});
    const line = $('[data-send]', form);
    line.textContent = c.ok ? c.why : c.error;
    line.className = 'lee-vault-sendline' + (c.ok && c.check_ok ? '' : ' blocked');
  };
  sel.addEventListener('change', check);
  check();
  form.onsubmit = async e => {
    e.preventDefault();
    const r = await vaultCall('/vault/extract', {...base, model: sel.value}), jobs = $('[data-job]', form);
    if (!r.html) return jobs.insertAdjacentHTML('afterbegin', `<div class="lee-job error" data-kind="${esc(r.kind || '')}"><span class="lee-job-error">${esc(r.error || 'it did not start')}</span></div>`);
    jobs.insertAdjacentHTML('afterbegin', r.html); htmx.process(jobs);
    const id = (r.html.match(/id="job-([^"]+)"/) || [])[1];
    if (id) vaultFollow(id, box, 'extract', () => { box.hidden = true; vaultFields(st, box, go); });
  };
}

async function leeOpenVaultDoc(doc, shelf = '', vault = '', title = '', jump = null) {
  lee.vaultJump = jump ? {doc, ...jump} : null;
  await htmx.ajax('POST', '/vault/open?' + new URLSearchParams({doc, shelf, vault, title}),
    {target: '#tabbar', swap: 'outerHTML'});
  return mountTab();
}
window.leeOpenVaultDoc = leeOpenVaultDoc;

/* The Chapters drawer: each chapter's verse numbers, a click opens the verse's page on its block; the problems are checked under Review > Verses. */
async function vaultChapters(st, box, go) {
  box.hidden = !box.hidden;
  if (box.hidden) return;
  const base = {doc: st.doc, shelf: st.shelf || '', vault: st.vault || ''};
  box.innerHTML = '<div class="lee-dim">gathering the verses…</div>';
  let b;
  try { b = await api('/vault/book?' + new URLSearchParams(base)); }
  catch (e) { box.textContent = e.message || String(e); return; }
  const open = b.probs.filter(p => p.state === 'open').length;
  box.innerHTML = `<div class="lee-vault-fieldshead"><strong>Chapters</strong><small>${b.chapters.length} · ${b.verses} verses · ${esc(b.preset)}</small></div>` +
    `<div class="lee-vault-bookbar"><button class="lee-btn${open ? ' warn' : ''}" data-book-probs>${open} problem${open === 1 ? '' : 's'} to check</button>` +
    `<button class="lee-btn" data-book-md>BOOK.md</button><button class="lee-btn" data-book-save>save beside the file</button></div>` +
    (b.changed.length ? `<div class="lee-dim" data-book-changed>pages ${b.changed.map(pageNo).join(', ')} read again since: the chapters follow the pages as they read now</div>` : '') +
    b.chapters.map((c, i) => `<section class="lee-vault-chapter" data-chapter="${i}"><strong>${esc(c.heading || `Chapter ${i + 1}`)}</strong>` +
      `<div class="lee-vault-verses">${c.verses.map((v, k) => `<button class="lee-vault-verse" data-verse="${i}.${k}" title="p. ${pageNo(v.page)} · ${esc(v.text.split('\n')[0])}">${esc(v.n)}</button>`).join('')}</div>` +
      (c.colophon ? `<small>${esc(c.colophon)}</small>` : '') + `</section>`).join('');
  $$('[data-verse]', box).forEach(el => el.onclick = () => {
    const [i, k] = el.dataset.verse.split('.').map(Number), v = b.chapters[i].verses[k];
    $$('.lee-vault-verse.active', box).forEach(x => x.classList.remove('active')); el.classList.add('active');
    go(v.page, {block: v.block, quote: v.block == null ? v.text.split('\n')[0] : ''});
  });
  $('[data-book-probs]', box).onclick = () => leeVaultReview(st.doc, st.shelf || '', st.vault || '', 'book');
  $('[data-book-md]', box).onclick = async () => {
    const r = await fetch('/vault/book.md?' + new URLSearchParams(base)), md = await r.text();
    if (!r.ok) return status(md, 'err');
    modal(`<div class="lee-mhead">BOOK.md<span class="sub">${esc(b.title)}</span></div><pre class="lee-vault-sent lee-review-md" data-book-preview>${esc(md)}</pre>`, null, null, {storageKey: 'vault-bookmd'});
  };
  $('[data-book-save]', box).onclick = async () => {
    const r = await vaultCall('/vault/book.md', base);
    status(r.ok ? `wrote ${r.path}` : r.error, r.ok ? 'ok' : 'err');
  };
}
/* ---- the Review queue: proofreading changes, personal information, types, verses and what the agent learned, decided from the keyboard ---- */

/* An accept files a new version of its page, which would make every other change on that page stale.
   So `a` stages a change, and a page's staged changes are applied together when the cursor leaves the
   page, on `A`, or from the apply bar. */

async function leeVaultReview(doc = '', shelf = '', vault = '', mode = '') {
  await leeVaultWorkbench('review');
  if (doc || mode) await htmx.ajax('GET', '/vault/view/review?' + new URLSearchParams({doc, shelf, vault, mode}), {target: '#vaultwbbody', swap: 'innerHTML'});
  mountReviews();
  $('.lee-vault-review')?.focus({preventScroll: true});
}
window.leeVaultReview = leeVaultReview;

function mountReviews() { $$('.lee-vault-review:not([data-mounted])').forEach(mountReview); }
document.addEventListener('htmx:afterSettle', mountReviews);

const reviewQ = (st, extra = {}) => new URLSearchParams({doc: st.doc, vault: st.vault, ...(st.doc ? {shelf: st.shelf} : {}), ...extra});
const rowKey = r => `${r.doc}|${r.page}`;
const rowQ = (st, r) => new URLSearchParams({doc: r.doc, shelf: r.shelf || '', vault: st.vault});

async function mountReview(host) {
  host.dataset.mounted = '1';
  host.__review = {vault: host.dataset.vault || '', doc: host.dataset.doc || '', shelf: host.dataset.shelf || '',
                   mode: host.dataset.mode || 'proof', doubts: false, at: 0, rows: [], undo: [], staged: new Map(), counts: {}, types: [], labels: [],
                   learned: {pending: [], lessons: [], chars: 0, limit: 0, error: ''}, ldiff: null};
  host.addEventListener('click', e => reviewClick(host, e));
  host.addEventListener('mousedown', e => { if (!e.target.closest('input, button, select, a')) setTimeout(() => host.focus({preventScroll: true}), 0); });
  await reviewLoad(host);
}

/* The learned queue is the agent's, not the vault's: fetched on its own, so a failure shows in its mode and leaves the rest. */
async function learnedLoad(st) {
  try { st.learned = {...await api('/agent/learned'), error: ''}; window.leeLearningShown?.(st.learned.learning); }
  catch (e) { st.learned = {pending: [], lessons: [], chars: 0, limit: 0, ...(e.body || {}), error: e.message || String(e)}; }
  st.ldiff = null;
}

async function reviewLoad(host) {
  const st = host.__review, tok = st.loads = (st.loads || 0) + 1, learned = learnedLoad(st);
  try {
    const [c, f, t, b] = await Promise.all([api('/vault/changes?' + reviewQ(st)), api('/vault/pii/findings?' + reviewQ(st, {state: 'found'})),
                                            api('/vault/types?' + new URLSearchParams({vault: st.vault})), api('/vault/book/problems?' + reviewQ(st))]);
    if (tok !== st.loads) return;     // a later load is on its way, and it is the one that counts
    st.changes = c.changes || []; st.findings = f.findings || []; st.probs = b.problems || [];
    st.types = (t.types || []).filter(r => !st.doc || r.doc === st.doc); st.labels = t.labels || [];
  } catch (e) { host.innerHTML = `<div class="lee-err">${esc(e.message || e)}</div>`; return; }
  await learned;
  if (tok !== st.loads) return;
  reviewPaint(host);
}

function reviewPaint(host) {
  const st = host.__review, proof = st.mode === 'proof', types = st.mode === 'types', book = st.mode === 'book', learned = st.mode === 'learned';
  st.rows = proof ? st.changes.filter(r => !st.doubts || r.state === 'doubt') : types ? st.types : book ? st.probs : learned ? st.learned.pending : st.findings;
  if (st.want) { const k = st.rows.findIndex(r => r.id === st.want); if (k >= 0) st.at = k; st.want = null; }
  st.at = Math.max(0, Math.min(st.at, st.rows.length - 1));
  const n = {proof: st.changes.length, pii: st.findings.length, types: st.types.length, book: st.probs.length, doubt: st.changes.filter(r => r.state === 'doubt').length,
             stale: st.changes.filter(r => r.stale).length, learned: st.learned.pending.length};
  const chip = (mode, label, k) => `<button class="lee-wb-subtab${st.mode === mode ? ' active' : ''}" data-review-mode="${mode}">${label} <span data-count="${mode}">${k}</span></button>`;
  let html = `<div class="lee-review-head">${chip('proof', 'Proofreading', n.proof)}${chip('pii', 'Personal info', n.pii)}${chip('types', 'Types', n.types)}${chip('book', 'Verses', n.book)}${chip('learned', st.learned.learning === false ? 'Learned · off' : 'Learned', n.learned)}` +
    (proof ? `<label class="lee-review-doubts"><input type="checkbox" data-review-doubts${st.doubts ? ' checked' : ''}> doubts only (d) · ${n.doubt}</label>` +
             (n.stale ? `<span class="lee-dim">${n.stale} stale</span>` : '') : '') +
    `<span class="lee-spacer"></span>` +
    (st.doc && proof ? `<button class="lee-btn" data-review-export>PROOFREAD.md</button><button class="lee-btn" data-review-save>save beside the file</button>` : '') +
    (st.doc && st.mode === 'pii' ? `<button class="lee-btn" data-review-scan title="find personal information in pages read before findings were kept">scan again</button>` : '') +
    (st.doc ? `<button class="lee-btn" data-review-all>every document</button>` : '') + `</div>` +
    `<div class="lee-review-staged" data-staged ${st.staged.size ? '' : 'hidden'}>${st.staged.size} staged to accept · ` +
    `<button class="lee-btn go" data-review-apply>apply</button></div>`;
  if (learned) return learnedPaint(host, html);
  if (!st.rows.length) html += `<div class="lee-wb-empty"><strong>${proof ? 'No changes to decide' : types ? 'No types to decide' : book ? 'No verse problems to check' : 'No personal information to decide'}</strong>` +
    `<span>${proof ? 'Proofread a document from its view (p) to file changes here.' : types ? 'A type the words cannot settle is proposed here; type untyped documents from Library.'
      : book ? 'Read a sanskrit or tamil book as a book of verses; missing numbers, doubled verses, mended akṣaras and counts that differ come here.' : 'Findings are filed as pages are read.'}</span></div>`;
  if (types) {
    st.rows.forEach((r, i) => {
      html += `<div class="lee-review-row lee-review-type${i === st.at ? ' active' : ''}" data-i="${i}" data-id="${esc(r.doc)}">` +
        `<div class="lee-review-doc">${esc(r.title || r.doc)}</div><div class="lee-review-change">` +
        `<span class="lee-vault-type proposed" data-proposed>${esc(String(r.proposed).replace(/_/g, ' '))}</span>` +
        `${r.doctype ? `<small>now ${esc(r.doctype)}</small>` : ''}<small>${esc(r.by || '')}${r.score != null ? ' · ' + Number(r.score).toFixed(2) : ''}</small></div></div>`;
    });
    host.innerHTML = html;
    $('.lee-review-row.active', host)?.scrollIntoView({block: 'nearest'});
    return;
  }
  let lastDoc = null, lastPage = null;
  st.rows.forEach((r, i) => {
    if (r.doc !== lastDoc) { html += `<div class="lee-review-doc">${esc(r.title || r.doc)}</div>`; lastDoc = r.doc; lastPage = null; }
    if (r.page !== lastPage) { html += `<div class="lee-review-page">${r.page == null ? 'the whole book' : `page ${pageNo(r.page)}`}</div>`; lastPage = r.page; }
    const q = rowQ(st, r);
    if (book) {
      html += `<div class="lee-review-row lee-review-prob${i === st.at ? ' active' : ''}" data-i="${i}" data-id="${esc(r.id)}" data-state="${esc(r.state)}">` +
        (r.page == null ? '' : `<img class="lee-review-img" loading="lazy" alt="" src="/vault/page/img?${q}&page=${r.page}&w=360">`) +
        `<div class="lee-review-change"><span data-prob>${esc(r.text)}</span><small>${esc(r.state)}</small>` +
        (r.page == null ? '' : `<button class="lee-btn" data-review-open="${i}" title="e: open the page to fix it">open page ${pageNo(r.page)}</button>`) + `</div></div>`;
      return;
    }
    const img = proof && r.box ? `/vault/page/crop?${q}&page=${r.page}&box=${r.box.join(',')}` : `/vault/page/img?${q}&page=${r.page}&w=360`;
    const staged = st.staged.has(r.id);
    html += `<div class="lee-review-row${i === st.at ? ' active' : ''}${r.stale ? ' stale' : ''}${staged ? ' staged' : ''}" data-i="${i}" data-id="${esc(r.id)}" data-state="${esc(r.state)}">` +
      `<img class="lee-review-img" loading="lazy" alt="" src="${img}">` +
      (proof ? `<div class="lee-review-change"><del>${esc(r.before || '∅')}</del> → <ins data-after>${esc(staged && st.staged.get(r.id).after != null ? st.staged.get(r.id).after : r.after || '∅')}</ins>` +
               `<small>${esc((r.by || []).join(', '))} · ${esc(staged ? 'staged' : r.state)}</small>` +
               (r.stale ? `<span class="lee-review-stalewhy">page re-read since</span><button class="lee-btn" data-review-reproof="${i}">proofread this page again</button>` : '') + `</div>`
             : `<div class="lee-review-change"><code>${esc(r.preview || 'gone from the page')}</code><small>${esc(r.kind)} · ${esc(r.state)}</small></div>`) +
      `</div>`;
  });
  host.innerHTML = html;
  $('.lee-review-row.active', host)?.scrollIntoView({block: 'nearest'});
}

async function reviewClick(host, e) {
  const st = host.__review, t = e.target;
  if (t.closest('[data-review-mode]')) {
    await reviewCommit(host); st.mode = t.closest('[data-review-mode]').dataset.reviewMode; st.at = 0;
    if (st.mode === 'learned') await learnedLoad(st);    // a Dhrona batch may have proposed more since the tab opened
    return reviewPaint(host);
  }
  if (t.matches('[data-review-doubts]')) return leeReview('doubts', 0, host);
  if (t.closest('[data-learned-compact-go]')) return learnedCompact(host);
  const fold = t.closest('[data-learned-compact-with]');
  if (fold) return learnedCompact(host, fold.dataset.learnedCompactWith);
  if (t.closest('[data-review-apply]')) return reviewCommit(host);
  if (t.closest('[data-review-all]')) { await reviewCommit(host); st.doc = st.shelf = ''; return reviewLoad(host); }
  if (t.closest('[data-review-export]')) {
    const r = await fetch('/vault/proof.md?' + reviewQ(st));
    const md = await r.text();
    if (!r.ok) return status(md, 'err');
    return modal(`<div class="lee-mhead">PROOFREAD.md<span class="sub">${esc(st.doc)}</span></div><pre class="lee-vault-sent lee-review-md">${esc(md)}</pre>`,
                 null, null, {storageKey: 'vault-proofmd'});
  }
  if (t.closest('[data-review-save]')) {
    const r = await vaultCall('/vault/proof.md', {doc: st.doc, shelf: st.shelf, vault: st.vault});
    return status(r.ok ? `wrote ${r.path}` : r.error, r.ok ? 'ok' : 'err');
  }
  if (t.closest('[data-review-scan]')) {
    const r = await vaultCall('/vault/pii/scan', {doc: st.doc, shelf: st.shelf, vault: st.vault});
    if (!r.ok) return status(r.error, 'err');
    return reviewLoad(host);
  }
  if (t.closest('[data-review-open]')) return reviewOpen(st, st.rows[+t.closest('[data-review-open]').dataset.reviewOpen]);
  if (t.closest('[data-review-reproof]')) return reviewReproof(host, st.rows[+t.closest('[data-review-reproof]').dataset.reviewReproof]);
  const row = t.closest('.lee-review-row');
  if (row) return reviewMove(host, +row.dataset.i);
}

async function reviewMove(host, i) {
  const st = host.__review, from = st.rows[st.at], to = st.rows[i];
  if (!to) return;
  st.at = i; st.want = to.id;
  if (st.mode === 'learned') { st.want = null; $$('.lee-review-row', host).forEach(r => r.classList.toggle('active', +r.dataset.i === i)); return learnedDiff(host); }
  if (from && rowKey(from) !== rowKey(to) && [...st.staged.values()].some(s => rowKey(s.row) === rowKey(from))) return reviewCommit(host, rowKey(from));
  $$('.lee-review-row', host).forEach(r => r.classList.toggle('active', +r.dataset.i === i));
  $('.lee-review-row.active', host)?.scrollIntoView({block: 'nearest'});
}

/* Apply the staged accepts, one call per document so each page gets one new version. */
async function reviewCommit(host, key = null) {
  const st = host.__review;
  const groups = new Map();
  for (const [id, s] of st.staged) if (!key || rowKey(s.row) === key) {
    if (!groups.has(s.row.doc)) groups.set(s.row.doc, []);
    groups.get(s.row.doc).push(s);
  }
  if (!groups.size) return;
  for (const [doc, ss] of groups) {
    const edits = Object.fromEntries(ss.filter(s => s.after != null).map(s => [s.row.id, s.after]));
    const r = await vaultCall('/vault/changes/accept', {doc, shelf: ss[0].row.shelf || '', vault: st.vault, ids: ss.map(s => s.row.id).join(','),
                                                       ...(Object.keys(edits).length ? {edits: JSON.stringify(edits)} : {})});
    ss.forEach(s => st.staged.delete(s.row.id));
    st.undo = st.undo.filter(u => !(u.t === 'stage' && ss.some(s => s.row.id === u.id)));
    if (r.ok) { st.undo.push({t: 'accept', doc, shelf: ss[0].row.shelf || '', ids: ss.map(s => s.row.id)}); status(`accepted ${r.accepted} change${r.accepted === 1 ? '' : 's'}`, 'ok'); }
    else status(r.kind === 'stale' ? 'the page was read again: proofread it again' : r.error, 'err');
  }
  await reviewLoad(host);
}

async function reviewReproof(host, r) {
  if (!r) return;
  const st = host.__review, base = {doc: r.doc, shelf: r.shelf || '', vault: st.vault};
  const est = await vaultCall('/vault/proofread', {...base, estimate: true});
  const readers = est.remembered?.readers || [];
  if (!readers.length) return vaultPageSheet('proof', {...base, title: r.title}, {pages: String(pageNo(r.page))});
  const go = await vaultCall('/vault/proofread', {...base, readers: readers.join(','), pages: String(pageNo(r.page)), agree: est.remembered.agree || 2});
  if (!go.html) return vaultPageSheet('proof', {...base, title: r.title}, {pages: String(pageNo(r.page))});
  status(`proofreading page ${pageNo(r.page)} again with ${readers.join(', ')}`);
  const id = (go.html.match(/id="job-([^"]+)"/) || [])[1];
  vaultFollow(id, host, 'proof', () => reviewLoad(host));
}

async function reviewDecide(host, url, rows, undo) {
  const st = host.__review, r0 = rows[0];
  const r = await vaultCall(url, {doc: r0.doc, shelf: r0.shelf || '', vault: st.vault, ids: rows.map(r => r.id).join(',')});
  if (!r.ok) { status(r.kind === 'stale' ? 'gone or changed since: the queue is reloaded' : r.error, 'err'); return reviewLoad(host); }
  if (undo) st.undo.push({...undo, doc: r0.doc, shelf: r0.shelf || '', ids: rows.map(r => r.id)});
  await reviewLoad(host);
}

function reviewEdit(host) {
  const st = host.__review, r = st.rows[st.at], el = $('.lee-review-row.active [data-after]', host);
  if (!r || !el || st.mode !== 'proof') return;
  if (r.stale) return status('the page was read again since: proofread it again', 'err');
  const inp = document.createElement('input');
  inp.className = 'lee-input lee-review-edit'; inp.value = st.staged.get(r.id)?.after ?? r.after ?? '';
  el.replaceWith(inp); inp.focus(); inp.select();
  inp.onkeydown = e => {
    e.stopPropagation();
    if (e.key === 'Escape') { e.preventDefault(); reviewPaint(host); host.focus(); }
    if (e.key !== 'Enter') return;
    e.preventDefault();
    st.staged.set(r.id, {row: r, after: inp.value});
    st.undo.push({t: 'stage', id: r.id});
    reviewPaint(host); host.focus();
  };
}

/* Keys queue behind each other: a second key acts on the queue the first one left. */
function leeReview(act, n = 1, el = null) {
  const host = el || document.activeElement?.closest?.('.lee-vault-review') || $('.lee-vault-review');
  if (!host?.__review) return status('open the Review tab first', 'err');
  return host.__chain = (host.__chain || Promise.resolve()).then(() => reviewAct(host, act, n)).catch(e => status(e.message || String(e), 'err'));
}

async function reviewAct(host, act, n) {
  const st = host.__review, r = st.rows[st.at], proof = st.mode === 'proof';
  const onPage = rows => rows.filter(x => r && rowKey(x) === rowKey(r));
  if (act === 'step') return reviewMove(host, Math.max(0, Math.min(st.rows.length - 1, st.at + n)));
  if (st.mode === 'learned') return learnedAct(host, act, r);
  if (act === 'doubts') { if (!proof) return; await reviewCommit(host); st.doubts = !st.doubts; st.at = 0; return reviewPaint(host); }
  if (act === 'undo') {
    const u = st.undo.pop();
    if (!u) return status('nothing to undo', 'err');
    if (u.t === 'stage') { st.staged.delete(u.id); return reviewPaint(host); }
    if (u.t === 'type') {
      const res = await vaultCall('/vault/types/undo', {doc: u.doc, shelf: u.shelf, vault: st.vault, was: JSON.stringify(u.was)});
      status(res.ok ? 'undone' : res.error, res.ok ? 'ok' : 'err');
      return reviewLoad(host);
    }
    const url = u.t === 'pii' ? '/vault/pii/findings/undo' : u.t === 'book' ? '/vault/book/probs/undo' : '/vault/changes/undo';
    const res = await vaultCall(url, {doc: u.doc, shelf: u.shelf, vault: st.vault, ids: u.ids.join(',')});
    status(res.ok ? 'undone' : res.error, res.ok ? 'ok' : 'err');
    return reviewLoad(host);
  }
  if (act === 'edit' && st.mode === 'types') return reviewRetype(host);
  if (act === 'edit' && st.mode === 'book') return r ? reviewOpen(st, r) : status('nothing to open', 'err');
  if (act === 'edit') return reviewEdit(host);
  if (!r) return status('nothing to decide', 'err');
  if (st.mode === 'types') {
    if (act === 'accept') return reviewType(host, 'accept', r);
    if (act === 'reject') return reviewType(host, 'reject', r);
    return status('types are decided one document at a time', 'err');
  }
  if (st.mode === 'book') {
    if (act === 'accept') return reviewDecide(host, '/vault/book/probs/accept', [r], {t: 'book'});
    if (act === 'reject') return reviewDecide(host, '/vault/book/probs/reject', [r], {t: 'book'});
    if (act === 'page') return reviewDecide(host, '/vault/book/probs/accept', onPage(st.rows), {t: 'book'});
    return status('verse problems are checked one book at a time', 'err');
  }
  if (!proof) {
    if (act === 'accept') return reviewDecide(host, '/vault/pii/findings/accept', [r], {t: 'pii'});
    if (act === 'reject') return reviewDecide(host, '/vault/pii/findings/reject', [r], {t: 'pii'});
    if (act === 'page') return reviewDecide(host, '/vault/pii/findings/accept', onPage(st.rows), {t: 'pii'});
    return;
  }
  if (act === 'reject') {
    if (st.staged.has(r.id)) { st.staged.delete(r.id); }
    return reviewDecide(host, '/vault/changes/reject', [r], {t: 'reject'});
  }
  if (r.stale && act === 'accept') return status('the page was read again since: proofread it again', 'err');
  if (act === 'accept') {
    if (!st.staged.has(r.id)) { st.staged.set(r.id, {row: r, after: null}); st.undo.push({t: 'stage', id: r.id}); }
    reviewPaint(host);
    return st.at < st.rows.length - 1 ? reviewMove(host, st.at + 1) : reviewCommit(host);
  }
  if (act === 'page') {
    onPage(st.rows).filter(x => x.state === 'proposed' && !x.stale && !st.staged.has(x.id)).forEach(x => st.staged.set(x.id, {row: x, after: null}));
    return reviewCommit(host, rowKey(r));
  }
  if (act === 'doc') {
    const all = st.changes.filter(x => x.doc === r.doc && x.state === 'proposed' && !x.stale);
    if (!all.length) return status('nothing proposed in this document', 'err');
    if (!await confirmDialog('accept the document', `Accept all ${all.length} proposed change${all.length === 1 ? '' : 's'} in ${r.title || r.doc}?`, 'accept')) return;
    all.forEach(x => { if (!st.staged.has(x.id)) st.staged.set(x.id, {row: x, after: null}); });
    return reviewCommit(host);
  }
}
window.leeReview = leeReview;

/* A type is a meta field, not a page: an accept or a reject is undone by putting back what the route said was there. */
async function reviewType(host, verdict, r, doctype = '') {
  const st = host.__review;
  const res = await vaultCall(`/vault/types/${verdict}`, {doc: r.doc, shelf: r.shelf || '', vault: st.vault, ...(doctype ? {doctype} : {})});
  if (!res.ok) { status(res.kind === 'stale' ? 'decided elsewhere since: the queue is reloaded' : res.error, 'err'); return reviewLoad(host); }
  st.undo.push({t: 'type', doc: r.doc, shelf: r.shelf || '', was: res.was});
  status(verdict === 'accept' ? `typed ${res.doctype}` : 'proposal dropped', 'ok');
  return reviewLoad(host);
}

function reviewRetype(host) {
  const st = host.__review, r = st.rows[st.at], el = $('.lee-review-row.active [data-proposed]', host);
  if (!r || !el) return;
  const sel = document.createElement('select');
  sel.className = 'lee-input lee-review-edit'; sel.setAttribute('aria-label', 'another type');
  sel.innerHTML = st.labels.map(l => `<option value="${esc(l)}"${l === r.proposed ? ' selected' : ''}>${esc(l.replace(/_/g, ' '))}</option>`).join('');
  el.replaceWith(sel); sel.focus();
  sel.onkeydown = e => {
    e.stopPropagation();
    if (e.key === 'Escape') { e.preventDefault(); reviewPaint(host); host.focus(); }
    if (e.key === 'Enter') { e.preventDefault(); host.focus(); reviewType(host, 'accept', r, sel.value); }
  };
}

/* A verse problem is fixed on its page: re-read it, or proofread it. */
function reviewOpen(st, r) {
  if (!r) return;
  if (r.page == null) return leeOpenVaultDoc(r.doc, r.shelf || '', st.vault, r.title);
  return leeOpenVaultDoc(r.doc, r.shelf || '', st.vault, r.title, {page: r.page});
}

/* ---- what the agent learned: Dhrona's candidates for the learned folder, one git branch each ---- */

/* Compact runs one model turn: the button stays pending while this tab's request or any other one runs, as `/agent/learned` says. */
function learnedPaint(host, html) {
  const st = host.__review, L = st.learned, near = L.limit && L.chars >= L.limit * 0.9, busy = st.lcompact?.busy || L.compacting;
  html += `<div class="lee-review-learned-head"><span class="lee-dim" title="the learned folder">${esc(L.folder || '')}</span>` +
    `<span data-learned-chars class="${near ? 'lee-warn' : 'lee-dim'}">AGENTS.md ${Number(L.chars || 0).toLocaleString()} of ${Number(L.limit || 0).toLocaleString()} characters</span>` +
    `<span data-learned-compact><button class="lee-btn" data-learned-compact-go${busy ? ' disabled' : ''} title="ask Dhrona for a shorter AGENTS.md, proposed as a candidate here">${busy ? 'compacting…' : 'Compact'}</button></span></div>`;
  if (L.learning === false) html += `<div class="lee-dim" data-learning-off>learning is off: briefings leave the learned folder out, Dhrona proposes nothing new and no lessons are kept. ` +
    `What waits here can still be accepted or rejected. Turn it on under the agent's settings › learning, or with <code>/learned on</code>.</div>`;
  if (st.lcompact?.error) html += `<div class="lee-err" data-learned-compact-error>${esc(st.lcompact.error)}</div>`;
  if (L.error) html += `<div class="lee-err" data-learned-error>${esc(L.error)}</div>`;
  /* A refusal stays on screen until the next decision. One for size offers to fold the candidate into a compaction. */
  const ref = st.lrefused;
  if (ref) html += `<div class="lee-err" data-learned-refused>${esc(ref.error)}` +
    (ref.length ? ` <button class="lee-btn" data-learned-compact-with="${esc(ref.id)}"${busy ? ' disabled' : ''}>Compact with this candidate</button>` : '') + `</div>`;
  if (!st.rows.length && !L.error) html += `<div class="lee-wb-empty"><strong>Nothing the agent learned waits for review</strong>` +
    `<span>Dhrona proposes changes to the learned folder; each waits here until you accept (a) or reject (x) it.</span></div>`;
  st.rows.forEach((r, i) => {
    html += `<div class="lee-review-row lee-review-learned${i === st.at ? ' active' : ''}" data-i="${i}" data-id="${esc(r.id)}">` +
      `<div class="lee-review-change"><span data-subject>${esc(r.subject || r.id)}</span>` +
      `<small>${esc((r.files || []).join(', '))} · ${esc(new Date(r.at * 1000).toLocaleString())}</small>` +
      (r.stale ? `<small class="lee-review-stalewhy" data-learned-stale>stale: ${esc(r.stale)}</small>` : '') + `</div></div>`;
  });
  html += `<div class="lee-diff lee-review-learned-diff" data-learned-diff></div><div class="lee-review-doc">Recent lessons</div>` +
    (L.lessons?.length ? `<ul class="lee-review-lessons">${L.lessons.map(l => `<li>${esc(l.lesson)}${l.cue ? ` <small>${esc(l.cue)}</small>` : ''}</li>`).join('')}</ul>`
                       : '<div class="lee-dim">no lessons kept yet</div>');
  host.innerHTML = html;
  $('.lee-review-row.active', host)?.scrollIntoView({block: 'nearest'});
  learnedDiff(host);
  if (!st.lcompact?.busy) learnedWatch(host);
}

/* The reply can outlive the request (a webview drops a long one), so a pending compaction is also watched through `/agent/learned`. */
async function learnedCompact(host, id = '') {
  const st = host.__review;
  if (st.lcompact?.busy || st.learned.compacting) return;
  st.lcompact = {busy: true}; st.lrefused = null; reviewPaint(host);
  try {
    const d = await post('/agent/learned/compact', id ? {id} : {});
    st.lcompact = {};
    if (d.id) st.want = d.id;
    status(d.id ? `compaction proposed as ${d.id}: ${Number(d.before).toLocaleString()} → ${Number(d.after).toLocaleString()} characters` : 'nothing to compact', 'ok');
  } catch (e) {
    st.lcompact = e.body ? {error: e.message || String(e)} : {};
    if (e.body) status(e.message || String(e), 'err');
  }
  await learnedLoad(st);
  if (st.mode === 'learned') reviewPaint(host);
  learnedWatch(host);
}

function learnedWatch(host) {
  const st = host.__review;
  if (!st.learned.compacting || st.lwatch) return;
  st.lwatch = setTimeout(async () => {
    st.lwatch = 0;
    if (!host.isConnected) return;
    await learnedLoad(st);
    if (st.mode === 'learned') reviewPaint(host);
    learnedWatch(host);
  }, 3000);
}

/* j and k fire faster than git answers: only the diff of the row still active is painted. */
async function learnedDiff(host) {
  const st = host.__review, r = st.rows[st.at], box = $('[data-learned-diff]', host);
  if (!box) return;
  if (!r) { box.innerHTML = ''; return; }
  if (st.ldiff?.id === r.id) { box.innerHTML = st.ldiff.html; return; }
  const tok = st.ldiffTok = (st.ldiffTok || 0) + 1;
  box.innerHTML = '<div class="lee-dim">reading the diff</div>';
  let html;
  try {
    const d = await post('/agent/learned/diff', {id: r.id});
    html = (d.rows?.length ? diffHtml(d.rows) : '<div class="lee-dim">no change</div>') + (d.truncated ? '<div class="lee-dim">the diff is cut short here</div>' : '');
  } catch (e) { html = `<div class="lee-err">${esc(e.message || e)}</div>`; }
  if (tok !== st.ldiffTok) return;
  st.ldiff = {id: r.id, html};
  const b = $('[data-learned-diff]', host); if (b) b.innerHTML = html;
}

/* An accept restacks the rest: say how many moved onto the new HEAD and which no longer apply. */
function learnedAccepted(d) {
  const head = d.commit ? `accepted ${d.id} as ${d.commit}` : `accepted ${d.id}: the learned folder already held it`;
  const moved = (d.moved || []).length, stale = d.stale || [];
  return head + (moved ? ` · ${moved} candidate${moved === 1 ? '' : 's'} moved onto it` : '') + (stale.length ? ` · stale now: ${stale.join(', ')}` : '');
}

/* Accepted and rejected at once: a candidate is its own commit, so there is nothing to stage, and git keeps no undo here. */
async function learnedAct(host, act, r) {
  const st = host.__review;
  if (act !== 'accept' && act !== 'reject')
    return status(act === 'undo' ? 'an accept or a reject of what the agent learned is not undone here' : 'what the agent learned is decided one candidate at a time', 'err');
  if (!r) return status('nothing to decide', 'err');
  st.lrefused = null;
  try {
    const d = await post(`/agent/learned/${act}`, {id: r.id});
    status(act === 'reject' ? `rejected ${d.id}` : learnedAccepted(d), 'ok');
  } catch (e) {
    status(e.message || String(e), 'err');
    if (act === 'accept' && e.body) st.lrefused = {id: r.id, error: e.message || String(e), length: e.body.length || 0};
  }
  await learnedLoad(st);
  reviewPaint(host);
}
/* The branch pill as a real Git control, and the three remote gestures beside it.
 *
 * One popup over branches and actions, in the order JetBrains settled on: what to do with the
 * branch you are on, then how to get a different one, then the branches themselves. Names
 * containing a `/` fold into a folder by their first segment, because forty `cursor/…` branches
 * are otherwise a wall of near-identical rows.
 *
 * Everything here posts to `/git/action`. The one new route is `/git/clone`, because a clone is
 * minutes of network and cannot be a request.
 */

const GIT_RECENT_KEY = 'lee-git-recent-branches';
const gitBranchFolders = new Set();      // which prefix folders are expanded, this session

function recentBranches(root) {
  try { return JSON.parse(localStorage.getItem(GIT_RECENT_KEY) || '{}')[root] || []; }
  catch (_) { return []; }
}
function rememberBranch(root, name) {
  let all = {};
  try { all = JSON.parse(localStorage.getItem(GIT_RECENT_KEY) || '{}'); } catch (_) {}
  all[root] = [name, ...(all[root] || []).filter(x => x !== name)].slice(0, 8);
  try { localStorage.setItem(GIT_RECENT_KEY, JSON.stringify(all)); } catch (_) {}
}

// A remote branch's first segment is its remote, not a folder: `origin/cursor/x` belongs in
// `cursor` beside the local branch of the same name.
function branchLeaf(b) { return b.remote ? b.name.split('/').slice(1).join('/') : b.name; }
function branchFolder(b) { const cut = branchLeaf(b).indexOf('/'); return cut < 0 ? '' : branchLeaf(b).slice(0, cut); }
function branchDrift(b) {
  return `${b.behind ? `<i class="behind">↙${b.behind}</i>` : ''}${b.ahead ? `<i class="ahead">↗${b.ahead}</i>` : ''}`;
}

function branchRow(b, label) {
  const upstream = b.gone ? 'upstream gone' : b.upstream || (b.remote ? 'remote' : 'no upstream');
  return `<button class="lee-mrow lee-branch-row${b.current ? ' current' : ''}" data-branch="${esc(b.name)}">` +
    `<span class="lee-branch-mark">${b.current ? '✓' : b.remote ? '☁' : '›'}</span>` +
    `<strong>${esc(label ?? branchLeaf(b))}</strong><span class="sub">${esc(upstream)}</span>` +
    `<span class="lee-spacer"></span>${branchDrift(b)}` +
    `<span class="lee-branch-more" data-more="${esc(b.name)}" role="button" title="branch actions">•••</span></button>`;
}

function branchGroup(title, rows, fold = false) {
  if (!rows.length) return '';
  let body = rows.map(b => branchRow(b)).join('');
  if (fold) {
    const folders = new Map(), loose = [];
    for (const b of rows) {
      const name = branchFolder(b);
      if (!name) { loose.push(b); continue; }
      if (!folders.has(name)) folders.set(name, []);
      folders.get(name).push(b);
    }
    // A collapsed folder's branches are absent from the DOM rather than hidden, so the modal's
    // arrow-key walk over `.lee-mrow` never selects a row nobody can see.
    body = loose.map(b => branchRow(b)).join('') + [...folders].map(([name, kids]) => {
      const open = gitBranchFolders.has(name) || kids.some(k => k.current);
      return `<button class="lee-mrow lee-branch-folder" data-folder="${esc(name)}">` +
        `<span class="lee-branch-mark">${open ? '▾' : '▸'}</span><strong>${esc(name)}/</strong>` +
        `<span class="sub">${kids.length}</span></button>` +
        (open ? kids.map(b => branchRow(b, branchLeaf(b).slice(name.length + 1))).join('') : '');
    }).join('');
  }
  return `<div class="lee-branch-group"><header>${esc(title)}</header>${body}</div>`;
}

async function switchBranch(d, name) {
  const b = (d.branches || []).find(x => x.name === name);
  if (!b || b.current) return leeLeft('git');
  rememberBranch(d.root, name);
  // A remote-only branch is checked out by its leaf name, and Git creates the tracking branch.
  // `/git/action` answers with the same `info()` that `/git/info` does, so a caller showing
  // branches can repaint from the reply.
  const fresh = await gitDo('checkout', {branch: b.remote ? branchLeaf(b) : name});
  const out = fresh.outcome || {};
  // A switch always reports that HEAD moved, which buries what became of the work it set aside.
  if (out.message) { leeLog('git', 'checkout', out.message, 'ok'); status(`git checkout · ${firstLine(out.message)}`, 'ok'); }
  return fresh;
}

function compareBranch(d, name) {
  Object.assign(gitUI, {tab: 'review', review: null, reviewBase: d.branch, reviewHead: name});
  leeLeft('git'); leeGitRefresh();
}

// `after` takes the snapshot each mutation answers with, so whatever opened this menu can show
// the repository as it is now rather than as it was when it was opened.
function branchActions(anchor, d, b, after = (x) => x) {
  if (!b) return;
  const leaf = branchLeaf(b);
  const act = async (op, extra) => { try { return after(await branchAct(op, extra)); } catch (_) {} };
  const rows = [
    {label: `Checkout ${leaf}`, disabled: b.current,
     run: async () => { try { after(await switchBranch(d, b.name)); } catch (_) {} }},
    {label: 'New Branch from…', detail: b.name, run: async () => {
      const branch = await inputDialog('new branch', `Branch name, starting at ${b.name}`, '', 'feature/name');
      if (branch) await act('create', {branch, start: b.name});
    }},
    {separator: true},
    {label: 'Compare with current', detail: `${d.branch} … ${leaf}`, disabled: b.current, run: () => compareBranch(d, b.name)},
    // Through the previews, as the git panel's identical entries go.
    {label: `Rebase ${d.branch} onto ${leaf}`, disabled: b.current, run: () => showRebasePreview(b.name, d, act)},
    {label: `Merge ${leaf} into ${d.branch}`, disabled: b.current, run: () => showMergePreview(b.name, d, act)},
  ];
  if (!b.remote && !b.current) rows.push({separator: true}, {label: `Delete ${leaf}`, warn: true, run: async () => {
    if (!await confirmDialog('delete branch', `Delete ${b.name}?`, 'delete')) return;
    // Never `-D` behind one confirmation. Git refusing an unmerged branch is the warning, and
    // `act` answering undefined is that refusal, so the second ask is the one that forces it.
    if (await act('delete', {branch: b.name})) return;
    if (await confirmDialog('force delete',
        `Git refused: ${b.name} has commits that are on no other branch. Delete it anyway? ` +
        'The log keeps the commit it was at, so it can be put back by sha.', 'force delete'))
      await act('delete', {branch: b.name, force: true});
  }});
  openChromeMenu(anchor, rows);
}

// Where "why is this divergent" usually starts: the PR, and whether its base moved under it.
async function branchPr(d) {
  const r = await api(gitUrl('/git/pr', {repo: gitUI.repo, branch: d.branch})).catch(() => null);
  const pr = r?.pr;
  if (!pr) return {id: 'pr', label: 'Pull request', detail: r?.note || 'unavailable', run: () => status(r?.note || 'no pull request', 'ok')};
  const c = pr.checks || {};
  const health = c.failing?.length ? `${c.failing.length} check${c.failing.length === 1 ? '' : 's'} red`
              : c.pending ? `${c.pending} check${c.pending === 1 ? '' : 's'} running` : 'checks green';
  return {id: 'pr', label: `#${pr.number} ${pr.title}`.slice(0, 60),
    detail: `${pr.base}${pr.behind_base ? ` · ${pr.behind_base} behind base` : ''} · ${health}`,
    run: () => openExternal(pr.url)};
}

function branchTopActions(d) {
  const changed = (d.changes || []).length;
  const remotes = (d.branches || []).filter(b => b.remote).length;
  return [
    {id: 'update', label: 'Update Project', detail: d.behind ? `${d.behind} behind ${d.upstream}` : 'pull, autostashing local work'},
    {id: 'fetch', label: 'Fetch', detail: remotes ? `refresh ${remotes} remote branch${remotes === 1 ? '' : 'es'}` : 'refresh remote branches'},
    {id: 'commit', label: 'Commit…', detail: changed ? `${changed} changed file${changed === 1 ? '' : 's'}` : 'working tree clean'},
    {id: 'push', label: 'Push', detail: !d.upstream ? 'publish this branch' : d.ahead ? `${d.ahead} ahead` : 'nothing to push'},
    {id: 'new', label: 'New Branch…', detail: `from ${d.branch}`},
    {id: 'revision', label: 'Checkout Tag or Revision…', detail: 'any tag, commit or branch'},
    {id: 'clone', label: 'Clone Repository…', detail: 'into a folder, then open it'},
  ];
}

const branchAct = async (op, extra = {}) => { const d = await gitDo(op, extra); refreshScmIfOpen(d); return d; };

function runBranchAction(id, d) {
  if (id === 'update') return d.ahead && d.behind ? showSyncPlan(d) : gitDo('pull');
  if (id === 'push') return leeGitQuick('push');
  if (id === 'commit') { gitUI.tab = 'changes'; leeLeft('git'); return leeGitRefresh(); }
  if (id === 'clone') return leeCloneRepo();
  if (id === 'new') return inputDialog('new branch', `Branch name, starting at ${d.branch}`, '', 'feature/name')
    .then(branch => branch && gitDo('create', {branch, start: d.branch}));
  return inputDialog('checkout tag or revision', 'Tag, commit or branch', '', 'v1.2.0  ·  a1b2c3d')
    .then(ref => ref && gitDo('checkout', {branch: ref}));
}

// The pill is about the active tab's repository, or the pinned one, never the panel's last snapshot.
async function leeBranchMenu(anchor) {
  let d;
  try { d = await gitInfo(gitUrl('/git/info', {repo: gitUI.repo})); }
  catch (e) { return leeFail('git', 'branches', e); }
  let recent = recentBranches(d.root);
  let search = null;
  const m = modal(
    `<div class="lee-mhead">Git Branches<span class="sub">${esc(gitRepoName(d.root))} · on ${esc(d.branch)}</span></div>` +
    `<input class="lee-input" id="branchsearch" autocomplete="off" spellcheck="false"` +
    ` placeholder="Search branches and actions…" aria-label="search branches and actions">` +
    `<div class="lee-modallist lee-branchlist" id="branchlist"></div>` +
    `<div class="lee-mfoot"><span class="lee-dim">Enter checks out · ••• compares, rebases and merges</span></div>`,
    // The arrow keys take the caret out of the box, so a printable key puts it back.
    e => { if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && document.activeElement !== search) search.focus(); },
    null, {className: 'lee-branchmodal', storageKey: 'branches'});
  search = m.querySelector('#branchsearch');
  const list = m.querySelector('#branchlist');
  const sub = m.querySelector('.lee-mhead .sub');

  let prRow = null;
  /* Replacing the children of a scrolled element puts it at scrollTop 0, so `keep` restores the
     old offset. That is exact for a fold, which only adds or removes rows below the folder
     clicked. Typing is the one repaint that goes back to the top, because those are different
     results rather than the same list rearranged. */
  const paint = (keep = true) => {
    const at = keep ? list.scrollTop : 0;
    const q = search.value.trim().toLowerCase();
    const hit = text => !q || String(text).toLowerCase().includes(q);
    const acts = [...branchTopActions(d), ...(prRow ? [prRow] : [])].filter(a => hit(a.label));
    const all = (d.branches || []).filter(b => hit(`${b.name} ${b.subject} ${b.author}`));
    const near = recent.map(n => all.find(b => b.name === n && !b.current)).filter(Boolean);
    const rest = all.filter(b => !near.includes(b));
    list.innerHTML =
      (acts.length ? `<div class="lee-branch-group">${acts.map(a =>
        `<button class="lee-mrow lee-branch-action" data-act="${a.id}"><strong>${esc(a.label)}</strong>` +
        `<span class="lee-spacer"></span><span class="sub">${esc(a.detail)}</span></button>`).join('')}</div>` : '') +
      branchGroup('Recent', near) +
      branchGroup('Local', rest.filter(b => !b.remote), true) +
      branchGroup('Remote', rest.filter(b => b.remote), true) ||
      '<div class="lee-dim">nothing matches</div>';
    list.scrollTop = at;
  };

  /* A modal that goes on describing the branch you just left puts the tick against the wrong row
     and offers every action against the old HEAD. Each mutation answers with a whole `info()`, so
     take it and repaint rather than closing.

     `recent` is re-read because checking out writes to it. `prRow` is dropped because the pull
     request belongs to the branch that was current when it was fetched, and two switches in quick
     succession would otherwise show the first answer under the second branch's heading. */
  const showPr = () => {
    const asked = d.branch;
    branchPr(d).then(r => { if (m.isConnected && d.branch === asked) { prRow = r; paint(); } });
  };
  const reload = (fresh) => {
    if (!m.isConnected || !fresh || !fresh.branches) return fresh;
    d = fresh;
    recent = recentBranches(d.root);
    if (sub) sub.textContent = `${gitRepoName(d.root)} · on ${d.branch}`;
    prRow = null;
    paint();
    showPr();
    return fresh;
  };

  list.onclick = e => {
    const more = e.target.closest('[data-more]');
    if (more) return branchActions(more, d, (d.branches || []).find(b => b.name === more.dataset.more), reload);
    const folder = e.target.closest('[data-folder]');
    if (folder) {
      const name = folder.dataset.folder;
      gitBranchFolders.has(name) ? gitBranchFolders.delete(name) : gitBranchFolders.add(name);
      return paint();
    }
    const row = e.target.closest('[data-branch]');
    if (row) {
      const b = (d.branches || []).find(x => x.name === row.dataset.branch);
      // Picking the branch already checked out is not a switch, it is "show me this repository".
      if (b && b.current) { m.remove(); return leeLeft('git'); }
      // `gitDo` re-throws what it has already reported. A refused checkout is a normal answer,
      // and the modal is still describing the branch that refused to be left.
      return switchBranch(d, row.dataset.branch).then(reload).catch(() => {});
    }
    const act = e.target.closest('[data-act]');
    if (act) {
      // Fetching comes before picking a branch, so it repaints the list rather than closing it.
      if (act.dataset.act === 'fetch') return branchAct('fetch').then(reload).catch(() => {});
      m.remove();
      return act.dataset.act === 'pr' ? prRow.run() : runBranchAction(act.dataset.act, d);
    }
  };
  search.oninput = () => paint(false);
  paint();
  showPr();
  setTimeout(() => search.focus(), 0);
}
window.leeBranchMenu = leeBranchMenu;

// `pull` is --ff-only, so a diverged branch had nowhere to go. Every way out, rehearsed.
async function showSyncPlan(d) {
  try {
    const p = await api(gitUrl('/git/sync-plan', {repo: gitUI.repo, fetch: 1}));
    if (!p.upstream) return status(`${p.branch} has no upstream. Publish it first.`, 'err');
    if (!p.behind) return status(p.ahead ? `${p.ahead} ahead, nothing to pull` : 'already up to date', 'ok');
    const dirty = p.clean ? '' : `<div class="lee-git-merge-warning"><strong>Uncommitted changes to ${p.dirty.length} tracked file${p.dirty.length === 1 ? '' : 's'}</strong><span>${p.dirty.map(esc).join(' · ')}</span></div>`;
    // Only `merge` and `rebase` are rehearsed, so only they carry `conflicts`; none carries a name.
    const SYNC_LABEL = {'fast-forward': 'Fast-forward', merge: 'Merge', rebase: 'Rebase',
                        reset: 'Reset to the upstream'};
    const why = o => {
      const c = o.conflicts || [];
      return c.length
        ? `${c.length} file${c.length === 1 ? '' : 's'} conflict · ${c.slice(0, 4).map(esc).join(' · ')}${o.note ? ' · ' + esc(o.note) : ''}`
        : o.note ? esc(o.note) : 'nothing conflicts in the rehearsal';
    };
    const row = o => `<label class="lee-syncopt${o.available ? '' : ' off'}${o.destructive ? ' warn' : ''}">` +
      `<input type="radio" name="how" value="${o.op}"${o.op === p.recommended ? ' checked' : ''}${o.available ? '' : ' disabled'}>` +
      `<span><strong>${esc(SYNC_LABEL[o.op] || o.op)}</strong><span class="sub">${why(o)}</span></span></label>`;
    const m = modal(`<div class="lee-mhead">Sync ${esc(p.branch)}<span class="sub">${p.ahead} ahead · ${p.behind} behind ${esc(p.upstream)}</span></div>` +
      `<div class="lee-git-merge-preview"><header><strong>${p.relation === 'diverged' ? 'The branches have diverged' : 'Behind the upstream'}</strong>` +
      `<span>${p.ours.length} commit${p.ours.length === 1 ? '' : 's'} of yours · ${p.theirs.length} of theirs</span></header>${dirty}` +
      `<div class="lee-syncopts">${p.options.map(row).join('')}</div></div>` +
      `<div class="lee-mfoot"><button class="lee-btn go" data-sync>sync</button><button class="lee-btn" data-close>cancel</button></div>`);
    $('[data-close]', m).onclick = () => m.remove();
    $('[data-sync]', m).onclick = async () => {
      const how = $('input[name=how]:checked', m)?.value; if (!how) return;
      const o = p.options.find(x => x.op === how);
      if (o.destructive && !await confirmDialog(`discard ${p.branch}`, `${o.note || 'This moves the branch to ' + p.upstream}. There is no way back to these commits from the branch.`, 'discard')) return;
      m.remove();
      const next = await branchAct('sync', {how});
      if ((next.changes || []).some(x => x.conflicted)) showConflictCenter();
    };
  } catch (e) { leeFail('git', 'sync', e); }
}
window.showSyncPlan = showSyncPlan;

async function leeGitQuick(op) {
  const button = $(`#git${op}`);
  if (button) button.disabled = true;
  try {
    // An unpublished branch has nowhere to push to, and saying "nothing to push" would be the
    // wrong half of the truth.
    const publish = op === 'push' && !(gitUI.snapshot || await gitInfo(gitUrl('/git/info', {repo: gitUI.repo}))).upstream;
    await gitDo(op, op === 'push' ? {publish} : {});
    refreshScmIfOpen();
  } catch (_) { /* gitDo already logged it, showed the log, and said so in the status line */ }
  finally { if (button) button.disabled = false; }
}
window.leeGitQuick = leeGitQuick;

// Poll a clone job until it stops. The cap ends a wedged job as a sentence rather than a spinner
// nothing will ever stop.
async function cloneProgress(id, say) {
  for (let i = 0; i < 900; i++) {
    await new Promise(r => setTimeout(r, 900));
    const job = await api(`/git/clone/status?job=${encodeURIComponent(id)}`);
    if (job.error) throw new Error(job.error);
    if (!job.active) return job.result || {};
    if (job.current) say.textContent = job.current;
  }
  throw new Error('the clone is still running; the jobs panel has it');
}

async function leeCloneRepo() {
  const info = await api('/workspace/info').catch(() => ({}));
  // Beside the folders that are already open, not inside one: a clone under an open folder is
  // covered by it and can never become a chosen project of its own.
  const beside = ((info.roots || [])[0]?.path || '').split('/').slice(0, -1).join('/');
  const m = modal(
    `<div class="lee-mhead">clone repository<span class="sub">the clone becomes an open folder</span></div>` +
    `<label class="lee-fieldlabel">Repository<input class="lee-input" id="cloneurl" autocomplete="off"` +
    ` spellcheck="false" placeholder="owner/name  ·  https://…  ·  git@…"></label>` +
    `<label class="lee-fieldlabel">Into<input class="lee-input" id="cloneinto" autocomplete="off"` +
    ` spellcheck="false" value="${esc(beside)}" placeholder="a folder that already exists"></label>` +
    `<div class="lee-mfoot"><button class="lee-btn go" id="clonego">clone</button>` +
    `<span class="lee-dim" id="clonesay"></span></div>`);
  const say = m.querySelector('#clonesay'), go = m.querySelector('#clonego');
  const start = async () => {
    const url = m.querySelector('#cloneurl').value.trim();
    if (!url) return m.querySelector('#cloneurl').focus();
    go.disabled = true; say.textContent = 'starting…';
    try {
      const r = await post('/git/clone', {url, parent: m.querySelector('#cloneinto').value.trim()});
      say.textContent = `cloning into ${r.root}…`;
      const done = await cloneProgress(r.job.id, say);
      m.remove();
      // The same three steps the folder picker takes, so a clone arrives like an opened folder.
      await post('/fs/add-root', {path: done.root});
      await refreshFileTree(done.root);
      await activateRoot(done.root);
      status(`cloned ${done.name}`, 'ok');
    } catch (e) {
      go.disabled = false; say.textContent = '';
      if (e.body?.cloned === false) return status(e.message, 'err');   // refused before anything was cloned
      if (e.body?.declined) return status(e.message);   // cloned, and the person kept the folder out of this window
      leeFail('git', 'clone', e);
    }
  };
  go.onclick = start;
  m.querySelector('#cloneurl').onkeydown = e => { if (e.key === 'Enter') { e.preventDefault(); start(); } };
  setTimeout(() => m.querySelector('#cloneurl').focus(), 0);
}
window.leeCloneRepo = leeCloneRepo;
/* The inline browser: one page from the persistent CDP Chrome, drawn in a Leela tab.
 *
 * Chrome renders offscreen and streams JPEG frames over `/browser/ws`. The page runs in a separate
 * process with fossick's profile, so it cannot reach Leela's DOM, and a site fossick is signed in
 * to is one Leela can read.
 *
 * Coordinates are 1:1, because the server pins Chrome's viewport to the canvas's CSS size. A
 * frame may carry more pixels than that box, and lands in a backing store sized to it.
 */

const wsURL = p => `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}${p}`;

// What the page should read as its own `devicePixelRatio`, so it picks the assets the display
// wants. How many pixels a frame carries is `SCALE_FLAG`, which Chrome takes at launch.
const webScale = () => Math.min(window.devicePixelRatio || 1, 2);

// Only the active tab is cast: a hidden canvas costs a JPEG encode per frame in Chrome.
let webView = null;

function closeWebView() {
  if (!webView) return;
  const v = webView; webView = null;
  v.resizer?.disconnect();
  v.unwatch?.();
  try { v.sock.close(); } catch (_) {}
}

function mountWeb(host, st) {
  closeWebView();
  host.innerHTML =
    `<div class="lee-doc lee-webview">` +
    `<div class="lee-doc-head lee-webbar">` +
    `<button class="lee-btn" data-web="back" title="back" aria-label="back" disabled>‹</button>` +
    `<button class="lee-btn" data-web="forward" title="forward" aria-label="forward" disabled>›</button>` +
    `<button class="lee-btn" data-web="reload" title="reload" aria-label="reload">⟳</button>` +
    `<input class="lee-input lee-weburl" data-web="url" spellcheck="false" autocomplete="off"` +
    ` aria-label="page address" placeholder="type a URL and press enter">` +
    `<span class="lee-spacer"></span>` +
    `<button class="lee-btn" data-web="markdown" title="read this page as markdown">read</button>` +
    `<button class="lee-btn" data-web="remember" title="read it and keep it in the vault">remember</button>` +
    `</div>` +
    `<div class="lee-doc-body lee-webbody" data-web="body">` +
    `<canvas class="lee-webcanvas" data-web="canvas" tabindex="0"` +
    ` aria-label="${esc(st.title || 'web page')}, drawn by the CDP browser"></canvas>` +
    `<div class="lee-webnote lee-dim" data-web="note">connecting to the browser…</div>` +
    `</div></div>`;

  const el = s => $(`[data-web="${s}"]`, host);
  const canvas = el('canvas'), note = el('note'), body = el('body'), urlBox = el('url');
  const ctx = canvas.getContext('2d', {alpha: false});
  const sock = new WebSocket(wsURL('/browser/ws'));
  // Frames arrive as raw JPEG rather than base64 in JSON: a third fewer bytes, and no data:
  // URL to parse before drawing. Everything else on this socket is still JSON.
  sock.binaryType = 'arraybuffer';
  const view = {sock, canvas, target: st.target, resizer: null, size: [0, 0], drawing: false};
  webView = view;

  const say = (msg, kind) => { note.textContent = msg || ''; note.hidden = !msg;
                               note.className = `lee-webnote ${kind === 'err' ? 'lee-err' : 'lee-dim'}`; };
  const send = m => { if (sock.readyState === 1) sock.send(JSON.stringify(m)); };
  view.send = send;

  const measure = () => {
    const r = body.getBoundingClientRect();
    return [Math.max(240, Math.round(r.width)), Math.max(180, Math.round(r.height))];
  };

  sock.onopen = () => {
    const [w, h] = measure();
    send({id: st.target, w, h, scale: webScale()});
  };
  sock.onerror = () => say('the inline browser socket failed', 'err');
  sock.onclose = () => { if (webView === view) say('the browser disconnected. Open the tab again', 'err'); };

  sock.onmessage = ev => {
    if (typeof ev.data !== 'string') return drawFrame(ctx, canvas, view, ev.data);
    const m = JSON.parse(ev.data);
    if (m.t === 'error') return say(m.error, 'err');
    if (m.t === 'ready') { view.size = [m.w, m.h]; sizeCanvas(canvas, m.w, m.h); paintNav(host, m);
                           say(''); warnScale(m); }
    else if (m.t === 'nav') paintNav(host, m);
  };

  // Chrome only emits a frame when something changes, so a resize re-asks for one. The server
  // restarts the cast, which always sends a fresh first frame.
  view.resizer = new ResizeObserver(() => {
    const [w, h] = measure();
    if (w === view.size[0] && h === view.size[1]) return;
    view.size = [w, h]; sizeCanvas(canvas, w, h);
    send({t: 'resize', w, h, scale: webScale()});
  });
  view.resizer.observe(body);

  wireToolbar(host, view, urlBox, say);
  wireInput(canvas, view);
  wireVisibility(view);
  canvas.focus();
}

/* Chrome takes `--force-device-scale-factor` at launch, so a browser already running when Leela
   connects goes on drawing at 1x and no restart of Leela changes it. Said once per Chrome, which
   is what the browser id keys: the server repeats the note on every `ready`. */
function warnScale(m) {
  if (!m.note) return;
  const key = 'lee-web-scale';
  if (localStorage.getItem(key) === (m.browser || '')) return;
  localStorage.setItem(key, m.browser || '');
  status(m.note, 'err');
}

/* A hidden window still has a live screencast behind it, so Chrome goes on encoding for a canvas
   nobody can see. The page stays open, and resuming asks for a frame immediately. */
function wireVisibility(view) {
  const onChange = () => {
    if (webView !== view || view.sock.readyState !== 1) return;
    if (document.visibilityState === 'hidden') view.send({t: 'pause'});
    else view.send({t: 'resume', w: view.size[0], h: view.size[1], scale: webScale()});
  };
  document.addEventListener('visibilitychange', onChange);
  view.unwatch = () => document.removeEventListener('visibilitychange', onChange);
}

/* The CSS box is the viewport, in the same pixels a click arrives in. The backing store starts
   there and `drawFrame` grows it to whatever the frame turns out to carry. */
function sizeCanvas(canvas, w, h) {
  canvas.width = w; canvas.height = h;
  canvas.style.width = `${w}px`; canvas.style.height = `${h}px`;
}

/* `createImageBitmap` decodes off the main thread, where an `<img>` with a data: URL would decode
   on it. A frame arriving mid-decode is dropped rather than queued. */
function drawFrame(ctx, canvas, view, buf) {
  if (!buf || view.drawing) return;
  view.drawing = true;
  createImageBitmap(new Blob([buf], {type: 'image/jpeg'}))
    .then(bmp => {
      // The frame is the last word on its own size. A Chrome rasterising at 2x sends twice the
      // pixels for the same viewport, and they land 1:1 in a box the display still paints at the
      // CSS size. One that does not is drawn 1:1 too, rather than stretched.
      if (bmp.width !== canvas.width || bmp.height !== canvas.height) {
        canvas.width = bmp.width; canvas.height = bmp.height;
      }
      ctx.drawImage(bmp, 0, 0, canvas.width, canvas.height);
      bmp.close();
    })
    .catch(() => {})
    .finally(() => { view.drawing = false; });
}

function paintNav(host, m) {
  const el = s => $(`[data-web="${s}"]`, host);
  const url = el('url');
  // Never overwrite a URL half-typed: `nav` frames arrive whenever the page redirects.
  if (url && document.activeElement !== url) url.value = m.url || '';
  el('back').disabled = !m.back;
  el('forward').disabled = !m.forward;
  const tab = $('.lee-tab.active .lee-tab-name');
  if (tab && m.title) tab.textContent = m.title;
}

function wireToolbar(host, view, urlBox, say) {
  const on = (name, fn) => $(`[data-web="${name}"]`, host).addEventListener('click', fn);
  on('back', () => view.send({t: 'back'}));
  on('forward', () => view.send({t: 'forward'}));
  on('reload', () => view.send({t: 'reload'}));
  urlBox.addEventListener('keydown', e => {
    if (e.key !== 'Enter') return;
    e.preventDefault();
    view.send({t: 'goto', url: urlBox.value.trim()});
    view.canvas.focus();
  });
  on('markdown', () => readWeb(view, false, say));
  on('remember', () => readWeb(view, true, say));
}

/* The live page as Markdown: the DOM after the scripts ran and after the login, which a fetch
   cannot reach. Comes back as research's own `Doc`, so saving it is a path that already
   exists. */
async function readWeb(view, remember, say) {
  say(remember ? 'reading and remembering…' : 'reading…');
  let d;
  try { d = await api(`/browser/markdown?id=${encodeURIComponent(view.target)}&remember=${remember ? 1 : 0}`); }
  catch (e) { return say(String(e.message || e), 'err'); }
  say('');
  if (remember) status(d.note || 'remembered', 'ok');
  lee.lastDoc = {title: d.title || d.url || 'page', url: d.url || '', text: d.markdown || ''};
  showWebMarkdown(lee.lastDoc);
}

// The same reader research uses for a fetched page, over the page that is on screen.
function showWebMarkdown(doc) {
  const m = modal(
    `<div class="lee-mhead"><span>${esc(doc.title)}</span><span class="lee-spacer"></span>` +
    `<button class="lee-btn" data-md="save">save markdown</button>` +
    `<button class="lee-btn" data-md="notebook">save as notebook</button></div>` +
    `<div class="lee-mbody lee-reader"><div class="lee-md" data-md="body"></div></div>`,
    null, null, {className: 'lee-research-modal', storageKey: 'web-read'});
  renderMarkdown($('[data-md="body"]', m), doc.text || '(the page had no readable text)');
  $('[data-md="save"]', m).onclick = () => saveDoc(doc, 'md');
  $('[data-md="notebook"]', m).onclick = () => saveDoc(doc, 'notebook');
}

/* Everything is `preventDefault`ed, because the canvas stands in for a viewport: a Space that
   scrolls the page must not also scroll Leela. The keymap router treats this panel like the
   terminal, so the chords that get you out still work. */
function wireInput(canvas, view) {
  const at = e => { const r = canvas.getBoundingClientRect();
                    return {x: e.clientX - r.left, y: e.clientY - r.top}; };
  const mods = e => (e.altKey ? 1 : 0) | (e.ctrlKey ? 2 : 0) | (e.metaKey ? 4 : 0) | (e.shiftKey ? 8 : 0);
  const BUTTONS = ['left', 'middle', 'right'];

  canvas.addEventListener('mousedown', e => {
    e.preventDefault(); canvas.focus();
    view.send({t: 'mouse', kind: 'mousePressed', ...at(e), button: BUTTONS[e.button] || 'left',
               clicks: e.detail || 1, modifiers: mods(e)});
  });
  canvas.addEventListener('mouseup', e => {
    e.preventDefault();
    view.send({t: 'mouse', kind: 'mouseReleased', ...at(e), button: BUTTONS[e.button] || 'left',
               clicks: e.detail || 1, modifiers: mods(e)});
  });
  // Hover drives menus and link underlines, but at frame rate: a fast mouse fires hundreds/s.
  // The frame sends where the mouse got to, not where it was: a flick ends where it stopped.
  let moveAt = null;
  canvas.addEventListener('mousemove', e => {
    const first = !moveAt;
    moveAt = {...at(e), modifiers: mods(e)};
    if (first) requestAnimationFrame(() => {
      const m = moveAt; moveAt = null;
      view.send({t: 'mouse', kind: 'mouseMoved', ...m, button: 'none'});
    });
  });
  canvas.addEventListener('contextmenu', e => e.preventDefault());
  canvas.addEventListener('wheel', e => {
    e.preventDefault();
    view.send({t: 'mouse', kind: 'mouseWheel', ...at(e), dx: -e.deltaX, dy: -e.deltaY,
               modifiers: mods(e)});
  }, {passive: false});

  canvas.addEventListener('keydown', e => {
    if (isEscapeChord(e)) return;          // let Leela's router have it
    e.preventDefault();
    view.send({t: 'key', kind: printable(e) ? 'keyDown' : 'rawKeyDown', ...keyFields(e)});
    if (printable(e)) view.send({t: 'key', kind: 'char', text: e.key, ...keyFields(e)});
  });
  canvas.addEventListener('keyup', e => {
    if (isEscapeChord(e)) return;
    e.preventDefault();
    view.send({t: 'key', kind: 'keyUp', ...keyFields(e)});
  });
  canvas.addEventListener('paste', e => {
    e.preventDefault();
    const text = e.clipboardData?.getData('text') || '';
    if (text) view.send({t: 'text', text});
  });
}

const printable = e => e.key.length === 1 && !e.ctrlKey && !e.metaKey;

// `windowsVirtualKeyCode` is what Chrome actually dispatches on for non-text keys; without it
// Enter, Backspace and the arrows arrive as no-ops.
const VKEY = {Backspace: 8, Tab: 9, Enter: 13, Shift: 16, Control: 17, Alt: 18, Escape: 27,
              ' ': 32, PageUp: 33, PageDown: 34, End: 35, Home: 36, ArrowLeft: 37, ArrowUp: 38,
              ArrowRight: 39, ArrowDown: 40, Insert: 45, Delete: 46, Meta: 91};

function keyFields(e) {
  const m = (e.altKey ? 1 : 0) | (e.ctrlKey ? 2 : 0) | (e.metaKey ? 4 : 0) | (e.shiftKey ? 8 : 0);
  const vk = VKEY[e.key] ?? (e.key.length === 1 ? e.key.toUpperCase().charCodeAt(0) : 0);
  return {key: e.key, code: e.code, modifiers: m, windowsVirtualKeyCode: vk,
          nativeVirtualKeyCode: vk, text: printable(e) ? e.key : ''};
}

// Asked of the router itself, so the list cannot drift from the one in `findBinding`.
const isEscapeChord = e => Boolean(findBinding(e, 'web'));

// Open a URL as a tab, the entry point for research and the palette. `/browser/open` answers with
// the tab strip, like every other route that opens a tab.

async function openWebTab(url, title = '') {
  if (!url) return status('no URL to open', 'err');
  status('opening in the inline browser…');
  try {
    await htmxPost(`/browser/open?url=${encodeURIComponent(url)}` +
                   (title ? `&title=${encodeURIComponent(title)}` : ''));
    await mountTab();
    status('');
  } catch (e) { status(`inline browser: ${e.message || e}`, 'err'); }
}
window.leeOpenWeb = openWebTab;

// The counterpart to `read_url`, which shows a page's Markdown: this one shows the page.
async function browseUrl() {
  const url = await inputDialog('open a page', 'address', '', 'example.com/article');
  if (url) return openWebTab(url.trim());
}

// Adopt what Chrome already has: a page need not start in Leela to end up in Leela.
async function pickWebTab(anchor) {
  let d;
  try { d = await api('/browser/tabs'); }
  catch (e) { return status(`inline browser: ${e.message || e}`, 'err'); }
  if (!d.ok) return status(d.error, 'err');
  const pages = (d.tabs || []).filter(t => !/^(chrome|devtools|about):/.test(t.url || ''));
  if (!pages.length) return status('the browser has no pages open', 'err');
  openChromeMenu(anchor || $('#tabbar') || document.body, pages.map(p => ({
    label: p.title || p.url, detail: researchDomain(p.url),
    run: async () => {
      await htmxPost(`/browser/attach?id=${encodeURIComponent(p.id)}`);
      await mountTab();
    },
  })));
}
window.leePickWeb = pickWebTab;
/* Opening a project when there is no command line to type one on.
 *
 * A packaged Leela is double-clicked. The ways in are the folders it had open last time, which the
 * server restores before the page loads, the recent list, and the picker. In the native shell the
 * picker is the platform's own, because a file input hands over contents, never a location.
 */

// `window.pywebview.api` is `leela.desktop.ShellApi`, injected by the native window.
const inShell = () => Boolean(window.pywebview?.api?.pick_folder);
const shortHome = p => lee.home && p.startsWith(lee.home) ? '~' + p.slice(lee.home.length) : p;

// pywebview injects its bridge asynchronously, so "is there a native chooser" cannot be answered
// by one synchronous look at load. The wait happens once: a browser tab never gets the bridge.
let shellSettled = null;
async function shellReady(waitMs = 1500) {
  if (inShell()) return (lee.inShell = true);
  return shellSettled ||= (async () => {
    for (const end = Date.now() + waitMs; !inShell() && Date.now() < end;)
      await new Promise(r => setTimeout(r, 50));
    return (lee.inShell = inShell());
  })();
}
window.leeShellReady = shellReady;
lee.inShell = inShell();
shellReady().catch(() => {});   // so `inDesktopShell` has an answer before anything asks

// The platform folder chooser, or null if there is none or it was cancelled.
async function nativeFolder() {
  if (!await shellReady()) return null;
  try { return await window.pywebview.api.pick_folder(); }
  catch (e) { return status(`folder chooser: ${e.message || e}`, 'err'), null; }
}

// A recent folder can have been renamed or deleted. htmx does not swap a 4xx and `htmx.ajax`
// resolves anyway, so the refusal has to be read off the event.
async function openFolder(path) {
  if (!path) return;
  const name = path.split('/').pop();
  status(`opening ${name}…`);
  let why = '';
  const note = e => { why = e.detail.xhr?.responseText || e.detail.error || 'no answer'; };
  document.body.addEventListener('htmx:responseError', note);
  document.body.addEventListener('htmx:sendError', note);
  try {
    await htmx.ajax('POST', '/fs/add_root?path=' + encodeURIComponent(path),
                    {target: 'body', swap: 'outerHTML'});
  } finally {
    document.body.removeEventListener('htmx:responseError', note);
    document.body.removeEventListener('htmx:sendError', note);
  }
  if (!why) return;
  // A No in the server's question is the person's answer, not a failure.
  if (jsonBody(why).declined) return status(jsonError(why));
  leeFail('project', `opening ${name}`, new Error(jsonError(why)));
}
// A refused route answers `{"ok": false, "error": …}`; anything else is shown as it came.
function jsonBody(text) { try { return JSON.parse(text) || {}; } catch (_) { return {}; } }
function jsonError(text) { return jsonBody(text).error || text; }
window.leeOpenFolder = openFolder;

/* A folder is a workspace, and a workspace is a window: `add_root` puts a second folder in the
 * window you are already in, and this gives it one of its own. The native shell builds the window,
 * because only the process running the GUI can; a browser gets a tab, being what it has. */
async function openFolderWindow(path) {
  path = path || await nativeFolder();
  if (!path) return;
  const name = path.split('/').pop();
  status(`opening ${name}…`);
  if (await shellReady()) {
    try { await window.pywebview.api.open_folder(path); }
    catch (e) { leeFail('project', `opening ${name}`, e); }
    return;
  }
  return hubOpen(path);
}
window.leeOpenFolderWindow = openFolderWindow;

// `/hub/open` sends a file where a Finder open sends it, and a folder to a window of its own.
async function hubOpen(path) {
  const name = path.split('/').pop();
  const r = await fetch('/hub/open?path=' + encodeURIComponent(path), {method: 'POST'});
  const d = await r.json().catch(() => ({ok: false, error: r.statusText}));
  if (!d.ok) return d.declined ? status(d.error) : leeFail('project', `opening ${name}`, new Error(d.error));
  if (new URL(d.url).host === location.host) { await refreshTabStrip(); return mountTab().catch(() => {}); }
  // In the app window a scripted `window.open` opens nothing and returns null; `openExternal`
  // knows that and asks the server to open a real browser instead.
  openExternal(d.url);
}

/* Open… as a Mac app has it: one chooser takes a file or a folder. An older native window
 * has the folder chooser only, and a browser tab has none, so it asks for the path. */
async function openAny() {
  if (!await shellReady()) {
    const path = await inputDialog('open', 'path of a file or a folder', '', '~/code/notes.md');
    return path && hubOpen(path);
  }
  const shell = window.pywebview.api;
  if (!shell.pick_path) return openFolderWindow();
  let path;
  try { path = await shell.pick_path(); } catch (e) { return status(`file chooser: ${e.message || e}`, 'err'); }
  if (!path) return;
  status(`opening ${path.split('/').pop()}…`);
  try { if (!await shell.open_path(path)) status(`Leela cannot open ${path} from here`, 'err'); }
  catch (e) { leeFail('project', `opening ${path.split('/').pop()}`, e); }
}

/* A file no open folder holds lands in the loose window. Its folder is offered once, and opened only on Open. */
function folderOffer(st) {
  let el = $('#leeoffer');
  if (!st?.offer || !st.path) { if (el) el.hidden = true; return; }
  if (!el) {
    el = document.createElement('div'); el.id = 'leeoffer'; el.className = 'lee-offer'; el.setAttribute('role', 'status');
    document.body.append(el);
  }
  const repo = st.offer, file = st.path, name = repo.split('/').pop();
  el.title = repo; el.hidden = false;
  el.innerHTML = `<span>This file is in ${esc(name)}. Open ${esc(name)} as a folder?</span>` +
    `<button class="lee-btn go" data-offer="open">Open</button><button class="lee-btn" data-offer="later">Not now</button>`;
  el.querySelector('[data-offer="open"]').onclick = async () => {
    el.hidden = true;
    const q = new URLSearchParams({path: repo, file, folder: '1'}); for (const a of st.also || []) q.append('also', a);
    const r = await fetch('/hub/open?' + q, {method: 'POST'});
    const d = await r.json().catch(() => ({ok: false, error: r.statusText}));
    if (!d.ok) return d.declined ? status(d.error) : leeFail('project', `opening ${name}`, new Error(d.error));
    await refreshTabStrip(); mountTab().catch(() => {});
    if (!await shellReady()) return openExternal(d.url);
    try { await window.pywebview.api.open_folder(repo); } catch (e) { leeFail('project', `opening ${name}`, e); }
  };
  el.querySelector('[data-offer="later"]').onclick = () => {
    el.hidden = true;
    post('/tab/offer/dismiss?path=' + encodeURIComponent(file), {}).catch(() => {});
  };
}
window.leeFolderOffer = folderOffer;

// The welcome screen's recent list: when Leela opens on nothing, this is the way back to work.
async function paintRecent() {
  const host = $('#leerecent'); if (!host) return;
  let d; try { d = await api('/fs/recent'); } catch (_) { return; }
  lee.home = d.home || '';
  const rows = (d.recent || []).filter(r => !r.open);
  host.hidden = !rows.length; if (!rows.length) return;
  host.innerHTML = `<h3>Recent projects</h3><ul class="lee-recentlist">` + rows.map(r =>
    `<li><button class="lee-recent" data-path="${esc(r.path)}">` +
    `<span class="lee-recent-name">${esc(r.name)}</span>` +
    `<span class="lee-recent-path lee-dim">${esc(shortHome(r.path))}</span></button>` +
    `<button class="lee-recent-x" data-forget="${esc(r.path)}" title="forget this project"` +
    ` aria-label="forget ${esc(r.name)}">×</button></li>`).join('') + `</ul>`;
  $$('.lee-recent', host).forEach(b => b.onclick = () => openFolder(b.dataset.path));
  $$('[data-forget]', host).forEach(b => b.onclick = async () => {
    await post('/fs/forget-recent', {path: b.dataset.forget});
    paintRecent();
  });
}
window.leePaintRecent = paintRecent;
let lessonDueRows = null, lessonDueError = '', lessonDueSeq = 0;
function paintLessonReview() {
  const body = $('#lessonreviewbody'); if (!body) return;
  body.replaceChildren();
  if (lessonDueError) {
    const message = document.createElement('p'); message.textContent = lessonDueError;
    const retry = document.createElement('button'); retry.type = 'button'; retry.className = 'lee-btn'; retry.textContent = 'Try again';
    retry.onclick = refreshLessonDue; body.append(message, retry); return;
  }
  if (lessonDueRows === null) { body.textContent = 'Loading review…'; return; }
  if (!lessonDueRows.length) { body.textContent = 'Nothing to learn or review right now.'; return; }
  for (const row of lessonDueRows) {
    const card = document.createElement('details'); card.className = 'lee-lesson-review-card';
    const title = document.createElement('summary'); title.textContent = row.name; card.appendChild(title);
    for (const [key, cls] of [['question', 'lee-lesson-question'], ['why', 'lee-lesson-why'], ['reason', 'lee-lesson-reason']]) {
      if (!row[key]) continue;
      const p = document.createElement('p'); p.className = cls; p.textContent = row[key]; card.appendChild(p);
    }
    const show = document.createElement('button'); show.type = 'button'; show.className = 'lee-btn'; show.textContent = 'Show my last answer';
    show.onclick = () => {
      const last = document.createElement('div'); last.className = 'lee-lesson-last-answer';
      for (const [key, label] of [['answer', 'My last answer'], ['thinking', 'Thinking'], ['actual', 'Actual']]) {
        const heading = document.createElement('h4'), p = document.createElement('p');
        heading.textContent = label; p.textContent = row[key] || ''; last.append(heading, p);
      }
      show.replaceWith(last);
    };
    card.appendChild(show); body.appendChild(card);
  }
}
async function refreshLessonDue() {
  const seq = ++lessonDueSeq;
  try {
    const rows = await api('/lesson/due'); if (seq !== lessonDueSeq) return;
    lessonDueRows = rows; lessonDueError = '';
    const item = $('#lessondue');
    if (item) { item.textContent = rows.length ? `${rows.length} due` : ''; item.hidden = !rows.length; }
  } catch (e) { if (seq !== lessonDueSeq) return; lessonDueError = String(e.message || e); }
  paintLessonReview();
}
