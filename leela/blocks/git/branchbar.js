/* The branch pill as a real Git control, and the three remote gestures beside it.
 *
 * One popup over branches and actions, in the order JetBrains settled on: what to do with the
 * branch you are on, then how to get a different one, then the branches themselves. Names
 * containing a `/` fold into a folder by their first segment, because forty `cursor/…` branches
 * are otherwise a wall of near-identical rows.
 *
 * Everything here posts to `/git/action`. The one new route is `/git/clone`, because a clone is
 * minutes of network and cannot be a request.
 */

const GIT_RECENT_KEY = 'lee-git-recent-branches';
const gitBranchFolders = new Set();      // which prefix folders are expanded, this session

function recentBranches(root) {
  try { return JSON.parse(localStorage.getItem(GIT_RECENT_KEY) || '{}')[root] || []; }
  catch (_) { return []; }
}
function rememberBranch(root, name) {
  let all = {};
  try { all = JSON.parse(localStorage.getItem(GIT_RECENT_KEY) || '{}'); } catch (_) {}
  all[root] = [name, ...(all[root] || []).filter(x => x !== name)].slice(0, 8);
  try { localStorage.setItem(GIT_RECENT_KEY, JSON.stringify(all)); } catch (_) {}
}

// A remote branch's first segment is its remote, not a folder: `origin/cursor/x` belongs in
// `cursor` beside the local branch of the same name.
function branchLeaf(b) { return b.remote ? b.name.split('/').slice(1).join('/') : b.name; }
function branchFolder(b) { const cut = branchLeaf(b).indexOf('/'); return cut < 0 ? '' : branchLeaf(b).slice(0, cut); }
function branchDrift(b) {
  return `${b.behind ? `<i class="behind">↙${b.behind}</i>` : ''}${b.ahead ? `<i class="ahead">↗${b.ahead}</i>` : ''}`;
}

function branchRow(b, label) {
  const upstream = b.gone ? 'upstream gone' : b.upstream || (b.remote ? 'remote' : 'no upstream');
  return `<button class="lee-mrow lee-branch-row${b.current ? ' current' : ''}" data-branch="${esc(b.name)}">` +
    `<span class="lee-branch-mark">${b.current ? '✓' : b.remote ? '☁' : '›'}</span>` +
    `<strong>${esc(label ?? branchLeaf(b))}</strong><span class="sub">${esc(upstream)}</span>` +
    `<span class="lee-spacer"></span>${branchDrift(b)}` +
    `<span class="lee-branch-more" data-more="${esc(b.name)}" role="button" title="branch actions">•••</span></button>`;
}

function branchGroup(title, rows, fold = false) {
  if (!rows.length) return '';
  let body = rows.map(b => branchRow(b)).join('');
  if (fold) {
    const folders = new Map(), loose = [];
    for (const b of rows) {
      const name = branchFolder(b);
      if (!name) { loose.push(b); continue; }
      if (!folders.has(name)) folders.set(name, []);
      folders.get(name).push(b);
    }
    // A collapsed folder's branches are absent from the DOM rather than hidden, so the modal's
    // arrow-key walk over `.lee-mrow` never selects a row nobody can see.
    body = loose.map(b => branchRow(b)).join('') + [...folders].map(([name, kids]) => {
      const open = gitBranchFolders.has(name) || kids.some(k => k.current);
      return `<button class="lee-mrow lee-branch-folder" data-folder="${esc(name)}">` +
        `<span class="lee-branch-mark">${open ? '▾' : '▸'}</span><strong>${esc(name)}/</strong>` +
        `<span class="sub">${kids.length}</span></button>` +
        (open ? kids.map(b => branchRow(b, branchLeaf(b).slice(name.length + 1))).join('') : '');
    }).join('');
  }
  return `<div class="lee-branch-group"><header>${esc(title)}</header>${body}</div>`;
}

async function switchBranch(d, name) {
  const b = (d.branches || []).find(x => x.name === name);
  if (!b || b.current) return leeLeft('git');
  rememberBranch(d.root, name);
  // A remote-only branch is checked out by its leaf name, and Git creates the tracking branch.
  // `/git/action` answers with the same `info()` that `/git/info` does, so a caller showing
  // branches can repaint from the reply.
  const fresh = await gitDo('checkout', {branch: b.remote ? branchLeaf(b) : name});
  const out = fresh.outcome || {};
  // A switch always reports that HEAD moved, which buries what became of the work it set aside.
  if (out.message) { leeLog('git', 'checkout', out.message, 'ok'); status(`git checkout · ${firstLine(out.message)}`, 'ok'); }
  return fresh;
}

