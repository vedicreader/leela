import asyncio
import pytest
from test_rupaka_slow import _page, _open, fence
from leela.blocks.nb.lesson import lesson_notebook
from leela.blocks.nb.nb import Notebook
from rupaka.spec import gallery

pytestmark = pytest.mark.slow


def test_prediction_retry_then_unaided_transfer(tmp_path, monkeypatch):
    from leela.blocks.nb import app
    monkeypatch.setattr(app, 'grade_explanation', lambda *a: dict(status='pending'))
    nb = lesson_notebook('Projectile range'); nb[1].source = fence(gallery()['throw-angle'])
    path = tmp_path/'throw.ipynb'; nb.save(path)
    async def go(pg):
        await _open(pg, path)
        host = pg.locator('.lee-cell[data-i="1"] .lee-rupaka')
        await host.locator('button.go').wait_for()
        await host.locator('.opts button', has_text='60').dispatch_event('click')
        await host.locator('textarea').fill('Complementary angles have the same sine of twice the angle.')
        await pg.route('**/lesson/predict', lambda route: route.fulfill(status=503, json=dict(error='Not saved. Retry.')))
        await host.locator('button.go').click()
        await host.get_by_role('button', name='Retry', exact=True).wait_for()
        assert await host.locator('p.verdict').is_hidden()
        assert await host.locator('.rk-slider').first.evaluate("e => e.classList.contains('rk-locked')")
        await pg.unroute('**/lesson/predict')
        await host.get_by_role('button', name='Retry', exact=True).click()
        await host.locator('p.verdict').wait_for()
        await host.get_by_text('Explanation: not graded yet').wait_for()
        async with pg.expect_response(lambda r: r.url.endswith('/nb/edit') and r.request.post_data_json.get('op') == 'rupaka_trial'):
            await host.get_by_role('button', name='Keep this run', exact=True).click()
        await host.get_by_role('button', name='Try a new case', exact=True).click()
        transfer = host.locator('.lee-rupaka-transfer')
        await transfer.locator('.opts button').first.wait_for()
        assert await host.locator('.rk-plot').first.is_hidden()
        await transfer.get_by_text('To reach transfer:', exact=False).wait_for()
        await transfer.locator('.opts button', has_text='70').dispatch_event('click')
        async with pg.expect_response('**/lesson/transfer') as saved: await transfer.locator('button.go').click()
        result = await (await saved.value).json()
        assert result['ok'] and result['aided'] is False
        await transfer.get_by_text('Counted as apply. One more new case, on your own, to reach transfer.', exact=True).wait_for()
        assert Notebook.load(path)[1].extra['rupaka']['throw-angle']['transfer']['filed']
        await transfer.get_by_role('button', name='Try a new case', exact=True).click()
        await transfer.get_by_text('At the same speed, which other angle lands as far as 15 degrees?', exact=True).wait_for()
        assert await transfer.locator('.rk-plot').count() == 0
        await transfer.locator('.opts button', has_text='75').dispatch_event('click')
        async with pg.expect_response('**/lesson/transfer') as saved: await transfer.locator('button.go').click()
        result = await (await saved.value).json()
        assert result['message'] == 'Transfer reached.' and result['progress']['depth'] == 5
        await transfer.get_by_text('Transfer reached.', exact=True).wait_for()
        assert await transfer.get_by_role('button', name='Try a new case', exact=True).count() == 0
    asyncio.run(_page(go, tmp_path))
