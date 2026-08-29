function paintGitTree(d) {
  const rows = new Map();   // indexed once rather than rescanned per change

  $$('.lee-file').forEach(row => {
    row.classList.remove('git-modified', 'git-staged', 'git-untracked', 'git-conflict');
    row.querySelectorAll('.lee-tree-git').forEach(badge => badge.remove());
    rows.set(row.dataset.path, row);
  });
  for (const c of (d.changes || [])) {
    const row = rows.get(d.root + '/' + c.path); if (!row) continue;
    const state = c.conflicted ? 'conflict' : c.untracked ? 'untracked' : c.staged && !c.unstaged ? 'staged' : 'modified';
    row.classList.add('git-' + state);
    const badge = document.createElement('span'); badge.className = 'lee-tree-git'; badge.textContent = state[0].toUpperCase();
    row.appendChild(badge);
  }
}
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
  if (had && had !== sig) gitChanged();     // `had` empty on the first poll: nothing has moved yet
}
function gitChanged() {
  refreshOpenGitMarks();                    // the file's lines, or the notebook's cells
  const left = $('#left');
  if (left?.classList.contains('left-git')) {
    // The snapshot and the loaded history are both about the commit we were on.
    gitUI.snapshot = null; gitUI.history = [];
    renderGitPanel();
  }
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
    const active = (d.roots || []).find(r => r.path === (gitUI.repo || d.active)) || (d.roots || [])[0];
    const name = $('#workspacename'); if (name) name.textContent = active?.name || 'open workspace';
    const workspace = $('#workspacepill'); if (workspace) workspace.title = active?.path || 'open workspace';
  } catch (_) {}
  try {
    const d = await api('/cwd');
    const cwd = $('#cwdpill');
    if (cwd) { cwd.textContent = (d.explicit ? 'cwd ' : 'cwd auto ') + (d.cwd.split('/').pop() || d.cwd);
               cwd.title = d.cwd || 'choose a working directory'; }
  } catch (_) {}
  try {
    // Bare, not `gitUrl`: the pill and the tree badges describe the repository the active tab is
    // in, so a panel pinned elsewhere must not repaint them. `api`, not `gitInfo`, because that
    // helper throws for a folder outside a repository, and being outside one is a normal answer.
    const d = await api('/git/info');
    const git = $('#gitpill'); if (!git) return;
    if (!d || d.repo === false) {
      // With no folder open there is nothing to be inside or outside of, so the pill says neither.
      const nothingOpen = !!(d && String(d.note || '').startsWith('no folder'));
      git.textContent = nothingOpen ? 'git …' : 'no git';
      git.className = 'lee-branch-switcher';
      git.title = (d && d.note) || 'not inside a Git repository';
      return;
    }
    const n = (d.changes || []).length;
    git.textContent = `${d.branch}${n ? ' · ' + n : ''}`;
    git.className = 'lee-branch-switcher ' + (n ? 'lee-pill-warn' : 'lee-pill-on');
    git.title = `${d.root}${d.upstream ? ' · ' + d.upstream : ''}${d.ahead ? ' · ahead ' + d.ahead : ''}${d.behind ? ' · behind ' + d.behind : ''}`;
    paintGitTree(d);
    noticeGitState(d);
  } catch (e) {
    // A failure is not an absence. Saying `no git` here claims the folder is not a checkout,
    // which is a statement about the user's project rather than about the request.
    const git = $('#gitpill');
    if (git) { git.textContent = 'git ?'; git.className = 'lee-branch-switcher lee-pill-warn';
               git.title = 'could not read the repository: ' + ((e && e.message) || e); }
    console.error('git pill', e);
  }
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

function gitPatchHtml(text) {
  if (!text) return '<div class="lee-git-empty-state"><strong>No patch yet</strong><span>Stage an untracked file to create its first patch.</span></div>';
  return String(text).split('\n').map(line => {
    const kind = line.startsWith('@@') ? 'hunk' : line.startsWith('+') && !line.startsWith('+++') ? 'add' :
                 line.startsWith('-') && !line.startsWith('---') ? 'del' : line.startsWith('diff ') || line.startsWith('index ') ? 'meta' : '';
    return `<div class="lee-patch-line ${kind}">${esc(line) || ' '}</div>`;
  }).join('');
}
function gitPatchParts(text) {
  const lines = String(text || '').split('\n'), first = lines.findIndex(x => x.startsWith('@@'));
  if (first < 0) return {header: text, hunks: []};
  const header = lines.slice(0, first).join('\n') + '\n', hunks = [];
  let current = [];
  for (const line of lines.slice(first)) {
    if (line.startsWith('@@') && current.length) { hunks.push(current.join('\n') + '\n'); current = []; }
    current.push(line);
  }
  if (current.length) hunks.push(current.join('\n') + '\n');
  return {header, hunks};
}
function showGitFileDiff(path, patch = '', line = 0, rawPatch = '', notebook = false, options = {}) {
  const name = String(path || '').split('/').pop(), parts = gitPatchParts(rawPatch || patch);
  const canPartial = !notebook && parts.hunks.length > 0 && options.group;
  const controls = canPartial ? `<button class="lee-btn" id="githunks">select hunks</button>` : '';
  const m = modal(`<div class="lee-mhead">${esc(name)}<span class="sub">${options.label || 'working tree against HEAD'}${line ? ' · line ' + line : ''}</span>` +
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

