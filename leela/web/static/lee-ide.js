/* leela IDE client.
 *
 * The keymap is not defined here. It is fetched from /keys.json, which Python
 * generates from leela.keys, so this file cannot drift from the TUI --
 * adding a binding in Python lights it up in both frontends.
 *
 * Dispatch is scope-aware: the focused pane sets `lee.scope`, a binding fires
 * when its scope matches or is 'global', and a chord that matches nothing is
 * left alone so the browser and CodeMirror keep their own behaviour.
 */
"use strict";

const lee = {
  keys: [], help: {}, scope: 'editor', execScope: 'live',
  editors: new Map(),        // cell id (or 'exec'/'file') -> CodeMirror view
  cells: [], sel: 0, kind: null, path: '',
  hist: [], histIdx: 0,
  varOpen: new Set(), varPrev: {},
  term: null, lastDoc: null,
};
window.lee = lee;

const $  = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, c =>
  ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));

async function api(url, opts) {
  const r = await fetch(url, opts);
  const ct = r.headers.get('content-type') || '';
  const body = ct.includes('json') ? await r.json() : await r.text();
  if (!r.ok) throw new Error((body && body.error) || r.statusText);
  return body;
}
const post = (url, data) => api(url, {method: 'POST', headers: {'Content-Type': 'application/json'},
                                      body: JSON.stringify(data || {})});

function status(msg, kind) {
  const el = $('#status'); if (!el) return;
  el.textContent = msg || '';
  el.className = 'lee-status' + (kind ? ' ' + kind : '');
  if (kind === 'ok') setTimeout(() => { if (el.textContent === msg) el.textContent = ''; }, 2500);
}

/* ------------------------------------------------------------------ keymap */
async function loadKeys() {
  const d = await api('/keys.json');
  lee.keys = d.keys; lee.help = d.help; lee.keyPath = d.path; lee.keyNotes = d.notes || [];
  lee.bars = d.bars || {};
  if (lee.keyNotes.length) status(lee.keyNotes[0] + ' — see the keys panel', 'err');
}

/* The physical key behind an event, for the one case where `e.key` lies.
 *
 * On macOS, Option is a compose key: alt+w arrives as `e.key === '∑'`, alt+i as a dead
 * key, and so on -- so every alt binding in the map would silently never match. `e.code`
 * is the physical key and is unaffected, so it is used as a second chance *only* when alt
 * is held. Anywhere else `e.key` is the right answer, because it is the one that respects
 * the user's keyboard layout. */
function physKey(e) {
  const c = e.code || '';
  if (/^Key[A-Z]$/.test(c)) return c.slice(3).toLowerCase();
  if (/^Digit[0-9]$/.test(c)) return c.slice(5);
  if (/^Bracket(Left|Right)$/.test(c)) return c === 'BracketLeft' ? '[' : ']';
  if (c === 'Slash') return '/';
  if (c === 'Backquote') return '`';
  if (c === 'Minus') return '-';
  if (c === 'Equal') return '=';
  return '';
}

function chordMatches(c, e) {
  const want = c.key.toLowerCase();
  const hit = want === (e.key || '').toLowerCase() ||
              (e.altKey && want.length === 1 && want === physKey(e));
  return hit && !!c.ctrl === (e.ctrlKey || e.metaKey) && !!c.alt === e.altKey && !!c.shift === e.shiftKey;
}

// In the terminal almost nothing is ours. A pty expects every keystroke, and the
// chords the IDE would otherwise claim are exactly the ones a shell needs most
// (ctrl+e, ctrl+b, ctrl+r are readline's end-of-line, back-char and history search).
// So `term` scope inverts the usual rule: only bindings declared *for* the terminal
// fire, plus the handful needed to get back out of it.
const TERM_ESCAPES = new Set(['help', 'quit', 'palette', 'toggle_left', 'toggle_right']);
const firesInTerm = (k) => k.scope === 'term' || k.action.startsWith('focus_') || TERM_ESCAPES.has(k.action);

function findBinding(e, scope) {
  const inScope = scope === 'term'
    ? firesInTerm
    : (k) => k.scope === scope || k.scope === 'global';
  return lee.keys.find(k => inScope(k) && k.chords.some(c => chordMatches(c, e)));
}

document.addEventListener('keydown', (e) => {
  const k = findBinding(e, lee.scope);
  if (!k) return;                      // unbound: let the browser and CodeMirror have it
  e.preventDefault(); e.stopPropagation();
  leeAct(k.action);
}, true);

/* The bindings CodeMirror must own, because they fire while it has the cursor
 * and would otherwise be swallowed by the editor's own keymap. */
function cmBinds(scope) {
  const cmKey = (c) => (c.ctrl ? 'Ctrl-' : '') + (c.alt ? 'Alt-' : '') + (c.shift ? 'Shift-' : '') +
    (c.key.length === 1 ? c.key : c.key.replace('Arrow', ''));
  return lee.keys.filter(k => k.scope === scope || k.scope === 'global')
                .flatMap(k => k.chords.map(c => ({cm: cmKey(c), run: () => leeAct(k.action)})));
}

/* ------------------------------------------------------------------ actions */
const ACTIONS = {
  focus_files:  () => { setScope('files'); $('#filetree')?.focus(); highlightTree(); },
  focus_editor: () => { setScope('editor'); focusCell(lee.sel); },
  focus_exec:   () => { setScope('exec'); lee.editors.get('exec')?.focus(); },
  focus_vars:   () => { setScope('vars'); $('#varfilter')?.focus(); },
  focus_agent:  () => { setScope('agent'); $('#agentprompt')?.focus(); },
  toggle_left:  () => $('#shell').classList.toggle('no-left'),
  toggle_right: () => $('#shell').classList.toggle('no-right'),
  toggle_scope: () => leeScope(lee.execScope === 'live' ? 'isolated' : 'live'),
  help:         showHelp,
  quick_open:   quickOpen,
  code_search:  codeSearch,
  run_app:      runApp,
  palette:      palette,
  save:         saveTab,
  save_all:     saveTab,
  close_tab:    () => htmxPost('/tab/close?i=' + activeTabIndex()),
  next_tab:     () => shiftTab(1),
  prev_tab:     () => shiftTab(-1),
  interrupt:    async () => { await post('/kernel/interrupt'); status('interrupted', 'ok'); },
  restart:      async () => { status('restarting kernel…'); await post('/kernel/restart'); status('kernel restarted', 'ok'); leeVars(); },
  switch_env:   () => status('env switching arrives with the dev-server panel'),
  quit:         () => status('close the browser tab to leave'),

  run_cell:     () => lee.kind === 'text' ? runFile() : runCell(lee.sel, false),
  run_advance:  () => lee.kind === 'text' ? runFile() : runCell(lee.sel, true),
  run_insert:   () => lee.kind === 'text' ? runFile() : runCell(lee.sel, 'insert'),
  run_all:      runAll,
  run_file:     runFile,
  run_selection: runSelection,
  pick_kernel:  pickKernel,
  new_notebook: () => htmxPost('/tab/new?kind=notebook'),
  edit_keys:    editKeys,
  cell_above:   () => nbEdit({op: 'insert', i: lee.sel}).then(() => selectCell(lee.sel)),
  cell_below:   () => nbEdit({op: 'insert', i: lee.sel + 1}).then(() => selectCell(lee.sel + 1)),
  cell_delete:  () => nbEdit({op: 'delete', i: lee.sel}).then(() => selectCell(Math.max(0, lee.sel - 1))),
  cell_type:    () => nbEdit({op: 'type', i: lee.sel, cycle: true}),
  capture:      captureScreen,
  cell_split:   () => { const v = lee.editors.get(lee.cells[lee.sel].id);
                        nbEdit({op: 'split', i: lee.sel, offset: v ? LeeCM.cursor(v) : 0}); },
  comment:      toggleComment,
  complete:     kernelComplete,
  ai_complete:  aiComplete,
  show_docs:    showDocs,
  show_diff:    showDiff,
  find_similar: findSimilar,
  code_map:     codeMap,

  exec_run:     runExec,
  exec_newline: () => {},
  exec_prev:    () => recall(-1),
  exec_next:    () => recall(1),
  exec_clear:   leeExecClear,
  exec_promote: () => { leeScope('live'); runExec(); },

  open:         () => { const n = $('.lee-node.sel'); if (n) htmxPost('/tab/open?path=' + encodeURIComponent(n.dataset.path)); },
  new_file:     () => newEntry('file'),
  new_dir:      () => newEntry('dir'),
  rename:       renameEntry,
  delete:       deleteEntry,
  add_root:     addRoot,
  refresh_files: () => location.reload(),
  up_dir:       () => {},
  filter_files: () => status('filter the tree with ctrl+p'),

  expand:       () => $('.lee-vrow.sel')?.click(),
  filter_vars:  () => $('#varfilter')?.focus(),
  edit_value:   editSelectedVar,
  grid:         () => status('click ▦ on a variable to open its grid'),
  copy_value:   () => copyVar('value'),
  copy_path:    () => copyVar('path'),
  promote:      promoteVar,
  sort:         () => { const s = $('#varsort'); s.selectedIndex = (s.selectedIndex + 1) % s.options.length; leeVars(); },
  profile_minimal:  () => setProfile('minimal'),
  profile_standard: () => setProfile('standard'),
  profile_full:     () => setProfile('full'),

  agent_send:   sendAgent,
  agent_stop:   stopAgent,
  agent_transcript: leeAgentTranscript,
  agent_tools:  agentTools,

  terminal:     () => openTerm('shell'),
  git:          () => openTerm('git'),
  term_close:   closeTerm,

  web_search:   webSearch,
  research:     researchQ,
  read_url:     () => readUrl(),
};
for (let i = 1; i <= 9; i++) ACTIONS['tab_' + i] = () => htmxPost('/tab/select?i=' + (i - 1));

