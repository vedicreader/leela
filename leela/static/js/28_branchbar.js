/* The branch pill as a real Git control, and the three remote gestures beside it.
 *
 * One popup over branches *and* actions, in the order JetBrains settled on: what to do with
 * the branch you are on, then how to get a different one, then the branches themselves. Names
 * containing a `/` fold into a folder by their first segment -- a checkout with forty
 * `cursor/…` branches is otherwise a wall of near-identical rows.
 *
 * Everything here posts to `/git/action`, which already knows checkout, fetch, pull, push,
 * create, merge, rebase and delete. The one new route is `/git/clone`, because a clone is
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
    // arrow-key walk over `.lee-mrow` never lands on a row nobody can see.
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
  // A remote-only branch is checked out by its leaf name; Git creates the tracking branch.
  const out = (await gitDo('checkout', {branch: b.remote ? branchLeaf(b) : name})).outcome || {};
  // A switch moves HEAD, so `summary` always says so -- and that buries the one sentence that
  // matters, which is what became of work the switch had to set aside. Say it instead.
  if (out.message) { leeLog('git', 'checkout', out.message, 'ok'); status(`git checkout · ${firstLine(out.message)}`, 'ok'); }
  return out;
}

function compareBranch(d, name) {
  Object.assign(gitUI, {tab: 'review', review: null, reviewBase: d.branch, reviewHead: name});
  leeLeft('git'); leeGitRefresh();
}

function branchActions(anchor, d, b) {
  if (!b) return;
  const leaf = branchLeaf(b);
  const rows = [
    {label: `Checkout ${leaf}`, disabled: b.current, run: () => switchBranch(d, b.name)},
    {label: 'New Branch from…', detail: b.name, run: async () => {
      const branch = await inputDialog('new branch', `Branch name, starting at ${b.name}`, '', 'feature/name');
      if (branch) gitDo('create', {branch, start: b.name});
    }},
    {separator: true},
    {label: 'Compare with current', detail: `${d.branch} … ${leaf}`, disabled: b.current, run: () => compareBranch(d, b.name)},
    // Through the previews, as the git panel's identical entries go.
    {label: `Rebase ${d.branch} onto ${leaf}`, disabled: b.current, run: () => showRebasePreview(b.name, d, branchAct)},
    {label: `Merge ${leaf} into ${d.branch}`, disabled: b.current, run: () => showMergePreview(b.name, d, branchAct)},
  ];
  if (!b.remote && !b.current) rows.push({separator: true}, {label: `Delete ${leaf}`, warn: true, run: async () => {
    if (await confirmDialog('delete branch', `Delete ${b.name}? Commits only on it are lost.`, 'delete'))
      gitDo('delete', {branch: b.name, force: !b.merged});
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
    run: () => window.open(pr.url, '_blank')};
}

function branchTopActions(d) {
  const changed = (d.changes || []).length;
  return [
    {id: 'update', label: 'Update Project', detail: d.behind ? `${d.behind} behind ${d.upstream}` : 'pull, autostashing local work'},
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
  try { d = await api(gitUrl('/git/info')); }
  catch (e) { return leeFail('git', 'branches', e); }
  const recent = recentBranches(d.root);
  let search = null;
  const m = modal(
    `<div class="lee-mhead">Git Branches<span class="sub">${esc(gitRepoName(d.root))} · on ${esc(d.branch)}</span></div>` +
    `<input class="lee-input" id="branchsearch" autocomplete="off" spellcheck="false"` +
    ` placeholder="Search branches and actions…" aria-label="search branches and actions">` +
    `<div class="lee-modallist lee-branchlist" id="branchlist"></div>` +
    `<div class="lee-mfoot"><span class="lee-dim">Enter checks out · ••• compares, rebases and merges</span></div>`,
    // The arrow keys walk the rows, which takes the caret out of the box; a printable key puts
    // it back, so searching never needs the mouse to come back first.
    e => { if (e.key.length === 1 && !e.ctrlKey && !e.metaKey && document.activeElement !== search) search.focus(); },
    null, {className: 'lee-branchmodal', storageKey: 'branches'});
  search = m.querySelector('#branchsearch');
  const list = m.querySelector('#branchlist');

  let prRow = null;
  const paint = () => {
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
  };

  list.onclick = e => {
    const more = e.target.closest('[data-more]');
    if (more) return branchActions(more, d, (d.branches || []).find(b => b.name === more.dataset.more));
    const folder = e.target.closest('[data-folder]');
    if (folder) {
      const name = folder.dataset.folder;
      gitBranchFolders.has(name) ? gitBranchFolders.delete(name) : gitBranchFolders.add(name);
      return paint();
    }
    const row = e.target.closest('[data-branch]');
    if (row) { m.remove(); return switchBranch(d, row.dataset.branch); }
    const act = e.target.closest('[data-act]');
    if (act) { m.remove(); return act.dataset.act === 'pr' ? prRow.run() : runBranchAction(act.dataset.act, d); }
  };
  search.oninput = paint;
  paint();
  branchPr(d).then(r => { prRow = r; paint(); });
  setTimeout(() => search.focus(), 0);
}
window.leeBranchMenu = leeBranchMenu;

/* ------------------------------------------------------------------ diverged */
// `pull` is --ff-only, so a diverged branch had nowhere to go. Every way out, rehearsed.
async function showSyncPlan(d) {
  try {
    const p = await api(gitUrl('/git/sync-plan', {fetch: 1}));
    if (!p.upstream) return status(`${p.branch} has no upstream — publish it first`, 'err');
    if (!p.behind) return status(p.ahead ? `${p.ahead} ahead, nothing to pull` : 'already up to date', 'ok');
    const dirty = p.clean ? '' : `<div class="lee-git-merge-warning"><strong>Uncommitted changes to ${p.dirty.length} tracked file${p.dirty.length === 1 ? '' : 's'}</strong><span>${p.dirty.map(esc).join(' · ')}</span></div>`;
    const why = o => o.conflicts.length
      ? `${o.conflicts.length} file${o.conflicts.length === 1 ? '' : 's'} conflict · ${o.conflicts.slice(0, 4).map(esc).join(' · ')}${o.note ? ' · ' + esc(o.note) : ''}`
      : o.note ? esc(o.note) : 'nothing conflicts in the rehearsal';
    const row = o => `<label class="lee-syncopt${o.available ? '' : ' off'}${o.destructive ? ' warn' : ''}">` +
      `<input type="radio" name="how" value="${o.op}"${o.op === p.recommended ? ' checked' : ''}${o.available ? '' : ' disabled'}>` +
      `<span><strong>${esc(o.label)}</strong><span class="sub">${why(o)}</span></span></label>`;
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

/* ------------------------------------------------------------ fetch/pull/push */
async function leeGitQuick(op) {
  const button = $(`#git${op}`);
  if (button) button.disabled = true;
  try {
    // Push is the one that needs to know where it stands: an unpublished branch has nowhere
    // to push to, and saying "nothing to push" would be the wrong half of the truth.
    const publish = op === 'push' && !(gitUI.snapshot || await api(gitUrl('/git/info'))).upstream;
    await gitDo(op, op === 'push' ? {publish} : {});
    refreshScmIfOpen();
  } catch (_) { /* gitDo already logged it, showed the log, and said so in the status line */ }
  finally { if (button) button.disabled = false; }
}
window.leeGitQuick = leeGitQuick;

/* ------------------------------------------------------------------- cloning */
// Poll a clone job until it stops. The cap is there so a wedged job ends as a sentence rather
// than a spinner nothing will ever stop.
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
  // Beside the folders that are already open, not inside one: a clone that lands *under* an
  // open folder is covered by it and can never become a chosen project of its own.
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
      // The same three steps the folder picker takes, so a clone lands where an opened folder
      // lands: added, drawn in the tree, and chosen as the project.
      await post('/fs/add-root', {path: done.root});
      await refreshFileTree(done.root);
      await activateRoot(done.root);
      status(`cloned ${done.name}`, 'ok');
    } catch (e) {
      go.disabled = false; say.textContent = '';
      leeFail('git', 'clone', e);
    }
  };
  go.onclick = start;
  m.querySelector('#cloneurl').onkeydown = e => { if (e.key === 'Enter') { e.preventDefault(); start(); } };
  setTimeout(() => m.querySelector('#cloneurl').focus(), 0);
}
window.leeCloneRepo = leeCloneRepo;
