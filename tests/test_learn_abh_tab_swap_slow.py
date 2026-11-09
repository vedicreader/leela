import pytest

from tests.test_learn_tab_pages_slow import OUT, _env, _learn, _run

pytestmark = pytest.mark.slow

IDLE = "() => !document.querySelector('.abh[aria-busy]')"


async def _open(pg, ws, jid):
    ws.open_walk('workspace', jid); ws.save(); await _learn(pg)
    await pg.locator('.abh #check .check').wait_for(timeout=30000)
    await pg.wait_for_function(IDLE, timeout=30000)


def test_a_chord_pressed_during_a_swap_waits_for_it(tmp_path, monkeypatch):
    pytest.importorskip('playwright.async_api')
    lr, jid, slug = _env(tmp_path, monkeypatch)
    async def scenario(pg, ws, port):
        hints = []
        async def slow(route):
            hints.append(route.request.url); await pg.wait_for_timeout(1200); await route.continue_()
        await pg.route('**/hint*', slow)
        await _open(pg, ws, jid)
        await pg.locator('.abh #ans').click()
        await pg.keyboard.press('Alt+KeyW')
        await pg.wait_for_function("() => document.querySelector('.abh').getAttribute('aria-busy') === 'true'", timeout=5000)
        assert len(hints) == 1
        await pg.evaluate("() => leeAbhSettled(document.querySelector('.abh'))")
        assert await pg.evaluate(IDLE)
    _run(tmp_path, scenario, dict(width=1500, height=900))


def test_option_b_offers_a_side_walk_for_the_selected_word(tmp_path, monkeypatch):
    pytest.importorskip('playwright.async_api')
    lr, jid, slug = _env(tmp_path, monkeypatch)
    async def scenario(pg, ws, port):
        offers = []
        pg.on('request', lambda r: offers.append(r.url) if '/rh/term' in r.url else None)
        await _open(pg, ws, jid)
        await pg.wait_for_function("() => !!window.abhyasaDetour", timeout=10000)
        await pg.evaluate("jid => document.querySelector('.abh #passage').insertAdjacentHTML('afterend', `<div class=\"rh-needs\" data-at=\"${jid}/0\"><div id=\"rh-offer\"></div></div>`)", jid)
        await pg.evaluate("""() => { const p = document.querySelector('.abh #passage'); const r = document.createRange(); r.selectNodeContents(p.querySelector('.md p') || p); getSelection().removeAllRanges(); getSelection().addRange(r); }""")
        await pg.keyboard.press('Alt+KeyB')
        await pg.wait_for_timeout(1500)
        assert offers, offers
        await pg.locator('.abh #rh-offer .rh-offer-card').wait_for(timeout=15000)
        await pg.screenshot(path=f'{OUT}/p1-side-walk-offer.png')
    _run(tmp_path, scenario, dict(width=1500, height=900))


def test_key_chip_on_the_main_button_has_no_box_in_dark(tmp_path, monkeypatch):
    pytest.importorskip('playwright.async_api')
    lr, jid, slug = _env(tmp_path, monkeypatch)
    async def scenario(pg, ws, port):
        await pg.evaluate("applyTheme('leela:dark:relaxed')")
        await _open(pg, ws, jid)
        got = await pg.evaluate("() => { const k = document.querySelector('.abh button.go kbd'), c = getComputedStyle(k); return [c.backgroundColor, c.borderTopWidth, c.paddingLeft] }")
        assert got == ['rgba(0, 0, 0, 0)', '0px', '0px'], got
    _run(tmp_path, scenario, dict(width=1500, height=900))
