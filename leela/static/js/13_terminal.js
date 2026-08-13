/* ------------------------------------------------------------------ terminal */
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
// Multiple xterm instances keep their websocket/pty alive while hidden. The 285kb bundle
// still loads only on the first terminal action, never during ordinary notebook startup.
// `taken` is the set of ids the *server* is holding. A pty deliberately outlives its websocket
// so that reloading the page can reattach to it -- but this counter restarts at zero on reload,
// so it handed out `term-1` again, `terms.open` found a live pty under that key and returned it,
// and a brand new terminal came up showing an old session's scrollback with its process still
// running in it. Both halves of that are the same bug.
function nextTermId(kind, taken = []) {
  if (kind === 'git') return 'git';
  const used = new Set([...lee.terms.keys(), ...taken]);
  do { lee.termSeq += 1; } while (used.has('term-' + lee.termSeq));
  return 'term-' + lee.termSeq;
}
function termLabel(kind, id) { return kind === 'git' ? 'lazygit' : kind === 'release' ? 'release pipeline' : kind === 'deploy' ? 'deploy' : kind === 'drive' ? 'drive' : kind === 'gh-auth' ? 'gh auth' : `terminal ${id.split('-').pop()}`; }
function paintTermTabs() {
  const bar = $('#termtabs'); if (!bar) return;
  /* The close control belongs to the tab, not to the header. One × over there always shut
     the *active* terminal, so closing a background one meant selecting it first, and which
     tab it would close was never visible from the tab itself. */
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
function leePane(which, show = null) {
  const shell = $('#shell'); if (!shell) return;
  const cls = which === 'left' ? 'no-left' : which === 'right' ? 'no-right' : 'no-bottom';
  const hidden = show === null ? !shell.classList.contains(cls) : !show;
  shell.classList.toggle(cls, hidden);
  if (matchMedia('(max-width: 1100px)').matches && which !== 'bottom') {
    shell.classList.toggle('mobile-' + which, !hidden);
    if (!hidden) {
      const other = which === 'left' ? 'right' : 'left';
      shell.classList.remove('mobile-' + other);
      shell.classList.add(other === 'left' ? 'no-left' : 'no-right');
    }
  }
  localStorage.setItem('lee-pane-' + which, hidden ? 'hidden' : 'shown');
  if (!hidden && which === 'bottom') requestAnimationFrame(() => lee.term?.refit());
}
window.leePane = leePane;
