"Terminals: where a new shell starts, and who is allowed to open one."

from __future__ import annotations

from ...core.web import fail
from .term import LazygitMissing, external_terminal_argv, lazygit_argv

__all__ = ['CAPS', 'connect', 'term_cwd', 'term_project']

CAPS = ('terms', 'gate')

def term_cwd(session, ref=None):
    "Where a new terminal starts. Ergonomics, not confinement: a shell can `cd` anywhere."
    if ref:
        try: return session.fs._check(ref, must_exist=True)
        except Exception: pass
    return session.cwd_for() or (session.fs.roots[0] if session.fs.roots else None)

def term_project(session, cwd):
    "The checkout a terminal belongs to, from where it is. The walk the interpreter takes."
    from ...core.projects import project_dir
    if not cwd: return ''
    try: root = session.fs.root_of(cwd)
    except Exception: root = None
    return str(project_dir(cwd, root) or root or '')

def connect(app, ctx):
    rt = app.route
    @rt('/term/info')
    def term_info():
        "What the client needs to open a terminal, including the token."
        try:
            lazygit_argv()
            git, git_why = True, ''
        except LazygitMissing as e: git, git_why = False, str(e)
        gate = ctx.gate
        cwd = term_cwd(ctx.session)
        return dict(enabled=gate.enabled, why=gate.why, token=gate.token if gate.enabled else '',
            cwd=str(cwd or ''), project=term_project(ctx.session, cwd),
            lazygit=git, lazygit_why=git_why,
            open=[{**state, 'project': term_project(ctx.session, state.get('cwd'))}
                  for state in ctx.terms.states()],
            external=_external() or [])
    @rt('/term/close')
    def term_close(id: str = 'shell'):
        ctx.terms.close(id)
        return {'ok': True}
    def _external():
        "The configured external terminal, or the first installed one. `None` if neither."
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
        try: subprocess.Popen(argv, start_new_session=True, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as e: return fail(f'could not open {argv[0]} — {e}')
        return {'ok': True, 'argv': argv}
