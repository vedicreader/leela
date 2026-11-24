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

/* Extraction and inlining in a file run against the file on disk: the endpoints read it themselves and address it by
   character offset, so an unsaved buffer would be rewritten from text the server never saw. Both refuse rather than
   save on the user's behalf. In a notebook they run on the selected code cell's text and land in its editor. */
function refactorTarget() {
  if (lee.observer || lee.present) { status('refactoring is not available here', 'err'); return null; }
  if (lee.readOnly) { status(`${compactPath(lee.path)} is read-only`, 'err'); return null; }
  if (lee.kind === 'notebook' && lee.scope !== 'exec' && lee.activeEditor !== 'secondary') {
    const c = lee.cells[lee.sel], view = c && lee.editors.get(c.id);
    if (c?.cell_type !== 'code' || !view || nbLang() !== 'python') { status('select a Python code cell to refactor', 'err'); return null; }
    return view;
  }
  if (lee.kind !== 'text' || !(lee.path || '').endsWith('.py')) {
    status('open a Python file or notebook to refactor', 'err'); return null;
  }
  if (lee.dirtyBuffers.has(lee.path)) { status('save the file before refactoring', 'err'); return null; }
  return curEditor();
}

//: A CodeMirror offset (UTF-16 units) as the code-point index Python reads.
const pyOffset = (text, pos) => [...text.slice(0, pos)].length;

/* One cell, refactored on the server and put back as a single change over the span that differs, so the cell's
   own undo takes it back. The code cells below go along: a name they read stays returned, and an inline that would
   break them is refused. */
async function runCellRefactor(view, body, note) {
  const key = lee.tabKey, i = lee.sel, id = lee.cells[i].id, source = LeeCM.getDoc(view);
  const later = lee.cells.slice(i + 1).filter(c => c.cell_type === 'code')
    .map(c => lee.editors.has(c.id) ? LeeCM.getDoc(lee.editors.get(c.id)) : c.source).join('\n');
  const at = p => pyOffset(source, p);
  const sent = {...body, ...(body.start != null ? {start: at(body.start), end: at(body.end)} : {}), ...(body.pos != null ? {pos: at(body.pos)} : {})};
  const data = await post('/refactor/cell', {...sent, source, later});
  if (lee.tabKey !== key || lee.editors.get(id) !== view || LeeCM.getDoc(view) !== source)
    return status('the cell changed while refactoring; try again', 'err');
  const {from, to} = textSpan(source, data.after);
  LeeCM.replaceRange(view, from, source.length - to, data.after.slice(from, data.after.length - to));
  LeeCM.focus(view); status(`${note} · undo in the cell takes it back`, 'ok');
}

//: Common prefix length, and common suffix length after it, of two texts.
function textSpan(a, b) {
  let from = 0; while (from < a.length && from < b.length && a[from] === b[from]) from++;
  let to = 0; while (to < a.length - from && to < b.length - from && a[a.length - 1 - to] === b[b.length - 1 - to]) to++;
  return {from, to};
}

async function runRefactor(url, body, note) {
  const view = curEditor();
  if (lee.kind === 'notebook') return runCellRefactor(view, {op: url === '/refactor/inline' ? 'inline' : 'extract', ...body}, note);
  const text = LeeCM.getDoc(view), at = p => p == null ? p : pyOffset(text, p);
  const data = await post(url, {path: lee.path, ...body, start: at(body.start), end: at(body.end), pos: at(body.pos)}), edits = data.summary.edits;
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
