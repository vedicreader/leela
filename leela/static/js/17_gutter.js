/* ---------------------------------------------------------------- change gutter popup
 * PyCharm's gutter, which is the one people mean: the mark thickens under the pointer, and
 * clicking it shows what the line used to say next to the four things you want at that moment --
 * step to the next change, put this one back, copy the old text, or commit only this.
 *
 * The hunks come from /git/file, where they are cut out of a three-context diff so that each one
 * is a patch Git can place by its own context. The browser never assembles a patch of its own:
 * a hand-built hunk with the wrong line numbers is applied silently in the wrong place, and this
 * surface's whole job is to change one change and nothing else.
 */
const fileHunks = () => lee.fileGit?.hunks || [];

function hunkAtLine(line) {
  const hunks = fileHunks();
  const inside = hunks.findIndex(h => line >= h.from && line <= h.to);
  if (inside >= 0) return inside;
  // Three context lines can merge two changes into one hunk, so a mark drawn from the exact
  // zero-context ranges can sit just outside the span of the hunk that carries it. The nearest
  // change is then the right answer, and is certainly better than the click doing nothing.
  let best = -1, gap = Infinity;
  hunks.forEach((h, i) => {
    const d = Math.min(Math.abs(line - h.from), Math.abs(line - h.to));
    if (d < gap) { gap = d; best = i; }
  });
  return best;
}

/* Which words of the old line the new one no longer has. PyCharm boxes them, and it is the
 * difference between reading "the line changed" and seeing what changed in it. A plain LCS over
 * words is enough at one line's length, and costs nothing at it. */
function tokenDiffHtml(before, after) {
  const a = String(before ?? '').match(/\w+|\s+|[^\w\s]/g) || [];
  const b = String(after ?? '').match(/\w+|\s+|[^\w\s]/g) || [];
  if (!a.length) return '';
  if (!b.length) return `<mark>${esc(before)}</mark>`;
  const n = a.length, m = b.length;
  const dp = Array.from({length: n + 1}, () => new Uint16Array(m + 1));
  for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--)
    dp[i][j] = a[i] === b[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
  let out = '', run = '', i = 0, j = 0;
  const flush = () => { if (run) out += `<mark>${esc(run)}</mark>`; run = ''; };
  while (i < n) {
    if (j < m && a[i] === b[j]) { flush(); out += esc(a[i]); i++; j++; }
    else if (j < m && dp[i + 1][j] < dp[i][j + 1]) j++;
    else run += a[i++];
  }
  flush();
  return out;
}

function closeChangePopup() {
  const pop = $('.lee-change-pop');
  if (!pop) return;
  pop._leeOff?.(); pop.remove();
}

/* The mark widens only while the pointer is actually on it. 12px is the editor bundle's own
 * click target for a change mark; if this number and that one disagreed, the gutter would
 * advertise an affordance it does not answer. */
function armChangeGutter(host) {
  if (!host || host._leeGutterArmed) return;
  host._leeGutterArmed = true;
  let hot = null;
  const cool = () => { hot?.classList.remove('lee-change-hot'); hot = null; };
  host.addEventListener('mousemove', e => {
    const line = e.target.closest?.('.cm-lee-change');
    if (!line || e.clientX > line.getBoundingClientRect().left + 12) return cool();
    if (line === hot) return;
    cool(); hot = line; line.classList.add('lee-change-hot');
  });
  host.addEventListener('mouseleave', cool);
}

function changePopupBody(h) {
  if (!h.old) return '<div class="lee-change-new">These lines are new — there is no committed version of them.</div>';
  const old = h.old.replace(/\n$/, '').split('\n'), now = (h.new || '').replace(/\n$/, '').split('\n');
  return `<pre class="lee-change-old">${old.map((l, k) => tokenDiffHtml(l, now[k])).join('\n')}</pre>`;
}

