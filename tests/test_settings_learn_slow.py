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
        await pg.locator('[data-settings-language]').select_option('python')
        await pg.locator('[data-settings-scope]').select_option('workspace')
        await pg.locator('[data-settings-page="learn"]').click()
        await expect(pg.locator('[data-settings-scope]')).to_have_value('user')
        await expect(pg.locator('[data-settings-language]')).to_have_value('')
        await pg.locator('[data-settings-page="editor"]').click()
        await expect(pg.locator('[data-settings-scope]')).to_have_value('workspace')
        await expect(pg.locator('[data-settings-language]')).to_have_value('python')
        await pg.locator('[data-settings-page="learn"]').click()
        await expect(pg.locator('[data-settings-scope]')).to_have_value('user')
        page = pg.locator('[data-settings-section="learn"]')
        await expect(page.locator('h4').first).to_be_visible()
        await expect(pg.locator('[data-settings-scope]')).to_be_disabled()
        await expect(pg.locator('[data-settings-language]')).to_be_disabled()
        await expect(pg.locator('[data-learn-scope]')).to_be_visible()
        pct = page.locator('[data-percent]').first
        key = await pct.get_attribute('data-pref')
        await pct.evaluate("el => { const fold = el.closest('details'); if (fold) fold.open = true; }")
        await pct.fill('42')
        toggle = page.locator('.lee-settings-checks input[type=checkbox]').first
        assert await toggle.evaluate("el => getComputedStyle(el.closest('label')).display") == 'flex'
        value = page.locator('[data-pref="walks.passage"]')
        fold = value.locator('xpath=ancestor::details')   # not the first fold: the speech group has one too
        await fold.evaluate('el => el.open = true')
        await expect(fold).to_have_attribute('open', '')
        await value.fill('700')
        async with pg.expect_request(lambda r: r.url.endswith('/settings/save')) as req:
            await pg.locator('[data-save]').click()
        sent = (await req.value).post_data_json
        assert sent['scope'] == 'user' and not sent['language'] and sent['section'] == 'learn'
        await expect(pg.locator('.lee-settings-modal')).to_have_count(0)
        assert json.loads(user.read_text())['learn']['walks.passage'] == 700
        assert json.loads(user.read_text())['learn'][key] == .42
        await pg.reload(wait_until='networkidle')
        await pg.wait_for_function('window.lee && lee.keys.length')
        await pg.evaluate("leeEditorSettings('')")
        await pg.locator('[data-settings-page="learn"]').click()
        await fold.locator('summary').click()
        await expect(value).to_have_value('700')
        assert await pg.evaluate("lee.learnPrefs['walks.passage']") == 700
        await expect(page.locator(f'[data-pref="{key}"]')).to_have_value('42')
        await pg.locator('[data-settings-page="editor"]').click()
        await expect(pg.locator('[data-settings-scope]')).to_be_enabled()
        await expect(pg.locator('[data-settings-scope]')).to_have_value('workspace')
        await expect(pg.locator('[data-settings-language]')).to_be_enabled()
        await pg.locator('[data-settings-page="learn"]').click()
        shot = Path('target/s1-learn-settings.png')
        shot.parent.mkdir(parents=True, exist_ok=True)
        await pg.screenshot(path=str(shot), full_page=True)
    _run(go, roots=[tmp_path.resolve()])
