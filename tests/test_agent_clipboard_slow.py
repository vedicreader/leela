"Cmd+C copies text selected in the agent pane and Cmd+V pastes into its input; in a notebook's command mode Cmd+C still copies the cell."

import asyncio, json

import pytest

pytestmark = pytest.mark.slow

pytest.importorskip('playwright.async_api')

from test_completion_caret_slow import _real_page   # noqa: E402

SAID = 'hello agent words'

MESSAGE = r"""said => {
  const card = agentTurnCard({prompt: 'hi'}); turnBody(card).appendChild(userMessage(said)); $('#agentlog').appendChild(card);
  leePane('right', true); leeRight('agent');
  window._copies = [];
  document.addEventListener('copy', e => setTimeout(() => _copies.push({sel: String(getSelection()).trim(), prevented: e.defaultPrevented})), true);
}"""

def _nb(path):
    cells = [{'cell_type': 'code', 'id': i, 'metadata': {}, 'execution_count': None, 'outputs': [], 'source': s}
             for i, s in (('c1', 'a = 1'), ('c2', 'z = 0'))]
    meta = {'kernelspec': {'name': 'python3', 'display_name': 'Python 3', 'language': 'python'}}
    path.write_text(json.dumps({'cells': cells, 'metadata': meta, 'nbformat': 4, 'nbformat_minor': 5}))

@pytest.mark.parametrize('browser', ['chromium', 'webkit'])
def test_agent_text_copies_and_pastes_while_a_notebook_keeps_cell_copy(tmp_path, browser):
    "With a notebook open and focus on the page, `file_copy` took Cmd+C from a selection in the agent pane, so nothing reached the clipboard."
    nb = tmp_path/'n.ipynb'; _nb(nb)

    async def go(pg):
        out = {}
        if browser == 'chromium': await pg.context.grant_permissions(['clipboard-read', 'clipboard-write'])
        await pg.evaluate('p => leeOpenFile(p)', str(nb))
        await pg.wait_for_function("() => lee.kind === 'notebook' && lee.editors.get(lee.cells[0]?.id)")
        await pg.evaluate(MESSAGE, SAID)
        await pg.locator('#agentlog').get_by_text(SAID).first.click(click_count=3)
        await pg.keyboard.press('Meta+c')
        await pg.wait_for_timeout(100)
        out['copy'] = await pg.evaluate('() => ({copies: _copies, action: lee.lastKeyEvent.action})')
        if browser == 'chromium': out['clipboard'] = await pg.evaluate('() => navigator.clipboard.readText()')
        await pg.click('#agentprompt')
        await pg.keyboard.press('Meta+v')
        await pg.wait_for_timeout(100)
        out['pasted'] = await pg.evaluate("() => $('#agentprompt').value")
        out['cell'] = await pg.evaluate("""() => {
          document.activeElement.blur(); getSelection().removeAllRanges(); lee.cellClipboard = null;
          const e = new KeyboardEvent('keydown', {key: 'c', code: 'KeyC', metaKey: MAC, ctrlKey: !MAC, bubbles: true, cancelable: true});
          document.querySelector('.lee-cell').dispatchEvent(e);
          leeAct('cell_paste_below');
          return {prevented: e.defaultPrevented, copied: lee.cellClipboard?.cells?.map(c => c.source)};
        }""")
        await pg.wait_for_function('() => lee.cells.length === 3')
        out['cell']['sources'] = await pg.evaluate('() => lee.cells.map(c => c.source)')
        return out
    got = asyncio.run(_real_page(go, tmp_path, browser))
    assert got['copy']['action'] == '', f"the keymap took Cmd+C from the agent pane: {got['copy']}"
    assert {'sel': SAID, 'prevented': False} in got['copy']['copies'], got['copy']
    if browser == 'chromium': assert got['clipboard'].strip() == SAID
    assert got['pasted'].strip() == SAID, got['pasted']
    assert got['cell']['prevented'] and got['cell']['copied'], got['cell']
    assert got['cell']['sources'].count(got['cell']['copied'][0]) == 2, got['cell']
