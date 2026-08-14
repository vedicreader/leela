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

async function workspaceHistoryRedo() {
  try {
    const result = await post('/history/redo', {}), paths = (result.operation.resources || []).map(x => x.path);
    if (paths.includes(lee.path)) await takeDiskVersion(lee.path);
    refreshFileTree(undefined, false); status('workspace operation redone', 'ok');
  } catch (e) { status(e.message || String(e), 'err'); }
}

ACTIONS.replace_workspace = replaceWorkspace;
ACTIONS.workspace_undo = () => operationHistory();
ACTIONS.workspace_redo = workspaceHistoryRedo;
