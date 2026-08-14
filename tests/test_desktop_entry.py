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
