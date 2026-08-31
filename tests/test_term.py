"What the agent reads back off a terminal."

from leela.blocks.term.term import MAX_FRAME, SCROLLBACK, Pty

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
    """macOS returns 1024 bytes a read whatever is asked for, so `stream` called `on_data` once per
    kilobyte and the socket sent a frame each, which is what made the terminal crawl in the app.
    Reads are gathered now, and the gathering must not swallow the output a child writes as it
    exits: the end of the stream can sit in the middle of a batch."""
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
