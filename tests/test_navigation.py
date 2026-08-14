"""Where a jump lands, and whether an undo can be found afterwards.

Both are about the same thing: a change you cannot see has happened *to* you rather than been
done by you. Asserted against the built bundle, because these are client behaviours.
"""

import sys

from fastcore.all import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT/'tools'))
import build_ide_js as builder  # noqa: E402

JS = builder.OUT.read_text()
CSS = (ROOT/'leela'/'static'/'lee-ide.css').read_text()


def test_a_jump_centres_rather_than_merely_revealing():
    """`scrollIntoView` moves the minimum distance, so a hit below the fold lands on the last
    visible line with nothing under it to read."""
    block = JS[JS.index('function centreOnPos'):JS.index('function openLocation')]
    assert 'coordsAtPos' in block and 'scrollTop +=' in block
    # A notebook scrolls its column of cells, not the cell's own editor.
    assert "scrollHeight - own.clientHeight > 4 ? own : $('#editor')" in block
    assert 'requestAnimationFrame(() => centreOnPos(v, pos))' in JS, 'measured after the layout it caused'


def test_the_span_an_undo_changed_is_selected_and_centred():
    block = JS[JS.index('function changedSpan'):JS.index('async function workspaceHistoryRedo')]
    assert 'while (s < A.length' in block and 'while (a >= s' in block, 'first and last differing lines'
    assert 'selection: {anchor, head}' in block, 'the change is selected, not just scrolled to'
    assert 'centreOnPos(v, anchor)' in block


def test_undo_and_redo_read_the_texts_the_right_way_round():
    "After an undo the file holds `before`; after a redo it holds `after`. Swapping them lies."
    block = JS[JS.index('async function afterHistory'):JS.index('async function workspaceHistoryRedo')]
    assert 'undone ? row.before : row.after, undone ? row.after : row.before' in block
    assert "afterHistory(result.operation, 'workspace operation redone', false)" in JS
    assert "`workspace operation ${redo ? 'redone' : 'undone'}`, !redo)" in JS


def test_a_notebook_undo_shows_which_cell_moved():
    assert "d.op === 'undo' || d.op === 'redo'" in JS
    assert "block: 'center'" in JS and 'lee-cell-changed' in JS
    assert '.lee-cell-changed' in CSS and '@keyframes lee-cell-flash' in CSS
    assert 'prefers-reduced-motion' in CSS, 'a flash is decoration; it must be optional'


def test_the_editors_re_measure_when_their_width_changes():
    """CodeMirror caches its width; nothing was telling it when the layout changed it.

    Toggling a pane, an unpinned pane auto-closing, a split, or a window resize all move the
    editor's right edge without a keystroke. The overview stripe is pinned to that edge, so a
    stale measurement drew it as a band through the middle of the text.
    """
    block = JS[JS.index('function observeEditorWidth'):JS.index('async function boot')]
    assert 'requestMeasure' in block and 'ResizeObserver' in block
    assert 'cancelAnimationFrame' in block, 'a splitter drag fires this every frame'
    for host in ("'#editor'", "'#shell'", "'#bottomdock'"): assert host in block, host
    assert 'observeEditorWidth();' in JS, 'and it is actually started'


def test_the_overview_stripe_cannot_lay_out_at_the_canvas_default_width():
    "A <canvas> with no width attribute is 300px wide, which is the band, not the stripe."
    rule = CSS[CSS.index('.cm-lee-overview {'):CSS.index('.cm-lee-overview[hidden]')]
    assert 'width: 14px' in rule
    assert 'padding-right: 15px' in CSS, 'the scroller still reserves room for it'
