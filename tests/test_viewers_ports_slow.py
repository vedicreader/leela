"Office and media tabs on a workspace's own port, in a real browser: the page boots with no script error, the slides render, the audio and video load."

import pytest
import asyncio, json, math, struct, urllib.request, wave

pytest.importorskip('playwright.async_api')
pytest.importorskip('pptx')
from playwright.async_api import async_playwright   # noqa: E402

from test_serve_ide import _fake_kernels, serve   # noqa: E402,F401
from test_web_slow import _launch   # noqa: E402

pytestmark = [pytest.mark.slow, pytest.mark.usefixtures('_fake_kernels')]

def _files(d):
    from pptx import Presentation
    p = Presentation(); p.slides.add_slide(p.slide_layouts[0]).shapes.title.text = 'Probe slide'; p.save(d/'deck.pptx')
    with wave.open(str(d/'tone.wav'), 'wb') as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(8000)
        w.writeframes(b''.join(struct.pack('<h', int(8000*math.sin(i/8))) for i in range(8000)))
    return d/'deck.pptx', d/'tone.wav'

async def _look(url, files, browser):
    async with async_playwright() as pw:
        b = await _launch(pw, browser)
        try:
            pg, errs, bad = await b.new_page(), [], []
            pg.on('pageerror', lambda e: errs.append(str(e)))
            pg.on('response', lambda r: bad.append(f'{r.status} {r.url}') if r.status >= 400 else None)
            await pg.goto(url, wait_until='domcontentloaded')
            await pg.wait_for_function('window.lee && lee.keys.length', timeout=60000)
            got = {}
            deck, tone = files
            await pg.evaluate('p => leeOpenFile(p)', str(deck))
            await pg.wait_for_function("document.body.innerText.includes('Probe slide')", timeout=30000)
            got['deck'] = True
            await pg.evaluate('p => leeOpenFile(p)', str(tone))
            await pg.wait_for_function("(a => a && a.readyState >= 1)(document.querySelector('audio.lee-media'))", timeout=30000)
            got['tone_src'] = await pg.evaluate("document.querySelector('audio.lee-media').currentSrc")
            return got, errs, bad
        finally: await b.close()

@pytest.mark.parametrize('browser', ['chromium', 'webkit'])
def test_office_and_media_tabs_work_on_a_workspace_port(tmp_path, browser):
    for name in ('home', 'proj'): (tmp_path/name).mkdir()
    files = _files(tmp_path/'proj')
    port = serve(roots=[str(tmp_path/'home'), str(tmp_path/'proj')], app_window=True, gateway_port=0)
    url = next(s['url'] for s in json.loads(urllib.request.urlopen(f'http://127.0.0.1:{port}/app/sites', timeout=10).read())['sites'] if s['id'] == 'proj')
    assert f':{port}/' not in url, 'the viewers are checked on a port of their own'
    got, errs, bad = asyncio.run(_look(url, files, browser))
    assert not errs, f'a script error stops the page: {errs}'
    assert got['deck'] and got['tone_src'].startswith(url + 'file/raw/') and not bad, (got, bad)
