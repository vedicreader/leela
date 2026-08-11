"""Driving dockeasy, vpseasy, cfeasy and gheasy a call at a time.

A block of its own, beside the deploy rather than inside it. The two are alternatives --
`deploy.py` run as three subcommands, or the same work as six library calls with six exit
codes -- and keeping them apart is what makes them comparable: same runner, same terminal,
same attribution on a failure, different driver.

`/drive/ws` is the same socket the other pipelines use, registered here because the pipeline
this one shows lives in this closure. `core.web.pipeline_socket` is the one implementation.
"""

from __future__ import annotations

from ...core.web import fail, off_loop, pipeline_socket
from .drive import Drive, DriveError
from ...core.envs import EnvStore
from ..git.repos import RepoSet, repo_for

__all__ = ['CAPS', 'connect']

CAPS = ('fs', 'gate')


def connect(app, ctx):
    rt = app.route
    live = {}

    def drive(target=''):
        "The driver for one project, made once and kept -- a running step is a process."
        root = repo_for(ctx.session, target)
        key = str(root)
        if key not in live: live[key] = Drive(root, env=EnvStore())
        live[key].python = ctx.session.pool.default_python
        return live[key]

    def state(target=''):
        d = drive(target)
        out = d.state()
        if out.get('failed'):
            try: out['blame'] = d.blame([str(r) for r in RepoSet(ctx.fs.roots).paths()])
            except Exception: out['blame'] = {}
        return out

    @rt('/drive')
    def drive_info(repo: str = ''):
        "Every part, its rendered snippet, and where the last run of it got to."
        try: return state(repo)
        except Exception as e: return fail(e)

    @rt('/drive/action')
    async def drive_action(req):
        """Run one part, or the lot. `step` with `auto` off is the normal move here.

        The point of this panel is a single library call at a time, so unlike the deploy the
        default is *not* to carry on into the next one -- you ran `tunnel` to find out about
        the tunnel.
        """
        d = await req.json()
        op, target = str(d.get('op') or ''), d.get('repo') or ''
        try:
            p = drive(target)
            if op == 'step': await p.start(d.get('step') or '', False)
            elif op == 'start': await p.start(d.get('step') or '', True)
            elif op == 'stop': p.stop()
            elif op == 'skip': p.skip(d.get('step') or '')
            elif op == 'reset': p.reset()
            elif op == 'reset_plan':
                p.steps = p.defaults(p.root)
                p._rendered = ''
            else: raise DriveError(f'unknown drive action: {op}')
            return state(target)
        except Exception as e: return fail(e)

    @rt('/drive/tail')
    async def drive_tail(repo: str = '', lines: int = 80):
        try: return {'text': await off_loop(drive(repo).tail, lines)}
        except Exception as e: return fail(e)

    pipeline_socket(app, '/drive/ws', ctx.gate,
                    lambda hello: drive(hello.get('repo') or hello.get('cwd') or ''))
