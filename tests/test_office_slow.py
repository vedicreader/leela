"A real browser opens a Word, a PowerPoint and an Excel file as read-only viewers and sees their content."

import pytest

pytestmark = pytest.mark.slow

import asyncio, hashlib

pytest.importorskip('playwright.async_api')
from test_completion_caret_slow import _real_page   # noqa: E402
from test_office import _docx, _pptx, _xlsx   # noqa: E402

def test_each_office_kind_opens_in_its_viewer(tmp_path):
    root = tmp_path.resolve()
    files = {k: f(root/f'a.{k}') for k, f in (('docx', _docx), ('pptx', _pptx), ('xlsx', _xlsx))}
    before = {k: hashlib.sha256(p.read_bytes()).hexdigest() for k, p in files.items()}
    async def go(pg):
        seen = {}
        await pg.evaluate('p => leeOpenFile(p)', str(files['docx']))
        await pg.wait_for_selector('.lee-office-doc h1')
        seen['docx'] = await pg.evaluate("""() => ({h1: document.querySelector('.lee-office-doc h1').textContent,
          li: document.querySelectorAll('.lee-office-doc li').length, img: !!document.querySelector('.lee-office-doc img[src^="data:image/png"]'),
          script: document.querySelectorAll('.lee-office-body script').length, cm: !!document.querySelector('.lee-editor .cm-content')})""")
        await pg.evaluate('p => leeOpenFile(p)', str(files['pptx']))
        await pg.wait_for_selector('.lee-office-slide')
        seen['pptx'] = await pg.evaluate("""() => ({n: document.querySelectorAll('.lee-office-slide').length,
          notes: document.querySelector('.lee-office-slide details').textContent, open: document.querySelector('.lee-office-slide details').open})""")
        seen['pptx']['visible'] = await pg.is_visible('.lee-office-slide h2') and await pg.is_visible('[data-office-copy]')
        await pg.evaluate('p => leeOpenFile(p)', str(files['xlsx']))
        await pg.wait_for_selector('[data-sheet-tab]')
        rows = lambda: pg.evaluate("() => document.querySelectorAll('.lee-sheet[data-sheet=\"0\"] tr').length")
        seen['rows'] = await rows()
        await pg.click('.lee-sheet-more button')
        await pg.wait_for_function("() => document.querySelectorAll('.lee-sheet[data-sheet=\"0\"] tr').length > 200")
        seen['more'] = await rows()
        await pg.click('[data-sheet-tab="1"]')
        seen['xlsx'] = await pg.evaluate("""() => ({tabs: [...document.querySelectorAll('[data-sheet-tab]')].map(b => b.textContent),
          shown: document.querySelector('.lee-sheet:not([hidden])').textContent})""")
        return seen
    seen = asyncio.run(_real_page(go, root))
    assert seen['docx'] == {'h1': 'Quarterly report', 'li': 2, 'img': True, 'script': 0, 'cm': False}
    assert seen['pptx']['n'] == 2 and 'Say this slowly' in seen['pptx']['notes'] and not seen['pptx']['open'] and seen['pptx']['visible']
    assert seen['rows'] == 200 and seen['more'] == 400
    assert seen['xlsx']['tabs'] == ['Sales', 'Notes <x>'] and 'hello sheet two' in seen['xlsx']['shown']
    assert before == {k: hashlib.sha256(p.read_bytes()).hexdigest() for k, p in files.items()}