function showChangePopup(path, line) {
  closeChangePopup();
  const hunks = fileHunks(), at = hunkAtLine(line);
  // An untracked file has no committed version of anything, so there is nothing for this popup
  // to show; the whole-file diff is the honest answer there.
  if (at < 0) return showGitFileDiff(path, lee.fileGit?.diff || '', line);
  const h = hunks[at], name = String(path || '').split('/').pop();
  const pop = document.createElement('div');
  pop.className = 'lee-change-pop'; pop.setAttribute('role', 'dialog');
  pop.setAttribute('aria-label', `change ${at + 1} of ${hunks.length} in ${name}, line ${h.from}`);
  pop.innerHTML =
    `<div class="lee-change-tools">` +
    `<button class="lee-change-icon" data-act="prev" title="previous change" aria-label="previous change">↑</button>` +
    `<button class="lee-change-icon" data-act="next" title="next change" aria-label="next change">↓</button>` +
    `<button class="lee-change-icon" data-act="revert" title="revert this change" aria-label="revert this change">⟲</button>` +
    `<button class="lee-change-icon" data-act="diff" title="show this file's whole diff" aria-label="show diff">◫</button>` +
    `<button class="lee-change-icon" data-act="copy" title="copy the previous version" aria-label="copy the previous version">⧉</button>` +
    `<span class="lee-change-count">${at + 1} / ${hunks.length}</span>` +
    `<input class="lee-input lee-change-msg" placeholder="Commit this change" aria-label="commit message for this change">` +
    `<button class="lee-btn go" data-act="commit">commit</button></div>` + changePopupBody(h);
  document.body.appendChild(pop);
  const anchor = $(`#filecm .cm-lee-change[data-change-line="${h.from}"]`) ||
                 $(`#filecm .cm-lee-change[data-change-line="${line}"]`) || $('#filecm');
  const rect = anchor.getBoundingClientRect(), size = pop.getBoundingClientRect();
  pop.style.left = Math.max(4, Math.min(rect.left, innerWidth - size.width - 4)) + 'px';
  pop.style.top = Math.max(4, Math.min(rect.bottom + 4, innerHeight - size.height - 4)) + 'px';

  const away = e => { if (!pop.contains(e.target)) closeChangePopup(); };
  const key = e => { if (e.key === 'Escape') { e.stopPropagation(); closeChangePopup(); } };
  // Deferred by a tick: the click that opened this popup is still on its way up.
  setTimeout(() => document.addEventListener('mousedown', away), 0);
  document.addEventListener('keydown', key, true);
  pop._leeOff = () => {
    document.removeEventListener('mousedown', away);
    document.removeEventListener('keydown', key, true);
  };

  pop.addEventListener('click', e => {
    const act = e.target.closest('[data-act]')?.dataset.act;
    if (!act) return;
    if (act === 'prev' || act === 'next') {
      const next = hunks[(at + (act === 'next' ? 1 : hunks.length - 1)) % hunks.length];
      jumpToLine(next.from);
      // The line has to be laid out before it can be measured, and the editor only renders the
      // lines it has scrolled to.
      return requestAnimationFrame(() => showChangePopup(path, next.from));
    }
    if (act === 'diff') { closeChangePopup(); return showGitFileDiff(path, lee.fileGit?.diff || '', h.from); }
    if (act === 'copy') return copyChangeHunk(h);
    if (act === 'revert') return revertChangeHunk(path, h);
    if (act === 'commit') return commitChangeHunk(path, h, pop.querySelector('.lee-change-msg').value);
  });
  return pop;
}

async function copyChangeHunk(h) {
  try { await navigator.clipboard.writeText(h.old || h.new || ''); status('previous version copied', 'ok'); }
  catch (_) { status('clipboard access failed', 'err'); }
}

/* Git reads and writes the file on disk, and this editor may be holding a newer version of it.
 * Both directions of that are silent data loss -- the revert overwrites the unsaved edit, or the
 * next autosave writes the reverted lines back -- so the file is saved first and the buffer is
 * reloaded after, rather than either being guessed at. */
