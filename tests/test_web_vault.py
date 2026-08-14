"""The vault's three browser surfaces, driven in a real browser.

The fragments are unit-tested in `tests/blocks/test_vault_surface.py`. What only a browser can
show is the wiring between them: a menu action that reaches the right document, htmx swapping a
job card into a panel it just loaded, and a badge that does not fetch until its row is seen.
"""

# drives a real browser through playwright, so it is out of the default run. `pytest -m slow` or `-m ""` includes it.
import pytest

pytestmark = pytest.mark.slow

import pytest

from conftest import serve

from leela.workspace import Workspace

pytest.importorskip('playwright.sync_api')


@pytest.fixture
def proj(tmp_path):
    (tmp_path/'notes.md').write_text('# Retrieval\n\nDurable notes about recall and ranking.\n')
    return tmp_path


def _open(pw, url):
    page = pw.chromium.launch(headless=True).new_page(viewport={'width': 1440, 'height': 900})
    page.goto(url, wait_until='networkidle')
    if page.locator('.lee-modal').count(): page.keyboard.press('Escape')
    return page


def _vault(page):
    "The vault view, which lives behind the right pane's memory tab."
    page.click('.lee-righttab[data-right="memory"]')
    page.click('[data-memory-view="vault"]')
    page.wait_for_selector('#vaultpanel')


def test_clipping_a_tree_file_opens_the_vault_on_its_own_job(proj):
    """The whole affordance: right-click a file, clip it, and watch it land.

    The panel is fetched before the clip is posted, because the job card swaps into it. Getting
    that order wrong loses the card silently -- htmx drops a swap whose target does not exist.
    """
    from playwright.sync_api import sync_playwright
    ws = Workspace(roots=[proj])
    with serve(ws) as url, sync_playwright() as pw:
        page = _open(pw, url)
        page.click('.lee-node.lee-root')          # roots render collapsed; the file is inside it
        page.wait_for_selector('.lee-node.lee-file')
        page.click('.lee-node.lee-file', button='right')
        page.wait_for_selector('.lee-ctxmenu')
        assert page.locator('.lee-menuitem', has_text='clip into the vault').count() == 1
        page.click('.lee-menuitem:has-text("clip into the vault")')

        page.wait_for_selector('#vaultpanel')
        assert page.locator('.lee-righttab[data-right="memory"].active').count() == 1
        assert page.locator('[data-memory-view="vault"].active').count() == 1, 'the nav follows'
        card = page.locator('#vaultjobs .lee-job').first
        card.wait_for()
        assert 'notes.md' in card.inner_text()
        page.wait_for_selector('#vaultjobs .lee-job.complete', timeout=20_000)
        assert ws.memory.documents(), 'the document reached the shelf'


def test_review_is_asked_for_and_answers_even_when_there_is_nothing_to_drop(proj):
    """Review swaps a list in; a shelf the ranker has no opinion about says so.

    The judgement round-trip is pinned at the route in `test_jobs.py`, because whether a corpus
    scores above the noise threshold is the ranker's business and not a thing to fake here.
    """
    from playwright.sync_api import sync_playwright
    ws = Workspace(roots=[proj])
    ws.memory.clip([proj/'notes.md'])
    with serve(ws) as url, sync_playwright() as pw:
        page = _open(pw, url)
        _vault(page)
        assert page.locator('#vaulttidy').inner_text() == '', 'nothing is scored until asked for'

        page.click('.lee-vault-tidy .lee-btn')
        page.wait_for_function("document.querySelector('#vaulttidy')?.innerText.trim().length > 0")
        rows = page.locator('.lee-tidy-row')
        if not rows.count():
            assert 'too small to have an opinion' in page.locator('#vaulttidy').inner_text()
            return
        rows.first.locator('button:has-text("keep")').click()
        page.wait_for_selector('.lee-tidy-row.judged')
        assert 'kept' in page.locator('.lee-tidy-row.judged').first.inner_text()


def test_a_pii_badge_loads_itself_and_says_what_it_found(proj):
    "The badge is lazy because a scan reads a whole document, and honest because coverage is partial."
    from playwright.sync_api import sync_playwright
    (proj/'minute.md').write_text('# Minute\n\nSigned by Dr Charles Babbage, ada@example.com.\n')
    ws = Workspace(roots=[proj])
    ws.memory.clip(list(proj.glob('*.md')))
    with serve(ws) as url, sync_playwright() as pw:
        page = _open(pw, url)
        doc = (ws.memory.documents() or [{}])[0]
        page.goto(f"{url}/vault/pii/badge?doc={doc.get('doc_id') or doc.get('id')}", wait_until='networkidle')
        badge = page.locator('.lee-pii')
        assert badge.count() == 1
        assert 'no pattern found' in badge.inner_text() or '×' in badge.inner_text()
        assert 'never looked for' in (badge.get_attribute('title') or ''), 'it must not imply "none"'


def test_a_document_in_the_panel_opens_as_a_reader_tab(proj):
    "The whole path a person takes: memory → vault → a document → its sections."
    from playwright.sync_api import sync_playwright
    ws = Workspace(roots=[proj])
    ws.memory.clip([proj/'notes.md'])
    with serve(ws) as url, sync_playwright() as pw:
        page = _open(pw, url)
        _vault(page)
        page.wait_for_selector('.lee-vault-doc')
        assert 'notes' in page.locator('.lee-vault-doc').first.inner_text()

        page.click('.lee-vault-doc')
        page.wait_for_selector('.lee-vault-reader')
        assert page.locator('.lee-vault-section').count() >= 1, 'the section rail is drawn'
        page.wait_for_function("document.querySelector('.lee-vault-text')?.innerText.trim().length > 0")
        assert 'ranking' in page.locator('.lee-vault-text').inner_text().lower()
        assert 'no pattern found' in page.locator('.lee-vault-reader').inner_text()
        assert page.locator('.lee-tab', has_text='notes').count() >= 1, 'it is a tab, not a modal'
