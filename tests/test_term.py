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
