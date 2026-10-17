"What the agent reads back off a terminal."

import asyncio, os, signal, sys
from leela.blocks.term.term import MAX_FRAME, SCROLLBACK, Pty


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


def test_a_second_stream_over_one_pty_is_refused_and_the_first_keeps_reading():
    """Two terminals keyed the same shared a pty, and `add_reader` handed the fd to whichever attached last: the older view stayed on screen and never printed another byte."""
    import asyncio, pytest
    async def run():
        p = Pty(['sh', '-c', 'echo one; sleep 30']).start()
        seen = bytearray()
        async def on_data(b): seen.extend(b)
        task = asyncio.create_task(p.stream(on_data))
        for _ in range(500):
            await asyncio.sleep(.02)
            if b'one' in seen: break
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
