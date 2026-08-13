"""Shipping a release: nbdev's four commands, as four steps.

`Pipeline` does the running, the terminal and the halting; what is here is the knowledge that
an nbdev project ships one way and a plain one another. The values the last two steps need come
from dockeasy through `leela.core.envs`.
"""

from __future__ import annotations

from fastcore.all import Path

from .pipelines import Pipeline, PipelineError, Step

__all__ = ['Release', 'ReleaseError', 'Step', 'RELEASE_FILE', 'nbdev_project', 'default_steps',
           'NBDEV_STEPS', 'PLAIN_STEPS']

RELEASE_FILE = '.leela/release.json'
ReleaseError = PipelineError


def nbdev_project(root):
    "Is this an nbdev project? `settings.ini` for nbdev 2, `[tool.nbdev]` in `pyproject.toml` for nbdev 3."
    root = Path(root)
    try:
        text = (root/'settings.ini').read_text(encoding='utf-8', errors='replace')
        if '[DEFAULT]' in text and any(k in text for k in ('nbs_path', 'lib_name', 'doc_path')):
            return True
    except OSError: pass
    try:
        import tomllib
        with open(root/'pyproject.toml', 'rb') as f: data = tomllib.load(f)
    except (OSError, ValueError): return False
    return 'nbdev' in (data.get('tool') or {}) or 'nbdev' in ((data.get('project') or {}).get('entry-points') or {})


NBDEV_STEPS = [
    Step('prepare', 'nbdev_prepare', 'nbdev_prepare',
        'Export the notebooks, run the tests, clean the metadata, rebuild the README.'),
    Step('bump', 'bump version', 'nbdev_bump_version',
        'Raise the version in settings.ini and commit it.'),
    Step('gh', 'GitHub release', 'nbdev_release_gh',
        'Tag the version and create the GitHub release from CHANGELOG.', ['GITHUB_TOKEN']),
    Step('pypi', 'PyPI release', 'nbdev_pypi',
        'Build the wheel and upload it to PyPI.', ['TWINE_USERNAME', 'TWINE_PASSWORD']),
]

PLAIN_STEPS = [
    Step('test', 'test', 'python -m pytest -q', 'Run the test suite before anything is published.'),
    Step('build', 'build', 'python -m build', 'Build the sdist and wheel into dist/.'),
    Step('gh', 'GitHub release', 'gh release create --generate-notes',
        'Tag and publish a GitHub release.', ['GITHUB_TOKEN']),
    Step('pypi', 'PyPI release', 'python -m twine upload dist/*',
        'Upload the built distributions to PyPI.', ['TWINE_USERNAME', 'TWINE_PASSWORD']),
]


def default_steps(root): return list(NBDEV_STEPS if nbdev_project(root) else PLAIN_STEPS)


class Release(Pipeline):
    "The release pipeline: nbdev's four commands where it is an nbdev project, else the plain four."

    FILE = RELEASE_FILE
    KIND = 'release'

    @staticmethod
    def defaults(root): return default_steps(root)

    def state(self): return super().state() | {'nbdev': nbdev_project(self.root)}