function leeAct(name) {
  const f = ACTIONS[name];
  if (!f) return status('no handler for ' + name);
  try { const r = f(); if (r && r.catch) r.catch(e => status(String(e.message || e), 'err')); }
  catch (e) { status(String(e.message || e), 'err'); }
}
window.leeAct = leeAct;

function setScope(s) { lee.scope = s; }
const activeTabIndex = () => $$('.lee-tab').findIndex(t => t.classList.contains('active'));
function shiftTab(d) {
  const n = $$('.lee-tab').length; if (!n) return;
  htmxPost('/tab/select?i=' + ((activeTabIndex() + d + n) % n));
}
function htmxPost(url) { htmx.ajax('POST', url, {target: '#tabbar', swap: 'outerHTML'}); }

/* ------------------------------------------------------------------ editor */
async function mountTab() {
  const st = await api('/tab/state');
  // Only the tab's own editors are torn down. The exec strip belongs to the app, not
  // to the tab, and destroying it here would silently leave the box unmounted.
  lee.editors.forEach((v, k) => { if (k !== 'exec') { LeeCM.destroy(v); lee.editors.delete(k); } });
  const host = $('#editor'); if (!host) return;
  lee.kind = st.kind; lee.path = st.path || ''; lee.cells = st.cells || [];
  if (!st.kind) { host.innerHTML = '<div class="lee-empty">open a file, or press <kbd>ctrl+p</kbd></div>'; return; }
  if (st.kind === 'error') { host.innerHTML = `<div class="lee-err">${esc(st.error)}</div>`; return; }
  if (st.kind === 'notebook') mountNotebook(host, st);
  else mountFile(host, st);
  refreshKernelPill();
}

function mountFile(host, st) {
  host.innerHTML = '<div class="lee-cm" id="filecm"></div>';
  const v = LeeCM.create($('#filecm'), {
    doc: st.text || '', lang: st.lang || 'python', lineNums: true,
    binds: cmBinds('editor'), completeUrl: '/complete',
    onChange: () => markDirty(),
  });
  lee.editors.set('file', v);
  $('#filecm').addEventListener('focusin', () => setScope('editor'));
}

function mountNotebook(host, st) {
  host.innerHTML = '';
  st.cells.forEach((c, i) => host.appendChild(cellEl(c, i)));
  st.cells.forEach((c, i) => mountCell(c, i));
  selectCell(Math.min(lee.sel, st.cells.length - 1));
}

// A prompt cell's gutter is its own mark, so the three kinds are told apart at a glance
// without reading any of them.
const gutterFor = (c) => c.cell_type === 'code' ? '[' + (c.execution_count ?? ' ') + ']'
                       : c.cell_type === 'prompt' ? '✦' : 'md';

/* The per-cell controls, from the same table the toolbar comes from. They act on the cell
 * they are drawn in rather than on the selected one -- clicking ▶ on the third cell has
 * to run the third cell, whatever the cursor was doing. */
function cellButtons(i) {
  return (lee.bars.cell || []).map(b =>
    `<button class="lee-cbtn ${esc(b.kind)}" title="${esc(b.title)}" ` +
    `onclick="leeCellAct(${i}, '${esc(b.action)}')">${esc(b.label)}</button>`).join('');
}
function leeCellAct(i, action) { selectCell(i); setScope('editor'); leeAct(action); }
window.leeCellAct = leeCellAct;

function cellEl(c, i) {
  const d = document.createElement('div');
  d.className = 'lee-cell ' + c.cell_type;
  d.dataset.i = i; d.dataset.id = c.id;
  d.innerHTML =
    `<div class="lee-gutter"><div id="g-${c.id}">${gutterFor(c)}</div>` +
    `<div class="lee-cellbtns">${cellButtons(i)}</div></div>` +
    `<div class="lee-cellmain"><div class="lee-cm" id="cm-${c.id}"></div><div id="out-${c.id}"></div></div>`;
  d.addEventListener('mousedown', () => { selectCell(i); setScope('editor'); });
  return d;
}

function mountCell(c, i) {
  const v = LeeCM.create($('#cm-' + c.id), {
    doc: c.source, lang: c.cell_type === 'code' ? 'python' : 'markdown',
    placeholder: c.cell_type === 'prompt' ? 'ask the assistant — ctrl+enter answers, in place' : '',
    binds: cmBinds('editor'), completeUrl: c.cell_type === 'code' ? '/complete' : null,
    onChange: (txt) => { lee.cells[i].source = txt; markDirty(); },
  });
  lee.editors.set(c.id, v);
  $('#cm-' + c.id).addEventListener('focusin', () => { lee.sel = i; setScope('editor'); paintSel(); });
  renderOutputs(c);
}

function renderOutputs(c) {
  const box = $('#out-' + c.id); if (!box) return;
  box.innerHTML = '';
  // A prompt cell's "output" is the answer, and it is stored in the cell rather than in
  // an nbformat output -- so it renders from its own fields.
  if (c.cell_type === 'prompt') {
    if ((c.calls || []).length)
      box.innerHTML += `<div class="lee-pcalls">${c.calls.map(
        x => `⚙ ${esc(x.tool)} ${esc(x.args)}`).join('<br>')}</div>`;
    if (c.reply) box.innerHTML += `<div class="lee-reply">${esc(c.reply)}</div>`;
    return;
  }
  for (const o of (c.outputs || [])) box.appendChild(outputEl(o));
}

