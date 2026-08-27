import asyncio
import threading

import pytest

import leela.cli

leela_app = pytest.importorskip('leela_app')

def test_desktop_entry_runs_inline_without_an_event_loop(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(leela.cli, 'main', lambda args: calls.append(args))
    monkeypatch.setattr(leela_app, 'free_port', lambda preferred=5001: 5123)
    monkeypatch.setattr(leela_app.sys, 'argv', ['leela_app.py', str(tmp_path)])
    assert leela_app.main() is None
    assert calls[0][:5] == ['--app', '--port', '5123', '--gateway-port', '0']

def test_running_desktop_entry_from_a_kernel_uses_a_background_thread(monkeypatch, tmp_path):
    called = threading.Event()
    monkeypatch.setattr(leela.cli, 'main', lambda args: called.set())
    monkeypatch.setattr(leela_app, 'free_port', lambda preferred=5001: 5124)
    monkeypatch.setattr(leela_app.sys, 'argv', ['leela_app.py', str(tmp_path)])
    async def run():
        thread = leela_app.main()
        assert isinstance(thread, threading.Thread) and thread.daemon
        await asyncio.to_thread(thread.join, 2)
    asyncio.run(run())
    assert called.is_set()

def test_the_frozen_entry_takes_the_shell_environment_the_window_was_denied():
    """`leela.cli` asks the login shell for the environment, and the bundle does not run it: py2app
    freezes `leela_app.py`. So the app kept launchd's environment, `OPENAI_API_KEY` was not in it,
    and every hosted model refused the turn with `Missing API key`."""
    from pathlib import Path
    src = (Path(__file__).resolve().parents[1]/'leela_app.py').read_text()
    frozen = src[src.index("if getattr(sys, 'frozen'"):src.index('def free_port')]
    assert 'import_login_env' in frozen, 'the entry the bundle freezes asks for it too'
    assert 'use_extras' in frozen and 'use_login_path' in frozen, 'and still does what it did'
    assert "LEELA_SHELL_ENV" in frozen, 'and the same switch turns it off'
