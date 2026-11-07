"A real browser opens a wav, an mp4 and a mov in their media tabs with a playable element, and a broken file offers the default app."

import pytest

pytestmark = pytest.mark.slow

import asyncio, hashlib

pytest.importorskip('playwright.async_api')
from test_completion_caret_slow import _real_page   # noqa: E402
from test_media import FIXTURES, _wav   # noqa: E402

READY = """() => { const m = document.querySelector('.lee-media');
  return m && m.readyState >= 1 && m.duration > 0 ? {tag: m.tagName, dur: m.duration, err: m.error && m.error.code} : null; }"""

@pytest.mark.parametrize('browser', ['chromium', 'webkit'])
def test_each_media_file_opens_with_a_playable_element(tmp_path, browser):
    root = tmp_path.resolve()
    tiny = (FIXTURES/'tiny.mp4').read_bytes()
    files = {'wav': _wav(root/'a.wav'), 'mp4': root/'a.mp4', 'mov': root/'a.mov'}
    files['mp4'].write_bytes(tiny); files['mov'].write_bytes(tiny)
    (bad := root/'bad.ogg').write_bytes(b'not audio at all')
    before = {k: hashlib.sha256(p.read_bytes()).hexdigest() for k, p in files.items()}
    async def go(pg):
        seen, ranges = {}, []
        pg.on('response', lambda r: '/file/raw/' in r.url and ranges.append(r.status))
        for k, p in files.items():
            await pg.evaluate('p => leeOpenFile(p)', str(p))
            h = await pg.wait_for_function(READY, timeout=20000)
            seen[k] = await h.json_value()
            seen[k]['head'] = await pg.evaluate("() => [...document.querySelectorAll('.lee-doc-head .lee-btn')].map(b => b.textContent)")
            seen[k]['cm'] = await pg.evaluate("() => !!document.querySelector('.lee-editor .cm-content')")
        await pg.evaluate('p => leeOpenFile(p)', str(bad))
        await pg.wait_for_selector('[data-media-error]', timeout=20000)
        seen['bad'] = await pg.evaluate("() => document.querySelector('[data-media-error]').textContent")
        seen['ranges'] = ranges
        return seen
    seen = asyncio.run(_real_page(go, root, browser))
    assert seen['wav']['tag'] == 'AUDIO' and seen['mp4']['tag'] == seen['mov']['tag'] == 'VIDEO'
    for k in files: assert not seen[k]['err'] and not seen[k]['cm'] and seen[k]['head'] == ['open in default app', 'download'], (k, seen[k])
    assert 'cannot play here' in seen['bad'] and 'default app' in seen['bad']
    assert 206 in seen['ranges'], seen['ranges']
    assert before == {k: hashlib.sha256(p.read_bytes()).hexdigest() for k, p in files.items()}

@pytest.mark.parametrize('browser', ['chromium', 'webkit'])
def test_a_screen_recording_name_plays_and_shows(tmp_path, browser):
    """`/file/raw` answered 400 for a name with U+202F, as every macOS recording and screenshot has, so the video showed its error."""
    from test_nb_md_images_slow import DOT
    root = tmp_path.resolve()/'Desktop 9.46 am'; root.mkdir()
    mov = root/'Screen Recording 2026-11-04 at 9.46.03 am.mov'; mov.write_bytes((FIXTURES/'tiny.mp4').read_bytes())
    png = root/'Screenshot 2026-11-04 at 9.46.03 am #1?.png'; png.write_bytes(DOT)
    pdf = root/'café 100%  am.pdf'; pdf.write_bytes(b'%PDF-1.4\ntrailer\n%%EOF\n')
    async def go(pg):
        bad = []
        pg.on('response', lambda r: '/file/raw/' in r.url and r.status >= 400 and bad.append((r.status, r.url)))
        await pg.evaluate('p => leeOpenFile(p)', str(mov))
        vid = await (await pg.wait_for_function(READY, timeout=20000)).json_value()
        err = await pg.evaluate("() => !!document.querySelector('[data-media-error]')")
        await pg.evaluate('p => leeOpenFile(p)', str(png))
        w = await (await pg.wait_for_function("() => { const i = document.querySelector('.lee-image'); return i && i.complete && i.naturalWidth; }", timeout=20000)).json_value()
        await pg.evaluate('p => leeOpenFile(p)', str(pdf))
        src = await (await pg.wait_for_selector('.lee-pdf')).get_attribute('src')
        r = await pg.evaluate("u => fetch(u, {headers: {Range: 'bytes=0-3'}}).then(r => [r.status, r.headers.get('content-disposition')])", src)
        return vid, err, w, r, bad
    vid, err, w, r, bad = asyncio.run(_real_page(go, root, browser))
    assert vid['tag'] == 'VIDEO' and not vid['err'] and not err, vid
    assert w == 1 and r[0] == 206 and r[1].startswith('inline; filename*='), (w, r)
    assert not bad, bad
