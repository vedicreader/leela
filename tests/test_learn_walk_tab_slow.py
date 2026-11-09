import asyncio
from types import SimpleNamespace

import pytest

from tools.isolate import isolate

isolate()

pytestmark = pytest.mark.slow


def test_native_walk_tab_repaints_after_a_theme_change(tmp_path, monkeypatch):
    pytest.importorskip('playwright.async_api')
    from abhyasa.learner import temp_learning
    from playwright.async_api import async_playwright
    from leela.workspace import Workspace
    from tests.test_web_slow import _free_port, _launch, _serve, _started, fake_kernels
    from leela.blocks.learn import walk

    async def go():
        restore = fake_kernels()
        lr = temp_learning()
        memory = SimpleNamespace(path=tmp_path/'learning.db', _store=lambda shelf: lr.v)
        ws = Workspace(roots=[tmp_path.resolve()])
        monkeypatch.setattr(ws.vaults, 'memory', lambda name: memory)
        monkeypatch.setattr(walk, 'walk_state_for', lambda memory, jid, settings=None: dict(status='ok', revision='one', data=dict(title='Numbers', current=0, steps=[dict(i=0, name='Addition', statement='Add values.', status='open', quote=None, check=None)], gauge={})))
        port = _free_port(); srv = _serve(ws, port); await _started(srv)
        try:
            async with async_playwright() as pw:
                browser = await _launch(pw)
                try:
                    pg = await browser.new_page()
                    await pg.goto(f'http://127.0.0.1:{port}/', wait_until='networkidle')
                    await pg.wait_for_function('window.lee && lee.keys.length')
                    ws.open_learn_walk('workspace', 's3-walk'); ws.save()
                    await pg.evaluate("() => mountTab()")
                    await pg.locator('.lee-walk').screenshot(path='target/s3-walk-tab.png')
                    before = await pg.locator('.lee-walk').evaluate("el => getComputedStyle(el).color")
                    await pg.evaluate("applyTheme('nord:dark:tight')")
                    after = await pg.locator('.lee-walk').evaluate("el => getComputedStyle(el).color")
                    assert before != after
                finally: await browser.close()
        finally:
            srv.should_exit = True; ws.shutdown_now(); restore()
    asyncio.run(go())
