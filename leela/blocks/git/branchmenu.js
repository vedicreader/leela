/* The branch row's `•••`, as a menu anchored to the button rather than a modal. Named for this
   panel because the branch pill in `branchbar.js` has its own, differently shaped menu, and the
   modules are concatenated into one scope, where two `function branchActions` meant the later file
   silently won. */
function gitBranchMenu(anchor, branch, d, act) {
  const current = branch === d.branch;
  const review = mode => {
    Object.assign(gitUI, {reviewBase: d.branch, reviewHead: branch, reviewMode: mode, review: null, tab: 'review'});
    renderGitPanel(d);
  };
  const rows = [
    {label: `Checkout ${branch}`, disabled: current, run: () => act('checkout', {branch})},
    {label: 'New branch from…', detail: branch, run: async () => {
      const name = await inputDialog('new branch', `Branch name, starting at ${branch}`, '', 'feature/name');
      if (name) act('create', {branch: name, start: branch});
    }},
    {separator: true},
    {label: `Review ${branch} into ${d.branch}`, detail: 'proposed changes', disabled: current,
     run: () => review('review')},
    {label: `Diff ${d.branch} … ${branch}`, detail: 'complete snapshots', disabled: current,
     run: () => review('snapshot')},
    {separator: true},
    {label: `Rebase ${d.branch} onto ${branch}`, disabled: current, run: () => showRebasePreview(branch, d, act)},
    {label: `Merge ${branch} into ${d.branch}`, disabled: current, run: () => showMergePreview(branch, d, act)},
    {separator: true},
    {label: 'Rename…', run: async () => {
      const name = await inputDialog('rename branch', 'New name', branch, 'feature/name');
      if (name) act('rename_branch', {branch, name});
    }},
    {label: 'Set upstream…', run: async () => {
      const upstream = await inputDialog('set upstream', 'Remote tracking branch', '', 'origin/' + branch);
      if (upstream) act('set_upstream', {branch, upstream});
    }},
  ];
  if (!current) rows.push({separator: true}, {label: `Delete ${branch}`, warn: true, run: async () => {
    if (await confirmDialog('delete branch', `Delete local branch ${branch}?`, 'delete')) act('delete', {branch});
  }});
  openChromeMenu(anchor, rows);
}
async function loadGitCommitInspector(ref, root = gitRepo()) {
  try { gitUI.selectedCommit = {...await api(gitUrl('/git/commit/review', {ref, repo: root})), root}; renderGitPanel(gitUI.snapshot); }
  catch (e) { leeFail('git', 'commit', e); }
}
async function openGitCommitFile(ref, path, c = gitUI.selectedCommit) {
  const root = c?.root || gitRepo();
  try {
    const d = noteHl(await api(gitUrl('/git/commit/file', {ref, path, repo: root})));
    return openGitDiffTab({...d, path, kind: 'commit', baseLabel: c?.parents?.[0]?.slice(0, 8) || 'empty tree', headLabel: c?.short || ref.slice(0, 8), absolutePath: root + '/' + path});
  } catch (e) { leeFail('git', 'commit file', e); }
}
async function showGitCommit(ref, root = gitRepo()) {
  try {
    const c = {...await api(gitUrl('/git/commit/review', {ref, repo: root})), root};
    const files = c.files.map(f => `<button class="lee-git-commit-file" data-path="${esc(f.path)}"><b>${esc(f.status)}</b><span>${esc(f.path)}</span><small>${f.binary ? 'binary' : `+${f.additions} −${f.deletions}`}</small></button>`).join('');
    const m = modal(`<div class="lee-mhead">${esc(c.short)}<span class="sub">${esc(c.author)} · ${new Date(c.timestamp * 1000).toLocaleString()}</span></div><article class="lee-git-commit-sheet"><h3>${esc(c.message)}</h3><section><b>${c.summary.files} files</b><span>+${c.summary.additions}</span><span>−${c.summary.deletions}</span></section><div>${files}</div></article>`);
    m.querySelectorAll('[data-path]').forEach(b => b.onclick = () => { m.remove(); openGitCommitFile(c.oid, b.dataset.path, c); });
  } catch (e) { leeFail('git', 'commit', e); }
}
async function showGitCompare(left, right) {
  if (!left || !right) return status('choose a base and target ref', 'err');
  gitUI.reviewBase = left; gitUI.reviewHead = right; gitUI.reviewMode = 'snapshot';
  gitUI.review = null; gitUI.reviewFile = ''; gitUI.reviewPatch = ''; gitUI.tab = 'review';
  await renderGitPanel(gitUI.snapshot);
}
async function showGitReflog() {
  try {
    const root = gitRepo(), d = await api(gitUrl('/git/reflog', {limit: 150, repo: root}));
    const m = modal(`<div class="lee-mhead">reflog<span class="sub">local recovery history · newest first</span></div><div class="lee-git-history">${(d.entries || []).map(x => `<button class="lee-git-commit-row" data-commit="${x.oid}"><span class="lee-git-graph">◆</span><span><strong>${esc(x.subject)}</strong><small>${esc(x.selector)} · ${esc(x.author)} · ${gitRelative(x.timestamp)} · ${esc(x.short)}</small></span></button>`).join('') || '<div class="lee-git-empty-state"><strong>No reflog entries</strong><span>This repository has no local movement history.</span></div>'}</div>`);
    m.querySelectorAll('[data-commit]').forEach(b => b.onclick = () => showGitCommit(b.dataset.commit, root));
  } catch (e) { leeFail('git', 'reflog', e); }
}
