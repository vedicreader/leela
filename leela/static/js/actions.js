const ACTIONS = {
  focus_files:  () => { leePane('left', true); leeLeft('files'); setScope('files'); $('#filetree')?.focus(); highlightTree(); },
  focus_editor: () => { setScope('editor'); if (lee.cells.length) focusCell(lee.sel); else $('#editor')?.focus(); },
  focus_exec:   () => { leePane('bottom', true); leeDock('exec'); setScope('exec'); lee.editors.get('exec')?.focus(); },
  focus_vars:   () => { leePane('right', true); leeRight('vars'); setScope('vars'); $('#varfilter')?.focus(); },
  focus_agent:  () => { leePane('right', true); leeRight('agent'); setScope('agent'); $('#agentprompt')?.focus(); },
  toggle_left:  () => leePane('left'),
  toggle_right: () => leePane('right'),
  toggle_bottom:() => leePane('bottom'),
  toggle_scope: () => leeScope(lee.execScope === 'live' ? 'agent' : 'live'),
  help:         () => showHelp(),
  settings:     () => editorSettings(),
  quick_open:   () => quickOpen(),
  code_search:  () => codeSearch(),
  find_definition: () => gotoDeclaration(),
  find_definition_only: () => findDefinition(),
  find_in_file: () => leeFind(),
  local_history: () => leeLocalHistory(),
  find_usages: () => findUsages(),
  rename_symbol: () => renameSymbol(),
  agent_selection: () => leeAgentSelection(),
  sync_index: () => syncCodeIndex(),
  nbdev_prepare: () => leeNbdevPrepare(),
  fastship:     () => leeFastship(),
  setup_models: () => leeSetupModal(),
  run_app:      () => runApp(),
  palette:      () => palette(),
  recent_tabs:  () => recentTabs(),
  save:         () => saveTab(),
  save_all:     () => saveAllTabs(),
  reload_file:  () => leeReloadFromDisk(),
  close_tab:    () => closeTab(),
  next_tab:     () => shiftTab(1),
  prev_tab:     () => shiftTab(-1),
  interrupt:    async () => {
    const r = await post('/kernel/interrupt');
    status(r.note || 'cell stopped', (r.forced || !r.ok) ? 'err' : 'ok');
  },
  restart:      async () => { status('restarting kernel…'); await post('/kernel/restart'); markPreviousRuns(); status('kernel restarted · saved outputs are from the previous kernel', 'ok'); leeVars(); },
  switch_env:   () => pickEnv(),
  edit_runs:    () => editRuns(),
  quit:         () => status('close the browser tab to leave'),

  run_cell:     () => lee.kind === 'text' ? runFile() : runCell(lee.sel, false),
  run_advance:  () => lee.kind === 'text' ? runFile() : runCell(lee.sel, true),
  run_insert:   () => lee.kind === 'text' ? runFile() : runCell(lee.sel, 'insert'),
  stop_cell:    () => stopCell(lee.sel),
  run_above:    () => runRange(0, lee.sel, 'cells above'),
  run_below:    () => runRange(lee.sel, lee.cells.length, 'this cell and below'),
  run_all:      () => runAll(),
  restart_run_all: () => restartRunAll(),
  run_file:     () => runFile(),
  run_selection: () => runSelection(),
  pick_kernel:  () => pickKernel(),
  new_notebook: () => htmxPost('/tab/new?kind=notebook'),
  new_canvas:   () => newCanvas(),
  notebook_language: () => pickNotebookLanguage(),
  add_folder:   () => treeAddFolder(),
  edit_keys:    () => editKeys(),
  cell_select_above: () => focusCell(lee.sel - 1),
  cell_select_below: () => focusCell(lee.sel + 1),
  cell_first: () => focusCell(0),
  cell_last: () => focusCell(lee.cells.length - 1),
  cell_page_up: () => focusCellPage(-1),
  cell_page_down: () => focusCellPage(1),
  cell_move_up: () => moveCellTo(lee.sel, lee.sel - 1),
  cell_move_down: () => moveCellTo(lee.sel, lee.sel + 1),
  cell_above:   async () => { const at = lee.sel; await nbEdit({op: 'insert', i: at}); focusCell(at); status('cell inserted above', 'ok'); },
  cell_below:   async () => { const at = lee.sel + 1; await nbEdit({op: 'insert', i: at}); focusCell(at); status('cell inserted below', 'ok'); },
  cell_delete:  async () => { const at = lee.sel; await nbEdit({op: 'delete', i: at}); focusCell(Math.min(at, lee.cells.length - 1)); status('cell deleted', 'ok'); },
  notebook_undo: async () => {
    if (lee.kind === 'text') return status('nothing to undo outside a notebook');
    const r = await nbEdit({op: 'undo', i: lee.sel});
    focusCell(r.index ?? lee.sel); status('cell operation undone', 'ok');
  },
  notebook_redo: async () => {
    if (lee.kind === 'text') return status('nothing to redo outside a notebook');
    const r = await nbEdit({op: 'redo', i: lee.sel});
    focusCell(r.index ?? lee.sel); status('cell operation redone', 'ok');
  },
  cell_type:    async () => {
    const id = lee.cells[lee.sel]?.id;
    const r = await nbEdit({op: 'type', i: lee.sel, cycle: true});
    const at = Math.max(0, r.cells.findIndex(c => c.id === id));
    focusCell(at); status(`cell ${at + 1} is now ${r.cells[at]?.cell_type || 'code'}`, 'ok');
  },
  capture:      () => captureScreen(),
  cell_split:   async () => {
    const at = lee.sel, v = lee.editors.get(lee.cells[at].id);
    await nbEdit({op: 'split', i: at, offset: v ? LeeCM.cursor(v) : 0});
    focusCell(at + 1); status('cell split', 'ok');
  },
  cell_split_symbols: async () => {
    const at = lee.sel, was = lee.cells.length;
    const r = await nbEdit({op: 'split_symbols', i: at});
    const made = (r?.cells?.length ?? was) - was;
    if (!made) return status('no top-level class or function to split out', 'err');
    focusCell(at); status(`split into ${made + 1} cells`, 'ok');
  },
  cell_collapse: () => setCellCollapsed(lee.sel),
  cell_duplicate: async () => {
    const at = lee.sel; await nbEdit({op: 'duplicate', i: at});
    focusCell(at + 1); status('cell duplicated', 'ok');
  },
  cell_copy: () => copyCell(lee.sel),
  cell_cut: () => cutCell(lee.sel),
  cell_paste_above: () => pasteCell(lee.sel),
  cell_paste_below: () => pasteCell(lee.sel + 1),
  cell_merge_above: async () => {
    const at = lee.sel; if (at < 1) return status('there is no cell above', 'err');
    await nbEdit({op: 'merge_above', i: at}); focusCell(at - 1); status('cells merged', 'ok');
  },
  cell_merge_below: async () => {
    const at = lee.sel; if (at + 1 >= lee.cells.length) return status('there is no cell below', 'err');
    await nbEdit({op: 'merge_below', i: at}); focusCell(at); status('cells merged', 'ok');
  },
  clear_cell_output: async () => {
    const at = lee.sel; await nbEdit({op: 'clear_cell', i: at});
    focusCell(at); status('cell output cleared', 'ok');
  },
  clear_all_outputs: async () => {
    await nbEdit({op: 'clear'}); focusCell(lee.sel); status('all outputs cleared', 'ok');
  },
  comment:      () => toggleComment(),
  complete:     () => kernelComplete(),
  ai_complete:  () => aiComplete(),
  ask_ai:       () => askSelection('[data-ask]'),
  summarise:    () => askSelection('[data-summary]'),
  show_docs:    () => showDocs(),
  show_diff:    () => lee.menuSurface === 'file' ? treeDiff() : showDiff(),
  git_blame:    () => lee.menuSurface === 'file' ? treeBlame() : leeBlame(),
  git_stage:    () => treeGitAction('stage'),
  git_unstage:  () => treeGitAction('unstage'),
  git_discard:  () => treeGitAction('discard'),
  git_ignore:   () => treeGitAction('ignore'),
  clip_to_vault: () => leeClipToVault(),
  memory_notes: () => leeMemoryNotes(),
  new_memory_note: () => leeNewMemoryNote(),
  open_vault: () => leeVaultWorkbench(),
  vault_read: () => leeVaultRead(),
  vault_find: () => leeVaultWorkbench('find'),
  vault_next_page: () => leeVaultPage(1),
  vault_prev_page: () => leeVaultPage(-1),
  vault_next_flag: () => leeVaultFlag(1),
  vault_prev_flag: () => leeVaultFlag(-1),
  indent_more:      () => leeIndent('indentMore'),
  indent_less:      () => leeIndent('indentLess'),
  indent_selection: () => leeIndent('indentSelection'),
  format_doc:   () => leeFormatDoc(),
  find_similar: () => findSimilar(),
  code_map:     () => codeMap(),

  exec_run:     () => runExec(),
  exec_newline: () => { const v = lee.editors.get('exec'); if (v) LeeCM.insert(v, '\n'); },
  exec_prev:    () => recall(-1),
  exec_next:    () => recall(1),
  exec_clear:   () => leeExecClear(),
  exec_promote: () => { leeScope('live'); runExec(); },

  file_copy:      () => fileClipboard(false),
  file_cut:       () => fileClipboard(true),
  file_paste:     () => pasteEntries(),
  file_duplicate: () => duplicateEntries(),
  tree_mark_up:   () => markTreeStep(-1),
  tree_mark_down: () => markTreeStep(1),
  open:         () => treeActivate(),
  tree_down:    () => moveTreeSelection(1),
  tree_up:      () => moveTreeSelection(-1),
  tree_expand:  () => treeExpand(),
  tree_collapse: () => treeCollapse(),
  new_file:     () => newEntry('file'),
  new_dir:      () => newEntry('dir'),
  rename:       () => renameEntry(),
  delete:       () => deleteEntry(),
  open_folder:  () => openFolderWindow(),
  add_root:     () => addRoot(),
  find_repo:    () => findRepo(),
  remove_root:  () => removeRoot(),
  refresh_files: () => refreshFileTree(),
  show_hidden:  () => toggleHidden(),
  up_dir:       () => treeCollapse(),
  filter_files: () => status('filter the tree with ctrl+p'),

  expand:       () => $('.lee-vrow.sel')?.click(),
  filter_vars:  () => $('#varfilter')?.focus(),
  edit_value:   () => editSelectedVar(),
  grid:         () => openGrid(),
  copy_rel_path: () => copyFilePath('relative'),
  copy_abs_path: () => copyFilePath('absolute'),
  copy_value:   () => copyVar('value'),
  copy_path:    () => copyVar('path'),
  promote:      () => promoteVar(),
  sort:         () => { const s = $('#varsort'); s.selectedIndex = (s.selectedIndex + 1) % s.options.length; leeVars(); },
  profile_minimal:  () => setProfile('minimal'),
  profile_standard: () => setProfile('standard'),
  profile_full:     () => setProfile('full'),

  agent_new:    () => leeAgentNew(),
  agent_threads: () => $('#agentthreads')?.focus(),
  agent_send:   () => sendAgent(),
  agent_steer_force: () => sendAgent(true),
  agent_stop:   () => stopAgent(),
  agent_tools:  () => agentTools(),
  agent_fold_turn: () => foldAgentTurn(currentAgentTurn(), !currentAgentTurn()?.classList.contains('folded')),
  agent_fold_all: () => foldAgentTurns(!agentTurnCards().every(c => c.classList.contains('folded'))),

  close_others: () => closeTabs('others'),
  close_right:  () => closeTabs('right'),
  close_saved:  () => closeTabs('saved'),

  terminal:     () => openTerm('shell'),
  git:          () => openTerm('git'),
  panel_git:      () => leeLeft('git'),
  panel_releases: () => leeLeft('releases'),
  panel_deploys:  () => leeLeft('deploys'),
  term_new:     () => leeNewTerm(),
  term_next:    () => cycleTerm(1),
  term_prev:    () => cycleTerm(-1),
  term_close:   () => closeTerm(),

  web_search:   () => webSearch(),
  research:     () => researchQ(),
  read_url:     () => readUrl(),
  browse_url:   () => browseUrl(),
  browse_tabs:  () => pickWebTab(),
};
for (let i = 1; i <= 9; i++) ACTIONS['tab_' + i] = () => htmxPost('/tab/select?i=' + (i - 1));

