"""Snapshot tests for the terminal IDE.

Each test drives the app and compares an SVG of the terminal against one on disk. Run
`pytest --snapshot-update` after a deliberate visual change, and *look at the diff report
it prints* before accepting it -- an unreviewed update turns the whole suite into a
rubber stamp.

These are here because the IDE's rendering had no tests at all: `leela` is a few
thousand lines of Textual and FastHTML that nbdev does not touch, and layout is exactly
the kind of thing that breaks silently. A snapshot is a blunt instrument -- it fails on
any change, meaningful or not -- but for a pane that either looks right or does not, that
is the correct sensitivity.
"""

import asyncio
import pytest
from textual.widgets import TextArea

from leela.keys import tui_key


async def settle(pilot, ticks=4):
    "Let mounts, workers and the first variable poll land before anything is captured."
    for _ in range(ticks): await pilot.pause()
    await asyncio.sleep(0.25)
    for _ in range(ticks): await pilot.pause()
    # A blinking caret is a coin flip at screenshot time; without this every snapshot
    # holding a focused editor fails about half the times it runs.
    for ta in pilot.app.query(TextArea): ta.cursor_blink = False
    await pilot.pause()


async def chord(pilot, canonical):
    "Press a binding by its canonical name, so the keymap itself is part of what is tested."
    await pilot.press(tui_key(canonical))
    await settle(pilot, ticks=2)


def test_opens_on_a_notebook(snap_compare, app):
    "Files left, cells centre, exec and agent below, variables right."
    assert snap_compare(app, terminal_size=(140, 42), run_before=settle)


def test_prompt_cell_shows_its_answer(snap_compare, app):
    """The reply and the tools that produced it render inside the cell.

    The fixture notebook stores both on disk, so this also covers the `from_nb` path that
    turns a markdown cell with leela metadata back into a prompt cell.
    """
    async def run(pilot):
        await settle(pilot)
        app._view().focus_cell(2)
        await settle(pilot, ticks=2)
    assert snap_compare(app, terminal_size=(140, 42), run_before=run)


# Cell-type cycling is deliberately *not* snapshotted. A structural edit rebuilds the cell
# column, and the scroll offset afterwards depends on when layout lands -- it settled
# differently on about half of otherwise identical runs, which is a flaky image rather than
# a real regression. The behaviour it would have covered is asserted directly in
# `test_keymap.py`, where a scrollbar cannot make it lie.


def test_unsaved_changes_diff(snap_compare, app):
    "ctrl+alt+/ diffs the buffer against the file, at cell granularity."
    async def run(pilot):
        await settle(pilot)
        v = app._view()
        v.focus_cell(1)
        v.box(1).ta.text = 'import pandas as pd\ndf = pd.DataFrame({"x": range(9)})\ndf.describe()'
        await settle(pilot, ticks=2)
        await chord(pilot, 'ctrl+alt+/')
    assert snap_compare(app, terminal_size=(140, 42), run_before=run)


def test_no_diff_when_nothing_changed(snap_compare, app):
    "And says so in the status line rather than opening an empty modal."
    async def run(pilot):
        await settle(pilot)
        await chord(pilot, 'ctrl+alt+/')
    assert snap_compare(app, terminal_size=(140, 42), run_before=run)


def test_completion_picker(snap_compare, app):
    "ctrl+space offers what the kernel says exists, as a list you choose from."
    async def run(pilot):
        await settle(pilot)
        box = app.query_one('#execbox')
        box.focus()
        box.text = 'df'
        box.move_cursor((0, 2))
        await settle(pilot, ticks=2)
        await chord(pilot, 'ctrl+space')
        await settle(pilot)
    assert snap_compare(app, terminal_size=(140, 42), run_before=run)


def test_docs_from_the_kernel(snap_compare, app):
    "ctrl+alt+h shows the signature and docstring of the object the kernel actually holds."
    async def run(pilot):
        await settle(pilot)
        box = app.query_one('#execbox')
        box.focus()
        box.text = 'df'
        box.move_cursor((0, 2))
        await settle(pilot, ticks=2)
        await chord(pilot, 'ctrl+alt+h')
        await settle(pilot)
    assert snap_compare(app, terminal_size=(140, 42), run_before=run)


