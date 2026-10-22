"A notebook cell draws the rich output a kernel sends."

import json
import pytest

pytestmark = pytest.mark.slow

pytest.importorskip('playwright.async_api')

from test_web_slow import _run   # noqa: E402

# What fastprogress sends: a FastHTML object offers `text/html` and a fenced copy as `text/markdown`.
BAR = lambda v: {'output_type': 'display_data', 'metadata': {}, 'data': {
    'text/plain': f'<div><progress max="3" value="{v}"></progress></div>',
    'text/html': f'<div><progress max="3" value="{v}"></progress></div>',
    'text/markdown': f'```html\n<div><progress max="3" value="{v}"></progress></div>\n\n```'}}

PAINT = r"""(outputs) => {
  const c = lee.cells[0]; c.outputs = outputs; renderOutputs(c);
  const box = document.getElementById('out-' + c.id);
  const hosts = [...box.querySelectorAll('.lee-out')];
  const bars = hosts.map(h => h.shadowRoot && h.shadowRoot.querySelector('progress'));
  return {n: hosts.length, rendered: bars.every(Boolean), value: bars.map(b => b && b.value),
          code: box.querySelectorAll('.cm-content, pre, .lee-code-surface').length, text: box.textContent};
}"""


def test_a_display_offering_html_and_markdown_draws_the_html(tmp_path):
    """A progress bar arrived as `text/markdown` first, so the cell showed its source in an `html` code view."""
    p = tmp_path/'bars.ipynb'
    p.write_text(json.dumps({'cells': [{'cell_type': 'code', 'source': ['x'], 'metadata': {}, 'outputs': [], 'execution_count': None}],
                             'metadata': {}, 'nbformat': 4, 'nbformat_minor': 5}))
    async def go(pg):
        await pg.evaluate(f'leeOpenFile({str(p)!r})')
        await pg.wait_for_function("() => lee.cells && lee.cells.length && document.querySelector('.lee-cell')")
        await pg.evaluate(PAINT, [BAR(0)])
        return await pg.evaluate(PAINT, [BAR(3)])
    out = _run(go, roots=[tmp_path])
    assert out['n'] == 1 and out['rendered'], out
    assert out['value'] == [3], out
    assert out['code'] == 0 and 'edit as markdown' not in out['text'], out
