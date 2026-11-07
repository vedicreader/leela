"A real browser opens a Word, a PowerPoint and an Excel file as read-only viewers, in the simple view and in Quick Look's, and sees their content."

import pytest

pytestmark = pytest.mark.slow

import asyncio, hashlib, sys

pytest.importorskip('playwright.async_api')
from test_completion_caret_slow import _real_page   # noqa: E402
from test_office import _docx, _pptx, _xlsx   # noqa: E402

def test_each_office_kind_opens_in_its_viewer(tmp_path):
    root = tmp_path.resolve()
    files = {k: f(root/f'a.{k}') for k, f in (('docx', _docx), ('pptx', _pptx), ('xlsx', _xlsx))}
    before = {k: hashlib.sha256(p.read_bytes()).hexdigest() for k, p in files.items()}
    async def go(pg):
        seen = {}
        await pg.evaluate("() => localStorage.setItem('lee-office-view', 'simple')")
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

FRAME = "() => document.querySelector('.lee-office-frame')?.contentDocument"

def _deck(p):
    "Two slides with a body, a picture and a chart; Quick Look cannot read python-pptx speaker notes."
    import io
    from pptx import Presentation
    from pptx.chart.data import CategoryChartData
    from pptx.enum.chart import XL_CHART_TYPE
    from pptx.util import Inches
    from test_office import _png
    pr = Presentation()
    s = pr.slides.add_slide(pr.slide_layouts[1]); s.shapes.title.text = 'Plan'; s.placeholders[1].text = 'Ship the viewer'
    s.shapes.add_picture(io.BytesIO(_png()), Inches(1), Inches(5))
    s2 = pr.slides.add_slide(pr.slide_layouts[5]); s2.shapes.title.text = 'Numbers'
    cd = CategoryChartData(); cd.categories = ['A', 'B']; cd.add_series('S', (1, 3))
    s2.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(1), Inches(2), Inches(6), Inches(4), cd)
    pr.save(p); return p

@pytest.mark.skipif(sys.platform != 'darwin', reason="Quick Look is macOS's")
@pytest.mark.parametrize('browser', ['chromium', 'webkit'])
def test_quick_look_shows_each_kind_in_the_tab(tmp_path, browser):
    root = tmp_path.resolve()
    files = {k: f(root/f'a.{k}') for k, f in (('docx', _docx), ('pptx', _deck), ('xlsx', _xlsx), ('notes.pptx', _pptx))}
    before = {k: hashlib.sha256(p.read_bytes()).hexdigest() for k, p in files.items()}
    async def frame_has(pg, sel):
        await pg.wait_for_function(f"() => {{ const d = ({FRAME})(); return d && d.readyState === 'complete' && d.querySelector({sel!r}); }}", timeout=60000)
    async def go(pg):
        seen = {}
        await pg.evaluate('p => leeOpenFile(p)', str(files['docx']))
        await frame_has(pg, 'p')
        seen['docx'] = await pg.evaluate(f"""() => {{ const d = ({FRAME})();
          return {{text: d.body.textContent.includes('Quarterly report'), img: [...d.images].some(i => i.complete && i.naturalWidth > 0),
                   sandbox: document.querySelector('.lee-office-frame').getAttribute('sandbox'), view: document.querySelector('[data-office-view]').textContent}}; }}""")
        await pg.evaluate('p => leeOpenFile(p)', str(files['pptx']))
        await frame_has(pg, 'div.slide')
        await pg.wait_for_function(f"() => [...({FRAME})().images].every(i => i.complete)")
        seen['pptx'] = await pg.evaluate(f"""() => {{ const d = ({FRAME})();
          return {{slides: d.querySelectorAll('div.slide').length, imgs: [...d.images].filter(i => i.naturalWidth > 0).length,
                   title: d.body.textContent.includes('Ship the viewer'), links: d.querySelectorAll('a[href]').length}}; }}""")
        await pg.evaluate('p => leeOpenFile(p)', str(files['notes.pptx']))
        await pg.wait_for_selector('.lee-office-body .lee-office-slide')
        seen['fallback'] = await pg.evaluate("() => [!!document.querySelector('.lee-office-frame'), document.querySelector('[data-office-view]').textContent]")
        await pg.evaluate('p => leeOpenFile(p)', str(files['xlsx']))
        await pg.wait_for_selector('.lee-office-ql [data-sheet-tab]')
        await frame_has(pg, 'td')
        tabs = await pg.evaluate("() => [...document.querySelectorAll('[data-sheet-tab]')].map(b => b.textContent)")
        await pg.click('[data-sheet-tab="1"]')
        await pg.wait_for_function(f"() => ({FRAME})()?.body?.textContent.includes('hello sheet two')")
        seen['xlsx'] = {'tabs': tabs, 'clip': await pg.is_visible('.lee-office-clip')}
        await pg.click('[data-office-view]')
        await pg.wait_for_selector('.lee-office-body .lee-sheet')
        seen['simple'] = await pg.evaluate("() => [localStorage.getItem('lee-office-view'), document.querySelector('[data-office-view]').textContent]")
        await pg.evaluate("() => localStorage.removeItem('lee-office-view')")
        return seen
    seen = asyncio.run(_real_page(go, root, browser))
    assert seen['docx'] == {'text': True, 'img': True, 'sandbox': 'allow-same-origin', 'view': 'simple view'}
    assert seen['pptx'] == {'slides': 2, 'imgs': 2, 'title': True, 'links': 0}   # the picture, and the chart as PNG
    assert seen['fallback'] == [False, 'Quick Look view']
    assert seen['xlsx'] == {'tabs': ['Sales', 'Notes <x>'], 'clip': False}
    assert seen['simple'] == ['simple', 'Quick Look view']
    assert before == {k: hashlib.sha256(p.read_bytes()).hexdigest() for k, p in files.items()}
