import time
from pathlib import Path

import pytest

from tests.test_learn_tab_pages_slow import OUT, SHELL, _env, _run

pytestmark = pytest.mark.slow

DAY = 86400.
PAGE = "() => document.querySelector('.abh main') && document.querySelector('.abh').getAttribute('aria-busy') !== 'true'"
ORDER = "() => [...document.querySelectorAll('.abh .st-concepts li .depth')].map(e => getComputedStyle(e).order)"


def _seed(lr, tmp_path, monkeypatch):
    from fastcore.nbio import mk_cell, new_nb, write_nb
    from abhyasa.sources import file_folder
    jid = lr.journeys()[0].id
    slugs = [s['slug'] for s in lr.journey(jid).steps]
    now = time.time()
    for k, (days, ok) in enumerate([(0, True), (0, False), (1, True), (2, True), (2, True), (4, False), (5, True)]):
        a = lr.record(slugs[k % 2], 'What does a fraction name?', 'equal parts', correct=ok, final=True, session=f's{days}')
        lr.mark_attempt(a.id, at=now - days * DAY - k * 60)
    lr.update(slugs[0], seen=4, floor=3, ceiling=6, last=now - DAY, stability=9., streak=3)
    lr.update(slugs[1], seen=3, floor=1, ceiling=6, last=now - 6 * DAY, stability=1., misses=2)
    row = lambda s, f0, f, ok: dict(qid='q', concept=s, name=s, depth=1, question='What does a fraction name?', correct=ok, outcome='solid' if ok else 'gap', floor0=f0, floor=f, turns=[])
    for k, days in enumerate((0, 2)):
        lr.log_session(f's{days}', f'{days}', start=now - days * DAY - 600, updated=now - days * DAY, ended=now - days * DAY, concepts=slugs, passed=2, asked=2,
                       journey=jid, log=[row(slugs[0], 1, 2 + k, True), row(slugs[1], 0, 1, False)])
    home = tmp_path.parent/f'{tmp_path.name}-home'; (home/'course22').mkdir(parents=True)
    monkeypatch.setattr(Path, 'home', lambda: home)
    write_nb(new_nb([mk_cell('# Noise\n\nA diffusion model adds noise, then learns to remove it.', 'markdown')]), home/'course22'/'01_noise.ipynb')
    write_nb(new_nb([mk_cell('# Steps\n\nThe sampler removes the noise in small steps.', 'markdown')]), home/'course22'/'02_steps.ipynb')
    docs = file_folder(lr, home/'course22')
    lr.walk_slug(jid, slugs[0], read=dict(shelf=docs[0].shelf, doc_id=docs[0].doc_id, src=f'vault:{docs[0].shelf}', ref=docs[0].doc_id, title='Noise', text='A diffusion model adds noise'))
    return jid, slugs, docs


async def _open(pg, path):
    await pg.evaluate('p => leeLearnOpen(p)', path)
    await pg.wait_for_function(PAGE, timeout=30000)
    await pg.wait_for_timeout(500)


