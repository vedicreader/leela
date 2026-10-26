"A markdown output reads like a markdown cell: prose in the body font, code in the mono font."
import json
import pytest

def _notebook(tmp_path):
    p = tmp_path/'out.ipynb'
    md = 'Some **prose** with `code` in it.'
    p.write_text(json.dumps({'cells': [
        {'cell_type': 'markdown', 'id': 'c0', 'metadata': {}, 'source': [md]},
        {'cell_type': 'code', 'id': 'c1', 'metadata': {}, 'execution_count': 1, 'source': ['from IPython.display import Markdown\nMarkdown("x")'],
         'outputs': [{'output_type': 'execute_result', 'execution_count': 1, 'metadata': {}, 'data': {'text/markdown': md, 'text/plain': '<Markdown>'}}]}],
        'metadata': {}, 'nbformat': 4, 'nbformat_minor': 5}))
    return p

@pytest.mark.slow
def test_a_markdown_output_uses_the_markdown_cells_fonts(tmp_path):
    "`.lee-out` sets the mono font for text outputs, and a markdown output kept it, so its prose read as code."
    pytest.importorskip('playwright.async_api')
    from test_web_slow import _run
    p = _notebook(tmp_path)
    cell, out = '.lee-cell[data-i="0"] .lee-md-cell', '.lee-cell[data-i="1"] .lee-md-output'
    async def go(pg):
        await pg.evaluate(f'leeOpenFile({str(p)!r})')
        await pg.wait_for_function(f'() => document.querySelector({out!r} + " p") && document.querySelector({cell!r} + " p")')
        return await pg.evaluate(f"""() => {{ const f = s => getComputedStyle(document.querySelector(s)).fontFamily;
          const z = s => getComputedStyle(document.querySelector(s)).fontSize;
          return {{cell: f({cell!r} + ' p'), out: f({out!r} + ' p'), cellSize: z({cell!r} + ' p'), outSize: z({out!r} + ' p'),
                   cellCode: f({cell!r} + ' code'), outCode: f({out!r} + ' code')}}; }}""")
    got = _run(go, roots=[tmp_path])
    assert got['out'] == got['cell'] and got['outSize'] == got['cellSize'], got
    assert got['outCode'] == got['cellCode'] != got['cell'], got