function leeAct(name) {
  const f = ACTIONS[name];
  if (!f) return status('no handler for ' + name);
  try { const r = f(); if (r && r.catch) r.catch(e => status(String(e.message || e), 'err')); }
  catch (e) { status(String(e.message || e), 'err'); }
}
window.leeAct = leeAct;

function setScope(s) {
  lee.scope = s;
  renderContextKeys(s);
}
const activeTabIndex = () => $$('.lee-tab').findIndex(t => t.classList.contains('active'));
async function closeTab(index = null) {
  const i = index == null ? (lee.menuTab == null ? activeTabIndex() : lee.menuTab) : Number(index);
  lee.menuTab = null;
  if (i < 0) return;
  const tab = $$('.lee-tab')[i];
  if (tab?.dataset.gitDiff) return closeGitDiffTab(tab.dataset.gitDiff);
  if (tab?.classList.contains('dirty') &&
      !await confirmDialog('close unsaved tab', `${$('.lee-tab-name', tab)?.textContent || 'This file'} has unsaved changes.`, 'close')) return;
  htmxPost('/tab/close?i=' + i);
}
window.leeCloseTab = closeTab;
async function closeTabs(which) {
  // `others`, `right` and `saved`. The reference point is the tab the menu was opened on, not the
  // active one: a right-click on a background tab selects it first, and the menu is still about
  // that tab.
  const at = lee.menuTab == null ? activeTabIndex() : lee.menuTab;
  lee.menuTab = null;
  if (at < 0) return;
  const tabs = $$('.lee-tab');
  const keep = i => which === 'others' ? i === at : which === 'right' ? i <= at
                  : tabs[i].classList.contains('dirty');
  // Git diff tabs live only in the browser and are appended after the real ones, so they are left
  // alone and cannot shift an index. Highest first, for the same reason.
  const doomed = tabs.map((_, i) => i).filter(i => !keep(i) && !tabs[i].dataset.gitDiff).reverse();
  if (!doomed.length) return status('nothing to close');
  const unsaved = doomed.filter(i => tabs[i].classList.contains('dirty')).length;
  if (unsaved && !await confirmDialog('close unsaved tabs',
      `${unsaved} of ${doomed.length} tabs have unsaved changes.`, 'close')) return;
  for (const i of doomed) await htmxPost('/tab/close?i=' + i);
  status(`closed ${doomed.length} tab${doomed.length === 1 ? '' : 's'}`);
}
function moveTab(from, to) {
  if (from === to || from < 0 || to < 0) return;
  htmxPost(`/tab/move?i=${from}&j=${to}`);
}
function rememberRecentTab(st) {
  const key = st.path || st.title || '';
  if (!key) return;
  const current = {key, path: st.path || '', title: st.title || key, kind: st.kind || 'text', at: Date.now()};
  lee.recentTabs = [current, ...lee.recentTabs.filter(x => x?.key !== key)].slice(0, 60);
  try { sessionStorage.setItem('lee-recent-tabs', JSON.stringify(lee.recentTabs)); } catch (_) {}
}
function recentTabs() {
  const open = $$('.lee-tab').map((tab, i) => ({
    i, key: tab.title || $('.lee-tab-name', tab)?.textContent || '',
    path: tab.title || '', title: $('.lee-tab-name', tab)?.textContent || 'untitled',
    dirty: tab.classList.contains('dirty'), running: !!$('.lee-tab-run', tab),
  }));
  if (!open.length) return status('no files are open', 'err');
  const byKey = new Map(open.map(x => [x.key, x]));
  let rows = lee.recentTabs.map(x => ({...x, ...byKey.get(x.key)})).filter(x => x.i != null);
  for (const row of open) if (!rows.some(x => x.i === row.i)) rows.push(row);
  const now = Date.now(), active = activeTabIndex();
  if (now - lee.recentCycleAt > 1400 || !lee.recentCycle.length)
    lee.recentCycle = rows.filter(x => x.i !== active).map(x => x.i);
  lee.recentCycleAt = now;
  if (lee.recentCycle.length) {
    const next = lee.recentCycle.shift(); lee.recentCycle.push(next);
    return htmxPost('/tab/select?i=' + next);
  }
  let filtered = rows, sel = Math.max(0, Math.min(1, rows.length - 1));
  const m = modal(`<div class="lee-mhead">Recent files<span class="sub">most recently used</span></div>` +
    `<input class="lee-input lee-recent-query" placeholder="filter open files…" autofocus>` +
    `<div class="lee-modallist lee-recent-list"></div><div class="lee-mfoot lee-dim">enter switch · delete close</div>`, e => {
      if (e.key === 'ArrowDown') { e.preventDefault(); sel = Math.min(sel + 1, filtered.length - 1); paint(); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); sel = Math.max(0, sel - 1); paint(); }
      else if (e.key === 'Enter') { e.preventDefault(); go(); }
      else if (e.key === 'Delete' && filtered[sel]) { e.preventDefault(); const row = filtered[sel]; m.remove(); closeTab(row.i); }
    });
  const list = $('.lee-recent-list', m), input = $('.lee-recent-query', m);
  const paint = () => {
    list.innerHTML = filtered.length ? filtered.map((r, i) => `<button class="lee-recent-row${i === sel ? ' sel' : ''}" data-i="${i}">` +
      `<span class="lee-recent-kind">${r.kind === 'notebook' ? 'NB' : 'FILE'}</span>` +
      `<span class="lee-recent-copy"><strong>${esc(r.title)}</strong><small>${esc(compactPath(r.path))}</small></span>` +
      `<span class="lee-recent-state">${r.running ? 'running' : r.dirty ? 'unsaved' : ''}</span></button>`).join('') :
      '<div class="lee-dim">No matching open files.</div>';
    $('.lee-recent-row.sel', list)?.scrollIntoView({block: 'nearest'});
  };
  const go = () => { const row = filtered[sel]; if (!row) return; m.remove(); htmxPost('/tab/select?i=' + row.i); };
  input.oninput = () => { const q = input.value.trim().toLowerCase(); filtered = rows.filter(r => `${r.title} ${r.path}`.toLowerCase().includes(q)); sel = 0; paint(); };
  list.onclick = e => { const row = e.target.closest('[data-i]'); if (!row) return; sel = +row.dataset.i; go(); };
  paint();
}
function shiftTab(d) {
  const n = $$('.lee-tab').length; if (!n) return;
  htmxPost('/tab/select?i=' + ((activeTabIndex() + d + n) % n));
}
function layoutTabs() {
  const bar = $('#tabbar'), more = $('#taboverflow'); if (!bar || !more) return;
  const tabs = $$('.lee-tab', bar), active = Math.max(0, activeTabIndex());
  // The active file and its neighbours stay spatially meaningful, and every other open document
  // is one click away in the overflow menu.
  const breakpointCap = innerWidth >= 1700 ? 7 : innerWidth >= 1300 ? 5 : innerWidth >= 960 ? 4 : 2;
  const cap = Math.max(1, Math.min(breakpointCap, Math.floor(bar.clientWidth / 138) || 1));
  const keep = new Set();
  if (tabs.length <= cap) tabs.forEach((_, i) => keep.add(i));
  else {
    keep.add(active);
    for (let distance = 1; keep.size < cap && distance < tabs.length; distance++) {
      if (active - distance >= 0) keep.add(active - distance);
      if (keep.size < cap && active + distance < tabs.length) keep.add(active + distance);
    }
    for (let i = 0; keep.size < cap && i < tabs.length; i++) keep.add(i);
  }
  tabs.forEach((tab, i) => tab.classList.toggle('overflowed', !keep.has(i)));
  const hidden = tabs.length - keep.size;
  more.hidden = hidden <= 0; more.textContent = hidden > 0 ? `+${hidden}` : '⋯';
  more.title = hidden > 0 ? `${hidden} more open files` : 'all open files';
}
function leeTabOverflow(anchor) {
  const rows = $$('.lee-tab').map((tab, i) => ({tab, i})).filter(x => x.tab.classList.contains('overflowed')).map(({tab, i}) => ({
    label: $('.lee-tab-name', tab)?.textContent || `tab ${i + 1}`,
    detail: `${tab.classList.contains('dirty') ? 'unsaved · ' : ''}${tab.title || ''}`,
    run: () => htmxPost('/tab/select?i=' + i),
  }));
  openChromeMenu(anchor, rows);
}
window.leeTabOverflow = leeTabOverflow;
// Returns htmx's promise: closing several tabs has to await each swap, because the server
// addresses tabs by index and the next index is only true once the strip has been rebuilt.
function htmxPost(url) { return htmx.ajax('POST', url, {target: '#tabbar', swap: 'outerHTML'}); }
let openFileVersion=0;
function gitDiffTabKey(data) { return encodeURIComponent(`${data.kind || 'review'}\0${data.base || ''}\0${data.head || ''}\0${data.path}`); }
function syncGitDiffTabs() {
  const bar = $('#tabbar'); if (!bar) return;
  for (const [key, data] of lee.gitDiffTabs) {
    if ($(`.lee-tab[data-git-diff="${CSS.escape(key)}"]`, bar)) continue;
    const tab = document.createElement('div');
    tab.className = 'lee-tab lee-git-diff-tab' + (lee.activeGitTab === key ? ' active' : '');
    tab.dataset.gitDiff = key; tab.dataset.kind = 'git-diff'; tab.title = `${data.base} → ${data.head} · ${data.path}`;
    tab.setAttribute('role', 'tab'); tab.innerHTML = `<span class="lee-git-diff-dot">±</span><span class="lee-tab-name">${esc(data.path.split('/').pop())}</span><span class="lee-git-diff-ref">${esc(data.headLabel || data.head.slice(0, 8))}</span><button class="lee-tab-x" title="close diff" aria-label="close diff">×</button>`;
    tab.onclick = e => { if (e.target.closest('.lee-tab-x')) closeGitDiffTab(key); else activateGitDiffTab(key); };
    bar.appendChild(tab);
  }
  requestAnimationFrame(layoutTabs);
}
function closeGitDiffTab(key) {
  const wasActive = lee.activeGitTab === key, returnTab = lee.gitDiffTabs.get(key)?.returnTab || 0;
  lee.gitDiffTabs.delete(key); $(`.lee-tab[data-git-diff="${CSS.escape(key)}"]`)?.remove();
  if (wasActive) { lee.activeGitTab = ''; lee.gitMergeView && LeeCM.destroyMerge(lee.gitMergeView); lee.gitMergeView = null; htmxPost('/tab/select?i=' + Math.max(0, Number(returnTab) || 0)); }
  else layoutTabs();
}
function binaryDiffHtml(data) {
  // An LFS pointer is text, so git diffs it as text: three lines of oid and size where the file
  // should be. Say which file it is and what it weighs instead of rendering the stand-in.
  const lfs = data.lfs || data.file?.lfs;
  const size = Number(lfs?.size);
  const detail = lfs
    ? `Stored with Git LFS${Number.isFinite(size) && size ? ` · ${(size / 1024).toFixed(0)} KB` : ''}`
    : 'Text comparison is not available for this file.';
  return `<div class="lee-git-empty-state"><strong>Binary file changed</strong><span>${esc(detail)}</span>` +
    `${lfs?.oid ? `<code>${esc(String(lfs.oid).replace(/^sha256:/, '').slice(0, 12))}</code>` : ''}</div>`;
}

