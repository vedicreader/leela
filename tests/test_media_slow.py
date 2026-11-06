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