const stripAnsi = (s) => String(s).replace(/\x1b\[[0-9;]*m/g, '');

function outputEl(o) {
  const d = document.createElement('div');
  d.className = 'lee-out' + (o.output_type === 'error' ? ' err' : '');
  if (o.output_type === 'stream') { d.textContent = o.text; return d; }
  if (o.output_type === 'error') {
    d.textContent = stripAnsi((o.traceback || []).join('\n')) || `${o.ename}: ${o.evalue}`;
    return d;
  }
  const data = o.data || {};
  if (data['image/png']) {
    const i = document.createElement('img');
    i.src = 'data:image/png;base64,' + data['image/png'];
    d.appendChild(i); return d;
  }
  if (data['text/html'] || data['image/svg+xml']) {
    // Rich reprs get their own shadow root. pandas ships a <style> block with every
    // DataFrame and `scoped` has been dead for years, so without this an output could
    // restyle the IDE around it.
    d.attachShadow({mode: 'open'}).innerHTML = data['text/html'] || data['image/svg+xml'];
    return d;
  }
  d.textContent = data['text/plain'] || '';
  return d;
}

function paintSel() {
  $$('.lee-cell').forEach(el => el.classList.toggle('sel', +el.dataset.i === lee.sel));
}
function selectCell(i) {
  if (!lee.cells.length) return;
  lee.sel = Math.max(0, Math.min(i, lee.cells.length - 1));
  paintSel();
}
function focusCell(i) {
  selectCell(i);
  const c = lee.cells[lee.sel]; if (!c) return;
  const v = lee.editors.get(c.id); if (v) LeeCM.focus(v);
}
function markDirty() {
  const t = $('.lee-tab.active'); if (t && !t.classList.contains('dirty')) t.classList.add('dirty');
}

async function runCell(i, advance) {
  const c = lee.cells[i]; if (!c) return;
  const v = lee.editors.get(c.id);
  const src = v ? LeeCM.getDoc(v) : c.source;
  const el = $(`.lee-cell[data-i="${i}"]`);
  if (c.cell_type === 'markdown') {
    if (el) el.querySelector('.lee-cm').style.display = 'none';
    const out = $('#out-' + c.id); if (out) out.innerHTML = `<div class="lee-md">${esc(src)}</div>`;
  } else if (c.cell_type === 'prompt') {
    await askCell(i, src, el);
  } else {
    el?.classList.add('running');
    $('#g-' + c.id).textContent = '[*]';
    try {
      const r = await post('/nb/run', {i, source: src});
      lee.cells[i] = r.cell;
      renderOutputs(r.cell);
      $('#g-' + c.id).textContent = '[' + (r.cell.execution_count ?? ' ') + ']';
    } catch (e) { status(String(e.message || e), 'err'); }
    el?.classList.remove('running');
    leeVars();
  }
  if (advance === 'insert') { await nbEdit({op: 'insert', i: i + 1}); focusCell(i + 1); }
  else if (advance) { if (i + 1 < lee.cells.length) focusCell(i + 1); else { await nbEdit({op: 'insert', i: i + 1}); focusCell(i + 1); } }
}

/* Running a prompt cell. The answer lands in the cell rather than in the pane below,
 * which is the point of the cell type: it saves with the notebook and reads in order.
 *
 * The tab is deliberately *not* re-mounted afterwards even though the assistant's tools
 * may have edited files -- /tab/state reloads the notebook from disk, which would throw
 * away the answer that has not been saved yet. Files it changed are reported instead. */
async function askCell(i, src, el) {
  const c = lee.cells[i];
  el?.classList.add('running');
  $('#g-' + c.id).textContent = '…';
  status('thinking…');
  try {
    const r = await post('/nb/ask', {i, source: src});
    lee.cells[i] = r.cell;
    renderOutputs(r.cell);
    for (const e of (r.edits || []))
      agentLog(`<div class="lee-runline"><span class="sub">✎ ${esc(e.path.split('/').pop())} ${esc(e.label)}</span></div>` +
               `<div class="lee-diff inline">${diffHtml(e.rows)}</div>`);
    const here = (r.edits || []).some(e => e.path === lee.path);
    status(here ? 'this notebook also changed on disk — your buffer wins until you save'
                : (r.note || 'answered'), r.ok && !here ? 'ok' : 'err');
    markDirty();
    leeVars();
  } catch (e) { status(String(e.message || e), 'err'); }
  $('#g-' + c.id).textContent = '✦';
  el?.classList.remove('running');
}

/* ---------------------------------------------------------- running files */
/* The exec log is where anything run outside a notebook cell lands -- the exec box, a
 * selection, a whole file. One place to look for "what have I asked this kernel to do". */
function execLine(code, text, ok) {
  const log = $('#execlog'); if (!log) return;
  const line = document.createElement('div');
  line.className = 'lee-runline' + (ok ? '' : ' err');
  line.innerHTML = `<span class="code">${esc(code)}</span><span class="arrow">→</span>` +
                   `<span class="res">${esc((text || 'ok').trim())}</span>`;
  log.appendChild(line); log.scrollTop = log.scrollHeight;
}

/* Run the open .py as a script, in the tab's own kernel: `__main__`, an argv, and a
 * traceback that points at the file -- but with everything it defines left in the
 * namespace the variable panel is watching, which a subprocess could not do. */
async function runFile() {
  if (lee.kind !== 'text') return status('this is a notebook — run its cells, or “▶ all”', 'err');
  const v = lee.editors.get('file');
  const name = (lee.path || '').split('/').pop();
  status('running ' + name + '…');
  const r = await post('/run/file', {text: v ? LeeCM.getDoc(v) : null});
  execLine('▶ ' + r.label, r.text, r.ok);
  status(r.ok ? r.label + ' finished' : r.label + ' raised — see the exec log', r.ok ? 'ok' : 'err');
  leeVars();
}

/* Just the selected code. Read straight off the CodeMirror state rather than through
 * `LeeCM`: the bundle in static/ is committed and rebuilding it needs node, so the client
 * does not grow a dependency on a wrapper function that is not in the shipped build. */
async function runSelection() {
  const v = curEditor();
  if (!v) return status('put the cursor in some code first', 'err');
  const s = v.state.selection.main;
  const code = s.empty ? '' : v.state.doc.sliceString(s.from, s.to);
  if (!code.trim()) return status('select some code first', 'err');
  const r = await post('/run/code', {code});
  const head = code.trim().split('\n')[0].slice(0, 60);
  execLine(head + (code.trim().includes('\n') ? ' …' : ''), r.text, r.ok);
  status(r.ok ? 'ran the selection' : 'the selection raised — see the exec log', r.ok ? 'ok' : 'err');
  leeVars();
}

/* Every code cell, in order, stopping where Jupyter's own "run all" stops. */
async function runAll() {
  if (lee.kind !== 'notebook') return runFile();
  for (let i = 0; i < lee.cells.length; i++) {
    const c = lee.cells[i];
    if (c.cell_type !== 'code' || !(c.source || '').trim()) continue;
    status(`running cell ${i}…`);
    await runCell(i, false);
    if ((lee.cells[i].outputs || []).some(o => o.output_type === 'error'))
      return status(`cell ${i} raised — stopped there`, 'err');
  }
  status('ran every cell', 'ok');
}

/* ---------------------------------------------------------- kernel picker */
/* Two questions, two lists: which interpreter's packages this tab can import, and which
 * launcher runs it. Both restart the kernel, so what that costs is on the screen while
 * the choice is being made rather than in a toast afterwards. */
async function pickKernel() {
  const o = await api('/kernel/options');
  const row = (cur, main, sub, attrs) =>
    `<div class="lee-mrow${cur ? ' sel' : ''}" ${attrs}>${cur ? '● ' : '○ '}${esc(main)}` +
    `<span class="sub">${esc(sub)}</span></div>`;
  const kinds = o.kinds.map(k => row(
    k.current, k.id,
    k.note || (k.id === 'ipymini' ? 'execs and completions run beside a busy cell'
                                  : 'the standard jupyter kernel'),
    `data-kind="${esc(k.id)}"${k.available ? '' : ' data-off="1"'}`)).join('');
  const pys = o.pythons.map(p => row(p.current, p.label, p.path, `data-py="${esc(p.path)}"`)).join('');
  const m = modal(
    `<div class="lee-mhead">kernel<span class="sub">${esc(o.key)} · ` +
    `${o.alive ? '⏺ running, pid ' + o.pid : '○ not started'} · ` +
    `${o.private ? 'private to this tab' : 'shared across this folder'}</span></div>` +
    (o.boot_error ? `<div class="lee-err">${esc(o.boot_error)}</div>` : '') +
    `<div class="lee-dim">choosing either of these restarts the kernel — its variables are lost</div>` +
    `<h4>launcher</h4><div class="lee-modallist">${kinds}</div>` +
    `<h4>interpreter</h4><div class="lee-modallist">${pys}</div>`);
  m.addEventListener('click', async (e) => {
    const r = e.target.closest('.lee-mrow'); if (!r) return;
    if (r.dataset.off) return status('not installed: pip install "leela[ipymini]"', 'err');
    m.remove();
    status('starting the new kernel…');
    const d = await post('/kernel/select',
                         r.dataset.kind ? {kind: r.dataset.kind} : {python: r.dataset.py});
    status(`kernel: ${d.running_kind} · ${(d.python || 'leela’s own python').split('/').pop()}`, 'ok');
    refreshKernelPill(); leeVars();
  });
}

/* ---------------------------------------------------------- the keymap */
/* Editable here, because the alternative is telling someone whose terminal or browser
 * eats ctrl+enter to go and find a JSON file. Saving re-reads it server-side and reloads
 * the table this client dispatches on, so a new chord works on the next keystroke. */
async function editKeys() {
  const d = await api('/keys/file');
  const m = modal(
    `<div class="lee-mhead">keybindings<span class="sub">${esc(d.path)}</span></div>` +
    `<div class="lee-dim">action → chord, or several separated by spaces; "" unbinds it. ` +
    `A chord is [ctrl+][alt+][shift+]base.</div>` +
    `<div id="keynotes"></div>` +
    `<textarea class="lee-keyedit" id="keytext" spellcheck="false"></textarea>` +
    `<div class="lee-mfoot"><button class="lee-btn go" id="keysave">save</button>` +
    `<button class="lee-btn" id="keyreset">restore defaults</button></div>`);
  const ta = m.querySelector('#keytext');
  ta.value = d.text;
  const notes = (ns) => {
    m.querySelector('#keynotes').innerHTML = (ns || []).map(n => `<div class="lee-err">${esc(n)}</div>`).join('');
  };
  notes(d.notes);
  const applied = (r) => {
    lee.keys = r.keys; lee.help = r.help; lee.keyNotes = r.notes || [];
    notes(r.notes);
    status(r.notes.length ? 'saved, but some entries were skipped' : 'keys saved and live', 'ok');
    remountEditors();
  };
  m.querySelector('#keysave').onclick = async () => {
    try { applied(await post('/keys/save', {text: ta.value})); }
    catch (e) { status(String(e.message || e), 'err'); }
  };
  m.querySelector('#keyreset').onclick = async () => {
    const r = await post('/keys/reset');
    ta.value = JSON.stringify({keys: Object.fromEntries(r.keys.map(k => [k.action, k.key]))}, null, 2);
    applied(r);
  };
}

/* CodeMirror captures its own keymap at creation, so a rebound chord only reaches the
 * editors after they are rebuilt. Cheap, and it happens once, when the map changes. */
function remountEditors() {
  const v = lee.editors.get('exec');
  if (v) { LeeCM.destroy(v); lee.editors.delete('exec'); }
  mountExec();
  mountTab();
}

/* Screen capture. The grab happens here, not on the server: getDisplayMedia needs a user
 * gesture and a real display, and a server process has neither. The track is kept across
 * captures so only the first press asks permission. */
async function captureScreen() {
  try {
    if (!lee.vtrack || lee.vtrack.readyState === 'ended') {
      const s = await navigator.mediaDevices.getDisplayMedia({video: true});
      lee.vtrack = s.getVideoTracks()[0];
    }
    const bmp = await new ImageCapture(lee.vtrack).grabFrame();
    const scale = Math.min(1280 / bmp.width, 1024 / bmp.height, 1);
    const cv = document.createElement('canvas');
    cv.width = Math.floor(bmp.width * scale); cv.height = Math.floor(bmp.height * scale);
    cv.getContext('2d').drawImage(bmp, 0, 0, cv.width, cv.height);
    bmp.close();
    const r = await post('/screen', {data_url: cv.toDataURL('image/png')});
    status(`screen captured (${Math.round(r.bytes / 1024)}kb) — it rides along with your next question`, 'ok');
  } catch (e) { status('capture failed: ' + (e.message || e), 'err'); }
}

async function nbEdit(d) {
  // A file is one document, not a column of cells; a structural edit here would split the
  // buffer the editor is showing.
  if (lee.kind !== 'notebook') { status('cells belong to notebooks — this tab is a file', 'err'); return {}; }
  const cur = lee.cells.map((c, i) => ({i, source: lee.editors.has(c.id) ? LeeCM.getDoc(lee.editors.get(c.id)) : c.source}));
  for (const c of cur) if (lee.cells[c.i]) lee.cells[c.i].source = c.source;
  if (d.op !== 'source') for (const c of cur) await post('/nb/edit', {op: 'source', i: c.i, source: c.source});
  const r = await post('/nb/edit', d);
  lee.cells = r.cells;
  mountNotebook($('#editor'), {cells: r.cells});
  markDirty();
  return r;
}

async function toggleComment() {
  const c = lee.cells[lee.sel]; const v = c && lee.editors.get(c.id);
  if (!v) return;
  const txt = LeeCM.getDoc(v);
  const lines = txt.split('\n');
  const allC = lines.every(l => !l.trim() || l.trimStart().startsWith('#'));
  LeeCM.setDoc(v, lines.map(l => allC ? l.replace(/^(\s*)#\s?/, '$1') : (l.trim() ? l.replace(/^(\s*)/, '$1# ') : l)).join('\n'));
}

/* ---- whichever editor has the cursor: a cell, a whole file, or the exec box ---- */
function curEditor() {
  if (lee.scope === 'exec') return lee.editors.get('exec');
  if (lee.kind === 'notebook') { const c = lee.cells[lee.sel]; return c && lee.editors.get(c.id); }
  return lee.editors.get('file');
}
function curLang() {
  if (lee.scope === 'exec') return 'python';
  if (lee.kind === 'notebook') return lee.cells[lee.sel]?.cell_type === 'markdown' ? 'markdown' : 'python';
  return $('#editor')?.dataset.lang || 'python';
}

function kernelComplete() {
  const v = curEditor();
  if (!v) return status('put the cursor in some code first', 'err');
  LeeCM.startCompletion(v);
}

/* Two completions, two different questions. ctrl+space asks the kernel what names
 * exist -- instant, and right by construction because it is the real namespace.
 * This asks the model what should come next, which costs a forward pass, so it is
 * never fired by typing and the suggestion stays ghost text until tab accepts it. */
async function aiComplete() {
  const v = curEditor();
  if (!v) return status('put the cursor in some code first', 'err');
  if (LeeCM.ghost(v)) { LeeCM.acceptGhost(v); return status('accepted', 'ok'); }
  const pos = LeeCM.cursor(v);
  status('asking the model…');
  const d = await post('/complete/ai', {code: LeeCM.getDoc(v), pos, lang: curLang()});
  if (!d.text) return status(d.note || 'no suggestion', 'err');
  if (LeeCM.cursor(v) !== pos) return status('cursor moved while the model was thinking', 'err');
  LeeCM.focus(v);
  LeeCM.setGhost(v, d.text);
  status('tab accepts · esc dismisses · ' + d.note, 'ok');
}

async function showDocs() {
  const v = curEditor();
  if (!v) return status('put the cursor on a name first', 'err');
  status('asking the kernel…');
  const d = await post('/inspect', {code: LeeCM.getDoc(v), pos: LeeCM.cursor(v)});
  if (!d.text) return status(d.note, 'err');
  status('');
  modal(`<div class="lee-mhead">docs<span class="sub">from the object the kernel actually has</span></div>
         <pre class="lee-docs">${esc(d.text)}</pre>`);
}

/* ------------------------------------------------------------------ diffs */
const diffHtml = (rows) => rows.map(r =>
  `<div class="lee-drow ${r.kind}"><span class="lee-dnum">${r.line || ''}</span>` +
  `<span class="lee-dtext">${esc(r.text)}</span></div>`).join('');

function diffModal(title, label, rows) {
  return modal(`<div class="lee-mhead">${esc(title)}<span class="sub">${esc(label)}</span></div>
                <div class="lee-diff">${diffHtml(rows)}</div>`);
}

// The dirty dot says *that* a tab changed. This says what changed -- the question
// actually worth answering before a save, or after something moved the file underneath.
function bufferBody() {
  return lee.kind === 'notebook'
    ? {cells: lee.cells.map((c, i) => ({i, source: lee.editors.has(c.id) ? LeeCM.getDoc(lee.editors.get(c.id)) : c.source}))}
    : {text: lee.editors.has('file') ? LeeCM.getDoc(lee.editors.get('file')) : ''};
}

async function showDiff() {
  if (!lee.kind) return status('nothing open', 'err');
  const d = await post('/diff', bufferBody());
  if (!d.rows.length) return status('no unsaved changes', 'ok');
  status(`${d.label} unsaved`, 'ok');
  diffModal('unsaved changes — ' + d.title, d.label, d.rows);
}

async function saveTab() {
  try {
    if (lee.kind === 'notebook') {
      const cells = lee.cells.map((c, i) => ({i, source: lee.editors.has(c.id) ? LeeCM.getDoc(lee.editors.get(c.id)) : c.source}));
      await post('/nb/save', {cells});
    } else {
      await post('/nb/save', {text: LeeCM.getDoc(lee.editors.get('file'))});
    }
    $('.lee-tab.active')?.classList.remove('dirty');
    status('saved', 'ok');
  } catch (e) { status(String(e.message || e), 'err'); }
}

/* ------------------------------------------------------------------ exec */
function mountExec() {
  const host = $('#execbox'); if (!host || lee.editors.has('exec')) return;
  const v = LeeCM.create(host, {
    doc: '', lang: 'python', placeholder: 'python — ctrl+enter runs · ctrl+↑/↓ history',
    binds: cmBinds('exec'), completeUrl: '/complete',
  });
  lee.editors.set('exec', v);
  host.addEventListener('focusin', () => setScope('exec'));
  leeScope(lee.execScope);
  api('/exec/history').then(d => { lee.hist = d.cells || []; lee.histIdx = lee.hist.length; }).catch(() => {});
}

function leeScope(s) {
  lee.execScope = s;
  $('#sc-live')?.classList.toggle('active', s === 'live');
  $('#sc-iso')?.classList.toggle('active', s === 'isolated');
  const tag = $('#execscope');
  if (tag) tag.textContent = s === 'live' ? '· runs in the kernel' : '· sandboxed, writes discarded';
  leeVars();
}
window.leeScope = leeScope;

async function runExec() {
  const v = lee.editors.get('exec'); if (!v) return;
  const code = LeeCM.getDoc(v).trim(); if (!code) return;
  const log = $('#execlog');
  try {
    const r = await post('/exec', {code, scope: lee.execScope});
    const line = document.createElement('div');
    line.className = 'lee-runline' + (r.ok ? '' : ' err');
    line.innerHTML = `<span class="code">${esc(code)}</span><span class="arrow">→</span>` +
                     `<span class="res">${esc((r.text || 'ok').trim())}</span>`;
    log.appendChild(line); log.scrollTop = log.scrollHeight;
    lee.hist.push(code); lee.histIdx = lee.hist.length;
    LeeCM.setDoc(v, '');
    leeVars();
  } catch (e) { status(String(e.message || e), 'err'); }
}

function recall(d) {
  const v = lee.editors.get('exec'); if (!v || !lee.hist.length) return;
  lee.histIdx = Math.max(0, Math.min(lee.hist.length, lee.histIdx + d));
  LeeCM.setDoc(v, lee.histIdx >= lee.hist.length ? '' : lee.hist[lee.histIdx]);
  LeeCM.focus(v, true);
}
function leeExecClear() { const l = $('#execlog'); if (l) l.innerHTML = ''; }
window.leeExecClear = leeExecClear;

/* ------------------------------------------------------------------ variables */
async function leeVars() {
  const box = $('#vars'); if (!box) return;
  const profile = $('#varprofile')?.value || 'minimal';
  const sort = $('#varsort')?.value || 'recent';
  let d;
  try { d = await api(`/vars?profile=${profile}&sort=${sort}&scope=${lee.execScope}`); }
  catch (e) { box.innerHTML = `<div class="lee-err">${esc(e.message)}</div>`; return; }
  if (d.error) { box.innerHTML = `<div class="lee-dim">${esc(d.error)}</div>`; return; }

  // A poll must not cost the user their place: remember what is open, what is selected
  // and where the panel is scrolled, re-render, then put all three back.
  const scroll = box.scrollTop, selName = selVar()?.dataset.name;
  const cur = {};
  const html = (d.groups || []).map(g => {
    const rows = (g.nodes || []).map(n => { cur[n.name] = n.value; return varRow(n); }).join('');
    return g.label ? `<div class="lee-vgroup">${esc(g.label)}</div>${rows}` : rows;
  }).join('');
  box.innerHTML = html || '<div class="lee-dim">(no variables yet)</div>';
  lee.varPrev = cur; lee.varSeen = true;
  await Promise.all([...lee.varOpen].map(acc => fillKids(acc)));
  if (selName) $$(`#vars .lee-vrow`).find(r => r.dataset.name === selName)?.classList.add('sel');
  box.scrollTop = scroll;
  leeFilterVars();
}
window.leeVars = leeVars;

function varRow(n, depth = 0) {
  // new/edited is a statement about the namespace, so it only makes sense for top-level
  // names -- tagging a DataFrame's own `shape` as "(new)" is noise, not news. Nor does
  // the very first render, where by definition everything is new.
  const tag = (depth || !lee.varSeen) ? ''
            : (!(n.name in lee.varPrev)) ? '<span class="lee-vnew"> (new)</span>'
            : (lee.varPrev[n.name] !== n.value ? '<span class="lee-vedit"> (edited)</span>' : '');
  const typ = n.shape ? `${n.type}: ${n.shape}` : n.type;
  const acc = encodeURIComponent(JSON.stringify(n.accessor));
  return `<div class="lee-vrow" data-name="${esc(n.name)}" data-acc="${acc}" data-container="${n.is_container ? 1 : 0}"
            onclick="leeVarClick(this)">` +
    `<span class="lee-vname">${esc(n.name)}</span> <span class="lee-vtype">{${esc(typ)}}</span> ` +
    `<span class="lee-vval">${esc(n.value)}</span>${n.is_grid ? ' <span class="lee-vgrid">▦</span>' : ''}${tag}</div>` +
    `<div class="lee-vkids" id="k-${acc}"></div>`;
}

async function fillKids(acc) {
  const box = document.getElementById('k-' + acc);
  if (!box) { lee.varOpen.delete(acc); return; }   // the variable is gone; stop tracking it
  try {
    const kids = await api(`/vars/expand?accessor=${acc}&scope=${lee.execScope}`);
    box.innerHTML = kids.map(k => varRow(k, 1)).join('');
  } catch (e) { lee.varOpen.delete(acc); }
}

async function leeVarClick(el) {
  $$('.lee-vrow').forEach(r => r.classList.remove('sel'));
  el.classList.add('sel');
  if (el.dataset.container !== '1') return;
  const acc = el.dataset.acc;
  const box = document.getElementById('k-' + acc);
  if (!box) return;
  if (lee.varOpen.has(acc)) { lee.varOpen.delete(acc); box.innerHTML = ''; return; }
  lee.varOpen.add(acc);
  await fillKids(acc);
}
window.leeVarClick = leeVarClick;

function leeFilterVars() {
  const q = ($('#varfilter')?.value || '').toLowerCase();
  $$('#vars .lee-vrow').forEach(r => {
    r.style.display = (!q || (r.dataset.name || '').toLowerCase().includes(q)) ? '' : 'none';
  });
}
window.leeFilterVars = leeFilterVars;

function setProfile(p) { const s = $('#varprofile'); if (s) { s.value = p; leeVars(); } }
const selVar = () => $('.lee-vrow.sel');

async function editSelectedVar() {
  const r = selVar(); if (!r) return status('select a variable first');
  const expr = prompt(`set ${r.dataset.name} =`, '');
  if (expr == null) return;
  const res = await post('/vars/set', {accessor: decodeURIComponent(r.dataset.acc), expr});
  res.ok ? (status('set ' + r.dataset.name, 'ok'), leeVars()) : status(res.error, 'err');
}
async function promoteVar() {
  const r = selVar(); if (!r) return status('select a variable first');
  const res = await api('/vars/promote?accessor=' + r.dataset.acc);
  res.ok ? (status('promoted ' + r.dataset.name, 'ok'), leeVars()) : status(res.error, 'err');
}
function copyVar(what) {
  const r = selVar(); if (!r) return status('select a variable first');
  const txt = what === 'path' ? decodeURIComponent(r.dataset.acc) : r.querySelector('.lee-vval').textContent;
  navigator.clipboard?.writeText(txt);
  status('copied ' + what, 'ok');
}

/* ------------------------------------------------------------------ agent */
async function leeAgentTranscript() {
  const d = await api('/agent/transcript');
  const log = $('#agentlog');
  log.innerHTML = (d.cells || []).map(c =>
    `<div class="lee-runline"><span class="${c.cell_type === 'markdown' ? 'res' : 'code'}">${esc(c.source)}</span></div>`
  ).join('') || '<div class="lee-dim">(no transcript yet)</div>';
  log.scrollTop = log.scrollHeight;
}
window.leeAgentTranscript = leeAgentTranscript;

function agentLog(html) {
  const log = $('#agentlog');
  log.innerHTML += html;
  log.scrollTop = log.scrollHeight;
}

// The assistant's tools edit files on disk, so a turn can change what is on screen.
// What comes back with the reply is the diff of every open file that actually moved,
// which is the model's work rather than its account of its work -- and it is what makes
// re-mounting the tab safe to decide about.
// Streamed over SSE, because a turn with a tool loop in it is far too long to sit in
// front of with nothing moving. Three kinds of event arrive: `activity` rows as each tool
// call starts and finishes, `chunk`s of the answer as the model writes it, and one `done`
// carrying the diffs. The last is what makes re-mounting the tab safe to decide about:
// it is the model's work rather than its account of its work.
function sendAgent() {
  const el = $('#agentprompt'); if (!el || !el.value.trim()) return;
  const q = el.value; el.value = '';
  agentLog(`<div class="lee-runline"><span class="code">▸ ${esc(q)}</span></div>`);
  status('thinking…');

  const log = $('#agentlog');
  const acts = document.createElement('div');           // tool calls, rewritten in place
  const out = document.createElement('div');            // the answer, appended to
  out.className = 'lee-runline';
  out.innerHTML = '<span class="res"></span>';
  log.appendChild(acts); log.appendChild(out);
  const body = out.querySelector('.res');
  const seen = new Map();

  const es = new EventSource('/agent/stream?prompt=' + encodeURIComponent(q));

  es.addEventListener('activity', ev => {
    const a = JSON.parse(ev.data);
    // Keyed by id so the ⏳ line a call opens with is *replaced* by its result, rather
    // than leaving a stale pending row above the finished one.
    let row = seen.get(a.id);
    if (!row) { row = document.createElement('div'); row.className = 'lee-runline'; acts.appendChild(row); seen.set(a.id, row); }
    row.innerHTML = `<span class="sub">${esc(a.line)}</span>`;
    log.scrollTop = log.scrollHeight;
  });

  es.addEventListener('chunk', ev => {
    body.textContent += JSON.parse(ev.data).text || '';
    log.scrollTop = log.scrollHeight;
  });

  es.addEventListener('error', ev => {
    try { body.textContent += JSON.parse(ev.data).error || ''; } catch (_) {}
  });

  es.addEventListener('done', async ev => {
    es.close();
    const d = JSON.parse(ev.data);
    for (const e of (d.edits || []))
      agentLog(`<div class="lee-runline"><span class="sub">✎ ${esc(e.path.split('/').pop())} ${esc(e.label)}</span></div>` +
               `<div class="lee-diff inline">${diffHtml(e.rows)}</div>`);
    const tail = d.usage ? `${d.note || 'done'} · ${d.usage}` : (d.note || 'done');
    status(d.ok ? tail : (d.note || 'assistant unavailable'), d.ok ? 'ok' : 'err');
    await reloadAfterEdits(d.edits || []);
  });

  // A dropped connection must not leave the pane saying "thinking…" for ever.
  es.onerror = () => { if (es.readyState === EventSource.CLOSED) status('the stream ended', 'err'); es.close(); };
}

/* Reloading the open tab is what makes an AI edit visible without a refresh -- but only
 * when there is nothing of the user's to lose. Typing while the model thinks is normal,
 * and a buffer with unsaved edits is not something to overwrite silently just because
 * the model happened to reach the same file. So that case is offered, with the diff, and
 * the choice is the user's. */
async function reloadAfterEdits(edits) {
  const e = edits.find(x => x.path && x.path === lee.path);
  if (!e) return;
  if (!$('.lee-tab.active')?.classList.contains('dirty')) return mountTab();
  const m = diffModal(e.path.split('/').pop() + ' changed on disk', e.label, e.rows);
  const bar = document.createElement('div');
  bar.className = 'lee-mfoot';
  bar.innerHTML = '<button class="lee-btn" id="dtake">reload from disk</button>' +
                  '<button class="lee-btn" id="dkeep">keep my buffer</button>' +
                  '<span class="lee-dim">you have unsaved edits in this tab</span>';
  m.querySelector('.lee-modalbox').appendChild(bar);
  bar.querySelector('#dtake').onclick = () => { m.remove(); mountTab(); status('reloaded from disk', 'ok'); };
  bar.querySelector('#dkeep').onclick = () => { m.remove(); status('kept your buffer — ctrl+s overwrites', 'ok'); };
}

async function stopAgent() {
  const d = await post('/agent/stop');
  status(d.ok ? 'asked the model to stop' : d.error, d.ok ? 'ok' : 'err');
}

async function agentTools() {
  const d = await api('/agent/status');
  const rows = (d.calls || []).map(c => `${c.tool}(${c.args})`).join('\n');
  agentLog(`<div class="lee-runline"><span class="sub">${esc(d.note)} · ${d.ntools} tools` +
           `${d.busy ? ' · thinking now' : ''}</span></div>` +
           (rows ? `<div class="lee-runline"><span class="code">${esc(rows)}</span></div>` : ''));
}

/* ------------------------------------------------------------------ terminal */
// One terminal at a time in the drawer. `kind` picks what runs on it: a shell, or
// lazygit. Both are the same pty on the server; only the argv differs.
async function openTerm(kind) {
  const d = await api('/term/info');
  if (!d.enabled) return status(d.why, 'err');
  if (kind === 'git' && !d.lazygit) return status(d.lazygit_why, 'err');
  $('#shell').classList.add('show-term');
  const host = $('#term');
  if (!host) return status('no terminal pane', 'err');
  if (lee.term) { lee.term.dispose(); lee.term = null; }
  host.innerHTML = '';
  $('#termtag').textContent = kind === 'git' ? 'lazygit' : (d.cwd || '').split('/').pop();
  lee.term = LeeTerm.create(host, {
    token: d.token, cwd: d.cwd, kind: kind || 'shell', id: kind || 'shell',
    onStatus: (m) => status('terminal: ' + m),
    onExit: () => { status('terminal exited'); },
  });
  setScope('term');
  lee.term.focus();
}

function closeTerm() {
  if (lee.term) { lee.term.dispose(); lee.term = null; }
  post('/term/close?id=shell'); post('/term/close?id=git');
  $('#shell').classList.remove('show-term');
  setScope('editor');
  // lazygit may have changed the working tree under us; the file tree is now stale.
  status('terminal closed');
}

/* ------------------------------------------------------------------ research */
// Web results reuse the hit-list modal shape, so search-the-code and search-the-web
// feel like the same gesture. Enter reads the page; ctrl+enter saves it into the project.
function docList(docs, note, title) {
  let sel = 0;
  const m = modal(
    `<div class="lee-mhead">${esc(title)}<span class="sub">${esc(note || '')}</span></div>
     <div class="lee-modallist" id="dl"></div>
     <div class="lee-dim lee-mfoot">enter read · ctrl+enter save as markdown · alt+enter save as notebook</div>`,
    (e) => {
      if (e.key === 'ArrowDown') { e.preventDefault(); sel = Math.min(sel + 1, docs.length - 1); paint(); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); sel = Math.max(sel - 1, 0); paint(); }
      else if (e.key === 'Enter') {
        e.preventDefault(); const d = docs[sel]; if (!d) return;
        m.remove();
        if (e.altKey) saveDoc(d, 'notebook');
        else if (e.ctrlKey || e.metaKey) saveDoc(d, 'markdown');
        else readUrl(d.url);
      }
    });
  const list = m.querySelector('#dl');
  const paint = () => {
    list.innerHTML = docs.length ? docs.map((d, i) =>
      `<div class="lee-mrow${i === sel ? ' sel' : ''}" data-i="${i}">` +
      `<span>${esc(d.title || d.url)}</span><span class="sub">${esc(d.url)}</span></div>`).join('')
      : '<div class="lee-dim">nothing found</div>';
    list.querySelector('.sel')?.scrollIntoView({block: 'nearest'});
  };
  list.addEventListener('click', e => {
    const r = e.target.closest('.lee-mrow'); if (!r) return;
    sel = +r.dataset.i; const d = docs[sel]; m.remove(); readUrl(d.url);
  });
  paint();
  return m;
}

async function webSearch() {
  const q = prompt('search the web'); if (!q) return;
  status('searching…');
  const d = await api('/research/search?q=' + encodeURIComponent(q));
  status(d.note, d.docs.length ? 'ok' : null);
  docList(d.docs, d.note, 'web search');
}

async function readUrl(url) {
  url = url || prompt('read a url'); if (!url) return;
  status('fetching ' + url);
  const d = await api('/research/read?url=' + encodeURIComponent(url));
  if (!d.doc) return status(d.note, 'err');
  status(d.note, 'ok');
  agentLog(`<div class="lee-runline"><span class="sub">${esc(d.doc.title)} — ${esc(d.doc.url)}</span></div>` +
           `<div class="lee-runline"><span class="res">${esc(d.doc.text.slice(0, 4000))}</span></div>`);
  lee.lastDoc = d.doc;
}

async function researchQ() {
  const q = prompt('research a question'); if (!q) return;
  status('reading the top results… this takes a moment');
  const d = await api('/research/dig?q=' + encodeURIComponent(q));
  status(d.note, d.docs.length ? 'ok' : 'err');
  agentLog(`<div class="lee-runline"><span class="res">${esc(d.digest.slice(0, 8000))}</span></div>`);
  lee.lastDoc = {title: q, url: '', text: d.digest};
}

async function saveDoc(doc, kind) {
  doc = doc || lee.lastDoc; if (!doc) return status('nothing fetched yet', 'err');
  const r = await post('/research/save', {kind: kind === 'notebook' ? 'notebook' : 'md',
                                          url: doc.url, title: doc.title, text: doc.text});
  if (!r.ok) return status(r.error, 'err');
  status('saved ' + r.entry.path, 'ok');
  htmxPost('/tab/open?path=' + encodeURIComponent(r.entry.path));
}

/* ------------------------------------------------------------------ overlays */
function modal(inner, onKey) {
  const m = document.createElement('div');
  m.className = 'lee-modal';
  m.innerHTML = `<div class="lee-modalbox">${inner}</div>`;
  m.addEventListener('mousedown', e => { if (e.target === m) m.remove(); });
  const key = (e) => {
    if (e.key === 'Escape') { e.preventDefault(); m.remove(); document.removeEventListener('keydown', key, true); return; }
    if (onKey) onKey(e, m);
  };
  document.addEventListener('keydown', key, true);
  document.body.appendChild(m);
  return m;
}

function showHelp() {
  const body = Object.entries(lee.help).map(([scope, rows]) =>
    `<h4>${esc(scope)}</h4>` + rows.map(([k, l]) =>
      `<div class="lee-krow"><kbd>${esc(k)}</kbd><span>${esc(l)}</span></div>`).join('')).join('');
  const m = modal(
    `<div class="lee-mhead">keys<span class="sub">${esc(lee.keyPath || '')}</span></div>` +
    (lee.keyNotes || []).map(n => `<div class="lee-err">${esc(n)}</div>`).join('') +
    `<div class="lee-dim">every one of these can be rebound, and every one of them also has a ` +
    `button — nothing here is reachable only by a chord.</div>` +
    `<div class="lee-help">${body}</div>` +
    `<div class="lee-mfoot"><button class="lee-btn" id="gokeys">edit keybindings</button></div>`);
  m.querySelector('#gokeys').onclick = () => { m.remove(); editKeys(); };
}

async function quickOpen(searchMode) {
  const d = await api('/fs/find');
  let hits = d.hits, sel = 0;
  const m = modal(
    `<input class="lee-input" id="qo" placeholder="${searchMode ? 'search files…' : 'open file…'}" autofocus>
     <div class="lee-modallist" id="qolist"></div>`,
    (e) => {
      if (e.key === 'ArrowDown') { e.preventDefault(); sel = Math.min(sel + 1, hits.length - 1); paint(); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); sel = Math.max(sel - 1, 0); paint(); }
      else if (e.key === 'Enter') { e.preventDefault(); go(); }
    });
  const list = m.querySelector('#qolist'), input = m.querySelector('#qo');
  const paint = () => {
    list.innerHTML = hits.slice(0, 300).map((h, i) =>
      `<div class="lee-mrow${i === sel ? ' sel' : ''}" data-i="${i}">${esc(h.name)}<span class="sub">${esc(h.path)}</span></div>`).join('');
    list.querySelector('.sel')?.scrollIntoView({block: 'nearest'});
  };
  const go = () => { const h = hits[sel]; if (h) { m.remove(); htmxPost('/tab/open?path=' + encodeURIComponent(h.path)); } };
  list.addEventListener('click', e => { const r = e.target.closest('.lee-mrow'); if (r) { sel = +r.dataset.i; go(); } });
  input.addEventListener('input', async () => {
    const q = input.value.trim();
    hits = (await api('/fs/find?q=' + encodeURIComponent(q))).hits; sel = 0; paint();
  });
  paint(); setTimeout(() => input.focus(), 0);
}

async function codeSearch() {
  let hits = [], sel = 0, backend = '';
  const m = modal(
    `<input class="lee-input" id="cs" placeholder="search code…" autofocus>
     <div class="lee-modallist" id="cslist"><div class="lee-dim">type to search</div></div>`,
    (e) => {
      if (e.key === 'ArrowDown') { e.preventDefault(); sel = Math.min(sel + 1, hits.length - 1); paint(); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); sel = Math.max(sel - 1, 0); paint(); }
      else if (e.key === 'Enter') { e.preventDefault(); go(); }
    });
  const list = m.querySelector('#cslist'), input = m.querySelector('#cs');
  const paint = () => {
    if (!hits.length) { list.innerHTML = `<div class="lee-dim">no matches · ${esc(backend)}</div>`; return; }
    list.innerHTML = hits.map((h, i) => {
      const f = h.path.split('/').pop();
      return `<div class="lee-mrow${i === sel ? ' sel' : ''}" data-i="${i}">` +
             `<span>${esc(h.symbol || h.text.slice(0, 60))}</span>` +
             `<span class="sub">${esc(f)}:${h.line} · ${esc(h.kind)}</span></div>`;
    }).join('');
    list.querySelector('.sel')?.scrollIntoView({block: 'nearest'});
  };
  const go = () => {
    const h = hits[sel]; if (!h) return;
    m.remove();
    htmxPost('/tab/open?path=' + encodeURIComponent(h.path));
    status(`${h.path.split('/').pop()}:${h.line}`);
  };
  list.addEventListener('click', e => { const r = e.target.closest('.lee-mrow'); if (r) { sel = +r.dataset.i; go(); } });
  let timer;
  input.addEventListener('input', () => {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      const q = input.value.trim();
      if (!q) { hits = []; list.innerHTML = '<div class="lee-dim">type to search</div>'; return; }
      const d = await api('/search?q=' + encodeURIComponent(q));
      hits = d.hits; backend = d.backend + (d.note ? ' · ' + d.note : ''); sel = 0;
      paint();
      status(`search: ${d.backend}${d.note ? ' — ' + d.note : ''}`);
    }, 180);
  });
  setTimeout(() => input.focus(), 0);
}

