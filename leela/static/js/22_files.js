/* ------------------------------------------------------------------ file ops */
const treeSel = () => $('.lee-node.sel');
const visibleTreeNodes = () => $$('.lee-node').filter(n => n.getClientRects().length);
function selectTreeNode(n) {
  if (!n) return;
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
/* Dotfiles are off by default because most of them are machinery, and on by choice because
   `.gitignore`, `.github` and `.env` are files you edit. `.venv` and `node_modules` are on
   neither side of this: the server's skip list drops them whatever the toggle says. */
function treeHidden() { return localStorage.getItem('lee-tree-hidden') === '1'; }
function treeQuery(sep = '?') { return treeHidden() ? sep + 'hidden=1' : ''; }
function paintHiddenBtn() {
  $$('[data-action="show_hidden"]').forEach(b => {
    b.classList.toggle('on', treeHidden());
    b.setAttribute('aria-pressed', String(treeHidden()));
  });
}
async function toggleHidden() {
  localStorage.setItem('lee-tree-hidden', treeHidden() ? '0' : '1');
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
    htmx.process(kids);
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
  old.replaceWith(fresh); htmx.process(fresh); paintHiddenBtn();
  const wanted = $$('.lee-node').find(n => n.dataset.path === selectPath) || visibleTreeNodes()[0];
  selectTreeNode(wanted); if ($('#filetree')) $('#filetree').scrollTop = scrollTop;
  if (focus) setScope('files');
  status('files refreshed', 'ok');
}

/* Pushed, not polled: an agent edit, a terminal command or another editor used to stay
   invisible until someone refreshed. A push never rebuilds the panel -- it reconciles the
   folders that changed and leaves every other row, its expansion and the scroll alone. */
const selfWrites = new Map();
const SELF_WRITE_MS = 4000;
function noteSelfWrite(...paths) { for (const p of paths) if (p) selfWrites.set(p, performance.now()); }
function notMine(paths) {
  const now = performance.now();
  for (const [p, at] of selfWrites) if (now - at > SELF_WRITE_MS) selfWrites.delete(p);
  return paths.filter(p => !selfWrites.has(p));
}
window.noteSelfWrite = noteSelfWrite;

const GIT_MARKS = ['git-modified', 'git-staged', 'git-untracked', 'git-conflict'];
function syncTreeRow(row, fresh) {
  if (row.classList.contains('lee-dir')) return;
  row.classList.remove(...GIT_MARKS);
  for (const c of GIT_MARKS) if (fresh.classList.contains(c)) row.classList.add(c);
  row.querySelectorAll('.lee-tree-git').forEach(b => b.remove());
  const badge = fresh.querySelector('.lee-tree-git');
  if (badge) row.appendChild(badge.cloneNode(true));
}
// Rows that are still there stay where they are, with whatever they had open inside them.
async function patchTreeDir(dir) {
  const kids = dir.querySelector(':scope > .lee-kids'); if (!kids) return;
  const html = await fetch('/tree?path=' + encodeURIComponent(dir.dataset.path) + treeQuery('&'),
                           {headers: {'HX-Request': 'true'}}).then(r => r.text());
  const box = document.createElement('div'); box.innerHTML = html;
  const have = new Map([...kids.children].map(n => [n.dataset.path, n]));
  [...box.children].forEach((fresh, i) => {
    const row = have.get(fresh.dataset.path) || fresh;
    if (have.has(fresh.dataset.path)) { syncTreeRow(row, fresh); have.delete(fresh.dataset.path); }
    if (kids.children[i] !== row) kids.insertBefore(row, kids.children[i] || null);
  });
  have.forEach(n => n.remove());
  htmx.process(kids);
}
/* A new folder's own path is open nowhere. Redraw the nearest open ancestor. */
async function patchTree(paths) {
  const open = $$('.lee-dir[open]'), want = new Set();
  for (const p of paths) {
    let best = null;
    for (const n of open) {
      const d = n.dataset.path;
      if ((p === d || p.startsWith(d + '/')) && (!best || d.length > best.dataset.path.length)) best = n;
    }
    if (best) want.add(best);
  }
  await Promise.all([...want].map(patchTreeDir));
}
async function refreshGitTreeMarks() {
  try { paintGitTree(await api(gitUrl('/git/info'))); } catch (_) {}
}

let fsWatchTimer = null, fsWatchSeen = [], fsWatchSince = 0;
const FS_DEBOUNCE = 250, FS_MAX_WAIT = 1000, FS_MAX_SEEN = 2000;
function watchFiles() {
  const es = new EventSource('/fs/events');
  es.addEventListener('changed', e => {
    try { fsWatchSeen.push(...JSON.parse(e.data).paths); } catch (_) { return; }
    // A build writes without pause. A timer that only resets never fires.
    if (fsWatchSeen.length > FS_MAX_SEEN) fsWatchSeen = fsWatchSeen.slice(-FS_MAX_SEEN);
    if (!fsWatchSince) fsWatchSince = performance.now();
    clearTimeout(fsWatchTimer);
    const wait = Math.max(0, Math.min(FS_DEBOUNCE, fsWatchSince + FS_MAX_WAIT - performance.now()));
    fsWatchTimer = setTimeout(async () => {
      const all = fsWatchSeen; fsWatchSeen = []; fsWatchSince = 0;
      const theirs = notMine(all);
      // Our own save changed no filenames, only what git thinks of one.
      if (theirs.length) await patchTree(theirs).catch(() => {});
      await refreshGitTreeMarks();
      if (theirs.some(p => p === lee.path)) { refreshOpenGitMarks(); watchOpenFile(); }
    }, wait);
  });
  es.onerror = () => { es.close(); setTimeout(watchFiles, 3000); };
  return es;
}
window.watchFiles = watchFiles;

async function treeGitAction(op) {
  const node = treeSel();
  if (!node || node.classList.contains('lee-root')) return status('select a file or folder first', 'err');
  const directory = node.classList.contains('lee-dir'), name = node.dataset.path.split('/').pop();
  if (op === 'discard' && !await confirmDialog(`discard changes in ${name}`, 'This restores the selected tracked file from HEAD.', 'discard')) return;
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
  const sel = treeSel();
  const parent = sel ? (sel.classList.contains('lee-dir') ? sel.dataset.path
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
  const sel = treeSel(); if (!sel) return status('select a file or folder first');
  const name = sel.dataset.path.split('/').pop(), folder = sel.classList.contains('lee-dir');
  const warning = folder
    ? 'This permanently deletes the folder and everything inside it from disk.'
    : 'This permanently deletes the file from disk.';
  if (lee.filePrefs.confirmDelete !== false && !await confirmDialog('delete ' + name + ' from disk', warning, 'delete')) return;
  const parent = sel.parentElement?.closest('.lee-node.lee-dir')?.dataset.path;
  noteSelfWrite(sel.dataset.path);
  await post('/fs/delete', {path: sel.dataset.path});
  await refreshFileTree(parent);
}
async function removeRoot() {
  const sel = treeSel();
  if (!sel?.classList.contains('lee-root')) return status('select an open project root first', 'err');
  const name = sel.dataset.path.split('/').pop();
  if (!await confirmDialog('remove ' + name + ' from workspace', 'Files stay on disk. Open tabs inside it will close.', 'remove')) return;
  await post('/fs/remove-root', {path: sel.dataset.path});
  await refreshFileTree();
  status(name + ' removed from the workspace; files were not deleted', 'ok');
}
/* `find` opens the same dialog with the repository filter focused. Browsing and searching are
   the two ways people actually find a checkout, and they want the same confirm button. */
async function findRepo() { return addRoot(true); }

/* One box, the way a shell has one.

   The picker used to be a path bar, a separate filter box, a list and an up button -- four
   controls for "which folder", and the path bar was the only one that took a path. Typing
   into it now completes folders under what is already typed, Tab takes the completion,
   and Enter opens. Repositories deeper down still answer to a bare name, because a
   directory of checkouts is more than one level deep and that was the other thing the
   second box was for. */
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
  // In the packaged app the platform's own chooser is the obvious way to find a folder, and
  // the only one that does not require knowing the path. In a browser tab there is none.
  // Wired now and shown when the bridge arrives, which is not always by the time this opens.
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
      '<div class="lee-dim">no folders match — Enter still opens what you typed, if it exists</div>';
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
    // The search below walks a tree, so it is debounced: a five-letter name is one search,
    // not five queued behind one worker.
    paint(`<div class="lee-searching"><span class="lee-spin"></span>searching ${esc(base)} for repositories…</div>`);
    timer = setTimeout(() => repos(frag), 200);
  };
  const complete = () => {
    const r = rows[sel]; if (!r) return false;
    input.value = r.path + '/'; draw(); return true;
  };
  const open = async path => {
    const target = path || input.value.trim(); if (!target) return;
    m.remove();
    try {
      await post('/fs/add-root', {path: target});
      // The tree is redrawn *before* the folder is activated: activating selects the new
      // root's node, and a tree that has not been rebuilt does not have one yet -- which
      // left a folder that was open on the server and absent from the panel until reload.
      await refreshFileTree(target);
      await activateRoot(target);           // the folder you just opened is the one you mean
    } catch (e) { status(String(e.message || e), 'err'); }
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
      // first Enter completes it and the second opens it -- Tab, for people who press Enter.
      if (v && (!frag || dirs.some(x => x.path === v.replace(/\/$/, '')))) return open(v);
      if (!complete()) if (v) open(v);
    } else if (e.key === 'Escape') { e.preventDefault(); m.remove(); }
  };
  list.onclick = e => {
    const r = e.target.closest('.lee-folderrow'); if (!r) return;
    input.value = r.dataset.path + '/'; input.focus(); draw();
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
  if (n) { selectTreeNode(n); setScope('files'); }
  if (e.target.closest('.lee-vars')) setScope('vars');
});
document.addEventListener('toggle', e => {
  if (e.target.matches?.('.lee-dir')) e.target.setAttribute('aria-expanded', e.target.open ? 'true' : 'false');
}, true);

// Middle-click closes a tab, as it does in every browser. Delegated because both strips are
// re-rendered whole -- the document strip by htmx, the terminal strip by `paintTermTabs`.
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

// Drag to reorder. The order is the user's arrangement of their own work, so the drop is
// posted rather than kept in the browser: it has to survive a reload like the tabs do.
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

