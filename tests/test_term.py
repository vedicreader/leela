"What the agent reads back off a terminal."

import asyncio, os, signal, sys
from leela.blocks.term.term import MAX_FRAME, SCROLLBACK, Pty

async def _ready(p, marker):
    async with asyncio.timeout(10):
        while marker not in p.sess.read_from(0)[0]: await asyncio.sleep(.01)

def test_owned_terminal_resize_and_interrupt():
    src = r'''
import os, signal
signal.signal(signal.SIGINT, lambda *_: exit(23))
print('READY', os.getpid(), os.getpgrp(), os.tcgetpgrp(0), os.get_terminal_size(), flush=True)
while True: signal.pause()
'''
    async def run():
        p = Pty([sys.executable, '-u', '-c', src], cols=93, rows=37).start()
        try:
            await _ready(p, b'READY')
            assert p.pid == p.sess.pid
            assert f'READY {p.pid} {p.pid} {p.pid}'.encode() in p.sess.read_from(0)[0]
            assert b'columns=93, lines=37' in p.sess.read_from(0)[0]
            p.write(b'\x03')
            await asyncio.wait_for(p.stream(lambda b: None), 10)
            assert p.exit_code == 23
        finally:
            p.kill(0)
    asyncio.run(run())

def test_group_shutdown_after_parent_exit(tmp_path):
    ready = tmp_path/'worker'
    src = r'''
import os, signal, sys
from pathlib import Path
signal.signal(signal.SIGHUP, signal.SIG_IGN)
pid = os.fork()
if pid:
    print('PARENT', flush=True)
    while not Path(sys.argv[1]).exists(): pass
    os._exit(0)
signal.signal(signal.SIGTERM, signal.SIG_IGN)
Path(sys.argv[1]).write_text(str(os.getpid()))
while True: signal.pause()
'''
    async def run():
        from leela.core.inspectors import alive
        p = Pty([sys.executable, '-u', '-c', src, str(ready)]).start()
        worker = None
        try:
            async with asyncio.timeout(10):
                while not ready.exists() or p.alive: await asyncio.sleep(.01)
            worker = int(ready.read_text())
            assert alive(worker)
            p.kill(.05)
            p.kill(.05)
            async with asyncio.timeout(3):
                while alive(worker): await asyncio.sleep(.01)
        finally:
            if worker is not None:
                try: os.kill(worker, signal.SIGKILL)
                except ProcessLookupError: pass
            p.kill(0)
    asyncio.run(run())

def test_escalation_stays_with_the_original_session():
    src = r'''
import signal
signal.signal(signal.SIGTERM, lambda *_: exit(0))
print('READY', flush=True)
while True: signal.pause()
'''
    async def run():
        p = Pty([sys.executable, '-u', '-c', src]).start()
        try:
            await _ready(p, b'READY')
            old = p.sess
            p.kill(.2)
            async with asyncio.timeout(5):
                while p.alive: await asyncio.sleep(.01)
            p.start()
            await _ready(p, b'READY')
            await asyncio.sleep(.3)
            assert p.alive and p.sess is not old
            assert old.escalation is None
        finally:
            p.kill(0)
            await asyncio.wait_for(p.stream(lambda b: None), 5)
    asyncio.run(run())

def _held(raw):
    "A Pty holding `raw` as scrollback, with no child ever spawned."
    p = Pty()
    p.scrollback = bytearray(raw)
    return p

def test_a_transcript_reads_as_its_final_state_and_only_its_tail():
    p = _held(b'building\r\n  0%\r 50%\r100%\r\ndone\r\n')
    assert p.text() == 'building\n100%\ndone'
    p = _held(b'\x1b[32mPASS\x1b[0m tests\r\n')
    assert p.text() == 'PASS tests'
    p = _held(b'a\r\nb\r\nc\r\n')
    assert p.text(2) == 'b\nc'
    assert p.text() == 'a\nb\nc'