/* ---- similarity: what else in this codebase looks like the thing under the cursor ---- */
function cursorLine() {
  if (lee.kind === 'notebook') {
    const c = lee.cells[lee.sel], v = c && lee.editors.get(c.id);
    return v ? LeeCM.lineOf(v) : 1;
  }
  const v = lee.editors.get('file');
  return v ? LeeCM.lineOf(v) : 1;
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
      `<span class="sub">${esc(h.path.split('/').pop())}:${h.line}` +
      `${h.score ? ' · d=' + h.score.toFixed(3) : ''}</span></div>`).join('')
      : '<div class="lee-dim">nothing found</div>';
    list.querySelector('.sel')?.scrollIntoView({block: 'nearest'});
  };
  const go = () => { const h = hits[sel]; if (h) { m.remove(); onPick(h); } };
  list.addEventListener('click', e => { const r = e.target.closest('.lee-mrow'); if (r) { sel = +r.dataset.i; go(); } });
  paint();
  return m;
}

const openHit = (h) => {
  htmxPost('/tab/open?path=' + encodeURIComponent(h.path));
  status(`${h.path.split('/').pop()}:${h.line}`);
};

async function findSimilar() {
  if (!lee.path) return status('open a file first', 'err');
  status('finding similar code…');
  const d = await api(`/similar?path=${encodeURIComponent(lee.path)}&line=${cursorLine()}&mode=cluster`);
  status(`${d.hits.length} similar · ${d.backend} · ${d.note}`, d.hits.length ? 'ok' : null);
  hitList(d.hits, `${d.backend} — ${d.note}`, 'code like this', openHit);
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
  hitList(rows, d.note, 'code map — clusters by shape', (r) => {
    const c = r._cluster;
    hitList(c.members, `${c.size} members across ${c.files.length} files`, `cluster: ${c.label}`, openHit);
  });
}

