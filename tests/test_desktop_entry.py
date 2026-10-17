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
