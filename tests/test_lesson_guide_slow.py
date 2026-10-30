import asyncio, json
from pathlib import Path
import pytest
from test_completion_caret_slow import _real_page

pytestmark = pytest.mark.slow
TOKEN = r'\bar\alpha_t'

def test_the_board_draws_a_mark_over_the_formula_part_the_tutor_names(tmp_path, monkeypatch):
    from leela.blocks.nb.lesson import lesson_notebook
    monkeypatch.setenv('PLAYWRIGHT_BROWSERS_PATH', str(Path.home()/'Library/Caches/ms-playwright'))
    home = tmp_path/'home'
    (home/'Library').mkdir(parents=True)
    (home/'Library/Keychains').symlink_to(Path.home()/'Library/Keychains', target_is_directory=True)
    monkeypatch.setenv('HOME', str(home))
    monkeypatch.setenv('XDG_DATA_HOME', str(tmp_path/'xdg-data'))
    monkeypatch.setenv('VISHALAKSHI_VAULT', str(tmp_path/'learning.db'))
    nb = lesson_notebook('Noise')
    nb[1].source = 'Alpha bar is the share left.\n\n$$ q=' + TOKEN + ' $$\n\n![A noisy cat](cat.png)'
    path = tmp_path/'noise.ipynb'; nb.save(path)
    posted = []
    board = dict(tier='tutor', steps=[dict(n=1, say='Alpha bar is the share of the picture left.', strokes=[dict(op='circle', at=dict(a='f1', tex=TOKEN))])],
                 sources=[], end='In the tutor\'s own words.', failed=False, dropped=0, demo_open=False, notes=[], ok=True)
    async def go(pg):
        await pg.set_viewport_size({'width': 1440, 'height': 1100})
        pg.set_default_timeout(15000)
        await pg.evaluate('p => leeOpenFile(p)', str(path))
        await pg.wait_for_function('lee.cells.length === 5')
        cell = pg.locator('.lee-cell[data-i="1"]')
        formula = cell.locator('[data-guide-id="f1"]')
        await formula.wait_for()
        await pg.wait_for_function("document.querySelector('.lee-cell[data-i=\"1\"] [data-guide-id=\"f1\"]').dataset.parts")
        ids = await cell.evaluate("c => [...c.querySelectorAll('[data-guide-id]')].map(e => e.dataset.guideId)")
        assert {'passage', 'f1', 'img1'} <= set(ids) and len(ids) == len(set(ids)), ids
        parts = json.loads(await formula.get_attribute('data-parts'))
        part_id = next(i for t, i in parts if t == TOKEN)
        async def fake(route):
            posted.append(json.loads(route.request.post_data))
            await route.fulfill(status=200, content_type='application/json', body=json.dumps(board))
        await pg.route('**/nb/guide', fake)
        await cell.locator('.lee-guide').click()
        await pg.locator('.lee-modal input').fill("I don't get alpha bar")
        await pg.locator('.lee-modal input').press('Enter')
        await pg.wait_for_function('window.abhyasaBoard?.state?.done === true')
        assert posted[0]['tokens']['f1'] and TOKEN in posted[0]['tokens']['f1'] and posted[0]['said'] == "I don't get alpha bar"
        got = await pg.evaluate("""id => { const r = e => { const b = e.getBoundingClientRect(); return [b.left, b.top, b.right, b.bottom]; };
          const part = document.getElementById(id), whole = document.querySelector('.lee-cell[data-i="1"] [data-guide-id="f1"]'), mark = document.querySelector('.board-hl .board-marker'),
                ring = document.querySelector('#board-layer g[data-op="circle"] path');
          return {part: r(part), whole: r(whole), mark: mark && r(mark), markPath: mark?.getAttribute('d')?.length || 0, ring: ring && r(ring), ringPath: ring?.getAttribute('d')?.length || 0,
                  off: document.querySelector('.lee-guide-out') === null}; }""", part_id)
        px0, py0, px1, py1 = got['part']; wx0, _, wx1, _ = got['whole']
        assert got['markPath'] > 0 and got['ringPath'] > 0 and got['off'], got
        mx0, my0, mx1, my1 = got['mark']
        assert abs(mx0 - px0) < 20 and abs(mx1 - px1) < 20 and my0 < py1 and my1 > py0, 'the marker lies over the part'
        assert (px1 - px0) < (wx1 - wx0) * .6, 'the part is smaller than the whole formula, so the mark is on the token and not on the formula'
        rx0, ry0, rx1, ry1 = got['ring']
        assert rx0 < px0 and rx1 > px1 and ry0 < py0 and ry1 > py1 and (rx1 - rx0) < (wx1 - wx0), 'the ring surrounds the part, not the whole formula'
    asyncio.run(_real_page(go, tmp_path))