async function runApp() {
  if (!lee.path || !lee.path.endsWith('.py')) return status('open a .py app first', 'err');
  status('starting dev server…');
  try {
    const d = await api('/dev/start?path=' + encodeURIComponent(lee.path));
    if (!d.ok) return status(d.error || 'failed to start', 'err');
    status(`${d.label} running · app ${d.app_url || '?'} · inspector ${d.base || '?'}`, 'ok');
    const log = $('#agentlog');
    if (log) log.textContent = (d.log || []).join('\n');
  } catch (e) { status(String(e.message || e), 'err'); }
}

function palette() {
  const cmds = lee.keys.filter(k => k.label).map(k => ({name: k.label, scope: k.scope, action: k.action, key: k.key}));
  let hits = cmds, sel = 0;
  const m = modal(`<input class="lee-input" id="cp" placeholder="command…" autofocus>
                   <div class="lee-modallist" id="cplist"></div>`,
    (e) => {
      if (e.key === 'ArrowDown') { e.preventDefault(); sel = Math.min(sel + 1, hits.length - 1); paint(); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); sel = Math.max(sel - 1, 0); paint(); }
      else if (e.key === 'Enter') { e.preventDefault(); go(); }
    });
  const list = m.querySelector('#cplist'), input = m.querySelector('#cp');
  const paint = () => {
    list.innerHTML = hits.slice(0, 200).map((h, i) =>
      `<div class="lee-mrow${i === sel ? ' sel' : ''}" data-i="${i}">${esc(h.name)}<span class="sub">${esc(h.scope)} · ${esc(h.key)}</span></div>`).join('');
    list.querySelector('.sel')?.scrollIntoView({block: 'nearest'});
  };
  const go = () => { const h = hits[sel]; if (h) { m.remove(); leeAct(h.action); } };
  list.addEventListener('click', e => { const r = e.target.closest('.lee-mrow'); if (r) { sel = +r.dataset.i; go(); } });
  input.addEventListener('input', () => {
    const q = input.value.toLowerCase();
    hits = cmds.filter(c => c.name.toLowerCase().includes(q) || c.action.includes(q)); sel = 0; paint();
  });
  paint(); setTimeout(() => input.focus(), 0);
}

