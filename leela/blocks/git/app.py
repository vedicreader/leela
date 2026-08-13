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

`repo` is the second boundary, and a different one. Every route here takes an optional
repository root so the panel can look at any checkout in the workspace rather than only the
active tab's, and that root is an absolute path from the browser — so it goes through
`RepoSet.require`, which answers only for repositories the workspace already discovered.
Omitting it keeps the original behaviour: the repository containing whatever is open.

Every call is a subprocess, so all of them go through `off_loop`.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from ...core.web import fail, off_loop
from .git import GitError, GitRepo
from .repos import RepoSet, find_repos, repo_for

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
                                                          d.get('choice') or '',
                                                          d.get('content')),
        'undo': lambda: repo.undo(str(d.get('token') or '')),
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

    def repos(): return RepoSet(ctx.fs.roots)

    def repo_at(target=''):
        """The repository a request names, else the chosen folder's, else the open file's.

        The chosen folder comes first because choosing it is the more recent and more
        deliberate statement of which project this is about -- and opening a file in another
        checkout re-chooses that one, so the two gestures cannot disagree for long.

        Deferring to `repo_for` rather than repeating its three steps is deliberate: every
        project panel has to answer this identically, and the one time these two spellings of
        it existed side by side they drifted -- source control followed the chosen folder and
        releases, deploys and drive stayed on the first one. The only difference left is the
        one that is real: this surface is about Git, so a folder that is not a checkout is an
        error here and merely unremarkable there.
        """
        return GitRepo.at(repo_for(ctx.session, target))

    @rt('/git/info')
    async def git_info(repo: str = ''):
        try: return await off_loop(lambda: repo_at(repo).info())
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
                r = repo_at(d.get('repo') or '')
                outcome = _apply(r, str(d.get('op') or ''), d)
                # Mutations that can leave the repository somewhere unexpected report what they
                # did; the snapshot alone cannot distinguish "squash staged your merge" from
                # "something dirtied your index". Ops that cannot surprise return nothing.
                snapshot = r.info()
                return snapshot | {'outcome': outcome} if isinstance(outcome, dict) else snapshot
            return await off_loop(act)
        except Exception as e: return fail(e)

    @rt('/git/find')
    async def git_find(base: str = '', q: str = '', limit: int = 60):
        """Repositories anywhere under `base`, so the open-folder dialog can be typed at.

        Separate from `/git/repos`, which reports the workspace. This one searches a folder
        you have not opened yet -- the directory of checkouts you keep everything in -- and is
        why it goes deep and takes a query.
        """
        try:
            found = await off_loop(find_repos, base or (ctx.fs.roots[0] if ctx.fs.roots else ''), q, limit)
            return {'base': str(base or ''), 'q': q,
                    'repos': [{'path': str(p), 'name': p.name, 'parent': str(p.parent)} for p in found]}
        except Exception as e: return fail(e)

    @rt('/git/repos')
    async def git_repos(expect: str = ''):
        """Every repository in the workspace as one row, and the workspace as a whole.

        The list is discovered per request from the open folders rather than held, so a
        folder opened, closed, or cloned into is reflected by the next refresh with nothing
        to invalidate. `expect` names the branch the workspace is supposed to be on; without
        it the branch most repositories already share is used, which is the answer in every
        workspace where one repository has been left behind.
        """
        try: return await off_loop(repos().overview, expect)
        except Exception as e: return fail(e)

    @rt('/git/repos/action')
    async def git_repos_action(req):
        """One operation across many repositories, answered per repository.

        Membership changes (`add`, `remove`) and `clone` return the refreshed overview along
        with their own result, for the same reason `/git/action` returns a snapshot: the
        browser renders this response directly.
        """
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

    @rt('/git/rebase-preview')
    async def git_rebase_preview(onto: str = '', repo: str = ''):
        try:
            if not onto: raise GitError('choose a branch to rebase')
            return await off_loop(repo_at(repo).rebase_preview, onto)
        except Exception as e: return fail(e)

    @rt('/git/blame')
    async def git_blame(path: str = '', start: int = 1, end: int = 0, repo: str = '',
                        cells: bool = True):
        """Who wrote these lines -- grouped into cells when the file is a notebook.

        A `.ipynb` blamed as text is a list of `"source": [` and escaped newlines, which is a
        result rather than an answer, so by default a notebook comes back as cells with their
        real source beside the attribution. `cells=false` asks for the raw file lines, which
        is the honest fallback when a notebook is in a shape the mapping cannot read.
        """
        try:
            clean = git_paths([path])[0]
            repository = repo_at(repo)
            if cells and clean.lower().endswith('.ipynb') and not end:
                return await off_loop(repository.blame_notebook, clean)
            rows = await off_loop(repository.blame, clean, start, end)
            return {'lines': rows, 'notebook': False, 'cells': [], 'path': clean,
                    'start': start, 'end': end}
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
        """The repository one file belongs to, whatever the panels are pointed at.

        Not `repo_at`: that answers "which project is this about", which the person chooses.
        A file's change marks are not a matter of opinion -- they come from the checkout the
        file is actually in, or there are none.
        """
        absolute = ctx.fs._check(path, must_exist=False)
        return GitRepo.at(absolute.parent), absolute

    @rt('/git/file')
    async def git_file(path: str = ''):
        "The active editor file's Git state, always in *its own* repository."
        try:
            r, absolute = repo_of(path)
            try: relative = str(absolute.relative_to(r.root))
            except ValueError: raise GitError('the active file is outside this repository')
            return await off_loop(r.file_changes, relative)
        except Exception as e: return fail(e)

    @rt('/git/notebook')
    async def git_notebook(path: str = ''):
        "The open notebook's changed cells, by cell id. Same repository rule as `/git/file`."
        try:
            r, absolute = repo_of(path)
            try: relative = str(absolute.relative_to(r.root))
            except ValueError: raise GitError('the active notebook is outside this repository')
            return await off_loop(r.notebook_changes, relative)
        except Exception as e: return fail(e)