function compareBranch(d, name) {
  Object.assign(gitUI, {tab: 'review', review: null, reviewBase: d.branch, reviewHead: name});
  leeLeft('git'); leeGitRefresh();
}

// `after` takes the snapshot each mutation answers with, so whatever opened this menu can show
// the repository as it is now rather than as it was when it was opened.
function branchActions(anchor, d, b, after = (x) => x) {
  if (!b) return;
  const leaf = branchLeaf(b);
  const act = async (op, extra) => { try { return after(await branchAct(op, extra)); } catch (_) {} };
  const rows = [
    {label: `Checkout ${leaf}`, disabled: b.current,
     run: async () => { try { after(await switchBranch(d, b.name)); } catch (_) {} }},
    {label: 'New Branch from…', detail: b.name, run: async () => {
      const branch = await inputDialog('new branch', `Branch name, starting at ${b.name}`, '', 'feature/name');
      if (branch) await act('create', {branch, start: b.name});
    }},
    {separator: true},
    {label: 'Compare with current', detail: `${d.branch} … ${leaf}`, disabled: b.current, run: () => compareBranch(d, b.name)},
    // Through the previews, as the git panel's identical entries go.
    {label: `Rebase ${d.branch} onto ${leaf}`, disabled: b.current, run: () => showRebasePreview(b.name, d, act)},
    {label: `Merge ${leaf} into ${d.branch}`, disabled: b.current, run: () => showMergePreview(b.name, d, act)},
  ];
  if (!b.remote && !b.current) rows.push({separator: true}, {label: `Delete ${leaf}`, warn: true, run: async () => {
    if (!await confirmDialog('delete branch', `Delete ${b.name}?`, 'delete')) return;
    // Never `-D` behind one confirmation. Git refusing an unmerged branch is the warning, and
    // `act` answering undefined is that refusal, so the second ask is the one that forces it.
    if (await act('delete', {branch: b.name})) return;
    if (await confirmDialog('force delete',
        `Git refused: ${b.name} has commits that are on no other branch. Delete it anyway? ` +
        'The log keeps the commit it was at, so it can be put back by sha.', 'force delete'))
      await act('delete', {branch: b.name, force: true});
  }});
  openChromeMenu(anchor, rows);
}

// Where "why is this divergent" usually starts: the PR, and whether its base moved under it.
async function branchPr(d) {
  const r = await api(gitUrl('/git/pr', {branch: d.branch})).catch(() => null);
  const pr = r?.pr;
  if (!pr) return {id: 'pr', label: 'Pull request', detail: r?.note || 'unavailable', run: () => status(r?.note || 'no pull request', 'ok')};
  const c = pr.checks || {};
  const health = c.failing?.length ? `${c.failing.length} check${c.failing.length === 1 ? '' : 's'} red`
              : c.pending ? `${c.pending} check${c.pending === 1 ? '' : 's'} running` : 'checks green';
  return {id: 'pr', label: `#${pr.number} ${pr.title}`.slice(0, 60),
    detail: `${pr.base}${pr.behind_base ? ` · ${pr.behind_base} behind base` : ''} · ${health}`,
    run: () => openExternal(pr.url)};
}

function branchTopActions(d) {
  const changed = (d.changes || []).length;
  const remotes = (d.branches || []).filter(b => b.remote).length;
  return [
    {id: 'update', label: 'Update Project', detail: d.behind ? `${d.behind} behind ${d.upstream}` : 'pull, autostashing local work'},
    {id: 'fetch', label: 'Fetch', detail: remotes ? `refresh ${remotes} remote branch${remotes === 1 ? '' : 'es'}` : 'refresh remote branches'},
    {id: 'commit', label: 'Commit…', detail: changed ? `${changed} changed file${changed === 1 ? '' : 's'}` : 'working tree clean'},
    {id: 'push', label: 'Push', detail: !d.upstream ? 'publish this branch' : d.ahead ? `${d.ahead} ahead` : 'nothing to push'},
    {id: 'new', label: 'New Branch…', detail: `from ${d.branch}`},
    {id: 'revision', label: 'Checkout Tag or Revision…', detail: 'any tag, commit or branch'},
    {id: 'clone', label: 'Clone Repository…', detail: 'into a folder, then open it'},
  ];
}