/* ------------------------------------------------------------------ file ops */
const treeSel = () => $('.lee-node.sel');
function highlightTree() { if (!treeSel()) $$('.lee-node')[0]?.classList.add('sel'); }

async function newEntry(kind) {
  const sel = treeSel();
  const parent = sel ? (sel.classList.contains('lee-dir') ? sel.dataset.path
                                                        : sel.dataset.path.replace(/\/[^/]+$/, '')) : '';
  const name = prompt(kind === 'dir' ? 'new folder name' : 'new file name', '');
  if (!name) return;
  const r = await post('/fs/new', {parent, name, kind});
  if (!r.ok) return status(r.error, 'err');
  status('created ' + name, 'ok');
  if (kind === 'file') htmxPost('/tab/open?path=' + encodeURIComponent(r.entry.path));
  else location.reload();
}
async function renameEntry() {
  const sel = treeSel(); if (!sel) return status('select a file first');
  const name = prompt('rename to', sel.dataset.path.split('/').pop());
  if (!name) return;
  const r = await post('/fs/rename', {path: sel.dataset.path, name});
  r.ok ? location.reload() : status(r.error, 'err');
}
async function deleteEntry() {
  const sel = treeSel(); if (!sel) return status('select a file first');
  if (!confirm('delete ' + sel.dataset.path + '?')) return;
  const r = await post('/fs/delete', {path: sel.dataset.path});
  r.ok ? location.reload() : status(r.error, 'err');
}
function addRoot() {
  const p = prompt('folder to open', '');
  if (p) htmx.ajax('POST', '/fs/add_root?path=' + encodeURIComponent(p), {target: '#shell', swap: 'outerHTML'});
}