def test_nameerror_suggests_a_near_miss(snap_compare, app):
    "A NameError in the exec strip is answered with the name that was probably meant."
    async def run(pilot):
        await settle(pilot)
        box = app.query_one('#execbox')
        box.focus()
        box.text = 'df_nrm'
        await settle(pilot, ticks=2)
        await chord(pilot, 'ctrl+enter')
        await settle(pilot)
        assert "did you mean 'df_norm'" in app._exec_lines[-1][1]
    assert snap_compare(app, terminal_size=(140, 42), run_before=run)


def test_a_file_fills_the_pane(snap_compare, app):
    """A `.py` tab is one editor over the whole pane, not a cell capped at twenty rows.

    It opened as a one-cell notebook, which is still how it is edited -- but a cell has a
    ceiling on its height, so a file longer than the ceiling was drawn with its tail simply
    missing. This is the regression test for that: the last line of the fixture has to be
    on the screen.
    """
    async def run(pilot):
        await settle(pilot)
        await pilot.app.open_path(str(pilot.app.ws.fs.roots[0] / 'sample.py'))
        await settle(pilot)
        v = pilot.app._view()
        assert v.whole_file and v.box(0).ta.show_line_numbers
    assert snap_compare(app, terminal_size=(140, 42), run_before=run)


def test_the_kernel_picker(snap_compare, app):
    "Launcher and interpreter, both pickable with the mouse, with the cost of doing so stated."
    async def run(pilot):
        await settle(pilot)
        pilot.app.action_pick_kernel()
        await settle(pilot)
    assert snap_compare(app, terminal_size=(140, 42), run_before=run)


def test_clicking_a_toolbar_button_runs_its_action(app):
    """The button and the key are two doors into one room, and this is the door with no keymap.

    Pressed rather than called: the whole point is that `on_button_pressed` finds the right
    action and dispatches it on the *app*, which is exactly where the equivalent bug in the
    keymap lived (a scoped binding that resolved against the pane and reached nothing).
    """
    from leela.buttons import bar
    from textual.widgets import Button

    async def run():
        async with app.run_test(size=(140, 42)) as pilot:
            await settle(pilot)
            i = [b.action for b in bar('toolbar')].index('cell_type')
            app._view().focus_cell(3)
            await settle(pilot, ticks=2)
            await pilot.click(f'#b-toolbar-{i}')
            await settle(pilot, ticks=3)
            return app._view().nb[3].cell_type
    assert asyncio.run(run()) == 'markdown'


def test_help_lists_every_binding(snap_compare, app):
    "f1 is generated from `leela.keys`, so a new binding appears here for free."
    async def run(pilot):
        await settle(pilot)
        await chord(pilot, 'f1')
        await settle(pilot)
    assert snap_compare(app, terminal_size=(140, 42), run_before=run)


def test_capture_holds_the_screen_for_the_next_question(snap_compare, app, tmp_path, monkeypatch):
    "ctrl+alt+p photographs the IDE's own screen: text for the assistant, SVG for the human."
    import leela.workspace as W
    monkeypatch.setattr(W, 'leela_cfg', tmp_path)

    async def run(pilot):
        await settle(pilot)
        await chord(pilot, 'ctrl+alt+p')
        png, screen, note = app.ws.screen
        assert png is None, 'the terminal has no picture to send, and should not pretend to'
        assert 'Scaling the frame' in screen, 'the captured text should be what is on the screen'
        assert note
        saved = list((tmp_path / 'screens').glob('*.svg'))
        assert len(saved) == 1 and saved[0].read_text().startswith('<svg')
    assert snap_compare(app, terminal_size=(140, 42), run_before=run)


def test_a_capture_is_consumed_by_one_question(app):
    "Something captured to explain one thing must not ride along with an unrelated question later."
    app.ws.put_screen(text='a screen', note='test')
    assert app.ws.take_screen() == (None, 'a screen', 'test')
    assert app.ws.take_screen() == (None, '', '')
