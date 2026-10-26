"The sticky declaration line names the def above the view, never a copy of a def the view already shows."
import json
import pytest

CELL = '#cm-c0'

@pytest.mark.slow
def test_a_code_cell_starting_with_a_def_has_no_sticky_copy_over_it(tmp_path):
    "A cell's first line `def odd_squares(n):` was painted again over itself, small and offset: ghost text."
    pytest.importorskip('playwright.async_api')
    from test_web_slow import _run
    p = tmp_path/'sticky.ipynb'
    p.write_text(json.dumps({'cells': [{'cell_type': 'code', 'id': 'c0', 'metadata': {}, 'execution_count': None, 'outputs': [],
                                        'source': ['def odd_squares(n):\n', '    return ...']}],
                             'metadata': {}, 'nbformat': 4, 'nbformat_minor': 5}))
    async def go(pg):
        await pg.evaluate(f'leeOpenFile({str(p)!r})')
        await pg.wait_for_function(f'() => document.querySelector({CELL!r} + " .cm-line")')
        await pg.wait_for_timeout(300)
        return await pg.evaluate(f"""() => [...document.querySelectorAll({CELL!r} + ' .cm-lee-sticky')]
            .filter(e => !e.hidden && e.getBoundingClientRect().height > 0).map(e => e.textContent)""")
    assert _run(go, roots=[tmp_path]) == []

@pytest.mark.slow
def test_a_file_whose_first_line_is_a_def_has_no_sticky_copy_at_the_top(tmp_path):
    "The same copy sat over line 1 of a file editor opened at the top."
    pytest.importorskip('playwright.async_api')
    from test_web_slow import _run
    p = tmp_path/'long.py'
    p.write_text('def outer():\n' + ''.join(f'    x{i} = {i}\n' for i in range(150)))
    async def go(pg):
        await pg.evaluate(f'leeOpenFile({str(p)!r})')
        await pg.wait_for_function('() => [...document.querySelectorAll(".cm-line")].some(l => l.textContent.includes("x1 = 1"))')
        await pg.wait_for_timeout(300)
        return await pg.evaluate("""() => [...document.querySelectorAll('.cm-lee-sticky')].filter(e => !e.hidden).map(e => e.textContent)""")
    assert _run(go, roots=[tmp_path]) == []