const branchAct = async (op, extra = {}) => { const d = await gitDo(op, extra); refreshScmIfOpen(d); return d; };

function runBranchAction(id, d) {
  if (id === 'update') return d.ahead && d.behind ? showSyncPlan(d) : gitDo('pull');
  if (id === 'push') return leeGitQuick('push');
  if (id === 'commit') { gitUI.tab = 'changes'; leeLeft('git'); return leeGitRefresh(); }
  if (id === 'clone') return leeCloneRepo();
  if (id === 'new') return inputDialog('new branch', `Branch name, starting at ${d.branch}`, '', 'feature/name')
    .then(branch => branch && gitDo('create', {branch, start: d.branch}));
  return inputDialog('checkout tag or revision', 'Tag, commit or branch', '', 'v1.2.0  ·  a1b2c3d')
    .then(ref => ref && gitDo('checkout', {branch: ref}));
}

async function leeBranchMenu(anchor) {
  let d;
  try { d = await gitInfo(gitUrl('/git/info')); }
  catch (e) { return leeFail('git', 'branches', e); }
  let recent = recentBranches(d.root);
  let search = null;
  const m = modal(
    `<div class="lee-mhead">Git Branches<span class="sub">${esc(gitRepoName(d.root))} · on ${esc(d.branch)}</span></div>` +
    `<input class="lee-input" id="branchsearch" autocomplete="off" spellcheck="false"` +
    ` placeholder="Search branches and actions…" aria-label="search branches and actions">` +
    `<div class="lee-modallist lee-branchlist" id="branchlist"></div>` +
    `<div class="lee-mfoot"><span class="lee-dim">Enter checks out · ••• compares, rebases and merges</span></div>`,
    // The arrow keys take the caret out of the box, so a printable key puts it back.
    e => { if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && document.activeElement !== search) search.focus(); },
    null, {className: 'lee-branchmodal', storageKey: 'branches'});
  search = m.querySelector('#branchsearch');
  const list = m.querySelector('#branchlist');
  const sub = m.querySelector('.lee-mhead .sub');

  let prRow = null;
  /* Replacing the children of a scrolled element puts it at scrollTop 0, so `keep` restores the
     old offset. That is exact for a fold, which only adds or removes rows below the folder
     clicked. Typing is the one repaint that goes back to the top, because those are different
     results rather than the same list rearranged. */
  const paint = (keep = true) => {
    const at = keep ? list.scrollTop : 0;
    const q = search.value.trim().toLowerCase();
    const hit = text => !q || String(text).toLowerCase().includes(q);
    const acts = [...branchTopActions(d), ...(prRow ? [prRow] : [])].filter(a => hit(a.label));
    const all = (d.branches || []).filter(b => hit(`${b.name} ${b.subject} ${b.author}`));
    const near = recent.map(n => all.find(b => b.name === n && !b.current)).filter(Boolean);
    const rest = all.filter(b => !near.includes(b));
    list.innerHTML =
      (acts.length ? `<div class="lee-branch-group">${acts.map(a =>
        `<button class="lee-mrow lee-branch-action" data-act="${a.id}"><strong>${esc(a.label)}</strong>` +
        `<span class="lee-spacer"></span><span class="sub">${esc(a.detail)}</span></button>`).join('')}</div>` : '') +
      branchGroup('Recent', near) +
      branchGroup('Local', rest.filter(b => !b.remote), true) +
      branchGroup('Remote', rest.filter(b => b.remote), true) ||
      '<div class="lee-dim">nothing matches</div>';
    list.scrollTop = at;
  };

  /* A modal that goes on describing the branch you just left puts the tick against the wrong row
     and offers every action against the old HEAD. Each mutation answers with a whole `info()`, so
     take it and repaint rather than closing.

     `recent` is re-read because checking out writes to it. `prRow` is dropped because the pull
     request belongs to the branch that was current when it was fetched, and two switches in quick
     succession would otherwise show the first answer under the second branch's heading. */
  const showPr = () => {
    const asked = d.branch;
    branchPr(d).then(r => { if (m.isConnected && d.branch === asked) { prRow = r; paint(); } });
  };
  const reload = (fresh) => {
    if (!m.isConnected || !fresh || !fresh.branches) return fresh;
    d = fresh;
    recent = recentBranches(d.root);
    if (sub) sub.textContent = `${gitRepoName(d.root)} · on ${d.branch}`;
    prRow = null;
    paint();
    showPr();
    return fresh;
  };

  list.onclick = e => {
    const more = e.target.closest('[data-more]');
    if (more) return branchActions(more, d, (d.branches || []).find(b => b.name === more.dataset.more), reload);
    const folder = e.target.closest('[data-folder]');
    if (folder) {
      const name = folder.dataset.folder;
      gitBranchFolders.has(name) ? gitBranchFolders.delete(name) : gitBranchFolders.add(name);
      return paint();
    }
    const row = e.target.closest('[data-branch]');
    if (row) {
      const b = (d.branches || []).find(x => x.name === row.dataset.branch);
      // Picking the branch already checked out is not a switch, it is "show me this repository".
      if (b && b.current) { m.remove(); return leeLeft('git'); }
      // `gitDo` re-throws what it has already reported. A refused checkout is a normal answer,
      // and the modal is still describing the branch that refused to be left.
      return switchBranch(d, row.dataset.branch).then(reload).catch(() => {});
    }
    const act = e.target.closest('[data-act]');
    if (act) {
      // Fetching comes before picking a branch, so it repaints the list rather than closing it.
      if (act.dataset.act === 'fetch') return branchAct('fetch').then(reload).catch(() => {});
      m.remove();
      return act.dataset.act === 'pr' ? prRow.run() : runBranchAction(act.dataset.act, d);
    }
  };
  search.oninput = () => paint(false);
  paint();
  showPr();
  setTimeout(() => search.focus(), 0);
}
window.leeBranchMenu = leeBranchMenu;

