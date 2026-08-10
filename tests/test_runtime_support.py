import subprocess

from leela.blocks.runtime import support as support


def completed(args, code=0, out='installed\n', err=''):
    return subprocess.CompletedProcess(args, code, out, err)


def test_project_python_probe_drops_frozen_app_redirection(monkeypatch):
    monkeypatch.setenv('PYTHONEXECUTABLE', '/Applications/Leela.app/Contents/MacOS/python')
    monkeypatch.setenv('__PYVENV_LAUNCHER__', '/Applications/Leela.app/Contents/MacOS/python')
    monkeypatch.setenv('PYTHONPATH', '/Applications/Leela.app/Contents/Resources/lib')
    seen = []
    def run(args, **kwargs):
        seen.append(kwargs['env'])
        return completed(args)
    monkeypatch.setattr(subprocess, 'run', run)
    state = support.kernel_support('/project/.venv/bin/python')
    assert state['ipykernel']['available'] and state['ipymini']['available']
    assert all('PYTHONEXECUTABLE' not in env and '__PYVENV_LAUNCHER__' not in env
               and 'PYTHONPATH' not in env for env in seen)


def test_install_prefers_uv_when_the_project_venv_has_no_pip(monkeypatch, tmp_path):
    python = tmp_path/'bin'/'python'; python.parent.mkdir(); python.write_text('')
    calls = []
    monkeypatch.setattr(support.shutil, 'which', lambda name: '/usr/local/bin/uv' if name == 'uv' else None)
    def run(args, timeout=180):
        calls.append(list(map(str, args)))
        return completed(args)
    monkeypatch.setattr(support, '_run', run)
    result = support.install_kernel_support(python)
    assert result['ok']
    assert calls[0][:5] == ['/usr/local/bin/uv', 'pip', 'install', '--python', str(python.absolute())]
    assert 'ipykernel>=7.3.0' in calls[0] and 'ipymini>=0.0.1' in calls[0]


def test_real_leela_environment_contains_both_kernel_launchers():
    state = support.kernel_support(__import__('sys').executable)
    assert state['ipykernel']['available'], state
    assert state['ipymini']['available'], state
