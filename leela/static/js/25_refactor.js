/* -------------------------------------------------------------- refactor */
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
      m.querySelector('.lee-modalbox').innerHTML = `<div class="lee-mhead">Replace preview<span class="sub">${data.summary.edits} replacements in ${data.summary.files} files</span></div>` +
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

/* Which lines differ, as one span from the first difference to the last.

   Not a real diff: the point is to put the change on screen and under a selection, and a span
   does that for every edit an undo can produce. A minimal diff would draw prettier ranges and
   would not answer the question -- "where did it change" -- any better. */
function changedSpan(now, other) {
  const A = String(now || '').split('\n'), B = String(other || '').split('\n');
  let s = 0;
  while (s < A.length && s < B.length && A[s] === B[s]) s++;
  let a = A.length - 1, b = B.length - 1;
  while (a >= s && b >= s && A[a] === B[b]) { a--; b--; }
  return {from: s + 1, to: Math.max(s + 1, a + 1)};
}

/* An undo that changes a file you cannot see has happened to you rather than been done by you.
   Select what moved and centre it, so the operation is legible instead of merely reported. */
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

/* Extraction and inlining run against the file *on disk*: the endpoints read it themselves and
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

/* Whole lines within one buffer, where `cell_move_up`/`cell_move_down` move whole cells.
   Written against the CodeMirror state directly rather than through a new `LeeCM` export: the
   vendored bundle is committed and rebuilding it needs node, so the page must not grow a
   dependency on a wrapper that is not in the shipped build. */
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
