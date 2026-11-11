"Build pipelines and releases: what ships, and the steps that ship it. pullup's, under `.leela/`."

from __future__ import annotations

from fastcore.basics import first
from fastcore.xtras import Path
from pullup.pipeline import Pipeline as _Pipeline, PipelineError, Release as _Release

from ..git.git import GitError, GitRepo, repo_root
from ..git.seam import invalidate
from ..runtime.kernels import NoVenv, python_project
from ..stack.packages import FAMILY

#: Only what Leela adds. Everything else pullup already publishes, and a caller that wants
#: `default_steps` or `resolve_script` imports it from `pullup` rather than through here.
__all__ = ['Pipeline', 'Release', 'PipelineError', 'ReleaseError', 'NotesError', 'STATE_DIR', 'RELEASE_FILE', 'step_python']

#: Where Leela keeps what it writes into somebody's project.
STATE_DIR = '.leela'
RELEASE_FILE = f'{STATE_DIR}/release.json'
ReleaseError = PipelineError

def step_python(session, root, need=True):
    "The interpreter a step in `root` runs on; `need` refuses a Python project with no pyproject.toml and no venv."
    #: With pyproject.toml the steps are pullup's `uv run`/`uv build`, and uv makes .venv when one needs it.
    root = Path(root)
    if need and python_project(root) and not (root/'pyproject.toml').exists() and (proj := session.missing_venv(root)) is not None:
        raise NoVenv(proj, f'No pyproject.toml and no Python environment in {proj.name}.')
    return session.user_python(root, need=False)

class NotesError(PipelineError):
    "A release-notes failure, worded for the person who sees it."
    def __init__(self, said): super().__init__(said); self.said = said

class _Leela:
    "What a pipeline of Leela's adds: where its plan lives, a terminal type for its steps, and whose stack it blames."
    def __init__(self, root, python=None, env=None): super().__init__(root, python, env, STATE_DIR)
    def _env(self):
        env = super()._env()
        if env.get('TERM') in (None, '', 'dumb'): env['TERM'] = 'xterm-256color'
        return env
    def blame(self, checkouts=()): return super().blame(checkouts, FAMILY)

class Pipeline(_Leela, _Pipeline): pass
class Release(_Leela, _Release):
    def save_notes(self, text):
        "Write the notes the waiting step needs and commit CHANGELOG.md by path; returns the id of the step to run."
        from pullup.pipeline import changelog_state, write_changelog
        if self.active: raise NotesError(f'{self.active} is still running.')
        row = first(r for r in self.state()['steps'] if r['status'] == 'needs_notes')
        if row is None: raise NotesError('No step is waiting for release notes.')
        text = str(text or '').strip()
        if not text: raise NotesError('Write the release notes first.')
        st = changelog_state(self.root)
        if not st['version']: raise NotesError(f'Leela cannot read the version of {self.root.name}, so it cannot name the notes. Set the version, then press continue.')
        if st['has']: return row['id']
        path = write_changelog(self.root, st['version'], text)
        try:
            top = repo_root(self.root)
            if top is None: raise GitError(f'{self.root.name} is not in a git repository')
            repo = GitRepo(top); repo.stage([path])
            try: repo.run('commit', '-m', f"Release notes for {st['version']}", '--', str(path))
            finally: invalidate(top)
        except GitError as e:
            raise NotesError(f'The notes are saved in CHANGELOG.md, but git did not commit them: {str(e).strip()[-400:]} Fix this, then press continue.') from e
        return row['id']