def test_killing_a_terminal_ends_its_stream_and_logs_nothing():
    "`kill` closed the pty fd under a live reader: `_pump` then read None and spun on the traceback."
    import asyncio
    async def run():
        problems = []
        asyncio.get_running_loop().set_exception_handler(lambda loop, ctx: problems.append(ctx))
        p = Pty(['sh', '-c', 'echo hi; sleep 30']).start()
        seen = bytearray()
        async def on_data(b): seen.extend(b)
        task = asyncio.create_task(p.stream(on_data))
        for _ in range(100):
            await asyncio.sleep(.02)
            if seen: break
        p.kill()
        await asyncio.wait_for(task, 5)
        await asyncio.sleep(.2)
        return bytes(seen), problems
    seen, problems = asyncio.run(run())
    assert b'hi' in seen
    assert problems == []


def test_a_burst_arrives_whole_in_few_frames_and_the_last_of_it_is_not_lost():
    """macOS returns 1024 bytes a read whatever is asked for, so `stream` called `on_data` once per kilobyte and the socket sent a frame each, which is what made the terminal crawl in the app."""
    import asyncio
    line, n = 'leela' * 4, 40000
    async def run():
        problems = []
        asyncio.get_running_loop().set_exception_handler(lambda loop, ctx: problems.append(ctx))
        p = Pty(['sh', '-c', f'yes {line} | head -{n}']).start()
        frames = []
        async def on_data(b):
            frames.append(b)
            await asyncio.sleep(.002)   # what sending a websocket frame costs, near enough
        await asyncio.wait_for(p.stream(on_data), 60)
        return frames, problems, bytes(p.scrollback)
    frames, problems, kept = asyncio.run(run())
    body = b''.join(frames)
    assert problems == [], problems
    assert body.count(line.encode()) == n, f'every line arrives once: {body.count(line.encode())} of {n}'
    assert max(len(f) for f in frames) <= MAX_FRAME, 'no frame is larger than the cap'
    # The point of the change: frames far larger than the kilobyte a read hands back, whenever the
    # consumer is the slow half. A consumer that keeps up gets small frames and pays nothing for them.
    assert len(frames) < len(body) / 1024, f'{len(frames)} frames for {len(body)} bytes'
    assert kept == body[-SCROLLBACK:], 'the scrollback is the same bytes, coalesced or not'


def test_a_child_that_writes_and_exits_at_once_still_delivers_what_it_wrote():
    "Data and end-of-output land in one batch here, which is the case that could drop the data."
    import asyncio
    async def run():
        p = Pty(['sh', '-c', "printf 'abcdef'; exit 0"]).start()
        seen = bytearray()
        async def on_data(b): seen.extend(b)
        await asyncio.wait_for(p.stream(on_data), 10)
        return bytes(seen)
    assert b'abcdef' in asyncio.run(run())

def test_a_second_stream_over_one_pty_is_refused_and_the_first_keeps_reading():
    """Two terminals keyed the same shared a pty, and `add_reader` handed the fd to whichever attached last: the older view stayed on screen and never printed another byte."""
    import asyncio, pytest
    async def run():
        p = Pty(['sh', '-c', 'echo one; sleep 30']).start()
        seen = bytearray()
        async def on_data(b): seen.extend(b)
        task = asyncio.create_task(p.stream(on_data))
        for _ in range(100):
            await asyncio.sleep(.02)
            if seen: break
        assert p.attached
        with pytest.raises(RuntimeError): await p.stream(on_data)
        p.write(b'echo two\n')
        for _ in range(100):
            await asyncio.sleep(.02)
            if b'two' in bytes(seen): break
        p.kill()
        await asyncio.wait_for(task, 5)
        return bytes(seen)
    seen = asyncio.run(run())
    assert b'one' in seen and b'two' in seen

def test_the_terminal_bundle_sends_the_id_the_server_keys_the_pty_by():
    """`dock.js` passes an id per session, but the wrapper dropped it and the hello went without one, so every shell keyed as its kind and the second one took the first one's pty."""
    import re
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    for js in (root/'frontend/term.js', root/'leela/vendor/lee-term.js'):
        hello = re.search(r"""t: ?['"]hello['"](.*?)\}""", js.read_text(), re.S)
        assert hello, js.name
        assert re.search(r'\bid\b', hello[1]), f'{js.name} sends no id; rebuild with npm run build'

