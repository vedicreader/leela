"""Every theme family, applied in a real browser.

The CSS blocks are checked for completeness in `tests/blocks/test_themes.py`. What only a browser
can show is that applying a family actually repaints: that the resolved `data-mode` lands on
<html>, that `--lee-bg` changes, and that the bundle parses at all (node is not available here).
"""

# drives a real browser through playwright, so it is out of the default run. `pytest -m slow` or `-m ""` includes it.
import pytest

pytestmark = pytest.mark.slow

from conftest import serve

from leela.workspace import Workspace

pytest.importorskip('playwright.sync_api')

FAMILIES = ['leela', 'cursor', 'vscode', 'jetbrains', 'solarized', 'gruvbox', 'nord', 'dracula']


@pytest.fixture
def proj(tmp_path):
    (tmp_path/'main.py').write_text('x = 1\n')
    return tmp_path


def _open(pw, url):
    page = pw.chromium.launch(headless=True).new_page(viewport={'width': 1440, 'height': 900})
    page.goto(url, wait_until='networkidle')
    if page.locator('.lee-modal').count(): page.keyboard.press('Escape')
    return page


def _bg(page): return page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--lee-bg').trim()")


def test_every_family_repaints_and_resolves_a_mode(proj):
    ws = Workspace(roots=[proj])
    with serve(ws) as url:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            page = _open(pw, url)
            seen = {}
            for family in FAMILIES:
                for mode in ('dark', 'light', 'system'):
                    page.evaluate('([f, m]) => applyTheme({family: f, mode: m})', [family, mode])
                    assert page.evaluate('document.documentElement.dataset.theme') == family
                    resolved = page.evaluate('document.documentElement.dataset.mode')
                    assert resolved in ('dark', 'light')
                    if mode != 'system': assert resolved == mode
                    assert page.evaluate('document.documentElement.style.colorScheme') == resolved
                    assert page.evaluate("localStorage.getItem('lee-theme')").startswith(f'{family}:{mode}:')
                    seen[family, resolved] = _bg(page)
            assert len(set(seen.values())) > len(FAMILIES)   # families do not share one background


def test_following_the_system_flips_without_a_reload(proj):
    """The point of `system`: a machine that turns dark at sunset turns leela dark too."""
    ws = Workspace(roots=[proj])
    with serve(ws) as url:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            page = browser.new_page(viewport={'width': 1440, 'height': 900})
            page.emulate_media(color_scheme='light')
            page.goto(url, wait_until='networkidle')
            if page.locator('.lee-modal').count(): page.keyboard.press('Escape')
            page.evaluate("applyTheme('gruvbox:system')")
            assert page.evaluate('document.documentElement.dataset.mode') == 'light'
            light = _bg(page)
            page.emulate_media(color_scheme='dark')
            page.wait_for_function("document.documentElement.dataset.mode === 'dark'")
            assert _bg(page) != light


def test_density_and_palette_are_independent(proj):
    """The ask: cursor's tightness with leela's colours. Header height must move, colours must not."""
    ws = Workspace(roots=[proj])
    with serve(ws) as url:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            page = _open(pw, url)
            head = lambda: page.evaluate("document.querySelector('.lee-header').getBoundingClientRect().height")
            page.evaluate("applyTheme('leela:dark:relaxed')")
            relaxed, bg = head(), _bg(page)
            page.evaluate("applyTheme('leela:dark:tight')")
            assert page.evaluate('document.documentElement.dataset.density') == 'tight'
            assert head() < relaxed                          # the chrome really did thin
            assert _bg(page) == bg                           # and the palette did not move
            page.reload(wait_until='networkidle')
            assert page.evaluate('document.documentElement.dataset.density') == 'tight'


def test_a_pre_family_preference_is_migrated_not_reset(proj):
    ws = Workspace(roots=[proj])
    with serve(ws) as url:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            page = _open(pw, url)
            page.evaluate("localStorage.setItem('lee-theme', 'dark')")
            page.reload(wait_until='networkidle')
            assert page.evaluate('document.documentElement.dataset.theme') == 'leela'
            assert page.evaluate('document.documentElement.dataset.mode') == 'dark'
            assert page.evaluate('document.documentElement.dataset.density') == 'relaxed'
            page.wait_for_function("localStorage.getItem('lee-theme') === 'leela:dark:relaxed'")


def test_the_bundle_parses(proj):
    """`node` is blocked here, so the browser is the syntax check."""
    ws = Workspace(roots=[proj])
    with serve(ws) as url:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            page = pw.chromium.launch(headless=True).new_page()
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)))
            page.goto(f'{url}/leestatic/nothing-here')   # a bare 404 on the app's own origin
            page.add_script_tag(url=f'{url}/leestatic/lee-ide.js')
            page.wait_for_timeout(200)
            assert not errors, errors


def test_the_picker_lists_families_with_a_variant_control(proj):
    ws = Workspace(roots=[proj])
    with serve(ws) as url:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            page = _open(pw, url)
            page.evaluate('leeEditorSettings()')
            page.wait_for_selector('.lee-settings-modal')
            page.click('[data-settings-page="appearance"]')
            assert page.locator('.lee-theme-choice').count() == len(FAMILIES)
            assert page.locator('[data-theme-mode]').count() == 3
            assert page.locator('[data-theme-density]').count() == 2
            page.click('[data-theme-density="relaxed"]')
            assert page.evaluate('document.documentElement.dataset.density') == 'relaxed'
            page.click('.lee-theme-mode[data-theme-mode="dark"]')
            page.click('.lee-theme-choice[data-theme="nord"]')
            assert page.evaluate('document.documentElement.dataset.theme') == 'nord'
            assert page.evaluate('document.documentElement.dataset.mode') == 'dark'
            page.click('[data-cancel]')                     # cancelling puts the original back
            assert page.evaluate('document.documentElement.dataset.theme') != 'nord'
