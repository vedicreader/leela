"Git, as one mutation per request and one refreshed snapshot back."

from __future__ import annotations

import asyncio
from pathlib import Path

from fastcore.all import first

from ...core.web import fail, off_loop
from ramabana.git import GitError, clone, clone_target, gateway, repo_root
from .git import GitRepo
from .repos import RepoSet, clone_url, find_repos, repo_for

__all__ = ['CAPS', 'connect', 'git_paths', 'Stale']

CAPS = ('fs', 'jobs', 'journal', 'docs')

#: Panes remembered per `(root, path)`, so a write can be checked against the text it was composed
#: from even when the browser does not send it back. Conflicts and merge reviews keep their own, so
#: reading one never refreshes the other's before-image.
PANES = 32

def _remember(seen, key, text):
    "Keep what one pane was built from, oldest out first."
    seen[key] = text
    while len(seen) > PANES: seen.pop(next(iter(seen)))

class Stale(GitError):
    "A write refused because the file moved under what the choice was made from."

def _failed(e):
    "The IDE's error shape for one Git route. `Stale` answers at 409, as `/refactor/apply` does."
    return fail(str(e), 409) if isinstance(e, Stale) else fail(e)

def _read(p):
    "The file as it is now, or None when it is not there. A before-image is never worth a failure."
    try: return Path(p).read_text(encoding='utf-8', errors='replace')
    except OSError: return None

def git_paths(values):
    "Pathspecs accepted from the browser, constrained to repository-relative files."
    out = []
    for value in values or ():
        p = Path(str(value))
        if p.is_absolute() or '..' in p.parts: raise GitError(f'invalid repository path: {value}')
        out.append(str(p))
    if not out: raise GitError('select at least one changed file')
    return out

def _dropped(repo, branch, force):
    """Delete a branch and report the commit it was at, which is the only handle for bringing it back.

    Git prints `Deleted branch x (was abc1234)` and the gateway returns None, so the sha never
    reached the panel. Read it first: after the delete there is no ref left to ask.
    """
    was = ''
    try: was = repo.run('rev-parse', '--short', branch).strip()
    except Exception: pass
    repo.delete(branch, force)
    return {'deleted': branch, 'was': was, 'recover': f'git branch {branch} {was}' if was else '',
            'summary': f'{branch} deleted, was at {was}' if was else f'{branch} deleted'}

def _dropped_stash(repo, ref):
    "Same for a stash: its own commit is what `git stash store` needs to put it back."
    was = ''
    try: was = repo.run('rev-parse', '--short', ref).strip()
    except Exception: pass
    repo.stash_drop(ref)
    return {'dropped': ref, 'was': was, 'recover': f'git stash store {was}' if was else '',
            'summary': f'{ref} dropped, was at {was}' if was else f'{ref} dropped'}

