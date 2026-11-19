"A Rupaka demo with a recorded sample plays it from the vault's demo media, through Leela's own `/leemedia/` route."
import asyncio, json, wave
import pytest

pytestmark = pytest.mark.slow

pytest.importorskip('playwright.async_api')
from test_three_slow import CELL, _in_tmp, _on   # noqa: E402

def _spec(src):
    "A one-block explainer whose Play button plays the recorded tha at `src`."
    from rupaka.spec import profile_hash, validate
    d = dict(label='Mridangam', sources=dict(tha=dict(url='https://www.mrithang.com/mridangam-tour/', title='Complete Photo Tour of the Mridangam', passage='A non-vibrating tone played on the left hand side of the mridangam.')),
             parts=dict(left=dict(kind='region', label='Left hand side', sources=['tha'])),
             media={'tha-1': dict(kind='audio', src=src, credit=dict(who='A test tone', license='CC0-1.0', url='https://creativecommons.org/publicdomain/zero/1.0/'))},
             techniques=dict(tha=dict(label='Tha', sources=['tha'], parts=['left'], voice=dict(kind='sample', media='tha-1'))))
    s = dict(rupaka=1, id='real-tha', title='A real tha', mode='learn', state={}, profiles=dict(mridangam=dict(id='mridangam-test', revision=profile_hash(d), data=d)),
             blocks=[dict(type='sound', play=dict(profile='mridangam', technique='tha'))])
    assert validate(s) == []
    return s

MEDIA = "(s) => document.querySelector(s)?.shadowRoot?.querySelector('[data-rk-media]')?.getAttribute('data-rk-media')"

def test_a_recorded_sample_loads_from_leelas_own_origin(monkeypatch):
    from leela.blocks.memory.memory import Memory
    from rupaka.media import import_asset
    def run(root):
        (root/'src').mkdir()
        with wave.open(str(root/'src'/'tha.wav'), 'wb') as w: w.setnchannels(1); w.setsampwidth(2); w.setframerate(8000); w.writeframes(b'\0\0' * 2400)
        src = import_asset(root/'src'/'tha.wav', Memory(path=root/'vault.db', offline=True)._store('learning').assets('demo-media'))
        nb = root/'tha.ipynb'
        nb.write_text(json.dumps({'cells': [{'cell_type': 'markdown', 'id': 'c0', 'metadata': {}, 'source': ['```rupaka\n' + json.dumps(_spec(src)) + '\n```\n']}],
                                  'metadata': {}, 'nbformat': 4, 'nbformat_minor': 5}))
        async def go(pg):
            await pg.evaluate(f'leeOpenFile({str(nb)!r})')
            h = pg.locator(CELL.format(0))
            await h.get_by_role('button', name='Play').wait_for(timeout=30000)
            await h.scroll_into_view_if_needed()
            async with pg.expect_response(lambda r: '/leemedia/' in r.url, timeout=30000) as got: await h.get_by_role('button', name='Play').click()
            r = await got.value
            return dict(status=r.status, url=r.url, origin=await pg.evaluate('location.origin'), type=r.headers.get('content-type'), base=await pg.evaluate(MEDIA, CELL.format(0)))
        return src, asyncio.run(_on(root, go, monkeypatch))
    src, f = _in_tmp(run)
    assert f['base'] == '/leemedia/', f
    assert f['status'] in (200, 206) and f['url'] == f"{f['origin']}/leemedia/{src[6:]}" and f['type'] == 'audio/wav', f
