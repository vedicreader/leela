// Blame, reachable from wherever you are rather than only from a changed-file row. A text
// file blames the lines you have selected -- "who wrote these six" is the question, and the
// whole-file answer is one button away. A notebook blames its cells, because blaming its
// JSON tells you about `"source": [` and nothing about your code.
function blameRelative(root, path) {
  const p = String(path || '');
  if (!root) return p;
  return p.startsWith(root + '/') ? p.slice(root.length + 1) : p;
}
function blameSelectionRange() {
  const view = curEditor(); if (!view || lee.kind === 'notebook') return null;
  const sel = view.state.selection.main;
  if (sel.empty) return null;
  const doc = view.state.doc;
  return {start: doc.lineAt(sel.from).number, end: doc.lineAt(sel.to).number};
}
async function leeBlame() {
  if (!lee.path) return status('open a file to blame it', 'err');
  let root = gitUI.snapshot?.root;
  if (!root) { try { root = (await gitInfo(gitUrl('/git/info'))).root; } catch (e) { return leeFail('git', 'blame', e); } }
  showGitBlame(root, blameRelative(root, lee.path), blameSelectionRange());
}
window.leeBlame = leeBlame;
function blameHue(oid, commits) {
  // Colour by commit so a cell made of three commits reads as three bands. Position in the
  // recency-sorted legend, not a hash: the newest change is the one being looked for.
  const i = commits.findIndex(c => c.oid === oid);
  return i < 0 ? 'var(--lee-fg4)' : `hsl(${(i * 47) % 360} 55% 55%)`;
}
function blameLineRows(lines, commits, showN) {
  return lines.map(l => `<button class="lee-blame-line${l.uncommitted ? ' uncommitted' : ''}" data-commit="${esc(l.oid)}" ` +
    `title="${esc(l.author)} · ${esc(l.summary || '')}">` +
    `<i style="background:${blameHue(l.oid, commits)}"></i>` +
    `<code>${l.uncommitted ? 'working' : esc(l.oid.slice(0, 8))}</code>` +
    `<span class="lee-blame-who">${esc(l.author || '')}</span>` +
    `<small>${l.timestamp ? gitRelative(l.timestamp) : ''}</small>` +
    `<em>${showN ? l.n : l.line}</em><pre>${esc(l.text)}</pre></button>`).join('');
}
function blameCells(d) {
  const commits = d.commits || [];
  const legend = commits.length ? `<div class="lee-blame-legend">${commits.map(c =>
    `<i style="border-color:${blameHue(c.oid, commits)}">${c.uncommitted ? 'working tree' : esc(c.oid.slice(0, 8))} · ${esc(c.author || '')}</i>`).join('')}</div>` : '';
  const cells = d.cells.map(c => {
    const t = c.touched || {};
    const made = c.commits.length;
    return `<details class="lee-blame-cell" data-cell="${c.index}">` +
      `<summary><b>${c.index}</b><span class="lee-blame-kind">${esc(c.kind)}</span>` +
      `<strong>${esc(t.author || 'never committed')}</strong>` +
      `<small>${t.timestamp ? gitRelative(t.timestamp) : ''}${made > 1 ? ` · ${made} commits` : ''}` +
      `${c.mapped ? '' : ' · lines not located'}</small>` +
      `<span class="lee-blame-bar">${c.commits.map(x =>
        `<i style="background:${blameHue(x.oid, commits)};flex:${x.lines}"></i>`).join('')}</span></summary>` +
      `<div class="lee-git-blame">${blameLineRows(c.lines, commits, true)}</div></details>`;
  }).join('');
  return legend + `<div class="lee-blame-cells">${cells}</div>`;
}
async function showGitBlame(root, path, range = null) {
  try {
    const params = range ? {path, start: range.start, end: range.end} : {path};
    const d = await api(gitUrl('/git/blame', params));
    const scope = d.notebook ? `${d.cells.length} cells`
                             : range ? `lines ${range.start}–${range.end}` : 'whole file';
    const commits = d.commits || [];
    const body = d.notebook ? blameCells(d)
      : `<div class="lee-git-blame">${blameLineRows((d.lines || []).map(x => ({...x, uncommitted: /^0+$/.test(x.oid)})), commits, false)}</div>`;
    const m = modal(`<div class="lee-mhead">${esc(path)}<span class="sub">who wrote this · ${esc(scope)}</span></div>` +
      `${d.error ? `<div class="lee-dialogcopy">${esc(d.error)}</div>` : ''}${body}` +
      `${range ? '<div class="lee-mfoot"><button class="lee-btn" id="blameall">blame the whole file</button></div>' : ''}`);
    m.querySelectorAll('[data-commit]').forEach(b => b.onclick = () => showGitCommit(b.dataset.commit));
    m.querySelector('#blameall')?.addEventListener('click', () => { m.remove(); showGitBlame(root, path, null); });
  } catch (e) { leeFail('git', 'blame', e); }
}
function leeGit() { leeLeft('git'); }
function leeGitRefresh() { gitUI.snapshot = null; gitUI.history = []; renderGitPanel(); refreshProjectPills(); }
window.leeGit = leeGit; window.leeGitRefresh = leeGitRefresh;

async function leeNbdevPrepare() {
  status('nbdev prepare…', 'busy');
  try {
    const r = await post('/project/nbdev_prepare', {});
    status(`nbdev prepare · ${PathName(r.root)}${r.nbs_path ? ' · ' + r.nbs_path : ''}`, 'ok');
    refreshFileTree(undefined, false).catch(() => {});
  } catch (e) { status(String(e.message || e), 'err'); }
}
function PathName(path) { return String(path || '').split('/').pop() || path || ''; }
window.leeNbdevPrepare = leeNbdevPrepare;

