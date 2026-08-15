/* --------------------------------------------------------- git conflicts */
async function showConflictCenter() {
  try {
    const d = await api(gitUrl('/git/conflicts')), files = d.files || [], s = d.summary || {};
    if (!files.length) return status('no unresolved Git conflicts', 'ok');
    const rows = files.map(f => `<button class="lee-mrow" data-conflict-path="${esc(f.path)}"><strong>${esc(f.path)}</strong>` +
      `<span class="sub">${f.kind} · ${f.blocks || 0} conflict${f.blocks === 1 ? '' : 's'} · ${f.safe ? `${f.safe} safe` : f.reason}</span></button>`).join('');
    const m = modal(`<div class="lee-mhead">Resolve conflicts<span class="sub">${esc(d.operation.active || 'Git operation')} paused · ${s.files} files · ${s.blocks} blocks</span></div>` +
      `<div class="lee-git-merge-preview"><header><strong>${s.safe || 0} safe resolution${s.safe === 1 ? '' : 's'} available</strong><span>Automatic changes are limited to identical sides.</span></header></div>` +
      `<div class="lee-modallist">${rows}</div><div class="lee-mfoot"><button class="lee-btn go" data-safe${s.safe ? '' : ' disabled'}>Resolve safe changes</button><button class="lee-btn" data-close>Close</button></div>`);
    $('[data-close]', m).onclick = () => m.remove();
    $$('[data-conflict-path]', m).forEach(b => b.onclick = () => { m.remove(); showGitConflict(b.dataset.conflictPath); });
    $('[data-safe]', m).onclick = async () => {
      if (!await confirmDialog('Resolve safe conflicts', `Stage ${s.safe} deterministic resolution${s.safe === 1 ? '' : 's'}?`, 'resolve')) return;
      const next = await gitDo('resolve_safe_conflicts', {paths: files.filter(f => f.safe).map(f => f.path)});
      m.remove(); afterConflictResolved(next, `${s.safe} resolved`);
    };
  } catch (e) { leeFail('git', 'resolve conflicts', e); }
}
window.showConflictCenter = showConflictCenter;

// One file resolved is not the task: step to the next, and finish the operation when none remain.
async function afterConflictResolved(d, done = '') {
  renderGitPanel(d);
  const left = (d.changes || []).filter(x => x.conflicted).map(x => x.path);
  if (left.length) {
    status(`${done}${done ? ' · ' : ''}${left.length} file${left.length === 1 ? '' : 's'} still conflicted`, 'ok');
    return showGitConflict(left[0]);
  }
  const op = (d.operation || {}).active;
  if (!op) return status(done || 'every conflict is resolved', 'ok');
  if (!await confirmDialog(`continue the ${op}`, 'Every conflict is resolved and staged.', 'continue')) return;
  renderGitPanel(await gitDo('operation_continue'));
}
window.afterConflictResolved = afterConflictResolved;
