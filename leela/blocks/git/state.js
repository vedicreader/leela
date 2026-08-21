function gitChangeRow(c, group) {
  const state = c.conflicted ? 'conflict' : c.untracked ? 'new file' : group === 'staged' ? 'will commit' : 'not staged';
  const selected = gitUI.selectedChanges.has(`${group}:${c.path}`);
  const list = gitUI.changeLists[c.path], stat = group === 'staged' ? c.staged_stat : c.unstaged_stat;
  return `<article class="lee-git-change ${group}${selected ? ' selected' : ''}" data-path="${esc(c.path)}" data-group="${group}">` +
    `<input type="checkbox" data-select-change aria-label="Select ${esc(c.path)}" ${selected ? 'checked' : ''}>` +
    `<button class="lee-git-file" title="review diff"><span class="lee-git-status">${esc(group === 'staged' ? c.index : c.worktree)}</span><span>${esc(c.path)}</span></button>` +
    `${list ? `<i class="lee-git-changelist">${esc(list)}</i>` : ''}${stat ? `<small class="lee-git-line-stat">${stat.binary ? 'binary' : `+${stat.additions} −${stat.deletions}`}</small>` : ''}` +
    `<span class="sub">${state}</span><span class="lee-spacer"></span>${c.conflicted ? '<button class="lee-btn warn" data-resolve>resolve</button>' : '<button class="lee-btn" data-blame title="file history and blame">blame</button>'}` +
    `<button class="lee-btn" data-open title="open file">open</button>` +
    `${group === 'unstaged' ? '<button class="lee-btn" data-git="stage">stage</button>' : '<button class="lee-btn" data-git="unstage">unstage</button>'}` +
    `${group === 'unstaged' && !c.untracked ? '<button class="lee-btn warn" data-git="discard">discard</button>' : ''}</article>`;
}
function gitRelative(stamp) {
  if (!stamp) return 'date unavailable';
  const seconds = Math.max(0, Date.now() / 1000 - stamp), units = [[31536000, 'y'], [2592000, 'mo'], [604800, 'w'], [86400, 'd'], [3600, 'h'], [60, 'm']];
  for (const [size, label] of units) if (seconds >= size) return `${Math.floor(seconds / size)}${label} ago`;
  return 'just now';
}
function gitFreshness(stamp) { return stamp ? `fetched ${gitRelative(stamp)}` : 'remote refs have not been fetched'; }
let savedGitLists = {}, savedGitReviews = {}, savedGitNotes = {};
try { savedGitLists = JSON.parse(localStorage.getItem('lee-git-changelists') || '{}'); } catch (_) {}
try { savedGitReviews = JSON.parse(localStorage.getItem('lee-git-reviews') || '{}'); } catch (_) {}
try { savedGitNotes = JSON.parse(localStorage.getItem('lee-git-review-notes') || '{}'); } catch (_) {}
const gitUI = {tab: 'changes', snapshot: null, repo: '', repos: null, reposResults: [], expect: '', history: [], historyQuery: '', branchQuery: '', branchScope: 'all', compareFrom: '', compareTo: '', reviewBase: '', reviewHead: '', reviewMode: 'review', review: null, reviewFile: '', reviewPatch: '', selectedCommit: null, selectedChanges: new Set(), changeLists: savedGitLists, reviewed: savedGitReviews, reviewNotes: savedGitNotes, busy: ''};
// Which repository a panel request is about. Empty means the one the active tab lives in,
// which is what the branch pill, the file tree and the editor's change marks always mean.
function gitUrl(path, params = {}) {
  const q = new URLSearchParams(params);
  if (gitUI.repo) q.set('repo', gitUI.repo);
  const query = q.toString();
  return query ? `${path}?${query}` : path;
}
function gitRepoName(root) { return String(root || '').split('/').filter(Boolean).pop() || root; }
function saveGitWorkflowState() { localStorage.setItem('lee-git-changelists', JSON.stringify(gitUI.changeLists)); localStorage.setItem('lee-git-reviews', JSON.stringify(gitUI.reviewed)); localStorage.setItem('lee-git-review-notes', JSON.stringify(gitUI.reviewNotes)); }
function gitReviewKey(d, path) { return `${d.root || gitUI.snapshot?.root || ''}\0${d.base}\0${d.head}\0${d.mode}\0${path}`; }
function paintGitPill(d) {
  // The pill and the tree badges belong to the repository the active tab is in. A panel
  // pinned to another repository in the workspace must not repaint them from a snapshot
  // that is not theirs -- a clean pill over a dirty file tree is worse than no pill.
  if (gitUI.repo) return;
  const git = $('#gitpill'); if (!git || !d) return;
  const n = (d.changes || []).length;
  git.textContent = `${d.branch}${n ? ' · ' + n : ''}${d.ahead ? ' · ↑' + d.ahead : ''}${d.behind ? ' · ↓' + d.behind : ''}`;
  git.className = 'lee-branch-switcher ' + (n ? 'lee-pill-warn' : 'lee-pill-on');
  git.title = `${d.root}${d.upstream ? ' · ' + d.upstream : ' · no upstream'} · ${gitFreshness(d.fetched_at)}`;
  paintGitTree(d);
}
async function gitDo(op, extra = {}) {
  const started = performance.now(), name = op.replaceAll('_', ' ');
  gitUI.busy = op; status(`git ${name}…`);
  try {
    const d = await post('/git/action', {op, repo: gitUI.repo, ...extra});
    gitUI.snapshot = d; paintGitPill(d);
    // Immediately, rather than up to one poll later -- and the signature is cleared so the
    // poll that follows does not treat our own mutation as news and do it all again.
    lee.gitSignature = ''; gitChanged();
    // What the operation *left behind* beats how long it took. A squash that staged twelve
    // files and a merge that stopped at a conflict both "complete", and saying only that is
    // how an index full of someone else's changes came to look like a bug in Leela.
    // One call, not two: a second `status` replaces the first, and the note is the half that
    // must not be the one dropped.
    const said = d.outcome?.summary || `complete · ${Math.round(performance.now() - started)} ms`;
    status(`git ${name} · ${said}${d.outcome?.note ? ' — ' + d.outcome.note : ''}`,
           d.outcome?.note ? 'err' : 'ok');
    leeLog('git', `${name} · ${gitRepoName(gitUI.repo || d.root || '')}`,
           [extra.branch, extra.ref, extra.message].filter(Boolean).join(' ') || '', 'ok');
    return d;
  } catch (e) {
    /* Without this the status line kept saying "git checkout…" for ever. Git refusing a
       switch because local changes would be overwritten is a normal, fast answer, and it
       looked identical to a hang -- the one thing a progress message must never do. */
    leeFail('git', name, e);
    throw e;
  } finally { gitUI.busy = ''; }
}
function gitOperationBanner(d) {
  const op = d.operation || {};
  if (!op.active) return '';
  return `<section class="lee-git-operation"><div><strong>${esc(op.active)} in progress</strong><span>Resolve the listed conflicts, then continue or abort.</span></div>` +
    `<span class="lee-spacer"></span><button data-conflict-center>resolve conflicts</button>${op.can_continue ? '<button data-operation="continue">continue</button>' : ''}${op.can_skip ? '<button data-operation="skip">skip</button>' : ''}` +
    `${op.can_abort ? '<button data-operation="abort" class="warn">abort</button>' : ''}</section>`;
}
// Why a file will not stay staged, said once, where the file list is. Git treats a filter it
// cannot run as nothing having gone wrong, so this is the only place the reason can come from.
function gitFilterBanner(d) {
  const f = d.filters || {};
  if (f.ok !== false || !f.explain) return '';
  return `<section class="lee-git-operation lee-git-filters"><div>` +
    `<strong>files here may not stay staged</strong><span>${esc(f.explain)}</span></div></section>`;
}

// The way back from the last thing that moved this branch. Offered whenever there is one,
// rather than only after a failure: "that merge was not what I wanted" arrives a minute later.
function gitUndoBanner(d) {
  const point = (d.safepoints || [])[0];
  if (!point) return '';
  return `<section class="lee-git-undo"><span>last: ${esc(point.describe)}</span>` +
    `<span class="lee-spacer"></span><button data-git-undo="${esc(point.token)}">undo</button></section>`;
}

