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

from ...core.web import fail
from .term import LazygitMissing, external_terminal_argv, lazygit_argv

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
                # With ids, so the client can avoid the ones already taken and reattach to a
                # session that outlived its page rather than silently inheriting it.
                'open': ctx.terms.states(),
                # The button is offered only when it can work; `argv[-1]` is the directory, so
                # `argv` also names which terminal is about to open.
                'external': (_external() or [])}

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
        """Hand the project to a real terminal application.

        xterm.js cannot be *connected* to one: an already-running terminal is itself an emulator
        with its own pty, and there is no way for a browser pane to adopt its window. What is
        possible is this -- launching it at the project directory, so the embedded terminal and
        the one you actually live in are both a click away rather than one pretending to be the
        other.

        Detached deliberately: this is a GUI application which will outlive the request, and
        holding it would tie its lifetime to a web handler.
        """
        argv = _external()
        if not argv:
            return fail('no external terminal found — set terminal.external in settings')
        import subprocess
        try:
            subprocess.Popen(argv, start_new_session=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as e:
            return fail(f'could not open {argv[0]} — {e}')
        return {'ok': True, 'argv': argv}
