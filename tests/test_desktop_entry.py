def test_the_frozen_entry_takes_the_shell_environment_the_window_was_denied():
    """`leela.cli` asks the login shell for the environment, and the bundle does not run it: py2app freezes `leela_app.py`."""
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1]/'leela_app.py').read_text()
    frozen = src[src.index("if getattr(sys, 'frozen'"):src.index('def free_port')]
    assert 'import_login_env' in frozen, 'the entry the bundle freezes asks for it too'
    assert 'use_extras' in frozen and 'use_login_path' in frozen, 'and still does what it did'
    assert "LEELA_SHELL_ENV" in frozen, 'and the same switch turns it off'

def test_leela_serves_on_5010_and_the_canvas_wires_to_the_same_port(monkeypatch):
    "`leela` with no `--port`, `serve_ide` and the canvas's component host name one port; the canvas once said 5001 whatever Leela served on."
    import inspect, leela, leela.app, leela.cli, leela.core.envs
    from leela.blocks.canvas.store import brick_host
    assert inspect.signature(leela.app.serve_ide).parameters['port'].default == 5010
    got = {}
    monkeypatch.setattr(leela.app, 'serve_ide', lambda roots, **kw: got.update(kw))
    monkeypatch.setattr(leela.core.envs, 'apply_stored_env', lambda: None)
    monkeypatch.setattr(leela, 'use_extras', lambda: None)
    monkeypatch.delenv('LEELA_SHELL_ENV', raising=False)
    monkeypatch.delenv('BRICK_HOST', raising=False)
    leela.cli.main([])
    assert got['port'] == 5010
    assert brick_host() == 'http://127.0.0.1:5010'

def test_desktop_port_ladder_starts_at_5010(monkeypatch):
    import leela_app as app
    assert list(app.PORTS) == list(range(5010, 5020))
    monkeypatch.setattr(app, 'is_port_free', lambda p, host: True)
    assert app.free_port() == 5010
    assert app.free_port(preferred=5030) == 5030
    monkeypatch.setattr(app, 'is_port_free', lambda p, host: p != 5010)
    assert app.free_port() == 5011
    monkeypatch.setattr(app, 'is_port_free', lambda p, host: False)
    monkeypatch.setattr(app, 'any_port', lambda host: 5040)
    assert app.free_port() == 5040
    monkeypatch.setattr(app, 'leela_on', lambda p, host: p == 5019)
    assert app.running_leela() == 5019

def _launch(monkeypatch, *, live=5010, argv=(), last=(), ok=True):
    "Run `leela_app.run` against stubs and return what it did. `last=None` keeps the real remembered session."
    import leela.desktop, leela_app as app
    got = dict(windows=[], served=0, remembered=[], opened=[])
    monkeypatch.setattr(leela.desktop, 'shell_ready', lambda: (ok, 'stub'))
    if last is not None: monkeypatch.setattr(leela.desktop, 'last_folder', lambda: list(last))
    monkeypatch.setattr(leela.desktop, 'remember', lambda f: got['remembered'].append(list(f)) or list(f))
    monkeypatch.setattr(leela.desktop, 'run_shell', lambda urls, titles=(), **kw: got['windows'].append((list(urls), list(titles), kw)))
    monkeypatch.setattr(leela.desktop, 'warm_cdp', lambda p: None)
    monkeypatch.setattr(app, 'running_leela', lambda *a, **k: live)
    monkeypatch.setattr(app, 'folders', lambda a=None, _v=list(argv): _v)
    monkeypatch.setattr(app, 'serve', lambda *a, **k: got.__setitem__('served', got['served'] + 1))
    monkeypatch.setattr(app, 'hub_open', lambda port, path, host='127.0.0.1', timeout=60:
                        got['opened'].append((port, str(path))) or dict(ok=True, id='proj', name='proj', url=f'http://proj.localhost:{port}/'))
    return got

BARE = 'http://127.0.0.1:5010/'

def test_attach_with_no_folder_opens_the_bare_loopback_window(monkeypatch):
    "`attach(port, [])` once printed 'opened none' and opened nothing."
    import leela_app as app
    got = _launch(monkeypatch)
    app.attach(5010, [])
    [(urls, titles, kw)] = got['windows']
    assert urls == [BARE] and titles == ['leela'] and kw['keys'] == [app.HOME_KEY]
    assert got['opened'] == [], 'no folder, so no hub route'