// `pull` is --ff-only, so a diverged branch had nowhere to go. Every way out, rehearsed.
async function showSyncPlan(d) {
  try {
    const p = await api(gitUrl('/git/sync-plan', {fetch: 1}));
    if (!p.upstream) return status(`${p.branch} has no upstream — publish it first`, 'err');
    if (!p.behind) return status(p.ahead ? `${p.ahead} ahead, nothing to pull` : 'already up to date', 'ok');
    const dirty = p.clean ? '' : `<div class="lee-git-merge-warning"><strong>Uncommitted changes to ${p.dirty.length} tracked file${p.dirty.length === 1 ? '' : 's'}</strong><span>${p.dirty.map(esc).join(' · ')}</span></div>`;
    // Only `merge` and `rebase` are rehearsed, so only they carry `conflicts`; none carries a name.
    const SYNC_LABEL = {'fast-forward': 'Fast-forward', merge: 'Merge', rebase: 'Rebase',
                        reset: 'Reset to the upstream'};
    const why = o => {
      const c = o.conflicts || [];
      return c.length
        ? `${c.length} file${c.length === 1 ? '' : 's'} conflict · ${c.slice(0, 4).map(esc).join(' · ')}${o.note ? ' · ' + esc(o.note) : ''}`
        : o.note ? esc(o.note) : 'nothing conflicts in the rehearsal';
    };
    const row = o => `<label class="lee-syncopt${o.available ? '' : ' off'}${o.destructive ? ' warn' : ''}">` +
      `<input type="radio" name="how" value="${o.op}"${o.op === p.recommended ? ' checked' : ''}${o.available ? '' : ' disabled'}>` +
      `<span><strong>${esc(SYNC_LABEL[o.op] || o.op)}</strong><span class="sub">${why(o)}</span></span></label>`;
    const m = modal(`<div class="lee-mhead">Sync ${esc(p.branch)}<span class="sub">${p.ahead} ahead · ${p.behind} behind ${esc(p.upstream)}</span></div>` +
      `<div class="lee-git-merge-preview"><header><strong>${p.relation === 'diverged' ? 'The branches have diverged' : 'Behind the upstream'}</strong>` +
      `<span>${p.ours.length} commit${p.ours.length === 1 ? '' : 's'} of yours · ${p.theirs.length} of theirs</span></header>${dirty}` +
      `<div class="lee-syncopts">${p.options.map(row).join('')}</div></div>` +
      `<div class="lee-mfoot"><button class="lee-btn go" data-sync>sync</button><button class="lee-btn" data-close>cancel</button></div>`);
    $('[data-close]', m).onclick = () => m.remove();
    $('[data-sync]', m).onclick = async () => {
      const how = $('input[name=how]:checked', m)?.value; if (!how) return;
      const o = p.options.find(x => x.op === how);
      if (o.destructive && !await confirmDialog(`discard ${p.branch}`, `${o.note || 'This moves the branch to ' + p.upstream}. There is no way back to these commits from the branch.`, 'discard')) return;
      m.remove();
      const next = await branchAct('sync', {how});
      if ((next.changes || []).some(x => x.conflicted)) showConflictCenter();
    };
  } catch (e) { leeFail('git', 'sync', e); }
}
window.showSyncPlan = showSyncPlan;

