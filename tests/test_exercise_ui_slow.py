"Pressing Check on an exercise cell lists its checks under the cell, and the button works from the keyboard."

import asyncio
import pytest

pytestmark = pytest.mark.slow

pytest.importorskip('playwright.async_api')

from test_completion_caret_slow import _real_page   # noqa: E402
from leela.blocks.nb.exercise import exercise_cells   # noqa: E402
from leela.blocks.nb.nb import Notebook   # noqa: E402

SPEC = dict(task='Double a number.', fname='double', stub='def double(x):\n    pass', tests=[
    dict(say='A positive number', test='assert double(2) == 4', shown=True),
    dict(say='A negative number', test='assert double(-123) == -246', shown=False)])
ROWS = "() => [...document.querySelectorAll('.lee-exercise .lee-ex-row')].map(r => [r.dataset.status, r.textContent])"

def test_check_lists_one_row_per_check_and_hides_the_hidden_expectation(tmp_path):
    task, code = exercise_cells(SPEC)
    Notebook([task, code]).save(tmp_path/'lesson.ipynb')
    async def go(pg):
        await pg.evaluate('p => leeOpenFile(p)', str(tmp_path/'lesson.ipynb'))
        check = pg.get_by_role('button', name='Check my code')
        await check.wait_for()
        assert await pg.evaluate(ROWS) == []
        await check.focus()
        await pg.keyboard.press('Enter')
        await pg.wait_for_function("() => document.querySelectorAll('.lee-exercise .lee-ex-row').length === 2", timeout=60000)
        return (await pg.evaluate(ROWS), await pg.get_by_role('button', name='Check my code').is_enabled(),
                await pg.get_by_role('button', name='Ask the tutor about this result').is_enabled(),
                await pg.evaluate("() => document.activeElement.getAttribute('data-ex')"))
    rows, enabled, ask, focused = asyncio.run(_real_page(go, tmp_path))
    assert [r[0] for r in rows] == ['fail', 'fail'] and 'A positive number' in rows[0][1] and 'A negative number' in rows[1][1]
    assert '-246' not in rows[1][1] and enabled and ask and focused == 'check'