def _apply(repo, op, d):
    ops = {
        'stage': lambda: repo.stage(git_paths(d.get('paths'))),
        'unstage': lambda: repo.unstage(git_paths(d.get('paths'))),
        'discard': lambda: repo.discard(git_paths(d.get('paths'))),
        'ignore': lambda: repo.ignore(git_paths([d.get('path')])[0], bool(d.get('directory'))),
        'write_worktree': lambda: repo.write_worktree(git_paths([d.get('path')])[0], d.get('content') or ''),
        'resolve_conflict': lambda: repo.resolve_conflict(git_paths([d.get('path')])[0], d.get('choice') or '', d.get('content')),
        'resolve_safe_conflicts': lambda: repo.resolve_safe_conflicts(git_paths(d.get('paths')) if d.get('paths') else ()),
        'undo': lambda: repo.undo(str(d.get('token') or '')),
        'apply_patch': lambda: repo.apply_patch(d.get('patch') or '', bool(d.get('staged', True)), bool(d.get('reverse'))),
        'checkout': lambda: repo.checkout(d.get('branch') or ''),
        'create': lambda: repo.create(d.get('branch') or '', d.get('start') or 'HEAD'),
        'rename_branch': lambda: repo.rename_branch(d.get('branch') or '', d.get('name') or ''),
        'set_upstream': lambda: repo.set_upstream(d.get('branch') or '', d.get('upstream') or ''),
        'unset_upstream': lambda: repo.unset_upstream(d.get('branch') or ''),
        'delete': lambda: _dropped(repo, d.get('branch') or '', bool(d.get('force'))),
        'delete_remote': lambda: repo.delete_remote(d.get('remote') or 'origin', d.get('branch') or ''),
        'commit': lambda: repo.commit(d.get('message') or '', bool(d.get('amend'))),
        'fetch': lambda: repo.fetch(d.get('remote') or '', bool(d.get('prune', True))),
        'pull': lambda: repo.pull(),
        'sync': lambda: repo.sync(d.get('how') or 'rebase', d.get('upstream') or ''),
        'push': lambda: repo.push(bool(d.get('publish')), bool(d.get('force_with_lease'))),
        'stash': lambda: repo.stash(d.get('message') or ''),
        'stash_pop': lambda: repo.stash_pop(d.get('ref') or 'stash@{0}'),
        'stash_apply': lambda: repo.stash_apply(d.get('ref') or 'stash@{0}'),
        'stash_drop': lambda: _dropped_stash(repo, d.get('ref') or 'stash@{0}'),
        'merge': lambda: repo.merge(d.get('branch') or '', d.get('strategy') or 'merge'),
        'rebase': lambda: repo.rebase(d.get('branch') or ''),
        'cherry_pick': lambda: repo.cherry_pick(d.get('ref') or ''),
        'revert': lambda: repo.revert(d.get('ref') or ''),
        'reset': lambda: repo.reset(d.get('ref') or 'HEAD', d.get('mode') or 'mixed'),
        'abort_merge': lambda: repo.operation_action('abort'),
        'abort_rebase': lambda: repo.operation_action('abort'),
        'tag': lambda: repo.tag(d.get('name') or '', d.get('message') or '', d.get('ref') or 'HEAD'),
        'delete_tag': lambda: repo.delete_tag(d.get('name') or '', d.get('remote') or ''),
        'add_remote': lambda: repo.add_remote(d.get('name') or '', d.get('url') or ''),
        'set_remote': lambda: repo.set_remote(d.get('name') or '', d.get('url') or '', bool(d.get('push'))),
        'remove_remote': lambda: repo.remove_remote(d.get('name') or ''),
        'add_worktree': lambda: repo.add_worktree(d.get('path') or '', d.get('branch') or '', bool(d.get('create'))),
        'remove_worktree': lambda: repo.remove_worktree(d.get('path') or '', bool(d.get('force'))),
    }
    if op in ops: return ops[op]()
    if op.startswith('operation_'): return repo.operation_action(op.removeprefix('operation_'))
    raise GitError(f'unknown Git action: {op}')

def _sandboxed(ctx, repo):
    "Point this repository's worktree writes at the sandbox, and collect them for the journal."
    rows = []
    def save(target, text):
        target = Path(target).resolve()
        # A repository rooted above every open folder is normal: `.gitignore` then sits outside the
        # sandbox, and refusing the write would break an operation that works today.
        if not ctx.fs.covers(target): return target.write_text(text, encoding='utf-8')
        before = _read(target)
        mode = target.stat().st_mode if target.is_file() else None
        ctx.fs.write(target, text)
        # `atomic_save` renames a fresh file into place, which would drop the executable bit.
        if mode is not None: target.chmod(mode)
        rows.append((str(target), before, text))
    repo.saver = save
    return rows

def _dropped_files(ctx, repo):
    "Files a resolution takes away, moved aside whole so undo puts back exactly what was there."
    gone = []
    def drop(target):
        # Resolving the path itself would follow a conflicted symlink and take away the file it
        # points at, which is on nobody's side of the merge.
        target = Path(target).parent.resolve()/Path(target).name
        # Same rule as `_sandboxed`: a repository rooted above every open folder is normal, and the
        # trash is reached through the sandbox, so a file outside it can only be removed outright.
        if not ctx.fs.covers(target) or ctx.journal.trash is None: return target.unlink()
        gone.append((str(target), ctx.journal.trash.keep(target)))
    repo.dropper = drop
    return gone

