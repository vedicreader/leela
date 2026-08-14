"""Terminals: where a new shell starts, and who is allowed to open one.

`term_cwd` is module level because the pty websocket is registered when the app is created,
before any block connects, and needs the same answer.
"""

from __future__ import annotations

from ...core.web import fail
from .term import LazygitMissing, external_terminal_argv, lazygit_argv

__all__ = ['CAPS', 'connect', 'term_cwd']

CAPS = ('terms', 'fs', 'gate')


def term_cwd(session, ref=None):
    "Where a new terminal starts. Ergonomics, not confinement: a shell can `cd` anywhere."
    if ref:
        try: return session.fs._check(ref, must_exist=True)
        except Exception: pass
    return session.cwd_for() or (session.fs.roots[0] if session.fs.roots else None)


def connect(app, ctx):
    rt = app.route

    @rt('/term/info')
    def term_info():
        """What the client needs to open a terminal, including the token.

        The token goes out over this same-origin route and nowhere else: websockets are exempt
        from the same-origin policy, so reaching the socket must not be enough to get a pty.
        """
        try:
            lazygit_argv()
            git, git_why = True, ''
        except LazygitMissing as e: git, git_why = False, str(e)
        gate = ctx.gate
        return dict(enabled=gate.enabled, why=gate.why, token=gate.token if gate.enabled else '',
            cwd=str(term_cwd(ctx.session) or ''), lazygit=git, lazygit_why=git_why,
            open=ctx.terms.states(),      # with ids, so the client can avoid taken ones and reattach
            external=_external() or [])   # `argv[-1]` is the directory, so argv also names the terminal

    @rt('/term/close')
    def term_close(id: str = 'shell'):
        ctx.terms.close(id)
        return {'ok': True}

    def _external():
        "The configured external terminal, or the first installed one -- `None` if neither."
        from ..settings.settings import Settings
        try: configured = Settings(ctx.session.project_root).effective().get('terminal', {}).get('external', '')
        except Exception: configured = ''
        return external_terminal_argv(term_cwd(ctx.session), configured)

    @rt('/term/external')
    def term_external():
        "Launch a real terminal application at the project directory, detached so it outlives the request."
        argv = _external()
        if not argv: return fail('no external terminal found — set terminal.external in settings')
        import subprocess
        try: subprocess.Popen(argv, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as e: return fail(f'could not open {argv[0]} — {e}')
        return {'ok': True, 'argv': argv}
