"What the agent reads back off a terminal."

from leela.blocks.term.term import Pty

def _held(raw):
    "A Pty holding `raw` as scrollback, with no child ever spawned."
    p = Pty()
    p.scrollback = bytearray(raw)
    return p

def test_a_progress_line_reads_as_its_final_state_not_every_redraw():
    "A pty redraws in place with a bare `\r`, so only the last state was ever on screen."
    p = _held(b'building\r\n  0%\r 50%\r100%\r\ndone\r\n')
    assert p.text() == 'building\n100%\ndone'

def test_colour_and_cursor_escapes_do_not_reach_the_reader():
    p = _held(b'\x1b[32mPASS\x1b[0m tests\r\n')
    assert p.text() == 'PASS tests'

def test_only_the_last_n_lines_come_back():
    p = _held(b'a\r\nb\r\nc\r\n')
    assert p.text(2) == 'b\nc'
    assert p.text() == 'a\nb\nc'
