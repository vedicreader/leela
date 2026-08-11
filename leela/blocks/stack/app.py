"""The stack under a deploy: the servers and tunnels it lands on, and the packages that run it.

Two views, one block, because they answer halves of the same question. When a deploy fails,
either the infrastructure is not what you thought -- no server, a tunnel from last month, a
record pointing somewhere else -- or one of your own packages raised. `Infra` reads the first
from Hetzner and Cloudflare through vpseasy and cfeasy; `packages` answers the second from
the pipeline's own transcript.

Nothing here is bulk and nothing is implicit. Every listing is a read, the two deletions name
exactly one thing each, and no route reaches a provider unless it was called -- opening the
panel costs one `status`, which is four `find_spec` calls and two lookups in dockeasy's store.
"""

from __future__ import annotations

from ...core.web import fail, off_loop
from ..pipelines.deploys import Deploy
from ...core.envs import EnvStore
from .infra import Infra, InfraError
from .packages import FAMILY, survey
from ..pipelines.releases import Release
from ..git.repos import RepoSet, repo_for

__all__ = ['CAPS', 'connect']

CAPS = ('fs',)

KINDS = {'release': Release, 'deploy': Deploy}


def connect(app, ctx):
    rt = app.route

    def infra(): return Infra(EnvStore())

    def checkouts():
        "Every repository this workspace has open -- where a fix would actually be made."
        return [str(p) for p in RepoSet(ctx.fs.roots).paths()]

    @rt('/stack')
    def stack_info(repo: str = ''):
        """The family: installed, which version, which copy runs, and whether it is yours.

        `shadowed` is the row worth the whole view -- a package checked out in this
        workspace but imported from site-packages means an edit here changes nothing there,
        which is a half-hour lost every time it goes unnoticed.
        """
        try:
            return {'packages': survey(FAMILY, checkouts()), 'checkouts': checkouts(),
                    'root': str(repo_for(ctx.session, repo))}
        except Exception as e: return fail(e)

    @rt('/infra')
    async def infra_info():
        "Servers, tunnels and zones at once, each half's failure kept to that half."
        try: return await off_loop(infra().overview)
        except Exception as e: return fail(e)

    @rt('/infra/records')
    async def infra_records(zone: str = ''):
        try: return {'records': await off_loop(infra().records, zone)}
        except Exception as e: return fail(e)

    @rt('/infra/action')
    async def infra_action(req):
        """The two destructive things, each naming exactly one target.

        There is deliberately no "delete everything unused": deciding what is unused is the
        judgement that goes wrong, and it goes wrong on infrastructure someone is serving
        from.
        """
        d = await req.json()
        op = str(d.get('op') or '')
        try:
            i = infra()
            if op == 'verify': return await off_loop(i.verify)
            if op == 'delete_tunnel': out = await off_loop(i.delete_tunnel, d.get('id') or '')
            elif op == 'delete_server': out = await off_loop(i.delete_server, d.get('name') or '')
            elif op == 'refresh': out = {}
            else: raise InfraError(f'unknown infrastructure action: {op}')
            return out | await off_loop(i.overview)
        except Exception as e: return fail(e)