async function leeGitQuick(op) {
  const button = $(`#git${op}`);
  if (button) button.disabled = true;
  try {
    // An unpublished branch has nowhere to push to, and saying "nothing to push" would be the
    // wrong half of the truth.
    const publish = op === 'push' && !(gitUI.snapshot || await gitInfo(gitUrl('/git/info'))).upstream;
    await gitDo(op, op === 'push' ? {publish} : {});
    refreshScmIfOpen();
  } catch (_) { /* gitDo already logged it, showed the log, and said so in the status line */ }
  finally { if (button) button.disabled = false; }
}
window.leeGitQuick = leeGitQuick;

// Poll a clone job until it stops. The cap ends a wedged job as a sentence rather than a spinner
// nothing will ever stop.
async function cloneProgress(id, say) {
  for (let i = 0; i < 900; i++) {
    await new Promise(r => setTimeout(r, 900));
    const job = await api(`/git/clone/status?job=${encodeURIComponent(id)}`);
    if (job.error) throw new Error(job.error);
    if (!job.active) return job.result || {};
    if (job.current) say.textContent = job.current;
  }
  throw new Error('the clone is still running; the jobs panel has it');
}

async function leeCloneRepo() {
  const info = await api('/workspace/info').catch(() => ({}));
  // Beside the folders that are already open, not inside one: a clone under an open folder is
  // covered by it and can never become a chosen project of its own.
  const beside = ((info.roots || [])[0]?.path || '').split('/').slice(0, -1).join('/');
  const m = modal(
    `<div class="lee-mhead">clone repository<span class="sub">the clone becomes an open folder</span></div>` +
    `<label class="lee-fieldlabel">Repository<input class="lee-input" id="cloneurl" autocomplete="off"` +
    ` spellcheck="false" placeholder="owner/name  ·  https://…  ·  git@…"></label>` +
    `<label class="lee-fieldlabel">Into<input class="lee-input" id="cloneinto" autocomplete="off"` +
    ` spellcheck="false" value="${esc(beside)}" placeholder="a folder that already exists"></label>` +
    `<div class="lee-mfoot"><button class="lee-btn go" id="clonego">clone</button>` +
    `<span class="lee-dim" id="clonesay"></span></div>`);
  const say = m.querySelector('#clonesay'), go = m.querySelector('#clonego');
  const start = async () => {
    const url = m.querySelector('#cloneurl').value.trim();
    if (!url) return m.querySelector('#cloneurl').focus();
    go.disabled = true; say.textContent = 'starting…';
    try {
      const r = await post('/git/clone', {url, parent: m.querySelector('#cloneinto').value.trim()});
      say.textContent = `cloning into ${r.root}…`;
      const done = await cloneProgress(r.job.id, say);
      m.remove();
      // The same three steps the folder picker takes, so a clone arrives like an opened folder.
      await post('/fs/add-root', {path: done.root});
      await refreshFileTree(done.root);
      await activateRoot(done.root);
      status(`cloned ${done.name}`, 'ok');
    } catch (e) {
      if (e.body?.declined) return status(e.message);   // cloned, and the person kept the folder out of this window
      go.disabled = false; say.textContent = '';
      leeFail('git', 'clone', e);
    }
  };
  go.onclick = start;
  m.querySelector('#cloneurl').onkeydown = e => { if (e.key === 'Enter') { e.preventDefault(); start(); } };
  setTimeout(() => m.querySelector('#cloneurl').focus(), 0);
}
window.leeCloneRepo = leeCloneRepo;