def _rollback(ctx, repo, rows, gone, staged, entries):
    "Put back every file and index entry a half-done mutation already changed."
    for path, key in reversed(gone):
        try: ctx.journal.trash.restore(key, ctx.fs._check(path))
        except Exception: pass
    for path, before, _ in reversed(rows):
        try:
            if before is None: ctx.fs._check(path).unlink(missing_ok=True)
            else: ctx.fs.write(path, before)
        except Exception: pass
    # `resolve_safe_conflicts` writes and stages one file at a time, so a failure part-way through
    # has already collapsed earlier files' conflict stages to one settled blob.
    if staged:
        try: repo.restore_index(staged, entries)
        except Exception: pass

def _staged(repo):
    "Collect what one mutation stages, and the index entries it stages over."
    staged, entries = [], []
    def watch(paths):
        entries.extend(repo.index_entries(paths))
        staged.extend(p for p in paths if p not in staged)
    repo.stager = watch
    return staged, entries

def _sided(repo, rows):
    "What a whole-side checkout replaced. Git wrote the worktree itself, so this is read, not saved."
    took = {}
    def side(target, before, after, oid):
        if before == after: return
        # A binary side cannot be a journal row: the bodies are text, and one read back through
        # `errors='replace'` is not the file. Its stages are still in the index, so the row says so.
        if '\x00' in before or '\x00' in after: took.update(oid=oid)
        else: rows.append((str(target), before, after))
    repo.sider = side
    return took

def _unmerged(entries):
    "Whether these index entries hold a conflict's stages rather than one settled blob."
    return any(l.split('\t')[0].split(' ')[-1] != '0' for l in entries)

def _bytes_back(repo, took, entries, paths):
    "Put a binary side back out of the stages just restored, when they still hold what it replaced."
    at = first(l for l in entries if l.split('\t')[0].split(' ')[-1] == '2')
    if at and at.split(' ')[1] == took.get('oid'):
        repo._mutate('checkout', '--ours', '--', *paths)
        return ''
    return (f"{', '.join(paths)} is binary, so the journal has no copy of its previous bytes and the "
            'working file still holds the side you chose')

def _index_back(op, side):
    "The half of a Git row's reversal that the journal's text cannot carry: the index."
    paths, entries = list(op.get('staged') or ()), list(op.get('index') or ())
    if not (paths and op.get('root')): return ''
    repo, took = GitRepo.at(op['root']), op.get('side') or {}
    if side == 'after':
        if took and gateway().active_operation(repo.root):
            repo._mutate('checkout', f"--{took.get('choice')}", '--', *paths)
        repo.stage(paths); return ''
    # Putting a conflict's stages back once the merge is over would leave a repository nothing in
    # the IDE can finish. Unstaging is the most of it that still means anything.
    if _unmerged(entries) and not gateway().active_operation(repo.root):
        repo.unstage(paths)
        note = f"that merge is over, so {', '.join(paths)} was unstaged rather than made conflicted again"
        return note + (', and the working file still holds the side you chose' if took else '')
    repo.restore_index(paths, entries)
    return _bytes_back(repo, took, entries, paths) if took else ''

def _journalled(ctx, repo, op, run, choice=''):
    "Run one mutation with its worktree writes atomic, versioned and undoable."
    rows = _sandboxed(ctx, repo)
    staged, entries = _staged(repo)
    took = _sided(repo, rows)
    gone = _dropped_files(ctx, repo)
    try: outcome = run()
    except Exception:
        _rollback(ctx, repo, rows, gone, staged, entries); raise
    finally: repo.saver = repo.stager = repo.sider = repo.dropper = None
    for path, _, _ in rows + [(p, None, None) for p, _ in gone]:
        ctx.docs.forget(path)
        for tab in ctx.session.tabs:
            if tab.path == path: tab.dirty = False
    # A whole-side choice can change no text at all and still change the index, so `choice` keeps
    # the row: without one, undo has nothing to reach and the staging is the operation.
    if rows or gone or (choice and staged):
        extra = {'root': str(repo.root), 'staged': staged, 'index': entries,
                 'paths': [str(repo.root/p) for p in staged]}
        if took: extra['side'] = took | {'choice': choice}
        ctx.journal.record(f"Git {op.replace('_', ' ')}", rows, kind='git', extra=extra,
                           trashed=gone, hooked=not (rows or gone))
    return outcome

