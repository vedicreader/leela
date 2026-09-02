"""What Leela is allowed to reach for in the libraries it composes.

A private import is not reuse. It is a request for a seam the library has not opened, and it breaks
without warning on the next release because nothing promised it. Seven of them had accumulated:
`gheasy.repo._invalidate`, `_plural`, `_unborn` and `_run`, `gheasy.core._gh_api` and
`_resolve_gh_token`, and `gheasy.workflow._yaml_instance`. All seven are public names in gheasy now.

`fossick.cdp._debug_ready` is the one that is left, because fossick is not ours to widen. It is
named here so that adding another is a decision rather than an accident, and so that a fossick
release which drops it fails this suite rather than the inline browser.
"""
import ast
import re
from pathlib import Path

import pytest

LEELA = Path(__file__).resolve().parent.parent/'leela'

#: The packages Leela composes and must only reach through their public names.
COMPOSED = ('ramabana', 'shalya', 'gheasy', 'rishi', 'dhrishti', 'vishalakshi', 'litesearch',
            'koshas', 'kosha', 'fossick', 'exhash', 'mdhtml', 'ptymini', 'ipymini', 'rgapi')

#: The seam requests still outstanding, each with the library that would have to open it.
ALLOWED = {('fossick.cdp', '_debug_ready')}


def _private_imports():
    "Every `from <composed> import _name` in Leela's own sources, as `(module, name, where)`."
    out = []
    for path in sorted(LEELA.rglob('*.py')):
        try: tree = ast.parse(path.read_text(encoding='utf-8'))
        except SyntaxError: continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or not node.module: continue
            if node.module.split('.')[0] not in COMPOSED: continue
            for alias in node.names:
                if alias.name.startswith('_'):
                    out.append((node.module, alias.name, f'{path.relative_to(LEELA.parent)}:{node.lineno}'))
    return out


def test_leela_reaches_no_private_name_in_the_libraries_it_composes():
    unexpected = [row for row in _private_imports() if (row[0], row[1]) not in ALLOWED]
    assert unexpected == [], (
        'each of these is a request for a public name in the library that owns it, not a fix here:\n'
        + '\n'.join(f'  {where}: {mod}.{name}' for mod, name, where in unexpected))


def test_every_allowed_seam_request_is_still_being_made():
    "An entry nobody needs any more is stale, and a stale allowance hides the next one."
    made = {(mod, name) for mod, name, _ in _private_imports()}
    assert ALLOWED - made == set(), f'no longer imported, so drop from ALLOWED: {ALLOWED - made}'


def test_no_module_of_a_composed_library_is_reached_through_a_private_attribute():
    "`core._gh_api(...)` is the same request as importing it, written the other way."
    pattern = re.compile(r'\b(?:' + '|'.join(COMPOSED) + r')(?:\.\w+)*\.(_\w+)\s*\(')
    found = []
    for path in sorted(LEELA.rglob('*.py')):
        for n, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
            if m := pattern.search(line): found.append(f'{path.relative_to(LEELA.parent)}:{n}: {m.group(0)}')
    assert found == [], '\n'.join(found)


def test_every_gheasy_helper_leela_uses_resolves_to_something_callable():
    "Either spelling is the same function; neither is an ImportError in the git panel."
    from leela.blocks.git import seam
    for name in ('invalidate', 'plural', 'unborn', 'gh_api', 'gh_token', 'yaml_instance'):
        assert callable(getattr(seam, name, None)), f'the seam has no {name}'
    import gheasy.repo as repo
    assert callable(getattr(repo, 'gateway', None)), 'gateway has always been public'


def test_the_seam_prefers_the_public_name_wherever_gheasy_has_opened_one(monkeypatch):
    "The supported spelling on a new gheasy, the private one only until then."
    import gheasy.repo as repo
    from leela.blocks.git.seam import _opened
    monkeypatch.setattr(repo, 'invalidate', lambda *a: 'public', raising=False)
    assert _opened(repo, 'invalidate')() == 'public'
    monkeypatch.delattr(repo, 'invalidate', raising=False)
    assert _opened(repo, 'invalidate') is repo._invalidate, 'and falls back where it has not'
    with pytest.raises(ImportError): _opened(repo, 'no_such_helper')


def test_the_one_outstanding_request_is_still_answerable():
    "If fossick renames it, this fails here rather than in the browser panel."
    cdp = pytest.importorskip('fossick.cdp')
    assert callable(getattr(cdp, '_debug_ready', None))


def test_a_git_stage_is_read_through_the_gateway_rather_than_its_private_runner():
    "`gheasy.repo._run` is `gateway().run`, and the gateway is what serialises it per repository."
    from gheasy.repo import gateway
    src = (LEELA/'blocks'/'git'/'git.py').read_text()
    assert 'gateway().run(' in src
    assert callable(gateway().run)
