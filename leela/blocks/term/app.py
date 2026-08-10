"""Terminals: where a new shell starts, and who is allowed to open one.

`term_cwd` lives at module level rather than inside `connect` because the websocket that
carries the pty is registered when the app is *created*, before any block connects, and it
needs the same answer. One definition, imported by both, rather than two that can drift.

The token in `/term/info` is the security boundary. A websocket is not bound by the
same-origin policy, so any page the user visits can open a connection to `127.0.0.1` --
what it cannot do is *read* this response, which is same-origin. Handing the token out here
and nowhere else is what makes "can reach the socket" different from "may have a pty".
"""

from __future__ import annotations

from .term import LazygitMissing, lazygit_argv

__all__ = ['CAPS', 'connect', 'term_cwd']

CAPS = ('terms', 'fs', 'gate')


def term_cwd(session, ref=None):
    "Where a new terminal starts. Ergonomics, not confinement -- a shell can `cd` anywhere."
    if ref:
        try: return session.fs._check(ref, must_exist=True)
        except Exception: pass
    return session.cwd_for() or (session.fs.roots[0] if session.fs.roots else None)


def connect(app, ctx):
    rt = app.route

    @rt('/term/info')
    def term_info():
        """What the client needs to open a terminal, including the token.

        The token is handed out over this same-origin route and nowhere else. That is the
        whole point: a websocket is not bound by the same-origin policy, so any page the
        user visits can reach `127.0.0.1` -- only one that can *read* this response is the IDE.
        """
        try: lazygit_argv(); git, git_why = True, ''
        except LazygitMissing as e: git, git_why = False, str(e)
        gate = ctx.gate
        return {'enabled': gate.enabled, 'why': gate.why, 'token': gate.token if gate.enabled else '',
                'cwd': str(term_cwd(ctx.session) or ''), 'lazygit': git, 'lazygit_why': git_why,
                'open': [t.state() for t in ctx.terms.all()]}

    @rt('/term/close')
    def term_close(id: str = 'shell'):
        ctx.terms.close(id)
        return {'ok': True}