async function refreshFileChanges(path, fromDisk = false) {
  const v = lee.editors.get('file');
  if (!v) return;
  if (fromDisk) {
    const st = await api('/tab/state?path=' + encodeURIComponent(path)).catch(() => null);
    if (typeof st?.text === 'string') {
      lee.dirtyBuffers.delete(path); lee.buffers.delete(path);
      if (st.text !== LeeCM.getDoc(v)) LeeCM.setDoc(v, st.text);
      $$('.lee-tab').find(x => x.title === path)?.classList.remove('dirty');
    }
  }
  const git = await api('/git/file?path=' + encodeURIComponent(path)).catch(() => null);
  if (!git) return;
  lee.fileGit = git; LeeCM.setChangedLines(v, git.ranges || []);
}

async function revertChangeHunk(path, h) {
  if ($('.lee-tab.active.dirty') && !await saveTab(true)) return;
  const ok = await confirmDialog('Revert this change?',
    `Lines ${h.from}–${h.to} of ${String(path).split('/').pop()} go back to their committed ` +
    `version. Every other change in the file is left alone.`, 'revert');
  if (!ok) return;
  closeChangePopup();
  // reverse against the working tree, not the index: this is an edit to the file, and the
  // index is not involved in it at all.
  try { await gitDo('apply_patch', {patch: h.patch, staged: false, reverse: true}); }
  catch (_) { return; }
  await refreshFileChanges(path, true);
}

async function commitChangeHunk(path, h, message) {
  const text = String(message || '').trim();
  if (!text) return status('write a message to commit this change', 'err');
  if ($('.lee-tab.active.dirty') && !await saveTab(true)) return;
  /* PyCharm commits the one change and nothing else. Git can only commit what is in the index, so
   * this stages the hunk and commits -- which means anything already staged rides along. Rather
   * than quietly widening a one-hunk commit, or quietly unstaging work someone deliberately
   * staged, the choice is put to whoever is looking at it. */
  const snapshot = gitUI.snapshot || await gitInfoOrNull();
  const staged = (snapshot?.changes || []).filter(c => c.staged && c.path !== path).map(c => c.path);
  if (staged.length) {
    const shown = staged.slice(0, 3).join(', ') + (staged.length > 3 ? `, and ${staged.length - 3} more` : '');
    const ok = await confirmDialog('Something else is already staged',
      `${shown} ${staged.length === 1 ? 'is' : 'are'} staged and would be committed together with ` +
      `this change. Unstage first to commit this change on its own.`, 'commit anyway');
    if (!ok) return;
  }
  closeChangePopup();
  try {
    await gitDo('apply_patch', {patch: h.patch, staged: true, reverse: false});
    await gitDo('commit', {message: text});
  } catch (_) { return; }
  await refreshFileChanges(path);
}

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
    `<form id="sccommit" class="lee-sc-commit"><label>Commit message<textarea rows="3" placeholder="Describe this change" aria-label="Commit message"></textarea></label>` +
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
  /* The fan-out answers all at once, so there is no per-repository progress to stream. What
     there is: which repositories are in flight. Naming them beats "workspace fetch…" when one
     of them is slow, because the question you have is always *which one*. */
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
// Pinning is a scope change, not a filter: every ref, commit and review already loaded
// belongs to the repository being left, so all of it goes rather than being shown against
// the wrong one.
async function gitPinRepo(root, tab = 'changes') {
  gitUI.repo = String(root || '');
  gitUI.snapshot = null; gitUI.history = []; gitUI.review = null; gitUI.reviewFile = ''; gitUI.reviewPatch = '';
  gitUI.reviewBase = ''; gitUI.reviewHead = ''; gitUI.compareFrom = ''; gitUI.compareTo = '';
  gitUI.selectedCommit = null; gitUI.selectedChanges.clear();
  gitUI.tab = tab;
  await renderGitPanel();
  if (!gitUI.repo) refreshProjectPills();
}

