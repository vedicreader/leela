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
const gitUI = {tab: 'changes', snapshot: null, repo: '', repos: null, reposResults: [], expect: '', history: [], historyQuery: '', branchQuery: '', branchScope: 'all', compareFrom: '', compareTo: '', reviewBase: '', reviewHead: '', reviewMode: 'review', review: null, reviewFile: '', reviewPatch: '', root: '', selectedCommit: null, selectedChanges: new Set(), commitDraft: '', changeLists: savedGitLists, reviewed: savedGitReviews, reviewNotes: savedGitNotes, busy: ''};
// The repository the panel's data came from: the pinned one, else the snapshot's. Empty means the one
// the active tab lives in, which is what the branch pill, the file tree and the change marks mean.
function gitRepo() { return gitUI.repo || gitUI.snapshot?.root || ''; }
// A sha or ref from the panel names its repository: the active tab can be in another by now.
function gitUrl(path, params = {}) {
  const q = new URLSearchParams(params);
  if (!q.has('repo') && gitRepo()) q.set('repo', gitRepo());
  const query = q.toString();
  return query ? `${path}?${query}` : path;
}
function gitRepoName(root) { return String(root || '').split('/').filter(Boolean).pop() || root; }
function saveGitWorkflowState() { localStorage.setItem('lee-git-changelists', JSON.stringify(gitUI.changeLists)); localStorage.setItem('lee-git-reviews', JSON.stringify(gitUI.reviewed)); localStorage.setItem('lee-git-review-notes', JSON.stringify(gitUI.reviewNotes)); }
function gitReviewKey(d, path) { return `${d.root || gitUI.snapshot?.root || ''}\0${d.base}\0${d.head}\0${d.mode}\0${path}`; }
function paintGitPill(d) {
  // The pill and the tree badges belong to the repository the active tab is in. A panel pinned to
  // another repository must not repaint them from a snapshot that is not theirs, because a clean
  // pill over a dirty file tree is worse than no pill.
  if (gitUI.repo) return;
  const git = $('#gitpill'); if (!git || !d) return;
  paintBranchPill(d);
  git.title = `${d.root}${d.upstream ? ' · ' + d.upstream : ' · no upstream'} · ${gitFreshness(d.fetched_at)}`;
  paintGitTree(d);
}
/* The one painter of the branch pill and the pull and push arrows beside it. `state` is `branch`,
   `nogit` (not a checkout), `pending` (not asked yet), `nofolder` (hidden: no folder is open) or `error`
   (the repository could not be read). The arrows show only when there is something to pull or push. */
const BRANCH_WORDS = {nogit: 'no git', pending: 'git …', error: 'git ?', nofolder: ''};
function paintBranchPill(d, state = 'branch') {
  const git = $('#gitpill'); if (!git) return;
  const n = state === 'branch' ? (d?.changes || []).length : 0;
  const name = state in BRANCH_WORDS ? BRANCH_WORDS[state] : d?.branch || (d?.head ? `detached at ${String(d.head).slice(0, 7)}` : 'detached');
  git.dataset.state = state;
  const label = git.querySelector('.lee-branch-name'), count = git.querySelector('.lee-change-count');
  if (label) label.textContent = name;
  if (count) { count.textContent = n || ''; count.hidden = !n; }
  git.setAttribute('aria-label', `switch branch: ${name}${n ? `, ${n} changed file${n === 1 ? '' : 's'}` : ''}`);
  for (const [op, k] of [['pull', state === 'branch' && d?.behind], ['push', state === 'branch' && d?.ahead]]) {
    const b = $(`#git${op}`); if (!b) continue;
    b.hidden = !k;
    const num = b.querySelector('.lee-sync-n'); if (num) num.textContent = k || '';
    const say = k ? `${op} ${k} commit${k === 1 ? '' : 's'}` : op;
    b.title = say; b.setAttribute('aria-label', say);
  }
}
async function gitDo(op, extra = {}) {
  const started = performance.now(), name = op.replaceAll('_', ' ');
  gitUI.busy = op; status(`git ${name}…`);
  try {
    const d = await post('/git/action', {op, repo: gitUI.repo, ...extra});
    gitUI.snapshot = d; paintGitPill(d);
    // Immediately rather than up to one look later. The new signature is stored, so the next look
    // does not treat our own mutation as news, and still sees a switch to another repository.
    noteGitSignature(d); gitChanged();
    // What the operation left behind beats how long it took. A squash that staged twelve files and
    // a merge that stopped at a conflict both "complete". One call, not two, because a second
    // `status` replaces the first.
    const said = d.outcome?.summary || `complete · ${Math.round(performance.now() - started)} ms`;
    status(`git ${name} · ${said}${d.outcome?.note ? '. ' + d.outcome.note : ''}`,
           d.outcome?.note ? 'err' : 'ok');
    // `recover` is the only handle on a deleted branch or a dropped stash, and a status line is
    // gone in seconds, so the log is where it has to end up.
    leeLog('git', `${name} · ${gitRepoName(gitUI.repo || d.root || '')}`,
           [extra.branch, extra.ref, extra.message, d.outcome?.recover].filter(Boolean).join(' ') || '', 'ok');
    return d;
  } catch (e) {
    /* Reporting the failure here is what clears the running status line. Git refusing a switch
       because local changes would be overwritten is a normal, fast answer. */
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
    `<strong>a filter changes files here when they are staged</strong><span>${esc(f.explain)}</span></div></section>`;
}

/* The way back from the last thing that moved this branch, because "that merge was not what I
   wanted" arrives a minute later.

   Only the guarded operations take a safepoint. Discard, branch create and delete, stash drop and
   apply_patch take none, so after one of those the newest safepoint is some older merge, and the
   banner was offering to undo that instead. It says how long ago, which is what tells the two
   apart. */
function gitUndoBanner(d) {
  const point = (d.safepoints || [])[0];
  if (!point) return '';
  const when = point.at ? gitRelative(point.at) : '';
  return `<section class="lee-git-undo"><span>last undoable: ${esc(point.describe)}` +
    `${when ? ` <small>${esc(when)}</small>` : ''}</span>` +
    `<span class="lee-spacer"></span><button data-git-undo="${esc(point.token)}">undo</button></section>`;
}

