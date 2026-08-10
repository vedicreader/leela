"""Git, as one mutation per request and one refreshed snapshot back.

`/git/action` is a single route with an `op` rather than thirty routes. That is not
laziness about URL design: the browser renders the response of a mutation *directly*, and a
route per operation would have each one followed by several duplicate status requests to
find out what changed. One op in, one `repo.info()` out, one render.

Destructive operations are confirmed by the client, and Git itself remains the final safety
check -- this layer does not try to second-guess `push --force-with-lease`.

`git_paths` is the security boundary. Everything a pathspec touches comes from the browser,
so absolute paths and `..` are refused outright rather than resolved; a repository-relative
path is the only shape that can reach Git. `/git/file` additionally converts an absolute
editor path through the sandbox and refuses anything outside the repository.

Every call is a subprocess, so all of them go through `off_loop`.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from ...core.web import fail, off_loop
from ...git import GitError, GitRepo

__all__ = ['CAPS', 'connect', 'git_paths']

CAPS = ('fs',)


def git_paths(values):
    "Pathspecs accepted from the browser, constrained to repository-relative files."
    out = []
    for value in values or ():
        p = Path(str(value))
        if p.is_absolute() or '..' in p.parts: raise GitError(f'invalid repository path: {value}')
        out.append(str(p))
    if not out: raise GitError('select at least one changed file')
    return out


# op name -> what it does to the repo. A table rather than an if/elif ladder so that adding
# an operation is one line, and so the set of known ops is inspectable (the client asks for
# nothing that is not in here).
def _apply(repo, op, d):
    ops = {
        'stage': lambda: repo.stage(git_paths(d.get('paths'))),
        'unstage': lambda: repo.unstage(git_paths(d.get('paths'))),
        'discard': lambda: repo.discard(git_paths(d.get('paths'))),
        'write_worktree': lambda: repo.write_worktree(git_paths([d.get('path')])[0], d.get('content') or ''),
        'resolve_conflict': lambda: repo.resolve_conflict(git_paths([d.get('path')])[0],
                                                          d.get('choice') or ''),
        'apply_patch': lambda: repo.apply_patch(d.get('patch') or '', bool(d.get('staged', True)),
                                                bool(d.get('reverse'))),
        'checkout': lambda: repo.checkout(d.get('branch') or ''),
        'create': lambda: repo.create(d.get('branch') or '', d.get('start') or 'HEAD'),
        'rename_branch': lambda: repo.rename_branch(d.get('branch') or '', d.get('name') or ''),
        'set_upstream': lambda: repo.set_upstream(d.get('branch') or '', d.get('upstream') or ''),
        'unset_upstream': lambda: repo.unset_upstream(d.get('branch') or ''),
        'delete': lambda: repo.delete(d.get('branch') or '', bool(d.get('force'))),
        'delete_remote': lambda: repo.delete_remote(d.get('remote') or 'origin', d.get('branch') or ''),
        'commit': lambda: repo.commit(d.get('message') or '', bool(d.get('amend'))),
        'fetch': lambda: repo.fetch(d.get('remote') or '', bool(d.get('prune', True))),
        'pull': lambda: repo.pull(),
        'push': lambda: repo.push(bool(d.get('publish')), bool(d.get('force_with_lease'))),
        'stash': lambda: repo.stash(d.get('message') or ''),
        'stash_pop': lambda: repo.stash_pop(d.get('ref') or 'stash@{0}'),
        'stash_apply': lambda: repo.stash_apply(d.get('ref') or 'stash@{0}'),
        'stash_drop': lambda: repo.stash_drop(d.get('ref') or 'stash@{0}'),
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
        'set_remote': lambda: repo.set_remote(d.get('name') or '', d.get('url') or '',
                                              bool(d.get('push'))),
        'remove_remote': lambda: repo.remove_remote(d.get('name') or ''),
        'add_worktree': lambda: repo.add_worktree(d.get('path') or '', d.get('branch') or '',
                                                  bool(d.get('create'))),
        'remove_worktree': lambda: repo.remove_worktree(d.get('path') or '', bool(d.get('force'))),
    }
    if op in ops: return ops[op]()
    # `operation_*` is a family rather than a fixed name: the client sends whatever the
    # in-progress operation offers (continue, skip, abort).
    if op.startswith('operation_'): return repo.operation_action(op.removeprefix('operation_'))
    raise GitError(f'unknown Git action: {op}')


def connect(app, ctx):
    rt = app.route

    def repo():
        cwd = ctx.session.cwd_for()
        if cwd is None: raise GitError('open a folder first')
        return GitRepo.at(cwd)

    @rt('/git/info')
    async def git_info():
        try: return await off_loop(lambda: repo().info())
        except Exception as e: return fail(e)

    @rt('/git/action')
    async def git_action(req):
        """Perform one explicit Git mutation and return the one refreshed snapshot.

        The browser renders this response directly; it must not follow each mutation with
        several duplicate status requests. Destructive operations remain confirmed by the
        client and Git itself remains the final safety check.
        """
        d = await req.json()
        try:
            def act():
                r = repo()
                _apply(r, str(d.get('op') or ''), d)
                return r.info()
            return await off_loop(act)
        except Exception as e: return fail(e)

    @rt('/git/history')
    async def git_history(limit: int = 100, skip: int = 0, query: str = '', ref: str = '--all', path: str = ''):
        try:
            clean = git_paths([path])[0] if path else ''
            return {'commits': await off_loop(repo().history, limit, skip, query, ref, clean)}
        except Exception as e: return fail(e)

    @rt('/git/reflog')
    async def git_reflog(limit: int = 100):
        try: return {'entries': await off_loop(repo().reflog, limit)}
        except Exception as e: return fail(e)

    @rt('/git/conflict')
    async def git_conflict(path: str = ''):
        try: return await off_loop(repo().conflict_versions, git_paths([path])[0])
        except Exception as e: return fail(e)

    @rt('/git/commit')
    async def git_commit_detail(ref: str = 'HEAD'):
        try: return await off_loop(repo().commit_detail, ref)
        except Exception as e: return fail(e)

    @rt('/git/commit/review')
    async def git_commit_review(ref: str = 'HEAD'):
        try: return await off_loop(repo().commit_review, ref)
        except Exception as e: return fail(e)

    @rt('/git/commit/file')
    async def git_commit_file(ref: str = 'HEAD', path: str = '', context: int = 3):
        try: return await off_loop(repo().commit_file, ref, git_paths([path])[0], context)
        except Exception as e: return fail(e)

    @rt('/git/compare')
    async def git_compare(left: str = 'HEAD', right: str = ''):
        try:
            if not right: raise GitError('choose two refs to compare')
            return await off_loop(repo().compare, left, right)
        except Exception as e: return fail(e)

    @rt('/git/review')
    async def git_review(base: str = 'HEAD', head: str = '', mode: str = 'review'):
        try:
            if not head: raise GitError('choose a branch to review')
            return await off_loop(repo().review, base, head, mode)
        except Exception as e: return fail(e)

    @rt('/git/review/file')
    async def git_review_file(base: str = 'HEAD', head: str = '', path: str = '',
                              mode: str = 'review', context: int = 3):
        try:
            if not head: raise GitError('choose a branch to review')
            return await off_loop(repo().review_file, base, head, git_paths([path])[0], mode, context)
        except Exception as e: return fail(e)

    @rt('/git/merge-preview')
    async def git_merge_preview(incoming: str = ''):
        try:
            if not incoming: raise GitError('choose a branch to merge')
            return await off_loop(repo().merge_preview, incoming)
        except Exception as e: return fail(e)

    @rt('/git/rebase-preview')
    async def git_rebase_preview(onto: str = ''):
        try:
            if not onto: raise GitError('choose a branch to rebase')
            return await off_loop(repo().rebase_preview, onto)
        except Exception as e: return fail(e)

    @rt('/git/blame')
    async def git_blame(path: str = '', start: int = 1, end: int = 0):
        try: return {'lines': await off_loop(repo().blame, git_paths([path])[0], start, end)}
        except Exception as e: return fail(e)

    @rt('/git/resources')
    async def git_resources():
        try:
            r = repo()
            worktrees, submodules = await asyncio.gather(off_loop(r.worktrees), off_loop(r.submodules))
            return {'worktrees': worktrees, 'submodules': submodules}
        except Exception as e: return fail(e)

    @rt('/git/diff')
    async def git_diff(path: str = '', staged: bool = False):
        try:
            clean = git_paths([path])[0]
            view = await off_loop(lambda: repo().diff_view(clean, staged))
            return {'path': path, 'staged': staged, **view}
        except Exception as e: return fail(e)

    @rt('/git/file')
    async def git_file(path: str = ''):
        try:
            r = repo()
            absolute = ctx.fs._check(path, must_exist=False)
            try: relative = str(absolute.relative_to(r.root))
            except ValueError: raise GitError('the active file is outside this repository')
            return await off_loop(r.file_changes, relative)
        except Exception as e: return fail(e)
