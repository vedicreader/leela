"What the agent reads back off a terminal."

from leela.blocks.term.term import Pty

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
