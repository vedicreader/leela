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
/* `/git/info` is several git subprocesses, and in the packaged app they are forked from the process
   drawing the window. A build writing without pause fired one of these per debounced batch. One at
   a time, and at most one more queued behind it: the trailing call always runs, so the marks still
   settle on the truth, but a hundred batches cost two walks of the repository rather than a
   hundred. */
let gitMarksBusy = false, gitMarksAgain = false;
async function refreshGitTreeMarks() {
  if (gitMarksBusy) { gitMarksAgain = true; return; }
  gitMarksBusy = true;
  try {
    const d = await gitInfoOrNull(gitUrl('/git/info'));
    if (d) paintGitTree(d);
  } finally {
    gitMarksBusy = false;
    if (gitMarksAgain) { gitMarksAgain = false; refreshGitTreeMarks(); }
  }
}

let fsWatchTimer = null, fsWatchSeen = [], fsWatchSince = 0;
const FS_DEBOUNCE = 250, FS_MAX_WAIT = 1000, FS_MAX_SEEN = 2000;
// Too many changes to name, so nothing is named: redraw rather than patch.
function resyncFiles() {
  clearTimeout(fsWatchTimer); fsWatchSeen = []; fsWatchSince = 0;
  refreshFileTree(undefined, false).catch(() => {});
  refreshGitTreeMarks(); watchOpenFile();
}
function watchFiles() {
  const es = new EventSource('/fs/events');
  es.addEventListener('changed', e => {
    let d; try { d = JSON.parse(e.data); } catch (_) { return; }
    if (d.resync) return resyncFiles();
    fsWatchSeen.push(...d.paths);
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
/* Created through `/fs/new`, not a route of its own: that is the seam that writes the starter
   document, files the undo entry and refreshes the tree, so a canvas is made the way a file is. */
async function newCanvas() {
  const sel = treeSel();
  const parent = sel ? (sel.classList.contains('lee-dir') ? sel.dataset.path
                                                          : sel.dataset.path.replace(/\/[^/]+$/, ''))
                     : (lee.activeRoot || lee.roots?.[0] || '');
  if (!parent) return status('open a folder first', 'err');
  let name = await inputDialog('new canvas', 'name', '', 'plan.canvas.md');
  if (!name) return;
  if (!name.endsWith('.canvas.md')) name = name.replace(/\.(md|canvas)$/, '') + '.canvas.md';
  const r = await post('/fs/new', {parent, name, kind: 'file'});
  noteSelfWrite(r.entry.path);
  status('created ' + name, 'ok');
  await refreshFileTree(r.entry.path);
  leeOpenFile(r.entry.path);
}
window.newCanvas = newCanvas;

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
  const bar = $('#tabbar'); if (!bar) return;
  try { bar.outerHTML = await (await fetch('/tab/bar')).text(); } catch (_) {}
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