def _guard(ctx, repo, op, d, seen):
    "Refuse a write the browser composed against text the file no longer holds."
    # `worktree` is the one choice that overwrites nothing: it stages the file exactly as it is on
    # disk, so a disk that moved is the input rather than a hazard.
    if op == 'resolve_conflict' and str(d.get('choice') or '') == 'worktree': return
    path, before = git_paths([d.get('path')])[0], d.get('before')
    # The panes of a notebook hold decoded cell sources, not the file, so writing them back is loss.
    if op == 'write_worktree' and path.lower().endswith('.ipynb'):
        raise GitError(f'{path} is a notebook: edit its cells rather than its diff')
    built = 'the conflict panes' if op == 'resolve_conflict' else 'the diff panes'
    if before is None: before = seen.get((str(repo.root), path))
    if before is None:
        raise Stale(f'reopen {path}: Leela no longer holds the text {built} were built from')
    if repo._version(path, 'worktree') != before:
        raise Stale(f'files changed after {built} were built: {path}')
    _unsaved(ctx, repo, path)

def _unsaved(ctx, repo, path):
    "Refuse a write over a file an editor tab is holding unsaved edits to."
    target = str((repo.root/path).resolve())
    if any(t.path == target and t.dirty for t in ctx.session.tabs):
        raise Stale(f'unsaved open file: {path}')

def _guard_batch(ctx, repo, d, plans):
    """Refuse an automatic resolution of several files at once when any of them moved under the plan.

    The whole batch is checked before a single file is written, so a stale file refuses the batch
    rather than half-applying it: `resolve_safe_conflicts` writes and stages one file at a time, and
    `_rollback` puts back what it can rather than what it must.
    """
    held = plans.get(str(repo.root))
    if held is None:
        raise Stale('reopen the conflict list: Leela no longer holds the text it was built from')
    wanted = git_paths(d.get('paths')) if d.get('paths') else list(held)
    for path in wanted:
        if path not in held or repo._version(path, 'worktree') != held[path]:
            raise Stale(f'files changed after the conflict list was built: {path}')
        _unsaved(ctx, repo, path)
    # Naming them makes the batch exactly the files that were checked, rather than every file that
    # happens to be conflicted by the time Ramabana reads the plan again.
    d['paths'] = wanted

def _clone_into(fs, url, parent, name=''):
    "The directory a clone is written into, defaulting to the first open root."
    parent = str(parent or '').strip() or (str(fs.roots[0]) if fs.roots else '')
    if not parent: raise GitError('choose a folder to clone into')
    return clone_target(url, parent, name)

