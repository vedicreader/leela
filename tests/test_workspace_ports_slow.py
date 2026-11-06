"Two workspaces of one server, each on a loopback port of its own, in a real browser: both boot, and neither page reaches the other."

import pytest
import asyncio, json, urllib.request

pytest.importorskip('playwright.async_api')
from playwright.async_api import async_playwright   # noqa: E402

from test_serve_ide import _fake_kernels, serve   # noqa: E402,F401
from test_web_slow import _launch   # noqa: E402

pytestmark = [pytest.mark.slow, pytest.mark.usefixtures('_fake_kernels')]

async def _two(port, browser):
    sites = {s['id']: s['url'] for s in json.loads(urllib.request.urlopen(f'http://127.0.0.1:{port}/app/sites', timeout=10).read())['sites']}
    async with async_playwright() as pw:
        b = await _launch(pw, browser)
        try:
            pages = {}
            for slug, url in sites.items():
                pages[slug] = pg = await b.new_page()
                await pg.goto(url, wait_until='domcontentloaded')
                await pg.wait_for_function('window.lee && lee.keys.length', timeout=60000)
            a, z = pages['alpha'], pages['beta']
            await a.evaluate("localStorage.setItem('lee-probe', 'alpha')")
            got = dict(beta_sees=await z.evaluate("localStorage.getItem('lee-probe')"),
                       titles=[await p.title() for p in pages.values()],
                       cross=await a.evaluate("u => fetch(u + 'tab/close', {method: 'POST', body: '{}', headers: {'Content-Type': 'application/json'}}).then(r => r.status, e => 'refused')", sites['beta']))
            return sites, got
        finally: await b.close()

@pytest.mark.parametrize('browser', ['chromium', 'webkit'])
def test_two_workspaces_boot_on_their_own_ports_and_stay_apart(tmp_path, browser):
    for name in ('alpha', 'beta'): (tmp_path/name).mkdir()
    port = serve(roots=[str(tmp_path/'alpha'), str(tmp_path/'beta')], app_window=True, gateway_port=0)
    sites, got = asyncio.run(_two(port, browser))
    assert len({u.split(':')[2] for u in sites.values()}) == 2, sites
    assert got['beta_sees'] is None, 'what one workspace keeps per origin, the other does not see'
    assert any('alpha' in t for t in got['titles']) and any('beta' in t for t in got['titles']), got
    assert got['cross'] in ('refused', 403), got
