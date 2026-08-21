async function renderGitPanel(snapshot = null) {
  const host = $('#gitpanel'); if (!host) return;
  host.dataset.features = 'Staged changes · Changes · Branches · Stashes · Remotes & tags · All repos · staged changes · working tree · fetch · pull · push · stash · tag · stage all · unstage all · fetch all · pull all · push all · clone';
  if (gitUI.tab === 'repos') {
    host.innerHTML = gitScope() + gitNav() + `<main class="lee-git-view">${gitReposView()}</main>`;
    wireGitPanel(host, gitUI.snapshot);
    if (!gitUI.repos) loadGitRepos();
    return;
  }
  if (!snapshot && !gitUI.snapshot) host.innerHTML = '<div class="lee-git-loading"><span></span><span></span><span></span><small>reading repository</small></div>';
  let d = snapshot || gitUI.snapshot;
  try { if (!d) d = await gitInfo(gitUrl('/git/info')); }
  catch (e) {
    // Still draw the nav: a workspace whose active folder is not a checkout can have five
    // other repositories in it, and Repos is how you reach them.
    host.innerHTML = gitScope() + gitNav() +
      `<main class="lee-git-view"><div class="lee-git-empty-state"><strong>No Git repository</strong><span>${esc(e.message || e)}</span></div></main>`;
    // `null`, not `{}`: switching to another view from here must re-read the repository
    // rather than render a snapshot-shaped object with no fields in it.
    wireGitPanel(host, null);
    return;
  }
  gitUI.snapshot = d; paintGitPill(d);
  const view = gitUI.tab === 'changes' ? gitChangesView(d) : gitUI.tab === 'review' ? gitReviewView(d) : gitUI.tab === 'branches' ? gitBranchesView(d) : gitUI.tab === 'history' ? gitHistoryView(d) : gitResourcesView(d);
  host.innerHTML = gitScope() + gitSummary(d) + gitNav() + `<main class="lee-git-view">${view}</main>`;
  wireGitPanel(host, d);
  if (gitUI.tab === 'history' && !gitUI.history.length) loadGitHistory();
  if (gitUI.tab === 'review' && !gitUI.review) loadGitReview();
  if (gitUI.tab === 'resources') loadGitResources();
}
async function loadGitReview() {
  if (!gitUI.reviewBase || !gitUI.reviewHead) return;
  const host = $('.lee-git-review-workspace');
  if (host) host.innerHTML = '<div class="lee-git-loading"><span></span><span></span><span></span><small>building review</small></div>';
  try {
    gitUI.review = await api(gitUrl('/git/review', {base: gitUI.reviewBase, head: gitUI.reviewHead, mode: gitUI.reviewMode}));
    gitUI.reviewFile = gitUI.review.files[0]?.path || ''; gitUI.reviewPatch = '';
    renderGitPanel(gitUI.snapshot);
  } catch (e) { leeFail('git', 'review', e); }
}
async function loadGitReviewFile(path, asTab = false) {
  if (!gitUI.review) return;
  gitUI.reviewFile = path;
  try {
    const d = await api(gitUrl('/git/review/file', {base: gitUI.review.base, head: gitUI.review.head, mode: gitUI.review.mode, path}));
    gitUI.reviewPatch = d.patch || '';
    if (asTab) return openGitDiffTab({...d, path, kind: 'review', baseLabel: gitUI.review.base, headLabel: gitUI.review.head, absolutePath: gitUI.snapshot.root + '/' + path, reviewKey: gitReviewKey({...gitUI.review, root: gitUI.snapshot.root}, path), allowWrite: !!d.can_apply && !path.toLowerCase().endsWith('.ipynb')});
    renderGitPanel(gitUI.snapshot);
  } catch (e) { leeFail('git', 'review file', e); }
}
function moveGitReviewFile(delta) {
  const files = gitUI.review?.files || [], at = files.findIndex(f => f.path === gitUI.reviewFile);
  if (!files.length) return;
  loadGitReviewFile(files[(Math.max(0, at) + delta + files.length) % files.length].path);
}
async function loadGitHistory() {
  const rows = $('#githistoryrows');
  try {
    const ref = $('#githistoryref')?.value || '--all';
    const result = await api(gitUrl('/git/history', {limit: 150, query: gitUI.historyQuery, ref}));
    gitUI.history = result.commits || []; renderGitPanel(gitUI.snapshot);
  } catch (e) { if (rows) rows.innerHTML = `<div class="lee-err">${esc(e.message || e)}</div>`; }
}
async function loadGitResources() {
  try {
    const r = await api(gitUrl('/git/resources'));
    const worktrees = $('#gitworktrees');
    if (worktrees) worktrees.innerHTML = (r.worktrees || []).map(w => `<article class="lee-git-resource-row" data-worktree="${esc(w.path)}"><div><strong>${esc(w.branch || 'detached')}</strong><code>${esc(w.path)}</code></div>${w.path === gitUI.snapshot.root ? '<i>current</i>' : '<button data-remove-worktree class="warn">remove</button>'}</article>`).join('') || '<span class="lee-dim">No worktrees</span>';
    const submodules = $('#gitsubmodules');
    if (submodules) submodules.innerHTML = (r.submodules || []).map(s => `<article class="lee-git-resource-row"><div><strong>${esc(s.path)}</strong><code>${esc(s.oid)}</code></div><i>${s.state === ' ' ? 'clean' : s.state === '-' ? 'not initialized' : s.state === '+' ? 'different commit' : 'conflict'}</i></article>`).join('') || '<span class="lee-dim">No submodules</span>';
    worktrees?.querySelectorAll('[data-remove-worktree]').forEach(b => b.onclick = async () => {
      const path = b.closest('[data-worktree]').dataset.worktree;
      if (await confirmDialog('remove worktree', `Remove ${path}? Uncommitted work prevents removal.`, 'remove')) renderGitPanel(await gitDo('remove_worktree', {path}));
    });
  } catch (e) { leeFail('git', 'worktrees and submodules', e); }
}
function wireGitPanel(host, d) {
  host.querySelectorAll('[data-git-tab]').forEach(b => b.onclick = () => { gitUI.tab = b.dataset.gitTab; if (gitUI.tab !== 'history') gitUI.history = []; renderGitPanel(d); });
  host.querySelector('#gitscopeclear')?.addEventListener('click', () => gitPinRepo(''));
  host.querySelectorAll('[data-repos-op]').forEach(b => b.onclick = () => gitReposDo(b.dataset.reposOp));
  host.querySelectorAll('.lee-git-repo-row').forEach(row => {
    const root = row.dataset.repo;
    row.querySelector('[data-repo-open]').onclick = () => gitPinRepo(root === gitUI.repo ? '' : root);
    row.querySelector('[data-repo-fetch]').onclick = () => gitReposDo('fetch', {paths: [root]});
    row.querySelector('[data-repo-remove]').onclick = async () => {
      if (!await confirmDialog('remove repository', `Stop listing ${gitRepoName(root)} here? The checkout is left alone.`, 'remove')) return;
      if (gitUI.repo === root) gitUI.repo = '';
      gitReposDo('remove', {path: root});
    };
  });
  const expect = host.querySelector('#gitrepoexpect');
  if (expect) expect.onchange = () => { gitUI.expect = expect.value.trim(); loadGitRepos(); };
  host.querySelector('#gitrepoadd')?.addEventListener('click', async () => {
    const path = await inputDialog('add repository', 'Path to a Git checkout', '', '/home/you/code/project');
    if (path) gitReposDo('add', {path});
  });
  host.querySelector('#gitrepoclone')?.addEventListener('click', async () => {
    const spec = await inputDialog('clone repositories', 'URLs or owner/name, one per line', '', 'AnswerDotAI/fastws');
    if (spec) gitReposDo('clone', {urls: spec.split(/[\s,]+/).filter(Boolean)});
  });
  const act = async (op, extra = {}) => renderGitPanel(await gitDo(op, extra));
  host.querySelectorAll('[data-operation]').forEach(b => b.onclick = async () => {
    if (b.dataset.operation === 'abort' && !await confirmDialog('abort Git operation', `Abort the active ${d.operation.active}?`, 'abort')) return;
    act('operation_' + b.dataset.operation);
  });
  host.querySelectorAll('[data-git-undo]').forEach(b => b.onclick = async () => {
    const point = (d.safepoints || [])[0];
    if (!await confirmDialog('undo Git operation',
        `Put this repository back where it was before ${point?.describe || 'the last operation'}?` +
        `\n\nHEAD returns to ${point?.head || 'the recorded commit'}` +
        `${point?.dirty ? ` and ${point.dirty} uncommitted file(s) are restored` : ''}.`, 'undo')) return;
    act('undo', {token: b.dataset.gitUndo});
  });
  host.querySelectorAll('[data-top]').forEach(b => b.onclick = () => b.dataset.top === 'publish' ? act('push', {publish: true}) : act(b.dataset.top));
  host.querySelector('#scstageall')?.addEventListener('click', e => { e.preventDefault(); act('stage', {paths: d.changes.filter(x => x.unstaged).map(x => x.path)}); });
  host.querySelector('#scunstageall')?.addEventListener('click', e => { e.preventDefault(); act('unstage', {paths: d.changes.filter(x => x.staged).map(x => x.path)}); });
  host.querySelector('#scstash')?.addEventListener('click', async () => { const message = await inputDialog('stash changes', 'Optional message', '', 'work in progress'); if (message !== null) act('stash', {message}); });
  host.querySelector('#sccommit')?.addEventListener('submit', e => { e.preventDefault(); const message = e.target.querySelector('textarea').value.trim(); if (message) act('commit', {message, amend: e.target.elements.amend.checked}); });
  host.querySelector('#screviewstaged')?.addEventListener('click', () => showStagedReview(d));
  host.querySelector('[data-conflict-center]')?.addEventListener('click', () => showConflictCenter());
  host.querySelectorAll('[data-selected-action]').forEach(b => b.onclick = async () => {
    const action = b.dataset.selectedAction;
    if (action === 'clear') { gitUI.selectedChanges.clear(); return renderGitPanel(d); }
    const selected = [...gitUI.selectedChanges].map(key => { const [group, ...parts] = key.split(':'); return {group, path: parts.join(':')}; });
    if (action === 'changelist') {
      const name = await inputDialog('move to changelist', 'Local changelist name', '', 'Focused change');
      if (name !== null) { for (const x of selected) { if (name) gitUI.changeLists[x.path] = name; else delete gitUI.changeLists[x.path]; } saveGitWorkflowState(); renderGitPanel(d); }
      return;
    }
    const paths = selected.filter(x => action === 'stage' ? x.group === 'unstaged' : x.group === 'staged').map(x => x.path);
    if (!paths.length) return status(`select ${action === 'stage' ? 'unstaged' : 'staged'} files`, 'err');
    gitUI.selectedChanges.clear(); act(action, {paths});
  });
  host.querySelectorAll('.lee-git-change').forEach(row => {
    const path = row.dataset.path, staged = row.dataset.group === 'staged';
    row.querySelector('[data-select-change]').onchange = e => { const key = `${row.dataset.group}:${path}`; if (e.target.checked) gitUI.selectedChanges.add(key); else gitUI.selectedChanges.delete(key); renderGitPanel(d); };
    row.querySelector('.lee-git-file').onclick = async () => { const patch = await api(gitUrl('/git/diff', {path, staged})); openGitDiffTab({kind: 'changes-' + row.dataset.group, path, absolutePath: d.root + '/' + path, base: staged ? 'HEAD' : 'index', head: staged ? 'index' : 'worktree', baseLabel: staged ? 'HEAD' : 'index', headLabel: staged ? 'staged' : 'working tree', left: patch.left || '', right: patch.right || '', patch: patch.content || patch.text || '', rawPatch: patch.text || '', notebook: !!patch.notebook, group: row.dataset.group, allowWrite: row.dataset.group === 'unstaged' && !patch.notebook}); };
    row.querySelector('[data-open]').onclick = () => leeOpenFile(d.root + '/' + path);
    row.querySelector('[data-blame]')?.addEventListener('click', () => showGitBlame(d.root, path, null));
    row.querySelector('[data-resolve]')?.addEventListener('click', () => showGitConflict(path));
    row.querySelectorAll('[data-git]').forEach(b => b.onclick = async () => { const op = b.dataset.git; if (op === 'discard' && !await confirmDialog('discard changes', `Restore ${path} from the index? This cannot be undone.`, 'discard')) return; act(op, {paths: [path]}); });
  });
  host.querySelectorAll('[data-stash]').forEach(row => { const ref = row.dataset.stash; row.querySelector('[data-apply]').onclick = () => act('stash_apply', {ref}); row.querySelector('[data-pop]').onclick = () => act('stash_pop', {ref}); row.querySelector('[data-drop]').onclick = async () => { if (await confirmDialog('drop stash', `Delete ${ref}?`, 'drop')) act('stash_drop', {ref}); }; });
  const branchFilter = host.querySelector('#gitbranchfilter'); if (branchFilter) branchFilter.oninput = () => { gitUI.branchQuery = branchFilter.value; renderGitPanel(d); requestAnimationFrame(() => { const x = $('#gitbranchfilter'); x?.focus(); x?.setSelectionRange(x.value.length, x.value.length); }); };
  const branchScope = host.querySelector('#gitbranchscope'); if (branchScope) { branchScope.value = gitUI.branchScope; branchScope.onchange = () => { gitUI.branchScope = branchScope.value; renderGitPanel(d); }; }
  host.querySelector('#scbranch')?.addEventListener('click', async () => { const branch = await inputDialog('new branch', 'Branch name', '', 'feature/name'); if (branch) act('create', {branch}); });
  host.querySelectorAll('[data-branch]').forEach(row => { const branch = row.dataset.branch; row.querySelector('[data-switch]').onclick = () => act('checkout', {branch}); row.querySelector('[data-compare]')?.addEventListener('click', () => { gitUI.reviewBase = d.branch; gitUI.reviewHead = branch; gitUI.reviewMode = 'review'; gitUI.review = null; gitUI.tab = 'review'; renderGitPanel(d); }); const more = row.querySelector('[data-more]'); more?.addEventListener('click', () => gitBranchMenu(more, branch, d, act)); });
  host.querySelector('#sctag')?.addEventListener('click', async () => { const name = await inputDialog('create tag', 'Tag name', '', 'v1.0.0'); if (!name) return; const message = await inputDialog('annotated tag', 'Optional annotation', '', ''); if (message !== null) act('tag', {name, message}); });
  host.querySelectorAll('[data-delete-tag]').forEach(b => b.onclick = async () => { const name = b.closest('[data-tag]').dataset.tag; if (await confirmDialog('delete tag', `Delete local tag ${name}?`, 'delete')) act('delete_tag', {name}); });
  host.querySelector('#gitreviewmode') && (host.querySelector('#gitreviewmode').value = gitUI.reviewMode);
  const swapReviewDirection = () => { const base = $('#gitreviewbase')?.value.trim() || gitUI.reviewBase; gitUI.reviewBase = $('#gitreviewhead')?.value.trim() || gitUI.reviewHead; gitUI.reviewHead = base; gitUI.review = null; loadGitReview(); };
  host.querySelector('#gitreviewcontrolswap')?.addEventListener('click', swapReviewDirection);
  host.querySelector('#gitreviewswap')?.addEventListener('click', swapReviewDirection);
  host.querySelector('#gitreviewsnapshot')?.addEventListener('click', () => { gitUI.reviewMode = 'snapshot'; gitUI.review = null; loadGitReview(); });
  host.querySelector('#gitreviewload')?.addEventListener('click', () => { gitUI.reviewBase = $('#gitreviewbase').value.trim(); gitUI.reviewHead = $('#gitreviewhead').value.trim(); gitUI.reviewMode = $('#gitreviewmode').value; gitUI.review = null; loadGitReview(); });
  host.querySelectorAll('[data-review-path]').forEach(b => b.onclick = () => loadGitReviewFile(b.dataset.reviewPath, true));
  host.querySelector('#gitreviewprev')?.addEventListener('click', () => moveGitReviewFile(-1));
  host.querySelector('#gitreviewnext')?.addEventListener('click', () => moveGitReviewFile(1));
  host.querySelector('#gitreviewmark')?.addEventListener('click', () => { const key = gitReviewKey({...gitUI.review, root: d.root}, gitUI.reviewFile); gitUI.reviewed[key] = !gitUI.reviewed[key]; saveGitWorkflowState(); renderGitPanel(d); });
  host.querySelector('#gitreviewnote')?.addEventListener('click', async () => { const key = gitReviewKey({...gitUI.review, root: d.root}, gitUI.reviewFile), note = await inputDialog('review note', `Note for ${gitUI.reviewFile}`, gitUI.reviewNotes[key] || '', 'Question, risk, or follow-up'); if (note !== null) { if (note.trim()) gitUI.reviewNotes[key] = note.trim(); else delete gitUI.reviewNotes[key]; saveGitWorkflowState(); renderGitPanel(d); } });
  host.querySelector('#gitreviewcopynotes')?.addEventListener('click', async () => { const prefix = `${d.root}\0${gitUI.review.base}\0${gitUI.review.head}\0${gitUI.review.mode}\0`, rows = Object.entries(gitUI.reviewNotes).filter(([key]) => key.startsWith(prefix)).map(([key, note]) => `- **${key.slice(prefix.length)}** — ${note}`); if (!rows.length) return status('this review has no notes', 'err'); const text = `# Review: ${gitUI.review.head} → ${gitUI.review.base}\n\n${rows.join('\n')}\n`; try { await navigator.clipboard.writeText(text); status(`copied ${rows.length} review note${rows.length === 1 ? '' : 's'}`, 'ok'); } catch (_) { status('clipboard access failed', 'err'); } });
  host.querySelector('#gitreviewapply')?.addEventListener('click', () => showReviewHunkApply(d));
  host.querySelector('#githistorygo')?.addEventListener('click', () => { gitUI.historyQuery = $('#githistoryfilter').value.trim(); gitUI.history = []; gitUI.selectedCommit = null; loadGitHistory(); });
  host.querySelector('#githistoryfilter')?.addEventListener('keydown', e => { if (e.key === 'Enter') { gitUI.historyQuery = e.target.value.trim(); gitUI.history = []; gitUI.selectedCommit = null; loadGitHistory(); } });
  host.querySelector('#githistoryref')?.addEventListener('change', () => { gitUI.history = []; gitUI.selectedCommit = null; loadGitHistory(); });
  host.querySelector('#gitreflog')?.addEventListener('click', showGitReflog);
  host.querySelectorAll('[data-history-commit]').forEach(b => b.onclick = () => loadGitCommitInspector(b.dataset.historyCommit));
  host.querySelectorAll('[data-commit]').forEach(b => b.onclick = () => showGitCommit(b.dataset.commit));
  host.querySelectorAll('[data-commit-file]').forEach(b => b.onclick = () => openGitCommitFile(gitUI.selectedCommit.oid, b.dataset.commitFile));
  host.querySelector('[data-close-commit]')?.addEventListener('click', () => { gitUI.selectedCommit = null; renderGitPanel(d); });
  host.querySelector('.lee-git-commit-inspector [data-cherry]')?.addEventListener('click', () => act('cherry_pick', {ref: gitUI.selectedCommit.oid}));
  host.querySelector('.lee-git-commit-inspector [data-revert]')?.addEventListener('click', async () => { if (await confirmDialog('revert commit', `Create a commit that reverses ${gitUI.selectedCommit.short}?`, 'revert')) act('revert', {ref: gitUI.selectedCommit.oid}); });
  host.querySelector('.lee-git-commit-inspector [data-reset]')?.addEventListener('click', async () => { const c = gitUI.selectedCommit, mode = await inputDialog('reset branch', 'Mode: soft keeps index; mixed keeps files; hard discards changes', 'mixed', 'soft, mixed, or hard'); if (!['soft','mixed','hard'].includes(mode)) return status('reset mode must be soft, mixed, or hard', 'err'); if (mode === 'hard' && !await confirmDialog('hard reset', `Discard tracked changes and reset to ${c.short}? This cannot be undone.`, 'reset')) return; act('reset', {ref: c.oid, mode}); });
  const rememberCompare = () => { gitUI.compareFrom = $('#gitcompareleft')?.value.trim() || ''; gitUI.compareTo = $('#gitcompareright')?.value.trim() || ''; };
  host.querySelector('#gitcompareleft')?.addEventListener('change', rememberCompare);
  host.querySelector('#gitcompareright')?.addEventListener('change', rememberCompare);
  host.querySelector('#gitcompareswap')?.addEventListener('click', () => { const left = $('#gitcompareleft'), right = $('#gitcompareright'), value = left.value; left.value = right.value; right.value = value; rememberCompare(); });
  host.querySelector('#gitcomparego')?.addEventListener('click', () => { rememberCompare(); showGitCompare(gitUI.compareFrom, gitUI.compareTo); });
  host.querySelector('[data-hosted-pr]')?.addEventListener('click', e => window.open(e.currentTarget.dataset.url, '_blank', 'noopener,noreferrer'));
  host.querySelector('#gitaddremote')?.addEventListener('click', async () => { const name = await inputDialog('add remote', 'Remote name', '', 'origin'); if (!name) return; const url = await inputDialog('add remote', 'Fetch URL', '', 'https://github.com/owner/repository.git'); if (url) act('add_remote', {name, url}); });
  host.querySelectorAll('[data-remote]').forEach(row => { const remote = row.dataset.remote; row.querySelector('[data-open-remote]')?.addEventListener('click', b => window.open(b.currentTarget.dataset.url, '_blank', 'noopener,noreferrer')); row.querySelector('[data-fetch-remote]').onclick = () => act('fetch', {remote}); row.querySelector('[data-edit-remote]').onclick = async () => { const url = await inputDialog('edit remote', `${remote} fetch URL`, row.querySelector('code').textContent, 'https://github.com/owner/repository.git'); if (url) act('set_remote', {name: remote, url}); }; row.querySelector('[data-remove-remote]').onclick = async () => { if (await confirmDialog('remove remote', `Remove ${remote}? Local commits and branches remain.`, 'remove')) act('remove_remote', {name: remote}); }; });
  host.querySelector('#gitaddworktree')?.addEventListener('click', async () => { const path = await inputDialog('add worktree', 'Directory path', '', '../project-feature'); if (!path) return; const branch = await inputDialog('add worktree', 'Existing branch, or a new branch name', '', 'feature/name'); if (branch) act('add_worktree', {path, branch, create: !(d.branches || []).some(b => !b.remote && b.name === branch)}); });
}
async function showStagedReview(d) {
  const files = (d.changes || []).filter(c => c.staged);
  if (!files.length) return status('stage changes before reviewing them', 'err');
  const m = modal(`<div class="lee-mhead">Review staged changes<span class="sub">${files.length} file${files.length === 1 ? '' : 's'} will be committed</span><span class="lee-spacer"></span><button class="lee-btn" data-prev>previous</button><button class="lee-btn" data-next>next</button></div><div class="lee-git-full-review"><aside></aside><main class="lee-git-patch"></main></div><div class="lee-mfoot"><span class="lee-dim">Only the index is shown. Unstaged edits are not part of the commit.</span></div>`);
  m.classList.add('lee-git-review-expanded');
  let at = 0;
  const paint = async next => {
    at = (next + files.length) % files.length;
    const active = files[at];
    m.querySelector('aside').innerHTML = files.map((f, i) => `<button data-index="${i}" class="${i === at ? 'active' : ''}"><b>${esc(f.index)}</b><span>${esc(f.path)}</span></button>`).join('');
    m.querySelectorAll('[data-index]').forEach(b => b.onclick = () => paint(+b.dataset.index));
    const detail = await api(gitUrl('/git/diff', {path: active.path, staged: true}));
    m.querySelector('main').innerHTML = gitPatchHtml(detail.content || detail.text || '');
  };
  m.querySelector('[data-prev]').onclick = () => paint(at - 1);
  m.querySelector('[data-next]').onclick = () => paint(at + 1);
  paint(0);
}
function showReviewHunkApply(d) {
  if (!gitUI.reviewPatch || !gitUI.review?.can_apply) return status('partial apply requires a clean current branch that is the review base', 'err');
  const parts = gitPatchParts(gitUI.reviewPatch);
  if (!parts.hunks.length) return status('this file has no text hunks to apply', 'err');
  const m = modal(`<div class="lee-mhead">Apply parts of ${esc(gitUI.reviewFile)}<span class="sub">from ${esc(gitUI.review.head)} into the current working tree</span></div><div class="lee-git-patch">${parts.hunks.map((h, i) => `<label class="lee-git-hunk"><input type="checkbox" data-hunk="${i}" checked><span>hunk ${i + 1}</span>${gitPatchHtml(h)}</label>`).join('')}</div><div class="lee-mfoot"><button class="lee-btn go" data-apply>apply selected hunks</button><span class="lee-dim">Changes remain uncommitted and can be reviewed before staging.</span></div>`);
  m.querySelector('[data-apply]').onclick = async () => {
    const selected = [...m.querySelectorAll('[data-hunk]:checked')].map(x => parts.hunks[+x.dataset.hunk]);
    if (!selected.length) return status('select at least one hunk', 'err');
    if (!await confirmDialog('apply branch hunks', `Apply ${selected.length} selected hunk${selected.length === 1 ? '' : 's'} from ${gitUI.review.head} to the working tree?`, 'apply')) return;
    try { const next = await gitDo('apply_patch', {patch: parts.header + selected.join(''), staged: false}); m.remove(); gitUI.review = null; gitUI.tab = 'changes'; renderGitPanel(next); }
    catch (e) { leeFail('git', 'apply hunks', e); }
  };
}
async function showMergePreview(branch, d, act) {
  try {
    const p = await api(gitUrl('/git/merge-preview', {incoming: branch}));
    const r = p.review, relation = {'fast-forward': 'Fast-forward available', 'already-merged': 'Already contained in current', 'identical': 'Branches are identical', 'diverged': 'Branches have diverged'}[p.relation] || p.relation;
    const conflict = p.conflict_likely ? `<div class="lee-git-merge-warning"><strong>Conflicts expected</strong><span>${p.conflicts.length ? p.conflicts.map(esc).join(' · ') : 'Git reports overlapping changes.'}</span></div>` : '<div class="lee-git-merge-ok"><strong>No conflicts found in merge rehearsal</strong><span>The working tree can still change before merge.</span></div>';
    // Untracked files are not dirt: git merges beside them and refuses only when the merge
    // would overwrite one, at which point it says so itself. Only tracked work blocks.
    const dirty = p.clean ? '' : `<div class="lee-git-merge-warning"><strong>Uncommitted changes to ${p.dirty.length} tracked file${p.dirty.length === 1 ? '' : 's'}</strong><span>${p.dirty.map(esc).join(' · ')}</span></div>`;
    const blocked = !p.clean ? `commit or stash ${p.dirty.length} changed file${p.dirty.length === 1 ? '' : 's'} first`
                  : p.relation === 'already-merged' ? `${p.current} already contains ${branch}`
                  : p.relation === 'identical' ? 'the two branches are identical' : '';
    const m = modal(`<div class="lee-mhead">Merge ${esc(branch)}<span class="sub">into ${esc(p.current)}</span></div><div class="lee-git-merge-preview"><header><strong>${esc(relation)}</strong><span>${r.head_only} commits · ${r.summary.files} files · +${r.summary.additions} −${r.summary.deletions}</span></header>${dirty}${conflict}<label>Strategy<select data-strategy><option value="merge">merge commit when needed</option><option value="squash">squash into working tree</option><option value="ff-only" ${p.relation === 'fast-forward' ? '' : 'disabled'}>fast-forward only</option></select></label><button class="lee-btn" data-review>review incoming files</button></div><div class="lee-mfoot"><button class="lee-btn go" data-merge>merge ${esc(branch)}</button><span class="lee-dim">${blocked ? esc(blocked) : 'Merge starts only after this preview.'}</span></div>`);
    m.querySelector('[data-review]').onclick = () => { m.remove(); gitUI.reviewBase = d.branch; gitUI.reviewHead = branch; gitUI.reviewMode = 'review'; gitUI.review = null; gitUI.tab = 'review'; renderGitPanel(d); };
    // Never a disabled button: one that cannot be pressed cannot say why, and "I clicked
    // merge and nothing happened" is the report that came back from exactly that.
    m.querySelector('[data-merge]').onclick = async () => {
      if (blocked) return status(`cannot merge — ${blocked}`, 'err');
      const strategy = m.querySelector('[data-strategy]').value;
      if (!await confirmDialog('merge branch', `Merge ${branch} into ${p.current} using ${strategy}?`, 'merge')) return;
      m.remove(); act('merge', {branch, strategy});
    };
  } catch (e) { leeFail('git', 'merge preview', e); }
}
async function showRebasePreview(branch, d, act) {
  try {
    const p = await api(gitUrl('/git/rebase-preview', {onto: branch})), r = p.review;
    const warning = p.conflict_likely ? `<div class="lee-git-merge-warning"><strong>Conflicts may occur while replaying commits</strong><span>${p.conflicts.length ? p.conflicts.map(esc).join(' · ') : 'Git reports overlapping changes.'}</span></div>` : '<div class="lee-git-merge-ok"><strong>No conflicts found in the tree rehearsal</strong><span>Rebase replays commits individually, so this remains a forecast.</span></div>';
    const rbDirty = p.clean ? '' : `<div class="lee-git-merge-warning"><strong>Uncommitted changes to ${p.dirty.length} tracked file${p.dirty.length === 1 ? '' : 's'}</strong><span>${p.dirty.map(esc).join(' · ')}</span></div>`;
    const rbBlocked = !p.clean ? `commit or stash ${p.dirty.length} changed file${p.dirty.length === 1 ? '' : 's'} first`
                    : p.already_based ? `${p.current} already contains ${branch}`
                    : !p.commits.length ? 'there is nothing to replay' : '';
    const m = modal(`<div class="lee-mhead">Rebase ${esc(p.current)}<span class="sub">onto ${esc(branch)}</span></div><div class="lee-git-merge-preview"><header><strong>${p.already_based ? 'Branch already contains the target history' : `${p.commits.length} commit${p.commits.length === 1 ? '' : 's'} will be replayed`}</strong><span>${r.summary.files} proposed files · +${r.summary.additions} −${r.summary.deletions}</span></header>${rbDirty}${warning}<div class="lee-git-rebase-commits">${p.commits.slice(0, 12).map(c => `<span><code>${esc(c.short)}</code>${esc(c.subject)}</span>`).join('')}</div><button class="lee-btn" data-review>review branch changes</button></div><div class="lee-mfoot"><button class="lee-btn go" data-rebase>start rebase</button><span class="lee-dim">The operation banner will offer continue, skip, and abort if Git pauses.</span></div>`);
    m.querySelector('[data-review]').onclick = () => { m.remove(); gitUI.reviewBase = branch; gitUI.reviewHead = d.branch; gitUI.reviewMode = 'review'; gitUI.review = null; gitUI.tab = 'review'; renderGitPanel(d); };
    m.querySelector('[data-rebase]').onclick = async () => {
      if (rbBlocked) return status(`cannot rebase — ${rbBlocked}`, 'err');
      if (!await confirmDialog('rebase branch', `Replay ${p.commits.length} commit${p.commits.length === 1 ? '' : 's'} from ${p.current} onto ${branch}?`, 'rebase')) return;
      m.remove(); act('rebase', {branch});
    };
  } catch (e) { leeFail('git', 'rebase preview', e); }
}
