"The notice for a project with no Python environment, and the choice a run asks for, in a real browser."
import pytest
pytestmark = [pytest.mark.slow, pytest.mark.no_venv]

import json, tempfile
from pathlib import Path

from test_web_slow import _run   # noqa: E402

def _project():
    "A Python project in a resolved temporary folder, with no venv: macOS gives /var and /private/var for the same folder."
    root = Path(tempfile.mkdtemp()).resolve()/'proj'; root.mkdir()
    (root/'pyproject.toml').write_text('')
    nb = root/'a.ipynb'
    nb.write_text(json.dumps({'cells': [{'cell_type': 'code', 'id': 'c0', 'source': 'df', 'metadata': {}, 'outputs': [], 'execution_count': None}],
                              'metadata': {}, 'nbformat': 4, 'nbformat_minor': 5}))
    return root, nb

def test_the_notice_stays_until_answered_and_a_run_asks_then_runs(monkeypatch):
    "Leela made the venv itself; now the person sees why nothing can run, and the run goes on after their click."
    import kunda.support as ks
    root, nb = _project()
    made = []
    def fake(r, python=None):
        assert Path(r) == root, 'only the temporary project'
        made.append(r); py = Path(r)/'.venv'/'bin'/'python'; py.parent.mkdir(parents=True)
        py.write_text('#!/bin/sh\nexit 1\n'); py.chmod(0o755)
        return str(py)
    monkeypatch.setattr(ks, 'make_venv', fake)
    async def go(pg):
        await pg.evaluate('p => leeOpenFile(p)', str(nb))
        bar = pg.locator('#venvnotice')
        await bar.wait_for()
        assert (await bar.locator('span').text_content()) == 'No Python environment for proj.'
        await pg.reload(wait_until='networkidle'); await pg.wait_for_function('window.lee && lee.keys.length')
        await bar.wait_for()
        await bar.get_by_text('Not now').click()
        await bar.wait_for(state='detached')
        await pg.reload(wait_until='networkidle'); await pg.wait_for_function('window.lee && lee.keys.length')
        await pg.wait_for_timeout(500)
        assert not await bar.count(), 'Not now holds for this session'
        async with pg.context.expect_page() as other:
            await pg.evaluate("window.open(location.href, '_blank', 'noopener')")
        second = await other.value
        await second.wait_for_function('window.lee && lee.keys.length')
        await second.locator('#venvnotice').wait_for()
        await second.close()
        assert not made and not (root/'.venv').exists()
        await pg.wait_for_selector('.lee-cell')
        await pg.evaluate('() => { runCell(0); }')
        ask = pg.locator('.lee-python-ask')
        await ask.wait_for()
        assert 'No Python environment for proj' in await ask.text_content()
        await ask.get_by_text('Set up .venv').click()
        await pg.wait_for_function("() => (document.querySelector('#out-c0')?.textContent || '').includes('<df>')")
        assert made == [root] and (root/'.venv').exists()
        await pg.evaluate('() => refreshKernelPill()')
        await pg.wait_for_timeout(300)
        assert not await pg.locator('#venvnotice').count()
    _run(go, roots=[root])