def test_a_view_that_reconnects_is_owed_only_what_it_missed():
    """A pty outlives the socket that draws it, and the ring holds what the child printed while nothing was attached."""
    import asyncio
    async def run():
        p = Pty(['sh', '-c', 'echo one; sleep .6; echo two; sleep 30']).start()
        first, second = bytearray(), bytearray()
        async def until(dst, want):
            for _ in range(200):
                await asyncio.sleep(.02)
                if want in bytes(dst): return
        task = asyncio.create_task(p.stream(lambda b: first.extend(b)))
        await until(first, b'one')
        task.cancel()
        try: await task
        except asyncio.CancelledError: pass
        await asyncio.sleep(1)   # 'two' is printed with nobody reading
        task = asyncio.create_task(p.stream(lambda b: second.extend(b)))
        await until(second, b'two')
        p.kill()
        await asyncio.wait_for(task, 5)
        return bytes(first), bytes(second)
    first, second = asyncio.run(run())
    assert b'one' in first and b'two' not in first
    assert b'two' in second and b'one' not in second, 'the replay starts where the last view stopped'

def test_a_shell_that_exits_while_a_background_job_holds_the_tty_still_ends_the_stream(monkeypatch):
    """`nohup sleep 100 &` keeps the slave open after the shell is gone, so on Linux the pty never sends EOF: the stream ran on with no `[exited]`, and the fd and its reader stayed registered. macOS revokes the slave when the leader exits, so the reader is staged to hear bytes and then silence, which is what a held slave gives."""
    from leela.blocks.term import term
    def held(self):
        try: data = os.read(self.fd, MAX_FRAME)
        except BlockingIOError: return
        except OSError: data = b''
        if not data: return self.loop.remove_reader(self.fd)
        self.buf.extend(data); self.end += len(data); self.changed.set()
    monkeypatch.setattr(term.PtySession, '_read', held)
    async def run():
        p = Pty(['sh', '-c', 'sleep 30 & echo up; exit 3']).start()
        seen = bytearray()
        await asyncio.wait_for(p.stream(lambda b: seen.extend(b)), 5)
        try: return bytes(seen), p.exit_note, p.sess.eof
        finally: p.kill(0)
    seen, note, eof = asyncio.run(run())
    assert b'up' in seen
    assert note == '[exited 3]'
    assert eof, 'the master fd is released once the leader is gone'

def test_escalation_reaches_sigkill_without_ps(monkeypatch):
    "The liveness check ran `ps -A` on the loop every 20 ms, and a `ps` that failed left the group alive."
    import subprocess
    from leela.blocks.term import term
    def no_ps(*a, **k): raise OSError('ps is not for the event loop')
    monkeypatch.setattr(term.subprocess, 'run', no_ps)
    src = r"""
import signal
signal.signal(signal.SIGTERM, signal.SIG_IGN)
print('READY', flush=True)
while True: signal.pause()
"""
    async def run():
        p = Pty([sys.executable, '-u', '-c', src]).start()
        try:
            await _ready(p, b'READY')
            p.kill(.1)
            async with asyncio.timeout(3):
                while p.alive: await asyncio.sleep(.01)
            assert p.exit_code == -signal.SIGKILL
        finally: p.kill(0)
    asyncio.run(run())

def test_kill_outside_a_loop_returns_as_soon_as_the_group_is_gone():
    "The synchronous fallback slept the whole grace whether or not anything was left to wait for."
    import time
    async def start(): return Pty(['sh', '-c', 'sleep 30']).start()
    p = asyncio.run(start())
    try:
        t = time.monotonic()
        p.kill(2.0)
        assert time.monotonic() - t < 1, 'polled, not slept'
        assert not p.alive
    finally: p.kill(0)
