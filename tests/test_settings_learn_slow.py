import json
from pathlib import Path
import pytest
from playwright.async_api import expect
from tests.test_web_slow import _run
from leela.blocks.settings.settings import user_settings_file

pytestmark = pytest.mark.slow

def test_learn_settings_save_and_reload(tmp_path, cfg_home):
    user = Path(user_settings_file())
    assert user.parent.resolve() == cfg_home.resolve()
    async def go(pg):
        await pg.evaluate("leeEditorSettings('')")
        await pg.locator('[data-settings-page="learn"]').click()
        page = pg.locator('[data-settings-section="learn"]')
        await expect(page.locator('h4').first).to_be_visible()
        fold = page.locator('[data-learn-more]').first
        await fold.locator('summary').click()
        await expect(fold).to_have_attribute('open', '')
        value = page.locator('[data-pref="walks.passage"]')
        await value.fill('700')
        await pg.locator('[data-save]').click()
        await expect(pg.locator('.lee-settings-modal')).to_have_count(0)
        assert json.loads(user.read_text())['learn']['walks.passage'] == 700
        await pg.reload(wait_until='networkidle')
        await pg.wait_for_function('window.lee && lee.keys.length')
        await pg.evaluate("leeEditorSettings('')")
        await pg.locator('[data-settings-page="learn"]').click()
        await page.locator('[data-learn-more]').first.locator('summary').click()
        await expect(value).to_have_value('700')
        assert await pg.evaluate("lee.learnPrefs['walks.passage']") == 700
        shot = Path('target/s1-learn-settings.png')
        shot.parent.mkdir(parents=True, exist_ok=True)
        await pg.screenshot(path=str(shot), full_page=True)
    _run(go, roots=[tmp_path.resolve()])
