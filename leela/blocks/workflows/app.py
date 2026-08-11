"""GitHub Actions as a panel: the files, the graph, the runs, and the values they need.

Every route here is a thin call into `leela.workflows`, which is itself a thin call into
gheasy and dockeasy. That layering is the point -- the panel must not know how a token is
resolved, how `owner/repo` is parsed, or which of a project's keys is a secret, because
gheasy already decides all three and a second opinion is a bug waiting to happen.

Two boundaries. `repo` is the same one the source-control panel uses: an absolute path from
the browser, resolved only against repositories the workspace already lists. And nothing
here reaches GitHub unless it was asked to -- `/workflows` reads local files and reports
whether the remote half is usable, so opening the panel never spends a rate-limited call or
fails because someone is offline.

Every GitHub call is network-bound and every generated workflow shells out to git, so all of
them go through `off_loop`.
"""

from __future__ import annotations

from ...core.web import fail, off_loop
from ...envs import EnvStore
from ...releases import Release
from ...repos import repo_for
from ...workflows import WorkflowError, Workflows

__all__ = ['CAPS', 'connect']

CAPS = ('fs',)


def connect(app, ctx):
    rt = app.route

    def flows(target=''): return Workflows(repo_for(ctx.session, target))

    def env_keys(root):
        """The keys this panel lists: gheasy's schema plus whatever the release steps need.

        The store is dockeasy's and shared across projects, so the panel never enumerates
        it. What a project declares is the only thing worth showing, and the release
        pipeline's `needs` is the other half of that declaration.
        """
        return Release(root).needs()

    @rt('/workflows')
    def workflows_info(repo: str = ''):
        "The local half, always, plus whether the GitHub half can be used and why not."
        try:
            wf = flows(repo)
            return {'root': str(wf.root), 'dir': str(wf.dir), 'status': wf.status(),
                    'workflows': wf.parsed(), 'config': wf.config(), 'schema': wf.schema()}
        except Exception as e: return fail(e)

    @rt('/workflows/catalogue')
    async def workflows_catalogue(repo: str = ''):
        """What this project is, and which workflows suit it.

        dockeasy answers the first question and gheasy builds every answer to the second;
        what is decided here is only which of them to mark as recommended, which is the part
        neither library can know -- it needs the project, not the packaging.
        """
        try: return await off_loop(flows(repo).catalogue)
        except Exception as e: return fail(e)

    @rt('/workflows/presets')
    def workflows_presets():
        """The builder's vocabulary: triggers and job presets, with their options.

        Data rather than markup, so the panel renders a form from it and a preset gained in
        `leela.wfbuild` appears in the browser without a line of frontend. It is also the
        teaching surface -- the form is the list of decisions a workflow actually has.
        """
        from ...wfbuild import preset_rows
        return preset_rows()

    @rt('/workflows/spec')
    def workflows_spec(repo: str = '', file: str = ''):
        "The spec a built workflow came from, and whether the file has been edited since."
        try: return flows(repo).spec(str(file)) or {'spec': None, 'stale': False}
        except Exception as e: return fail(e)

    @rt('/workflows/docker')
    async def workflows_docker(repo: str = ''):
        "What dockeasy would build here -- the thing a docker job in the workflow builds."
        try: return await off_loop(flows(repo).docker)
        except Exception as e: return fail(e)

    @rt('/workflows/runs')
    async def workflows_runs(repo: str = '', workflow: str = '', limit: int = 20):
        try: return {'runs': await off_loop(flows(repo).runs, limit, workflow)}
        except Exception as e: return fail(e)

    @rt('/workflows/jobs')
    async def workflows_jobs(repo: str = '', id: int = 0):
        try:
            if not id: raise WorkflowError('choose a run')
            return {'jobs': await off_loop(flows(repo).run_jobs, id)}
        except Exception as e: return fail(e)

    @rt('/workflows/action')
    async def workflows_action(req):
        """One explicit thing, and the refreshed local view with it.

        `generate` and `write` are separate on purpose: seeing the workflow gheasy would
        produce is not the same as agreeing to have it written into the repository.
        """
        d = await req.json()
        op = str(d.get('op') or '')
        try:
            wf = flows(d.get('repo') or '')
            if op == 'dispatch':
                out = await off_loop(wf.dispatch, d.get('workflow') or '', d.get('ref') or '',
                                     d.get('inputs') or {})
            elif op == 'cancel': out = await off_loop(wf.cancel, d.get('id') or 0)
            elif op == 'preview': out = {'yaml': await off_loop(wf.preview, d.get('workflow') or '')}
            elif op == 'add': out = await off_loop(wf.add, d.get('workflow') or '', d.get('file') or '')
            elif op == 'build': out = {'yaml': await off_loop(wf.build, d.get('spec') or {})}
            elif op == 'write_spec':
                out = await off_loop(wf.write_spec, d.get('spec') or {}, d.get('file') or '')
            elif op == 'generate': out = {'yaml': await off_loop(wf.generate)}
            elif op == 'write': out = await off_loop(wf.write_generated)
            elif op == 'dockerfile': out = await off_loop(wf.write_dockerfile)
            elif op == 'refresh': out = {}
            else: raise WorkflowError(f'unknown workflow action: {op}')
            return out | {'workflows': wf.parsed(), 'status': wf.status()}
        except Exception as e: return fail(e)

    @rt('/workflows/env')
    async def workflows_env(repo: str = '', remote: bool = False):
        """What each declared key is, and whether it is set -- never what a secret is set to.

        `remote` is opt-in because it is a GitHub call: the panel opens on the local answer
        and asks for the other one when someone wants to compare.
        """
        try:
            wf = flows(repo)
            schema = wf.schema()
            rows = EnvStore().entries(schema, env_keys(wf.root))
            out = {'entries': rows, 'schema': schema, 'status': wf.status()}
            if remote: out['remote'] = await off_loop(wf.remote_env)
            return out
        except Exception as e: return fail(e)

    @rt('/workflows/env/action')
    async def workflows_env_action(req):
        """Set a value, remove it, or send declared ones to GitHub.

        Pushing goes through gheasy's `gh_push_env`, so the same schema that decides a key
        is a secret here decides it there, and an undeclared key is skipped rather than
        guessed at.
        """
        d = await req.json()
        op, key = str(d.get('op') or ''), str(d.get('key') or '')
        try:
            wf = flows(d.get('repo') or '')
            store = EnvStore()
            if op == 'set': out = store.set(key, d.get('value') or '', bool(d.get('secret', True)))
            elif op == 'unset': out = store.unset(key)
            elif op == 'push':
                keys = [str(k) for k in (d.get('keys') or ())] or list(wf.schema())
                values = store.values(keys)
                out = {'results': await off_loop(wf.push_env, values, keys, bool(d.get('dry_run')))}
            else: raise WorkflowError(f'unknown environment action: {op}')
            return out | {'entries': store.entries(wf.schema(), env_keys(wf.root))}
        except Exception as e: return fail(e)