def test_a_no_folder_launch_attaches_to_a_running_leela_instead_of_serving(monkeypatch):
    "It once started a second server on the next port, with no workspace."
    import leela_app as app
    got = _launch(monkeypatch)
    app.run()
    assert got['served'] == 0
    assert [w[0] for w in got['windows']] == [[BARE]]
    assert got['remembered'] == [], 'remember([]) would have erased the saved open set'

def test_a_launch_whose_remembered_folder_was_deleted_attaches_the_same_way(monkeypatch, tmp_path):
    import leela.core.projects as projects, leela_app as app
    from fastcore.all import Path
    gone = tmp_path/'gone'; gone.mkdir()
    store = Path(tmp_path/'session.json')
    store.write_text(f'{{"folders": ["{gone}"], "recent": ["{gone}"]}}')
    monkeypatch.setattr(projects, 'SESSION', store)
    got = _launch(monkeypatch, last=None)
    gone.rmdir()
    app.run()
    assert got['served'] == 0 and got['remembered'] == []
    assert [w[0] for w in got['windows']] == [[BARE]]
    assert str(gone) in store.read_text(), 'the saved open set was kept'

def test_a_folder_launch_still_opens_through_the_hub_route(monkeypatch, tmp_path):
    import leela_app as app
    got = _launch(monkeypatch, argv=[str(tmp_path)])
    app.run()
    assert got['opened'] == [(5010, str(tmp_path))] and got['served'] == 0
    assert got['remembered'] == [[str(tmp_path)]]
    [(urls, titles, kw)] = got['windows']
    assert urls == ['http://proj.localhost:5010/'] and kw['keys'] == ['proj']

def test_the_bare_window_key_cannot_be_a_folders_slug():
    "`open_window` raises the window it finds under a key, so a folder named `leela` must not share the bare window's."
    import leela_app as app
    from leela.hub import workspace_slug
    assert workspace_slug('leela') == 'leela' != app.HOME_KEY
    assert workspace_slug(app.HOME_KEY) != app.HOME_KEY

def test_with_no_native_shell_a_launch_does_not_look_for_a_running_leela(monkeypatch):
    import leela_app as app
    got = _launch(monkeypatch, live=5010, ok=False)
    app.run()
    assert got['served'] == 1 and got['windows'] == []

def test_the_frozen_entry_seals_the_bundle_before_anything_else():
    "pyskills writes its `.pth` at import, so the seal has to come before any import that reaches it."
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1]/'leela_app.py').read_text()
    frozen = src[src.index("if getattr(sys, 'frozen'"):src.index('def free_port')]
    first = frozen.index('seal_bundle()')
    assert all(first < frozen.index(s) for s in ('leela.core.envs', 'use_extras()', 'use_login_path()', 'import_login_env()'))

def test_sealing_moves_the_cwd_out_puts_pyskills_on_the_path_and_stops_bytecode(monkeypatch, tmp_path):
    import os, sys, leela
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path/'data'))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, 'path', list(sys.path))
    monkeypatch.setattr(sys, 'dont_write_bytecode', False)
    assert leela.seal_bundle() == os.getcwd() == str((tmp_path/'data'/'leela').resolve())
    sk = tmp_path/'data'/'pyskills'
    assert sk.is_dir() and str(sk) in sys.path and sys.dont_write_bytecode
    leela.seal_bundle()
    assert sys.path.count(str(sk)) == 1, 'twice is harmless'

def test_sealing_falls_back_to_home_when_the_data_dir_cannot_be_made(monkeypatch, tmp_path):
    import os, sys, leela
    (tmp_path/'file').write_text('')
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path/'file'))
    monkeypatch.setenv('HOME', str(tmp_path))
    monkeypatch.chdir(tmp_path/'..')
    monkeypatch.setattr(sys, 'path', list(sys.path))
    monkeypatch.setattr(sys, 'dont_write_bytecode', sys.dont_write_bytecode)
    assert leela.seal_bundle() == str(tmp_path.resolve())

