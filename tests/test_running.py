"""Tests for running a *file* -- the thing leela could not do until now.

A notebook runs its cells, and a `.py` tab used to be a one-cell notebook, so "run" on a
script meant "run the whole thing as a cell": no `__main__`, no `sys.argv`, and a
traceback that pointed at `<ipython-input-3>`. `run_file_src` is the fix, and what it has
to get right is a short list -- so it is tested by running its output in a plain dict,
which is exactly what a kernel's user namespace is.
"""

import sys

import pytest

from leela.blocks.runtime.kernels import find_pythons, run_file_src
from leela.workspace import Workspace


def _run(src_code):
    "Exec generated code the way a kernel would: one namespace, used as globals and locals."
    ns = {'__name__': '__main__'}
    exec(src_code, ns)
    return ns


def test_what_the_script_defines_stays_in_the_namespace(tmp_path):
    """The whole reason this runs in the kernel rather than in a subprocess.

    `runpy.run_path` and `python file.py` both give the script its own globals, and the
    variable panel would have nothing to show when it finished.
    """
    p = tmp_path / 'thing.py'
    p.write_text('x = 41\ndef bump(v): return v + 1\ny = bump(x)\n')
    ns = _run(run_file_src(p))
    assert ns['x'] == 41 and ns['y'] == 42 and callable(ns['bump'])


def test_it_runs_as_main_with_its_own_argv(tmp_path):
    "A script's `if __name__ == '__main__':` block has to run, and `sys.argv[0]` has to be the file."
    p = tmp_path / 'main.py'
    p.write_text('import sys\nran = False\nargv0 = sys.argv[0]\n'
                 "if __name__ == '__main__': ran = True\n")
    before = list(sys.argv)
    ns = _run(run_file_src(p))
    assert ns['ran'] is True
    assert ns['argv0'] == str(p)
    assert sys.argv == before, 'argv must be put back, whatever the script did with it'


def test_argv_is_restored_even_when_the_script_raises(tmp_path):
    p = tmp_path / 'boom.py'
    p.write_text('raise ValueError("nope")\n')
    before = list(sys.argv)
    with pytest.raises(ValueError): _run(run_file_src(p))
    assert sys.argv == before


def test_it_leaves_no_scaffolding_behind(tmp_path):
    "An IDE with a variable panel cannot litter the namespace it is showing you."
    p = tmp_path / 'quiet.py'
    p.write_text('a = 1\n')
    ns = _run(run_file_src(p))
    assert not [k for k in ns if k.startswith('_lee')]


def test_the_buffer_runs_rather_than_the_file_when_one_is_given(tmp_path):
    "Editing and then pressing run should run what is on the screen, not the last save."
    p = tmp_path / 'stale.py'
    p.write_text('v = "on disk"\n')
    ns = _run(run_file_src(p, src='v = "in the editor"\n'))
    assert ns['v'] == 'in the editor'


def test_the_traceback_points_at_the_file(tmp_path):
    "Compiled under the path, so an error in a script is locatable in the script."
    p = tmp_path / 'bad.py'
    p.write_text('def f():\n    return 1/0\nf()\n')
    with pytest.raises(ZeroDivisionError) as e: _run(run_file_src(p))
    assert str(p) in str(e.traceback[-1].path)


# ---- what the frontends ask the workspace for ------------------------------
def test_run_file_code_refuses_what_it_cannot_run(ws):
    "Each refusal names the reason, because 'nothing happened' is the worst possible answer."
    assert ws.run_file_code()[0] is None                       # nothing open
    ws.open(str(ws.fs.roots[0] / 'dialog.ipynb'))
    code, why = ws.run_file_code()
    assert code is None and 'notebook' in why
    ws.open(str(ws.fs.roots[0] / 'sample.py'))
    code, label = ws.run_file_code()
    assert code and label == 'sample.py' and 'compile(' in code


def test_the_kernel_picker_offers_this_interpreter_first(ws):
    "Whatever else is on the machine, the interpreter leela is running under always works."
    pys = find_pythons(ws.fs.roots)
    assert pys and pys[0]['path'] == sys.executable
    assert len({p['path'] for p in pys}) == len(pys), 'the same interpreter must not be listed twice'


def test_kernel_options_says_what_is_running_and_what_could(ws):
    o = ws.kernel_options()
    assert {k['id'] for k in o['kinds']} == {'ipykernel', 'ipymini'}
    assert [k for k in o['kinds'] if k['current']] == [k for k in o['kinds'] if k['id'] == 'ipykernel']
    assert any(p['current'] for p in o['pythons'])
    # An option that is not installed stays on the list, carrying the reason: a picker that
    # hides it just makes the feature look like it does not exist.
    ipymini = next(k for k in o['kinds'] if k['id'] == 'ipymini')
    assert ipymini['available'] or ipymini['note']


def test_choosing_a_kernel_changes_what_the_next_one_starts_as(ws):
    "The pool's default is what a kernel is born with, so the picker writes there."
    ws.pool.choose(kernel='ipymini', python='/usr/bin/python3')
    assert ws.pool.default_kernel == 'ipymini' and ws.pool.default_python == '/usr/bin/python3'
    ws.pool.choose(python=None)
    assert ws.pool.default_python is None, 'None is a real choice: leela’s own interpreter'
    ws.pool.choose(kernel='nonsense')
    assert ws.pool.default_kernel == 'ipymini', 'an unknown launcher is ignored, not stored'
