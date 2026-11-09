"""A step page in a Leela tab keeps what you typed through a Hint, and refuses an empty answer."""
import pytest

from tools.isolate import isolate

isolate()
pytestmark = pytest.mark.slow

from test_learn_surface_walk_slow import _env, _open, _run   # noqa: E402


def _hints(be):
    old = be._oneshot
    be._oneshot = lambda p, sp, mt, deadline=None: 'Think about sums.' if 'Give hint level' in p else old(p, sp, mt, deadline)


def test_hint_and_a_late_swap_keep_the_typed_answer_and_send_needs_text(tmp_path, monkeypatch):
    pytest.importorskip('playwright.async_api')
    lr, jid = _env(monkeypatch)
    async def scenario(pg, ws, port, bad, be):
        _hints(be)
        ws.open_walk('workspace', jid); ws.save(); await pg.evaluate('mountTab()')
        await _open(pg, f'/w/{jid}/0', '.abh #check .check')
        abh = pg.locator('.abh')
        send, ans = abh.locator('#send'), abh.locator('#ans')
        assert await send.is_disabled()
        await ans.fill('   ')
        assert await send.is_disabled()
        await ans.fill('a draft of mine')
        await abh.locator('#think').fill('I think so')
        await abh.locator('[name=confidence][value="70"]').check()
        assert await send.is_enabled()
        await abh.locator('#hint').click()
        await abh.locator('#check .hint').wait_for(timeout=30000)
        await pg.wait_for_timeout(500)
        assert await ans.input_value() == 'a draft of mine'
        assert await abh.locator('#think').input_value() == 'I think so'
        assert await abh.locator('[name=confidence]:checked').get_attribute('value') == '70'
        assert await send.is_enabled()
        assert await pg.evaluate("document.activeElement?.id === 'ans' ? document.activeElement.selectionStart : -1") in (-1, len('a draft of mine'))
        await pg.keyboard.press('Alt+w')
        await pg.wait_for_timeout(1500)
        assert await ans.input_value() == 'a draft of mine'
        n = len(lr.attempts())
        await send.click()
        await abh.locator('#check').get_by_text('Look at positions.').wait_for(timeout=30000)
        assert len(lr.attempts()) == n + 1
        assert await abh.locator('#ans').input_value() == ''
        assert await abh.locator('#send').is_disabled()
        assert not bad, bad
    _run(tmp_path, scenario)


def test_missing_walk_in_the_tab_shows_a_short_box_inside_the_container(tmp_path, monkeypatch):
    pytest.importorskip('playwright.async_api')
    lr, jid = _env(monkeypatch)
    async def scenario(pg, ws, port, bad, be):
        ws.open_walk('workspace', jid); ws.save(); await pg.evaluate('mountTab()')
        await _open(pg, '/w/nope/0', '.abh .not-here')
        abh = pg.locator('.abh')
        assert 'This walk is not here.' in await abh.locator('.not-here').text_content()
        assert await abh.locator('.not-here a', has_text='Go Home').count() == 1
        assert await abh.locator('link[rel=canonical], h1').count() == 0
    _run(tmp_path, scenario)