_SEALED = r'''
import os, site, sys
site.getsitepackages = lambda: [sys.argv[1]]
site.getusersitepackages = lambda: sys.argv[1]
import leela
assert 'pyskills' not in sys.modules, 'importing leela reaches pyskills'
if sys.argv[2] == 'seal': leela.seal_bundle()
import pyskills.core
assert pyskills.core.pyskills_dir() == leela.pyskills_home()
from fasthtml.common import FastHTML
FastHTML()
'''

def test_a_sealed_start_writes_no_pth_or_session_key_where_it_started(tmp_path):
    "The bundle's `Contents/Resources` is both the cwd py2app starts in and the site-packages pyskills writes to."
    import os, subprocess, sys
    def run(how):
        res, sp = tmp_path/how/'Resources', tmp_path/how/'site-packages'
        res.mkdir(parents=True); sp.mkdir()
        env = {**os.environ, 'XDG_DATA_HOME': str(tmp_path/how/'data')}
        subprocess.run([sys.executable, '-B', '-c', _SEALED, str(sp), how], cwd=res, env=env, check=True, timeout=120)
        return res, sp, tmp_path/how/'data'
    res, sp, _ = run('open')
    assert (res/'.sesskey').exists() and (sp/'pyskills.pth').exists(), 'unsealed, both land in the bundle'
    res, sp, data = run('seal')
    assert not list(res.iterdir()) and not list(sp.iterdir())
    assert (data/'leela'/'.sesskey').exists()

def test_a_kernel_started_from_the_bundle_inherits_the_pyskills_dir(monkeypatch, tmp_path):
    "A kernel on the bundle's interpreter imports pyskills too, and its `sys.path` is the app's."
    import sys, leela
    from kunda.spec import frozen_pythonpath
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, 'path', list(sys.path))
    monkeypatch.setattr(sys, 'dont_write_bytecode', sys.dont_write_bytecode)
    monkeypatch.setattr(sys, 'frozen', 'macosx_app', raising=False)
    leela.seal_bundle()
    assert str(tmp_path/'pyskills') in frozen_pythonpath().split(':')

def test_closing_the_shell_reaps_worker_processes_however_it_ends(monkeypatch):
    "A quit that returns from the window loop instead of through the Dock delegate still stops forked pools."
    import pytest, leela.desktop as d
    calls = []
    monkeypatch.setattr(d, 'quit_cleanly', lambda: calls.append('reaped'))
    monkeypatch.setattr(d, '_run_shell', lambda urls, titles, **kw: calls.append('shell'))
    d.run_shell(['http://127.0.0.1:1/'])
    assert calls == ['shell', 'reaped']
    def boom(*a, **k): raise RuntimeError('no window')
    monkeypatch.setattr(d, '_run_shell', boom)
    with pytest.raises(RuntimeError): d.run_shell(['http://127.0.0.1:1/'])
    assert calls[-1] == 'reaped'

def test_the_dock_delegate_reaps_and_runs_atexit_on_quit():
    "Cmd+Q is NSApp `terminate:`, whose C `exit()` skips Python's atexit and leaves forked pools alive."
    import pytest, sys
    if sys.platform != 'darwin': pytest.skip('Cocoa only')
    from kavacha.window import dock_delegates, quit_cleanly
    _, App = dock_delegates()
    assert 'applicationWillTerminate_' in App.__dict__

def test_the_shell_opens_on_the_saved_themes_background(monkeypatch):
    "Every launch route goes through `leela.desktop.run_shell`, so windows open on the theme, not kavacha's dark default."
    import leela.desktop as d
    from leela.blocks.settings.settings import Settings
    got = []
    monkeypatch.setattr(d, 'quit_cleanly', lambda: None)
    monkeypatch.setattr(d, '_run_shell', lambda urls, titles, **kw: got.append(kw.get('background')))
    Settings().save('user', 'appearance', {'theme': 'ember:light:relaxed'}, language='')
    try:
        d.run_shell(['http://127.0.0.1:1/'])
        d.run_shell(['http://127.0.0.1:1/'], background='#123456')
    finally: Settings().save('user', 'appearance', {'theme': ''}, language='')
    assert got == ['#efe6d6', '#123456']
