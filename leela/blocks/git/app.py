"Git, as one mutation per request and one refreshed snapshot back."

from __future__ import annotations

import asyncio
from pathlib import Path

from ...core.web import fail, off_loop
from ramabana.git import GitError, clone, clone_target, repo_root
from .git import GitRepo
from .repos import RepoSet, clone_url, find_repos, repo_for

__all__ = ['CAPS', 'connect', 'git_paths']

CAPS = ('fs', 'jobs')

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
    def repos(): return RepoSet(ctx.fs.roots)
    def repo_at(target=''):
        "The repository a request names, else the chosen folder's, else the open file's."
        return GitRepo.at(repo_for(ctx.session, target))
    @rt('/git/info')
    async def git_info(repo: str = ''):
        "Answers `repo: False` rather than a 400, since being outside a repository is a normal answer."
        try:
            target = repo_for(ctx.session, repo)
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
                r = repo_at(d.get('repo') or '')
                outcome = _apply(r, str(d.get('op') or ''), d)
                snapshot = r.info()
                return snapshot | {'outcome': outcome} if isinstance(outcome, dict) else snapshot
            return await off_loop(act)
        except Exception as e: return fail(e)
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
        try: return await off_loop(repo_at(repo).conflict_plan)
        except Exception as e: return fail(e)
    @rt('/git/conflict')
    async def git_conflict(path: str = '', repo: str = ''):
        try: return await off_loop(repo_at(repo).conflict_versions, git_paths([path])[0])
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
            return await off_loop(repo_at(repo).review_file, base, head, git_paths([path])[0], mode, context)
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
                outcome = _apply(repository, op, payload)
                snapshot = repository.info()
                return snapshot | {'outcome': outcome} if isinstance(outcome, dict) else snapshot
            return await off_loop(act)
        except Exception as e: return fail(e)
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
