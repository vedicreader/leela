"Windows terminals: ConPTY through a fake `winpty`, WSL as the default shell."

import asyncio, queue, subprocess, sys, types
import pytest
from leela.blocks.term import term as T

class FakeProc:
    spawned = []
    def __init__(self, argv, cwd, env, dimensions):
        self.argv, self.cwd, self.dimensions, self.pid = argv, cwd, dimensions, 4242
        self.q, self.sent, self.up, self.status = queue.Queue(), [], True, None
    @classmethod
    def spawn(cls, argv, cwd=None, env=None, dimensions=(24, 80)):
        cls.spawned.append(p := cls(argv, cwd, env, dimensions))
        return p
    def read(self, n=1024):
        if (x := self.q.get()) is None: raise EOFError
        return x
    def write(self, s):
        self.sent.append(s)
        return len(s)
    def isalive(self): return self.up
    @property
    def exitstatus(self): return self.status
    def setwinsize(self, rows, cols):
        if not self.up: raise OSError('gone')
        self.dimensions = (rows, cols)
    def die(self, status=0): self.up, self.status = False, status; self.q.put(None)

@pytest.fixture
def win(monkeypatch):
    FakeProc.spawned.clear()
    monkeypatch.setattr(T, 'IS_WIN', True)
    monkeypatch.setattr(T, 'which_exe', lambda n, env=None: n)
    monkeypatch.setattr(T, '_taskkill', lambda pid: FakeProc.spawned[-1].die(1))
    monkeypatch.setitem(sys.modules, 'winpty', types.SimpleNamespace(PtyProcess=FakeProc))
    return FakeProc

def run(co): return asyncio.run(asyncio.wait_for(co, 10))

def test_default_shell_order(win, monkeypatch):
    monkeypatch.setenv('COMSPEC', 'C:/cmd.exe')
    have = {'wsl.exe', 'powershell.exe'}
    monkeypatch.setattr(T, 'which_exe', lambda n, env=None: n if n in have else None)
    assert T.default_shell() == 'wsl.exe'
    have.discard('wsl.exe')
    assert T.default_shell() == 'powershell.exe'
    have.clear()
    assert T.default_shell() == 'C:/cmd.exe'

def test_wsl_gets_no_login_flag(win):
    assert T.shell_argv('wsl.exe', login=True) == ['wsl.exe']
    assert T.shell_argv('wsl', ['-d', 'Ubuntu']) == ['wsl', '-d', 'Ubuntu']
    assert T.shell_argv('/bin/bash') == ['/bin/bash', '-l']

def test_wsl_starts_in_cwd_with_spaces(win):
    assert T.win_argv(['wsl.exe'], 'C:\\My Dir') == ['wsl.exe', '--cd', 'C:\\My Dir']
    assert T.win_argv(['wsl.exe', '--cd', '/x'], 'C:\\y') == ['wsl.exe', '--cd', '/x']
    assert T.win_argv(['powershell.exe'], 'C:\\y') == ['powershell.exe']

def test_no_path_prelude_on_windows(win): assert T.path_prelude('/x/bin/python') == ''

def test_external_template_keeps_backslashes(win):
    assert T.external_terminal_argv('C:\\x', 'C:\\Tools\\wt.exe -d {dir}') == ['C:\\Tools\\wt.exe', '-d', 'C:\\x']

def test_roundtrip_resize_exit(win):
    async def go():
        p = T.Pty(['wsl.exe'], cwd='C:\\x', env={}).start()
        fake = win.spawned[-1]
        assert fake.argv == ['wsl.exe', '--cd', 'C:\\x'] and fake.dimensions == (24, 80)
        frames = []
        task = asyncio.create_task(p.stream(frames.append))
        fake.q.put('h\u00e9llo')
        assert p.write(b'\xc3') == 1 and p.write(b'\xa9') == 1
        assert fake.sent == ['\u00e9']
        p.resize(100, 30)
        assert fake.dimensions == (30, 100)
        fake.die(3)
        await task
        assert b''.join(frames) == 'h\u00e9llo'.encode() and p.exit_note == '[exited 3]'
        p.sess.thread.join(2)
        assert not p.sess.thread.is_alive()
        assert p.write(b'x') == 0
        p.resize(10, 10)
    run(go())

def test_stream_ends_when_exit_status_is_unknown(win):
    async def go():
        p = T.Pty(['powershell.exe'], env={}).start()
        task = asyncio.create_task(p.stream(lambda d: None))
        win.spawned[-1].die(None)
        await task
        assert p.exit_note == '[exited -1]'
    run(go())

def test_kill_twice(win):
    async def go():
        p = T.Pty(['powershell.exe'], env={}).start()
        p.kill(.05); p.kill(.05)
        p.sess.thread.join(2)
        assert not p.alive and not p.sess.thread.is_alive()
    run(go())

def test_missing_pywinpty_is_toolmissing(win, monkeypatch):
    monkeypatch.setitem(sys.modules, 'winpty', None)
    async def go(): T.Pty(['wsl.exe'], env={}).start()
    with pytest.raises(T.ToolMissing, match='pywinpty'): run(go())

def test_term_module_imports_without_pty():
    code = "import sys; sys.modules.update(pty=None, termios=None); import leela.blocks.term.term as t; assert t.pty is None"
    subprocess.run([sys.executable, '-c', code], check=True)