def connect(app, ctx):
    rt = app.route
    def run_clone(job, report):
        report(current=f'cloning {job.target}')
        root = clone(job.target, job.params.get('parent') or '', job.params.get('name') or '')
        return {'root': str(root), 'name': root.name}
    ctx.jobs.register('git_clone', run_clone)
    #: What the conflict centre's one-click button was built from: every conflicted file's text at
    #: the moment `/git/conflicts` served the plan, one entry per repository rather than per file, so
    #: a forty-file merge cannot evict its own before-images.
    panes, reviews, plans = {}, {}, {}
    def git_undo(op, side):
        "A Git row's own reversal. It reports what it could not do rather than failing the undo."
        try: op['note'] = _index_back(op, side)
        except Exception as e: op['note'] = f"the files are back, but Git's index is not: {e}"
    ctx.journal.hooks['git'] = git_undo
    def repos(): return RepoSet(ctx.fs.roots)
    def repo_at(target=''):
        "The repository a request names, else the chosen folder's, else the open file's."
        return GitRepo.at(repo_for(ctx.session, target))
    @rt('/git/info')
    async def git_info(repo: str = ''):
        "Answers `repo: False` rather than a 400, since being outside a repository is a normal answer."
        try:
            try: target = repo_for(ctx.session, repo)
            # No folder open is the same kind of answer as no repository: normal, and not the
            # client's failure to report. Raised, it reached the browser console as a problem.
            except GitError as e:
                if 'open a folder first' not in str(e): raise
                return {'ok': True, 'repo': False, 'root': '', 'note': 'no folder open'}
            if repo_root(target) is None:
                return {'ok': True, 'repo': False, 'root': '',
                        'note': f'{Path(target).name or target} is not inside a Git repository'}
            return dict(await off_loop(lambda: GitRepo.at(target).info()), repo=True)
        except Exception as e: return fail(e)
    @rt('/git/action')
    async def git_action(req):
        "Perform one explicit Git mutation and return the one refreshed snapshot."
        d = await req.json()
        try:
            def act():
                r, op = repo_at(d.get('repo') or ''), str(d.get('op') or '')
                if op in ('resolve_conflict', 'write_worktree'):
                    _guard(ctx, r, op, d, panes if op == 'resolve_conflict' else reviews)
                if op == 'resolve_safe_conflicts': _guard_batch(ctx, r, d, plans)
                outcome = _journalled(ctx, r, op, lambda: _apply(r, op, d),
                    str(d.get('choice') or '') if op == 'resolve_conflict' else '')
                # Every remembered file just changed, so the plan is spent rather than stale.
                if op == 'resolve_safe_conflicts': plans.pop(str(r.root), None)
                snapshot = r.info()
                return snapshot | {'outcome': outcome} if isinstance(outcome, dict) else snapshot
            return await off_loop(act)
        except Exception as e: return _failed(e)
    @rt('/git/find')
    async def git_find(base: str = '', q: str = '', limit: int = 60):
        "Repositories anywhere under `base`, so the open-folder dialog can be typed at."
        try:
            found = await off_loop(find_repos, base or (ctx.fs.roots[0] if ctx.fs.roots else ''), q, limit)
            return {'base': str(base or ''), 'q': q,
                'repos': [{'path': str(p), 'name': p.name, 'parent': str(p.parent)} for p in found]}
        except Exception as e: return fail(e)
    @rt('/git/repos')
    async def git_repos(expect: str = ''):
        "Every repository in the workspace as one row, and the workspace as a whole."
        try: return await off_loop(repos().overview, expect)
        except Exception as e: return fail(e)
    @rt('/git/repos/action')
    async def git_repos_action(req):
        "One operation across many repositories, answered per repository."
        d = await req.json()
        op, paths = str(d.get('op') or ''), [str(p) for p in (d.get('paths') or ())]
        try:
            def act():
                set_ = repos()
                if op == 'add': return {'added': str(set_.add(d.get('path') or '')), 'results': []}
                if op == 'remove': return {'removed': str(set_.remove(d.get('path') or '')), 'results': []}
                if op == 'clone': return {'results': set_.clone(d.get('urls') or (), d.get('into') or None)}
                return {'results': set_.run(op, paths)}
            outcome = await off_loop(act)
            return outcome | await off_loop(repos().overview, str(d.get('expect') or ''))
        except Exception as e: return fail(e)
    @rt('/git/clone')
    async def git_clone(req):
        "Start a clone into a folder. Returns at once; the browser watches `/git/clone/status`."
        d = await req.json()
        try:
            url = clone_url(d.get('url') or '')
            target = _clone_into(ctx.fs, url, str(d.get('parent') or ''), str(d.get('name') or ''))
            job = ctx.jobs.start('git_clone', url, parent=str(target.parent), name=target.name)
            return {'job': job.dict(), 'root': str(target)}
        except Exception as e: return fail(e)
    @rt('/git/clone/status')
    def git_clone_status(job: str = ''):
        "How a clone is going. JSON, because the branch popup polls it rather than a job card."
        try: return ctx.jobs.get(job).dict()
        except Exception as e: return fail(e)
    @rt('/git/history')
    async def git_history(limit: int = 100, skip: int = 0, query: str = '', ref: str = '--all',
        path: str = '', repo: str = ''):
        try:
            clean = git_paths([path])[0] if path else ''
            return {'commits': await off_loop(repo_at(repo).history, limit, skip, query, ref, clean)}
        except Exception as e: return fail(e)
    @rt('/git/reflog')
    async def git_reflog(limit: int = 100, repo: str = ''):
        try: return {'entries': await off_loop(repo_at(repo).reflog, limit)}
        except Exception as e: return fail(e)
    @rt('/git/conflicts')
    async def git_conflicts(repo: str = ''):
        try:
            def act():
                r = repo_at(repo)
                d = r.conflict_plan()
                _remember(plans, str(r.root), {f['path']: r._version(f['path'], 'worktree')
                                               for f in d['files']})
                return d
            return await off_loop(act)
        except Exception as e: return fail(e)
    @rt('/git/conflict')
    async def git_conflict(path: str = '', repo: str = ''):
        try:
            r, clean = repo_at(repo), git_paths([path])[0]
            d = await off_loop(r.conflict_versions, clean)
            _remember(panes, (str(r.root), clean), d['worktree'])
            return d
        except Exception as e: return fail(e)
    @rt('/git/commit')
    async def git_commit_detail(ref: str = 'HEAD', repo: str = ''):
        try: return await off_loop(repo_at(repo).commit_detail, ref)
        except Exception as e: return fail(e)
    @rt('/git/commit/review')
    async def git_commit_review(ref: str = 'HEAD', repo: str = ''):
        try: return await off_loop(repo_at(repo).commit_review, ref)
        except Exception as e: return fail(e)
    @rt('/git/commit/file')
    async def git_commit_file(ref: str = 'HEAD', path: str = '', context: int = 3, repo: str = ''):
        try: return await off_loop(repo_at(repo).commit_file, ref, git_paths([path])[0], context)
        except Exception as e: return fail(e)
    @rt('/git/compare')
    async def git_compare(left: str = 'HEAD', right: str = '', repo: str = ''):
        try:
            if not right: raise GitError('choose two refs to compare')
            return await off_loop(repo_at(repo).compare, left, right)
        except Exception as e: return fail(e)
    @rt('/git/review')
    async def git_review(base: str = 'HEAD', head: str = '', mode: str = 'review', repo: str = ''):
        try:
            if not head: raise GitError('choose a branch to review')
            return await off_loop(repo_at(repo).review, base, head, mode)
        except Exception as e: return fail(e)
    @rt('/git/review/file')
    async def git_review_file(base: str = 'HEAD', head: str = '', path: str = '',
        mode: str = 'review', context: int = 3, repo: str = ''):
        try:
            if not head: raise GitError('choose a branch to review')
            r, clean = repo_at(repo), git_paths([path])[0]
            d = await off_loop(r.review_file, base, head, clean, mode, context)
            if d['can_apply'] and not clean.lower().endswith('.ipynb'):
                d['worktree'] = r._version(clean, 'worktree')
                _remember(reviews, (str(r.root), clean), d['worktree'])
            return d
        except Exception as e: return fail(e)
    @rt('/git/merge-preview')
    async def git_merge_preview(incoming: str = '', repo: str = ''):
        try:
            if not incoming: raise GitError('choose a branch to merge')
            return await off_loop(repo_at(repo).merge_preview, incoming)
        except Exception as e: return fail(e)
    @rt('/git/pr')
    async def git_pr(repo: str = '', branch: str = ''):
        "The pull request this branch belongs to, or why there is nothing to say about it."
        from .hub import pr_context
        try:
            r = repo_at(repo)
            return await off_loop(pr_context, r.root, branch or r.run('branch', '--show-current').strip())
        except Exception as e: return fail(e)
    @rt('/git/sync-plan')
    async def git_sync_plan(repo: str = '', upstream: str = '', fetch: bool = False):
        "Where the branch stands against its upstream, and each way to reconcile. What the Sync dialog reads."
        try: return await off_loop(repo_at(repo).divergence, upstream, fetch)
        except Exception as e: return fail(e)
    @rt('/git/rebase-preview')
    async def git_rebase_preview(onto: str = '', repo: str = ''):
        try:
            if not onto: raise GitError('choose a branch to rebase')
            return await off_loop(repo_at(repo).rebase_preview, onto)
        except Exception as e: return fail(e)
    @rt('/git/blame')
    async def git_blame(path: str = '', start: int = 1, end: int = 0, repo: str = '', cells: bool = True):
        "Who wrote these lines, grouped into cells when the file is a notebook."
        try:
            clean = git_paths([path])[0]
            repository = repo_at(repo)
            if cells and clean.lower().endswith('.ipynb') and not end:
                return await off_loop(repository.blame_notebook, clean)
            rows = await off_loop(repository.blame, clean, start, end)
            return {'lines': rows, 'notebook': False, 'cells': [], 'path': clean, 'start': start, 'end': end}
        except Exception as e: return fail(e)
    @rt('/git/resources')
    async def git_resources(repo: str = ''):
        try:
            r = repo_at(repo)
            worktrees, submodules = await asyncio.gather(off_loop(r.worktrees), off_loop(r.submodules))
            return {'worktrees': worktrees, 'submodules': submodules}
        except Exception as e: return fail(e)
    @rt('/git/diff')
    async def git_diff(path: str = '', staged: bool = False, repo: str = ''):
        try:
            clean = git_paths([path])[0]
            view = await off_loop(lambda: repo_at(repo).diff_view(clean, staged))
            return {'path': path, 'staged': staged, **view}
        except Exception as e: return fail(e)
    def repo_of(path):
        "The repository one file belongs to, whatever the panels are pointed at."
        absolute = ctx.fs._check(path, must_exist=False)
        return GitRepo.at(absolute.parent), absolute
    def repo_relative(path, what):
        "That repository and the file's path inside it, refusing a file that is not in it."
        r, absolute = repo_of(path)
        try: return r, str(absolute.relative_to(r.root))
        except ValueError: raise GitError(f'the active {what} is outside this repository')
    @rt('/git/tree/action')
    async def git_tree_action(req):
        "One Git mutation for a tree path, resolved server-side to its repository-relative path."
        d = await req.json()
        try:
            def act():
                repository, relative = repo_relative(d.get('path') or '', 'tree path')
                op = str(d.get('op') or '')
                if op not in ('stage', 'unstage', 'discard', 'ignore'): raise GitError(f'unknown tree Git action: {op}')
                payload = {'paths': [relative], 'path': relative, 'directory': bool(d.get('directory'))}
                outcome = _journalled(ctx, repository, op, lambda: _apply(repository, op, payload))
                snapshot = repository.info()
                return snapshot | {'outcome': outcome} if isinstance(outcome, dict) else snapshot
            return await off_loop(act)
        except Exception as e: return _failed(e)
    @rt('/git/tree/prepare')
    async def git_tree_prepare(req):
        """Stage a folder the way a person who knows the language would.

        `git add` already honours `.gitignore`; a folder you just made does not have one, which is
        the whole difficulty. This writes the rules the folder's project kinds need -- and only the
        ones git says are missing -- and then stages, so `target/` and `__pycache__` never have to
        be noticed one at a time.
        """
        from .ignores import prepare
        d = await req.json()
        try:
            def act():
                repository, relative = repo_relative(d.get('path') or '', 'tree path')
                folder = Path(repository.root)/relative if relative else Path(repository.root)
                if not folder.is_dir(): raise GitError(f'{folder.name} is not a folder')
                rules = prepare(repository, folder, write=not d.get('dry_run'))
                staged = []
                if not d.get('dry_run'):
                    # The rules live inside the folder, so staging the folder carries them along.
                    paths = [relative or '.']
                    _journalled(ctx, repository, 'stage',
                                lambda: _apply(repository, 'stage', {'paths': paths}))
                    staged = paths
                return repository.info() | {'prepared': rules | {'staged': staged}}
            return await off_loop(act)
        except Exception as e: return _failed(e)
    @rt('/git/file')
    async def git_file(path: str = ''):
        "The active editor file's Git state, always in *its own* repository."
        try:
            r, relative = repo_relative(path, 'file')
            return await off_loop(r.file_changes, relative)
        except Exception as e: return fail(e)
    @rt('/git/notebook')
    async def git_notebook(path: str = ''):
        "The open notebook's changed cells, by cell id. Same repository rule as `/git/file`."
        try:
            r, relative = repo_relative(path, 'notebook')
            return await off_loop(r.notebook_changes, relative)
        except Exception as e: return fail(e)