document.addEventListener('click', (e) => {
  const n = e.target.closest('.lee-node');
  if (n) { $$('.lee-node').forEach(x => x.classList.remove('sel')); n.classList.add('sel'); setScope('files'); }
  if (e.target.closest('.lee-vars')) setScope('vars');
});

/* ------------------------------------------------------------------ splitters */
function initSplits() {
  $$('.lee-split').forEach(sp => {
    sp.onpointerdown = (e) => {
      e.preventDefault(); sp.classList.add('drag'); sp.setPointerCapture(e.pointerId);
      const side = sp.dataset.split;
      const move = (ev) => {
        const w = side === 'left' ? ev.clientX : window.innerWidth - ev.clientX;
        const v = Math.max(140, Math.min(window.innerWidth - 300, w));
        document.documentElement.style.setProperty(`--lee-${side}-w`, v + 'px');
        localStorage.setItem(`lee-${side}-w`, v + 'px');
      };
      const up = () => { sp.classList.remove('drag'); sp.onpointermove = null; sp.onpointerup = null; };
      sp.onpointermove = move; sp.onpointerup = up;
    };
  });
  const hs = $('.lee-hsplit');
  if (hs) hs.onpointerdown = (e) => {
    e.preventDefault(); hs.classList.add('drag'); hs.setPointerCapture(e.pointerId);
    const move = (ev) => {
      const v = Math.max(80, Math.min(window.innerHeight - 220, window.innerHeight - ev.clientY - 190));
      document.documentElement.style.setProperty('--lee-exec-h', v + 'px');
      localStorage.setItem('lee-exec-h', v + 'px');
    };
    hs.onpointermove = move;
    hs.onpointerup = () => { hs.classList.remove('drag'); hs.onpointermove = null; };
  };
  ['left-w', 'right-w', 'exec-h'].forEach(k => {
    const v = localStorage.getItem('lee-' + k);
    if (v) document.documentElement.style.setProperty('--lee-' + k, v);
  });
}

