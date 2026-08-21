/* ------------------------------------------------------------------- move */
/* Lift whole functions and classes into another file. Unlike extract and inline this
   changes several files at once, so it previews before it writes and every file it would
   touch is its own row. */

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

/* The diff is built when its row is opened, not when the list is drawn. A move across a dozen
   call sites would otherwise mount a dozen merge views nobody asked to see. */
function moveDiffs(m, files) {
  const built = [];
  $$('[data-move-file]', m).forEach(row => row.addEventListener('toggle', () => {
    const i = +row.dataset.moveFile;
    if (!row.open || built[i]) return;
    const f = files[i];
    built[i] = LeeCM.createMerge($(`[data-move-diff="${i}"]`, row), {
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
