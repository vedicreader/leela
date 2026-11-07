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