async function openGitDiffTab(data) {
  const key = gitDiffTabKey(data), existing = lee.gitDiffTabs.get(key), returnTab = $('.lee-tab.active:not([data-git-diff])')?.dataset.i || existing?.returnTab || 0;
  lee.gitDiffTabs.set(key, {...existing, ...data, key, returnTab, view: existing?.view || data.view || 'unified'});
  syncGitDiffTabs(); await activateGitDiffTab(key);
}
async function activateGitDiffTab(key) {
  const data = lee.gitDiffTabs.get(key); if (!data) return;
  lee.activeGitTab = key; $$('.lee-tab').forEach(t => t.classList.toggle('active', t.dataset.gitDiff === key));
  lee.cellObserver?.disconnect(); lee.cellObserver = null;
  lee.editors.forEach((v, k) => { if (k !== 'exec') { LeeCM.destroy(v); lee.editors.delete(k); } });
  if (lee.gitMergeView) { LeeCM.destroyMerge(lee.gitMergeView); lee.gitMergeView = null; }
  lee.kind = 'git-diff'; lee.path = ''; lee.tabKey = `git-diff:${key}`; updateToolbarForKind('git-diff');
  const host = $('#editor'); if (!host) return;
  host.innerHTML = `<section class="lee-diff-document"><header><div><strong>${esc(data.path)}</strong><span>${esc(data.baseLabel || data.base)} → ${esc(data.headLabel || data.head)}</span></div><nav aria-label="Diff layout"><button data-diff-view="unified">unified</button><button data-diff-view="split">side by side</button>${isMarkdownPath(data.path) ? '<button data-diff-view="rendered">rendered</button>' : ''}</nav><span class="lee-spacer"></span><span class="lee-diff-edit-state" hidden>preview changed</span>${data.allowWrite ? '<button data-apply-merge-result hidden>apply result to working tree</button>' : ''}${data.reviewKey ? '<button data-review-note>note…</button><button data-review-mark>mark reviewed</button>' : ''}${data.can_apply ? '<button data-review-apply>apply hunks…</button>' : ''}${data.group ? '<button data-diff-hunks>select hunks</button>' : ''}<button data-open-source>open working file</button></header><div class="lee-diff-document-body"></div></section>`;
  host.querySelectorAll('[data-diff-view]').forEach(b => { b.classList.toggle('active', b.dataset.diffView === data.view); b.onclick = () => { data.view = b.dataset.diffView; activateGitDiffTab(key); }; });
  host.querySelector('[data-open-source]').onclick = () => data.absolutePath ? leeOpenFile(data.absolutePath) : status('this historical file has no working-tree path', 'err');
  host.querySelector('[data-diff-hunks]')?.addEventListener('click', () => showGitFileDiff(data.absolutePath || data.path, data.patch, 0, data.rawPatch || data.patch, !!data.notebook, {group: data.group, label: `${data.baseLabel} → ${data.headLabel}`}));
  const mark = host.querySelector('[data-review-mark]'); if (mark) { mark.classList.toggle('active', !!gitUI.reviewed[data.reviewKey]); mark.textContent = gitUI.reviewed[data.reviewKey] ? 'reviewed ✓' : 'mark reviewed'; mark.onclick = () => { gitUI.reviewed[data.reviewKey] = !gitUI.reviewed[data.reviewKey]; saveGitWorkflowState(); activateGitDiffTab(key); }; }
  host.querySelector('[data-review-note]')?.addEventListener('click', async () => { const note = await inputDialog('review note', `Note for ${data.path}`, gitUI.reviewNotes[data.reviewKey] || '', 'Question, risk, or follow-up'); if (note !== null) { if (note.trim()) gitUI.reviewNotes[data.reviewKey] = note.trim(); else delete gitUI.reviewNotes[data.reviewKey]; saveGitWorkflowState(); } });
  host.querySelector('[data-review-apply]')?.addEventListener('click', () => { gitUI.reviewFile = data.path; gitUI.reviewPatch = data.patch; showReviewHunkApply(gitUI.snapshot); });
  host.querySelector('[data-apply-merge-result]')?.addEventListener('click', async () => {
    if (data.mergeResult == null) return;
    const message = `Replace the working-tree version of ${data.path} with this reviewed result? The file will remain uncommitted.`;
    if (!await confirmDialog('apply split diff result', message, 'apply result')) return;
    const at = data.root ? {repo: data.root} : {};
    try { const next = await gitDo('write_worktree', {path: data.path, content: data.mergeResult, before: data.worktreeBefore ?? null, ...at}), fresh = noteHl(await api(gitUrl('/git/diff', {path: data.path, staged: false, ...at}))); data.base = 'index'; data.head = 'worktree'; data.baseLabel = 'index'; data.headLabel = 'working tree'; data.left = fresh.left || ''; data.right = fresh.right || ''; data.patch = fresh.content || fresh.text || ''; data.rawPatch = fresh.text || ''; data.group = 'unstaged'; data.mergeResult = null; data.worktreeBefore = fresh.right || ''; gitUI.review = null; paintGitPill(next); await activateGitDiffTab(key); status(`${data.path} updated in the working tree`, 'ok'); }
    catch (e) { status(e.message || String(e), 'err'); }
  });
  const body = host.querySelector('.lee-diff-document-body');
  if (data.binary || data.file?.binary) body.innerHTML = binaryDiffHtml(data);
  else if (data.view === 'rendered' && isMarkdownPath(data.path)) await mountMarkdownDiff(body, data);
  else if (data.view === 'split') {
    body.className += ' split';
    const changed = result => { data.mergeResult = result; const state = host.querySelector('.lee-diff-edit-state'), apply = host.querySelector('[data-apply-merge-result]'); if (state) state.hidden = false; if (apply) apply.hidden = false; };
    lee.gitMergeView = createMerge(body, {left: data.left || '', right: data.mergeResult ?? data.right ?? '', lang: codeLang('', data.path), settings: lee.editorPrefs, readOnlyRight: !data.allowWrite, revertControls: data.allowWrite ? 'a-to-b' : false, onChange: data.allowWrite ? changed : null});
  } else {
    body.innerHTML = gitDiffNotebookHtml(data.patch, data);
    body.querySelectorAll('[data-fold-diff]').forEach(b => b.onclick = () => { const cell = b.closest('.lee-diff-cell'), folded = cell.classList.toggle('collapsed'); b.textContent = folded ? '+' : '−'; });
  }
  setScope('editor'); layoutTabs();
}
function gitDiffNotebookHtml(patch, data) {
  const parts = gitPatchParts(patch);
  if (!parts.hunks.length) return `<div class="lee-git-empty-state"><strong>No textual patch</strong><span>${data.path} has no line-level changes in this comparison.</span></div>`;
  return `<div class="lee-diff-notebook">${parts.hunks.map((h, i) => { const title = h.split('\n')[0] || `hunk ${i + 1}`; return `<article class="lee-diff-cell"><header><button data-fold-diff aria-label="collapse hunk">−</button><strong>change ${i + 1}</strong><code>${esc(title)}</code><span class="lee-spacer"></span><small>${h.split('\n').filter(x => x.startsWith('+') && !x.startsWith('+++')).length} added · ${h.split('\n').filter(x => x.startsWith('-') && !x.startsWith('---')).length} removed</small></header><div class="lee-git-patch">${gitPatchHtml(h)}</div></article>`; }).join('')}</div>`;
}
window.openGitDiffTab = openGitDiffTab;

