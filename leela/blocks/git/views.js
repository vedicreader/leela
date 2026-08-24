function gitNav() {
  return `<nav class="lee-git-nav" aria-label="Source control views">${[['changes','Changes'],['review','Review'],['branches','Branches'],['history','History'],['resources','Repository'],['repos','All repos']].map(([id, label]) =>
    `<button data-git-tab="${id}" class="${gitUI.tab === id ? 'active' : ''}">${label}</button>`).join('')}</nav>`;
}
function gitSummary(d) {
  return `<header class="lee-sc-branch"><div><strong>${esc(d.branch)}</strong><span>${esc(d.upstream || 'unpublished branch')}</span></div>` +
    `<span class="lee-spacer"></span>${d.behind ? `<b>↓${d.behind}</b>` : ''}${d.ahead ? `<b>↑${d.ahead}</b>` : ''}` +
    `<small title="Remote-derived branch data may be stale">${esc(gitFreshness(d.fetched_at))}</small></header>`;
}
function gitChangesView(d) {
  const staged = (d.changes || []).filter(c => c.staged), unstaged = (d.changes || []).filter(c => c.unstaged);
  const allStats = [...staged.map(c => c.staged_stat), ...unstaged.map(c => c.unstaged_stat)].filter(Boolean);
  const additions = allStats.reduce((n, x) => n + (x.additions || 0), 0), deletions = allStats.reduce((n, x) => n + (x.deletions || 0), 0);
  const rows = (items, group) => items.length ? items.map(c => gitChangeRow(c, group)).join('') :
    `<div class="lee-git-empty-state"><strong>${group === 'staged' ? 'Nothing staged' : 'Working tree clean'}</strong><span>${group === 'staged' ? 'Stage files or individual hunks to prepare a commit.' : 'There are no local file changes.'}</span></div>`;
  return gitOperationBanner(d) + gitFilterBanner(d) + gitUndoBanner(d) + `<div class="lee-git-change-summary"><strong>${d.changes.length} changed file${d.changes.length === 1 ? '' : 's'}</strong><span>+${additions}</span><span>−${deletions}</span><small>${staged.length} staged · ${unstaged.length} unstaged</small></div>` + `<div class="lee-sc-actions"><button data-top="fetch">fetch</button><button data-top="pull">pull</button><button data-top="push">push</button>` +
    `${!d.upstream ? '<button data-top="publish">publish branch</button>' : ''}<button id="scstash">stash</button></div>` +
    `<div class="lee-git-selection" ${gitUI.selectedChanges.size ? '' : 'hidden'}><strong>${gitUI.selectedChanges.size} selected</strong><button data-selected-action="stage">stage</button><button data-selected-action="unstage">unstage</button><button data-selected-action="changelist">move to changelist</button><button data-selected-action="clear">clear</button></div>` +
    `<form id="sccommit" class="lee-sc-commit"><label>Commit message<textarea rows="3" placeholder="Describe this change" aria-label="Commit message">${esc(gitUI.commitDraft)}</textarea></label>` +
    `<label class="lee-git-check"><input type="checkbox" name="amend"> amend previous commit</label><button type="button" id="screviewstaged" ${staged.length ? '' : 'disabled'}>review staged</button><button ${staged.length ? '' : 'disabled'}>commit ${staged.length || ''}</button></form>` +
    `<details class="lee-sc-group" open><summary><span>Staged changes</span><b>${staged.length}</b>${staged.length ? '<button type="button" id="scunstageall">unstage all</button>' : ''}</summary><div>${rows(staged, 'staged')}</div></details>` +
    `<details class="lee-sc-group" open><summary><span>Changes</span><b>${unstaged.length}</b>${unstaged.length ? '<button type="button" id="scstageall">stage all</button>' : ''}</summary><div>${rows(unstaged, 'unstaged')}</div></details>` +
    `<details class="lee-sc-group"><summary><span>Stashes</span><b>${(d.stashes || []).length}</b></summary><div class="lee-sc-refs">` +
    `${(d.stashes || []).map(s => `<div class="lee-sc-ref" data-stash="${esc(s.ref)}"><span>${esc(s.ref)}</span><small>${esc(s.subject)} · ${gitRelative(s.timestamp)}</small><button data-apply>apply</button><button data-pop>pop</button><button data-drop>drop</button></div>`).join('') || '<div class="lee-dim lee-git-empty">No stashes</div>'}</div></details>`;
}
function gitBranchesView(d) {
  let branches = [...(d.branches || [])];
  const q = gitUI.branchQuery.toLowerCase();
  if (q) branches = branches.filter(b => `${b.name} ${b.subject} ${b.author}`.toLowerCase().includes(q));
  if (gitUI.branchScope === 'local') branches = branches.filter(b => !b.remote);
  if (gitUI.branchScope === 'remote') branches = branches.filter(b => b.remote);
  if (gitUI.branchScope === 'unmerged') branches = branches.filter(b => !b.merged);
  branches.sort((a, b) => b.timestamp - a.timestamp);
  return `<div class="lee-git-filter"><input id="gitbranchfilter" class="lee-input" value="${esc(gitUI.branchQuery)}" placeholder="Filter branches, commits, authors…">` +
    `<select id="gitbranchscope"><option value="all">all refs</option><option value="local">local</option><option value="remote">remote</option><option value="unmerged">unmerged</option></select><button id="scbranch">new branch</button></div>` +
    `<div class="lee-git-branch-list">${branches.map((b, index) => `<article class="lee-git-branch-row${b.current ? ' current' : ''}${b.latest ? ' latest' : ''}" data-branch="${esc(b.name)}">` +
      `<button data-switch ${b.current ? 'disabled' : ''} title="${b.remote ? 'create local tracking branch' : 'switch branch'}">${b.current ? '●' : '○'}</button><div class="lee-git-branch-copy"><strong>${esc(b.name)}</strong>` +
      `<span>${esc(b.subject || 'No commit subject')}</span><small>${esc(b.author)} · ${gitRelative(b.timestamp)} · ${esc(b.oid)}</small></div>` +
      `<div class="lee-git-badges">${index === 0 ? '<i>latest commit</i>' : ''}${b.default ? '<i>default</i>' : ''}${b.remote ? '<i>remote</i>' : ''}${b.merged ? '<i>merged</i>' : '<i>unmerged</i>'}${b.track ? `<i>${esc(b.track)}</i>` : ''}</div>` +
      `${b.current ? '<span></span>' : '<button data-compare title="Review changes proposed by this branch">review</button>'}${b.remote ? '<span></span>' : '<button data-more title="branch actions">•••</button>'}</article>`).join('') || '<div class="lee-git-empty-state"><strong>No matching branches</strong><span>Change the filter or fetch remote refs.</span></div>'}</div>` +
    `<details class="lee-sc-group"><summary><span>Tags</span><b>${(d.tags || []).length}</b><button id="sctag">new tag</button></summary><div class="lee-sc-meta">` +
    `${(d.tag_details || []).map(t => `<span class="lee-sc-tag" data-tag="${esc(t.name)}">${esc(t.name)} <small>${gitRelative(t.timestamp)}</small><button data-delete-tag>×</button></span>`).join('') || '<span>no tags</span>'}</div></details>`;
}
function gitReviewView(d) {
  if (!gitUI.reviewBase) gitUI.reviewBase = d.branch;
  if (!gitUI.reviewHead) gitUI.reviewHead = (d.branches || []).find(b => !b.current && !b.merged)?.name || (d.branches || []).find(b => !b.current)?.name || d.upstream || d.branch;
  const refs = [...new Set([d.branch, ...(d.branches || []).map(b => b.name), ...(d.tags || [])])];
  const options = refs.map(ref => `<option value="${esc(ref)}"></option>`).join('');
  const r = gitUI.review;
  const reviewedCount = r ? r.files.filter(f => gitUI.reviewed[gitReviewKey({...r, root: d.root}, f.path)]).length : 0;
  const summary = r ? `<div class="lee-git-review-summary"><strong>${r.summary.files} files</strong><span class="add">+${r.summary.additions}</span><span class="del">−${r.summary.deletions}</span><span>${reviewedCount}/${r.summary.files} reviewed</span><button id="gitreviewcopynotes">copy notes</button></div>` : '';
  const commits = r?.commits.length ? `<details class="lee-git-review-commits"><summary>${r.commits.length} incoming commit${r.commits.length === 1 ? '' : 's'}</summary>${r.commits.map(c => `<button data-commit="${esc(c.oid)}"><code>${esc(c.short)}</code><span>${esc(c.subject)}</span><small>${esc(c.author)} · ${gitRelative(c.timestamp)}</small></button>`).join('')}</details>` : '';
  const alternative = r?.snapshot_alternative?.files ? `<div class="lee-git-review-direction"><strong>No changes are proposed by ${esc(r.head)}</strong><span>${esc(r.head)} is already contained in ${esc(r.base)}. The refs still have ${r.snapshot_alternative.files} file difference${r.snapshot_alternative.files === 1 ? '' : 's'} because ${esc(r.base)} is ${r.base_only} commit${r.base_only === 1 ? '' : 's'} ahead.</span><button id="gitreviewsnapshot">show ${r.snapshot_alternative.files} snapshot differences</button><button id="gitreviewswap">review the opposite direction</button></div>` : '';
  const files = r?.files.length ? r.files.map((f, i) => {
    const reviewed = !!gitUI.reviewed[gitReviewKey({...r, root: d.root}, f.path)];
    const note = gitUI.reviewNotes[gitReviewKey({...r, root: d.root}, f.path)];
    return `<button class="lee-git-review-file${f.path === gitUI.reviewFile ? ' active' : ''}${reviewed ? ' reviewed' : ''}" data-review-path="${esc(f.path)}" data-review-index="${i}"><b>${reviewed ? '✓' : f.status}</b><span>${f.old_path ? `${esc(f.old_path)} → ` : ''}${esc(f.path)}${note ? ' · note' : ''}</span><small>${f.binary ? 'binary' : `+${f.additions} −${f.deletions}`}</small></button>`;
  }).join('') : r ? '<div class="lee-git-empty-state"><strong>No files in this review direction</strong><span>Swap base and branch, or use complete snapshots to see content that differs.</span></div>' : '<div class="lee-git-empty-state"><strong>Choose a branch to review</strong><span>Review proposed branch changes or compare complete snapshots.</span></div>';
  return `<section class="lee-git-review-controls"><label>Base<input id="gitreviewbase" list="gitreviewrefs" value="${esc(gitUI.reviewBase)}"></label><label>Branch<input id="gitreviewhead" list="gitreviewrefs" value="${esc(gitUI.reviewHead)}"></label>` +
    `<datalist id="gitreviewrefs">${options}</datalist><button id="gitreviewcontrolswap" title="Swap base and branch">swap direction</button><select id="gitreviewmode"><option value="review">proposed changes</option><option value="snapshot">complete snapshots</option></select><button id="gitreviewload">review</button></section>` + summary + alternative + commits +
    `<div class="lee-git-review-workspace"><header><strong>Changed files</strong><span>Click a file to open its diff in an editor tab.</span></header><aside class="lee-git-review-files">${files}</aside></div>`;
}
function gitCommitInspector() {
  const c = gitUI.selectedCommit; if (!c) return '';
  const files = c.files.map(f => `<button class="lee-git-commit-file" data-commit-file="${esc(f.path)}"><b>${esc(f.status)}</b><span>${f.old_path ? `${esc(f.old_path)} → ` : ''}${esc(f.path)}</span><small>${f.binary ? 'binary' : `+${f.additions} −${f.deletions}`}</small></button>`).join('');
  return `<article class="lee-git-commit-inspector"><header><div><strong>${esc(c.message.split('\n')[0])}</strong><span>${esc(c.author)} · ${gitRelative(c.timestamp)} · ${esc(c.short)}</span></div><button data-cherry>cherry-pick</button><button data-revert>revert</button><button data-reset>reset…</button><button data-close-commit aria-label="Close commit details">×</button></header><section class="lee-git-commit-stats"><b>${c.summary.files} files</b><span>+${c.summary.additions}</span><span>−${c.summary.deletions}</span><code>${esc(c.oid)}</code></section>${c.message.includes('\n') ? `<div class="lee-git-commit-message">${esc(c.message)}</div>` : ''}<details open><summary>changed files</summary><div>${files}</div></details></article>`;
}
function gitHistoryView(d) {
  const refs = [...new Set([...(d.branches || []).map(b => b.name), ...(d.tags || [])])];
  if (!gitUI.compareTo) gitUI.compareTo = d.branch;
  if (!gitUI.compareFrom) gitUI.compareFrom = (d.branches || []).find(b => b.default && b.name !== d.branch)?.name || (d.branches || []).find(b => !b.current)?.name || d.upstream || d.branch;
  const suggestions = refs.map(ref => `<option value="${esc(ref)}"></option>`).join('');
  return `<div class="lee-git-filter"><input id="githistoryfilter" class="lee-input" value="${esc(gitUI.historyQuery)}" placeholder="Search commit messages…"><button id="githistorygo">search</button>` +
    `<select id="githistoryref"><option value="--all">all refs</option>${(d.branches || []).map(b => `<option value="${esc(b.name)}">${esc(b.name)}</option>`).join('')}</select><button id="gitreflog">reflog</button></div>` +
    `<section class="lee-git-compare"><header><strong>Compare snapshots</strong><span>All file changes, including branches behind current</span></header>` +
    `<div class="lee-git-compare-fields"><label>From (base)<input id="gitcompareleft" list="gitcomparerefs" value="${esc(gitUI.compareFrom)}" autocomplete="off"></label>` +
    `<button id="gitcompareswap" title="Swap comparison direction" aria-label="Swap comparison direction">⇄</button><label>To (target)<input id="gitcompareright" list="gitcomparerefs" value="${esc(gitUI.compareTo)}" autocomplete="off"></label>` +
    `<datalist id="gitcomparerefs">${suggestions}</datalist><button id="gitcomparego">compare files</button></div><small>Shows the exact change needed to turn the base snapshot into the target.</small></section>` +
    gitCommitInspector() + `<div id="githistoryrows" class="lee-git-history">${gitUI.history.length ? gitUI.history.map(c => `<button class="lee-git-commit-row${gitUI.selectedCommit?.oid === c.oid ? ' active' : ''}" data-history-commit="${c.oid}"><span class="lee-git-graph">${c.parents.length > 1 ? '◆' : '●'}</span><span><strong>${esc(c.subject)}</strong><small>${esc(c.author)} · ${gitRelative(c.timestamp)} · ${esc(c.short)}${c.decoration ? ' · ' + esc(c.decoration) : ''}</small></span></button>`).join('') : '<div class="lee-git-loading"><span></span><span></span><span></span><small>reading commit graph</small></div>'}</div>`;
}
function gitResourcesView(d) {
  const hosted = (d.remotes || []).find(r => r.web_url);
  const pr = hosted ? `${hosted.web_url}/${hosted.web_url.includes('gitlab') ? '-/merge_requests/new?merge_request[source_branch]=' : 'compare/' + encodeURIComponent(d.branch) + '?expand=1'}${hosted.web_url.includes('gitlab') ? encodeURIComponent(d.branch) : ''}` : '';
  return `<section class="lee-git-resource"><header><strong>Remotes</strong>${pr ? `<button data-hosted-pr data-url="${esc(pr)}">open pull request</button>` : ''}<button id="gitaddremote">add remote</button></header><div class="lee-sc-meta">` +
    `${(d.remotes || []).map(r => `<article data-remote="${esc(r.name)}"><strong>${esc(r.name)}</strong><code>${esc(r.fetch)}</code><code>${esc(r.push)}</code><span>${r.web_url ? `<button data-open-remote data-url="${esc(r.web_url)}">open host</button>` : ''}<button data-fetch-remote>fetch</button><button data-edit-remote>edit</button><button data-remove-remote class="warn">remove</button></span></article>`).join('') || '<div class="lee-git-empty-state"><strong>No remotes</strong><span>Add a remote to fetch, publish, and collaborate.</span></div>'}</div></section>` +
    `<section class="lee-git-resource"><header><strong>Worktrees</strong><button id="gitaddworktree">add worktree</button></header><div id="gitworktrees"><div class="lee-git-loading"><small>reading worktrees</small></div></div></section>` +
    `<section class="lee-git-resource"><header><strong>Submodules</strong></header><div id="gitsubmodules"><div class="lee-git-loading"><small>reading submodules</small></div></div></section>`;
}
function gitScope() {
  if (!gitUI.repo) return '';
  return `<div class="lee-git-scope" title="The branch pill, tree badges and editor change marks still follow the file you have open."><b>${esc(gitRepoName(gitUI.repo))}</b>` +
    `<span>pinned</span><span class="lee-spacer"></span><button id="gitscopeclear">follow active tab</button></div>`;
}
function gitRepoBadges(r) {
  if (r.error) return `<i class="warn">${esc(r.error)}</i>`;
  return [r.changed ? `<i class="warn">${r.changed} changed</i>` : '<i>clean</i>',
    r.behind ? `<i class="warn">↓${r.behind}</i>` : '', r.ahead ? `<i>↑${r.ahead}</i>` : '',
    r.upstream ? '' : '<i>unpublished</i>', r.off_branch ? '<i class="warn">off branch</i>' : '',
    r.unreleased ? `<i>${r.unreleased} since ${esc(r.tag)}</i>` : '',
    r.operation ? `<i class="warn">${esc(r.operation)} in progress</i>` : ''].filter(Boolean).join('');
}
function gitReposView() {
  const d = gitUI.repos;
  if (!d) return '<div class="lee-git-loading"><span></span><span></span><span></span><small>reading repositories</small></div>';
  const s = d.summary || {}, rows = d.repos || [];
  const results = gitUI.reposResults.length ? `<details class="lee-sc-group" open><summary><span>Last run</span><b>${gitUI.reposResults.length}</b></summary>` +
    `<div class="lee-git-repo-results">${gitUI.reposResults.map(r => `<article class="${r.ok === false ? 'failed' : r.skipped ? 'skipped' : 'done'}">` +
      `<strong>${esc(r.name || r.spec || '')}</strong><span>${esc(r.error || r.skipped || r.output || 'done')}</span></article>`).join('')}</div></details>` : '';
  const list = rows.length ? rows.map(r => `<article class="lee-git-repo-row${r.root === gitUI.repo ? ' active' : ''}${r.off_branch ? ' off-branch' : ''}${gitUI.reposBusy?.has(r.root) ? ' working' : ''}" data-repo="${esc(r.root)}" title="${esc(r.root)}">` +
    `<button data-repo-open title="Point source control at this repository">${gitUI.reposBusy?.has(r.root) ? '<span class="lee-spin"></span>' : (r.root === gitUI.repo ? '●' : '○')}</button>` +
    `<div class="lee-git-repo-copy"><strong>${esc(r.name)}</strong><span>${esc(r.branch || 'no branch')}${r.upstream ? ' · ' + esc(r.upstream) : ''}</span>` +
    `<small>${esc(r.last_commit?.subject || 'no commits yet')}${r.last_commit?.timestamp ? ' · ' + gitRelative(r.last_commit.timestamp) : ''}</small>` +
    `<div class="lee-git-badges">${gitRepoBadges(r)}<button data-repo-fetch title="Fetch this repository">fetch</button></div></div>` +
    `<button data-repo-remove title="Stop listing this repository here" aria-label="Stop listing this repository">×</button></article>`).join('') :
    `<div class="lee-git-empty-state"><strong>No repositories in this workspace</strong><span>Open a folder that is a checkout or holds them, clone one, or add a checkout from elsewhere.</span></div>`;
  return `<section class="lee-git-repos-summary"><strong>${s.repos || 0} repositor${s.repos === 1 ? 'y' : 'ies'}</strong>` +
    `${s.dirty ? `<span class="warn">${s.dirty} dirty</span>` : '<span>all clean</span>'}` +
    `${s.behind ? `<span class="warn">${s.behind} behind</span>` : ''}${s.ahead ? `<span>${s.ahead} ahead</span>` : ''}` +
    `${s.off_branch ? `<span class="warn">${s.off_branch} off branch</span>` : ''}` +
    `${s.unreleased ? `<span>${s.unreleased} unreleased</span>` : ''}${s.errors ? `<span class="warn">${s.errors} unreadable</span>` : ''}</section>` +
    `<div class="lee-sc-actions"><button data-repos-op="status">refresh</button><button data-repos-op="fetch">fetch all</button>` +
    `<button data-repos-op="pull">pull all</button><button data-repos-op="push">push all</button>` +
    `<button id="gitrepoclone">clone…</button><button id="gitrepoadd">add repository…</button></div>` +
    `<div class="lee-git-filter"><input id="gitrepoexpect" class="lee-input" value="${esc(gitUI.expect)}" placeholder="Expected branch — default: ${esc(d.expected_branch || 'the one most share')}" aria-label="Expected branch"></div>` +
    `<div class="lee-git-repo-list">${list}</div>` + results;
}
async function loadGitRepos() {
  try { gitUI.repos = await api('/git/repos' + (gitUI.expect ? '?expect=' + encodeURIComponent(gitUI.expect) : '')); }
  catch (e) { return leeFail('git', 'workspace repositories', e); }
  if (gitUI.tab === 'repos') renderGitPanel(gitUI.snapshot);
}
async function gitReposDo(op, extra = {}) {
  const started = performance.now();
  const targets = (extra.paths && extra.paths.length ? extra.paths
                   : ((gitUI.repos && gitUI.repos.repos) || []).map(r => r.root));
  /* The fan-out answers all at once, so there is no per-repository progress to stream. Naming the
     repositories in flight beats "workspace fetch…" when one of them is slow. */
  gitUI.reposBusy = new Set(targets);
  gitUI.reposResults = [];
  if (gitUI.tab === 'repos') renderGitPanel(gitUI.snapshot);
  status(`workspace ${op} · ${targets.length} ${targets.length === 1 ? 'repository' : 'repositories'}…`);
  try {
    const d = await post('/git/repos/action', {op, expect: gitUI.expect, ...extra});
    gitUI.repos = d; gitUI.reposResults = d.results || [];
    const failed = gitUI.reposResults.filter(r => r.ok === false).length;
    const skipped = gitUI.reposResults.filter(r => r.ok !== false && r.skipped).length;
    const done = gitUI.reposResults.length - failed - skipped;
    status(`workspace ${op}: ${done} done · ${skipped} skipped · ${failed} failed · ${Math.round(performance.now() - started)} ms`,
           failed ? 'err' : 'ok');
    for (const r of gitUI.reposResults) {
      leeLog('git', `${op} · ${r.name}${r.skipped ? ' — ' + r.skipped : ''}`,
             r.ok === false ? (r.error || 'failed') : (r.output || ''), r.ok === false ? 'err' : '');
    }
    if (failed) showLog('git');       // one repository refusing is the reason to read the log
    if (gitUI.repo && !(d.repos || []).some(r => r.root === gitUI.repo)) gitUI.repo = '';
    gitUI.snapshot = null;
    await renderGitPanel();
    refreshProjectPills();
    return d;
  } catch (e) { leeFail('git', `workspace ${op}`, e); }
  finally {
    gitUI.reposBusy = null;
    if (gitUI.tab === 'repos') renderGitPanel(gitUI.snapshot);
  }
}
// Pinning is a scope change, not a filter: every ref, commit and review already loaded belongs to
// the repository being left, so all of it goes rather than being shown against the wrong one.
async function gitPinRepo(root, tab = 'changes') {
  gitUI.repo = String(root || '');
  gitUI.snapshot = null; gitUI.history = []; gitUI.review = null; gitUI.reviewFile = ''; gitUI.reviewPatch = '';
  gitUI.reviewBase = ''; gitUI.reviewHead = ''; gitUI.compareFrom = ''; gitUI.compareTo = '';
  gitUI.selectedCommit = null; gitUI.selectedChanges.clear();
  gitUI.tab = tab;
  await renderGitPanel();
  if (!gitUI.repo) refreshProjectPills();
}