def test_progress_profile_library_search_in_the_tab(tmp_path, monkeypatch):
    pytest.importorskip('playwright.async_api')
    lr, jid, slug = _env(tmp_path, monkeypatch)
    jid, slugs, docs = _seed(lr, tmp_path, monkeypatch)
    async def scenario(pg, ws, port):
        bad = []
        ws.vaults.learn(path=lr.vault.path)
        pg.on('pageerror', lambda e: bad.append(str(e)))
        pg.on('response', lambda r: bad.append((r.status, r.url)) if r.status >= 400 and '/git/file' not in r.url else None)
        await pg.evaluate("applyTheme('leela:light:relaxed')")
        before = await pg.evaluate(SHELL)
        for mode in ('light', 'dark'):
            await pg.evaluate(f"applyTheme('leela:{mode}:relaxed')")
            for path, name in (('/you', 'p5-you'), ('/you/profile', 'p5-profile'), ('/library/sources', 'p9-library'), ('/search?q=noise', 'p9-search')):
                await _open(pg, path)
                await pg.screenshot(path=f'{OUT}/{name}-{mode}.png')
        await pg.evaluate("applyTheme('leela:light:relaxed')")

        await _open(pg, '/you')
        assert await pg.locator('.abh nav.subtabs a.on').inner_text() == 'Progress'
        assert '7 questions in the last seven days' in await pg.locator('.abh [data-part=week]').inner_text()
        assert await pg.locator('.abh .week .col:not(.none)').count() == 5
        assert await pg.locator('.abh .st-concepts li .depth').count() == 1
        assert set(await pg.evaluate(ORDER)) == {'0'}
        assert await pg.locator('.abh a[href^="/s/"], .abh .runs').count() or await pg.locator('.abh').inner_text()

        await _open(pg, '/you/profile')
        assert await pg.locator('.abh nav.subtabs a.on').inner_text() == 'Profile'
        assert await pg.evaluate("getComputedStyle(document.querySelector('.abh .modes-pick input')).opacity") == '0'
        await pg.locator('.abh .modes-pick label', has_text='Gentle').click()
        await pg.wait_for_function("document.querySelector('.abh #learning-pace-m, .abh .srow .saved')", timeout=10000)
        assert lr.profile()['pace'] == 'gentle'
        assert not await pg.evaluate("window.lee.learnPrefs && Object.keys(window.lee.learnPrefs).includes('pace')")
        await pg.evaluate('() => document.querySelector(".abh").insertAdjacentHTML("beforeend", \'<a id="t-set" href="/settings#g-research">Turn this off in Settings</a>\')')
        await pg.locator('#t-set').evaluate('el => el.click()')
        await pg.locator('[data-settings-section="learn"]:not([hidden])').wait_for(timeout=10000)
        await pg.keyboard.press('Escape')

        await _open(pg, '/library/sources')
        assert await pg.locator('.abh nav.subtabs a.on').inner_text() == 'Sources'
        assert 'course22' in await pg.locator('.abh [data-part=sources]').inner_text()
        await pg.locator('.abh [data-part=sources] summary').click()
        await pg.locator('.abh [data-part=sources] ul a', has_text='01_noise').or_(pg.locator('.abh [data-part=sources] ul a').first).first.evaluate('el => el.click()')
        await pg.wait_for_function('window.lee && document.querySelector("#tabbar .active, #tabbar [aria-selected=true]") !== null', timeout=10000)
        assert ws.tab.kind == 'vault' and ws.tab.ref.startswith('learn|notebooks|'), (ws.tab.kind, ws.tab.ref)
        await pg.get_by_text('diffusion model adds noise').first.wait_for(timeout=15000)

        await pg.evaluate('() => leeLearnOpen("/")')
        await pg.locator('.abh main').first.wait_for()
        await pg.locator('.lee-learn-find input').fill('noise')
        await pg.keyboard.press('Enter')
        await pg.locator('.abh h1.query').wait_for(timeout=15000)
        for _ in range(40):
            if ws.tab.page.startswith('/search'): break
            await pg.wait_for_timeout(100)
        assert ws.tab.kind == 'learn' and ws.tab.page.startswith('/search'), ws.tab.page
        assert await pg.locator('.abh h2', has_text='In your vault').count() and await pg.locator('.abh ul.hits').last.locator('li').count() == 2
        assert await pg.locator('.abh a[href^="/c/"], .abh a[href^="/w/"]').count()
        await pg.locator('.abh ul.hits a[href^="/v/"]').first.evaluate('el => el.click()')
        await pg.wait_for_timeout(800)
        assert ws.tab.kind == 'vault' and ws.tab.ref.startswith('learn|notebooks|')

        await pg.evaluate('() => leeLearnOpen("/search?q=noise")')
        await pg.locator('.abh h1.query').wait_for(timeout=15000)
        await pg.evaluate('() => document.querySelector(".abh").insertAdjacentHTML("beforeend", \'<a id="t-pane" class="pane-link src-open" target="_blank" data-pane="/v/notebooks/x?pane=1" href="/v/notebooks/%s">Open in your vault</a>\')' % docs[0].doc_id)
        await pg.locator('#t-pane').evaluate('el => el.click()')
        await pg.wait_for_timeout(800)
        assert ws.tab.kind == 'vault' and ws.tab.ref.endswith(docs[0].doc_id), ws.tab.ref
        assert [t.ref for t in ws.tabs].count(ws.tab.ref) == 1

        assert await pg.evaluate(SHELL) == before
        assert not bad, bad
    _run(tmp_path, scenario, viewport=dict(width=1500, height=900))


def test_add_a_source_from_the_walk_page_files_the_folder(tmp_path, monkeypatch):
    pytest.importorskip('playwright.async_api')
    from fastcore.nbio import mk_cell, new_nb, write_nb
    from abhyasa.sources import vault_roots
    lr, jid, slug = _env(tmp_path, monkeypatch)
    jid, slugs, docs = _seed(lr, tmp_path, monkeypatch)
    home = Path.home(); (home/'notes22').mkdir()
    write_nb(new_nb([mk_cell('# Sampling\n\nA sampler draws one value from a distribution.', 'markdown')]), home/'notes22'/'01_sampling.ipynb')
    async def scenario(pg, ws, port):
        bad = []
        pg.on('pageerror', lambda e: bad.append(str(e)))
        await _open(pg, f'/w/{jid}')
        await pg.locator('.abh #walk-src-q').fill('~/nothing-here')
        await pg.locator('.abh #walk-src-go').click()
        await pg.wait_for_function("document.querySelector('.abh #walk-src-out')?.innerText.includes('home folder')", timeout=15000)
        await pg.locator('.abh #walk-src-q').fill(str(home/'notes22'))
        await pg.locator('.abh #walk-src-go').click()
        for _ in range(100):
            if 'notes22' in vault_roots(lr): break
            await pg.wait_for_timeout(200)
        assert 'notes22' in vault_roots(lr)
        await _open(pg, '/library/sources')
        assert 'notes22' in await pg.locator('.abh [data-part=sources]').inner_text()
        assert not bad, bad
    _run(tmp_path, scenario, viewport=dict(width=1500, height=900))
