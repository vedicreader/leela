"""What Leela is allowed to reach for in the libraries it composes."""
import ast
import re
from pathlib import Path

import pytest

LEELA = Path(__file__).resolve().parent.parent/'leela'

#: The packages Leela composes and must only reach through their public names.
COMPOSED = ('ramabana', 'shalya', 'gheasy', 'rishi', 'dhrishti', 'vishalakshi', 'litesearch',
            'koshas', 'kosha', 'fossick', 'exhash', 'mdhtml', 'ptymini', 'ipymini', 'rgapi',
            'kunda', 'pullup')

#: The seam requests still outstanding, each with the library that would have to open it. Leela
#: cannot widen any of these from here, so each one is a decision recorded rather than an accident,
#: and a release that drops one fails this suite rather than the feature that needed it.
ALLOWED = {
    ('fossick.cdp', '_debug_ready'),        # fossick: the inline browser waits on CDP being up
    ('kunda.kernel', '_Inspector'),         # kunda: `runtime.runners.Runner` is one
    ('kunda.kernel', '_give_up_after'),     # kunda: the start deadline a pool admission uses
    ('kunda.pythons', '_venv_roots'),       # kunda: where to look for a project's environment
    ('kunda.spec', '_runtime_python'),      # kunda: the interpreter to spawn, right inside a bundle
    ('kunda.spec', '_spec'),                # kunda: a kernelspec built from Leela's own languages
    ('pullup.workflows', '_gheasy'),        # pullup: the gheasy core a new fastship workflow needs
}


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
    # gheasy 0.0.10 opened every helper the seam reaches for, so there is no private name left on
    # the installed one to fall back to. The fallback is what an older gheasy looks like.
    from types import ModuleType
    older = ModuleType('gheasy.repo')
    older._invalidate = lambda *a: 'private'
    assert _opened(older, 'invalidate')() == 'private', 'and falls back where it has not'
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


def test_the_configuration_leela_sets_in_a_library_takes():
    """`kunda.use_app` and `pullup.use_spec_dir` are module globals, which is the only seam either offers."""
    from kunda.pythons import app_name, env_name
    import leela.blocks.runtime.kernels                     # noqa: F401  the import that calls it
    assert app_name() == 'leela'
    assert env_name('MAX_KERNELS') == 'LEELA_MAX_KERNELS'
    from pullup.wfbuild import spec_dir
    from leela.blocks.workflows.workflows import SPEC_DIR
    import leela.blocks.workflows.workflows                 # noqa: F401
    assert spec_dir() == SPEC_DIR == '.leela/workflows'

def test_a_seam_module_re_exports_nothing_the_library_already_publishes():
    """A raw pass-through is not a seam."""
    import leela.blocks.pipelines.pipelines as pl
    import leela.blocks.drive.drive as dr
    assert set(pl.__all__) == {'Pipeline', 'Release', 'PipelineError', 'ReleaseError',
                               'STATE_DIR', 'RELEASE_FILE'}
    assert set(dr.__all__) == {'Drive', 'DriveError', 'DRIVE_FILE'}
    assert not (LEELA/'blocks'/'workflows'/'wfbuild.py').exists(), 'a pure pass-through module'
    for name in ('default_steps', 'resolve_script', 'uv_argv', 'APP_STEPS', 'env_value'):
        assert name not in pl.__all__, f'{name} is pullup\'s to publish'
    for name in ('PARTS', 'Part', 'context', 'parts'):
        assert name not in dr.__all__, f'{name} is pullup\'s to publish'

def test_the_support_seam_holds_only_what_leela_renames():
    """It re-exported almost the whole of kunda's support half while `leela/core/envs.py` went straight to kunda for three of the same names, so `clean_env` had two spellings depending on which module you were reading."""
    import leela.blocks.runtime.support as sup
    from kunda.support import HOST_PY
    assert sup.__all__ == ['LEELA_PY'] and sup.LEELA_PY is HOST_PY
    for gone in ('clean_env', 'work_dir', 'installable', 'INSPECTOR', 'kernel_support'):
        assert not hasattr(sup, gone), f'{gone} is kunda\'s to publish'

def test_nothing_reaches_kunda_support_through_two_doors():
    "One spelling per name: `from kunda...` everywhere, and the seam only for `LEELA_PY`."
    bad = []
    for path in sorted(LEELA.rglob('*.py')):
        for i, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
            m = re.match(r'\s*from \.{1,2}(?:runtime\.)?support import (.+)', line)
            if not m: continue
            names = {n.strip() for n in m.group(1).split('#')[0].split(',')}
            if names - {'LEELA_PY'}: bad.append(f'{path.relative_to(LEELA.parent)}:{i}: {line.strip()}')
    assert bad == [], 'these should import from kunda directly:\n  ' + '\n  '.join(bad)
