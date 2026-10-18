"""What Leela is allowed to reach for in the libraries it composes."""
import ast
from pathlib import Path

LEELA = Path(__file__).resolve().parent.parent/'leela'

#: The packages Leela composes and must only reach through their public names.
COMPOSED = ('ramabana', 'shalya', 'gheasy', 'rishi', 'dhrishti', 'vishalakshi', 'litesearch',
            'koshas', 'kosha', 'fossick', 'exhash', 'mdhtml', 'ipymini', 'rgapi',
            'kunda', 'pullup')

#: Leela modules that are another package under one of Leela's names, so a relative import
#: through them reaches a composed library without naming it.
ALIASES = ('agent.tools', 'agent')

#: The seam requests still outstanding, each with the library that would have to open it. Leela
#: cannot widen any of these from here, so each one is a decision recorded rather than an accident,
#: and a release that drops one fails this suite rather than the feature that needed it.
ALLOWED = {
    ('fossick.cdp', '_debug_ready'),        # fossick: the inline browser waits on CDP being up
    ('kunda.kernel', '_Inspector'),         # kunda: `runtime.runners.Runner` is one
    ('kunda.kernel', '_give_up_after'),     # kunda: the start deadline a pool admission uses
    ('kunda.pythons', '_venv_roots'),       # kunda: where to look for a project's environment
    ('kunda.spec', '_runtime_python'),      # kunda: the interpreter to spawn, right inside a bundle
    ('kunda.spec', '_frozen_pythonpath'),   # kunda: the paths a bundle's helper Python needs, for the terminal
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
            if node.module.split('.')[0] not in COMPOSED and node.module not in ALIASES: continue
            for alias in node.names:
                if alias.name.startswith('_'):
                    out.append((node.module, alias.name, f'{path.relative_to(LEELA.parent)}:{node.lineno}'))
    return out


def test_leela_reaches_no_private_name_in_the_libraries_it_composes():
    unexpected = [row for row in _private_imports() if (row[0], row[1]) not in ALLOWED]
    assert unexpected == [], (
        'each of these is a request for a public name in the library that owns it, not a fix here:\n'
        + '\n'.join(f'  {where}: {mod}.{name}' for mod, name, where in unexpected))


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