async function refreshKernelPill() {
  try {
    const d = await api('/kernel/info');
    const pill = $('#kpill'); if (!pill) return;
    pill.className = 'lee-pill ' + (d.alive ? 'lee-pill-on' : 'lee-pill-err');
    pill.textContent = (d.alive ? '⏺ ' : '○ ') + (d.key || '').split('/').pop();
    pill.title = (d.base || 'no inspector') + (d.boot_error ? ' · ' + d.boot_error : '');
  } catch (e) {}
}

/* ------------------------------------------------------------------ boot */
async function boot() {
  await loadKeys();
  initSplits();
  mountExec();
  await mountTab();
  leeVars();
  setInterval(leeVars, 2500);          // the kernel's own inspector is the source of truth; poll it
  setInterval(refreshKernelPill, 5000);
  status('ready', 'ok');
}

document.addEventListener('DOMContentLoaded', boot);

document.addEventListener('htmx:afterSwap', (e) => {
  const id = e.target.id || '';
  // A tab change swaps only the tab bar; re-mount the editor for whatever is now active.
  if (id === 'tabbar') mountTab().then(leeVars);
  // Adding a folder rebuilds the whole shell, so everything the client owns is remounted.
  else if (id === 'shell') { lee.editors.clear(); initSplits(); mountExec(); mountTab().then(leeVars); }
});
