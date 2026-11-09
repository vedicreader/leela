"The agent head's ⋯ menu in a browser: no focus taken, keys, toggles that stay open, and what a new conversation posts."
import pytest

pytestmark = pytest.mark.slow

import asyncio, json
from pathlib import Path

pytest.importorskip('playwright.async_api')
from playwright.async_api import async_playwright   # noqa: E402

from test_web_slow import _serve, _free_port, _started, _launch, fake_model, fake_kernels   # noqa: E402
from leela.workspace import Workspace   # noqa: E402

SHOTS = Path(__file__).parents[1]/'target'/'agent-head'

async def _page(fn, **attrs):
    "The app with `attrs` set on its workspace, one page in playwright's own chromium, closed afterwards. Preference writes never leave the browser."
    restore = fake_kernels(); ws = Workspace(roots=[], approvals='auto'); fake_model(ws)
    for k, v in attrs.items(): setattr(ws, k, v)
    port = _free_port(); srv = _serve(ws, port); await _started(srv)
    try:
        async with async_playwright() as pw:
            b = await _launch(pw)
            try:
                pg = await b.new_page(viewport={'width': 1440, 'height': 900})
                await pg.route('**/settings/save', lambda r: asyncio.ensure_future(r.fulfill(status=200, content_type='application/json', body='{}')))
                await pg.goto(f'http://127.0.0.1:{port}/', wait_until='networkidle')
                await pg.wait_for_function('window.lee && lee.keys.length')
                return await fn(pg)
            finally: await b.close()
    finally:
        srv.should_exit = True; ws.shutdown_now(); restore()

def test_a_new_conversation_posts_the_workspace_defaults_and_then_the_chosen_toggles():
    async def go(pg):
        seen = []
        async def fulfil(route):
            seen.append(json.loads(route.request.post_data))
            await route.fulfill(status=200, content_type='application/json', body='{"ok": true, "active": "t1"}')
        await pg.route('**/agent/thread/new', lambda route: asyncio.ensure_future(fulfil(route)))
        await pg.evaluate("() => { leePane('right', true); leeRight('agent'); lee.prefs = {agent: {}}; localStorage.clear(); }")
        await pg.evaluate("() => leeAgentNew()")
        await pg.evaluate("() => { leeAgentWarmToggle(); leeAgentFullToggle(); leeAgentOptinToggle('research'); leeAgentOptinToggle('exhash'); }")
        await pg.evaluate("() => leeAgentNew()")
        return seen
    defaults, chosen = asyncio.run(_page(go, agent_optin=('research',), agent_profile='full'))
    pick = lambda d: {k: d[k] for k in ('warm', 'optin', 'profile')}
    assert pick(defaults) == {'warm': False, 'optin': ['research'], 'profile': 'full'}, defaults
    assert pick(chosen) == {'warm': True, 'optin': ['exhash'], 'profile': ''}, chosen

STATE = r"""() => {
  const m = document.querySelector('.lee-ctxmenu'), more = document.querySelector('#agentmore'), a = document.activeElement;
  return {open: !!m, role: m?.getAttribute('role'), inside: !!m?.contains(a), focus: a?.dataset?.action || a?.id || a?.tagName,
          expanded: more.getAttribute('aria-expanded'), dotted: more.classList.contains('dotted'), label: more.getAttribute('aria-label')};
}"""

def test_the_more_menu_takes_no_focus_on_load_answers_the_keyboard_and_keeps_toggles_open():
    async def go(pg):
        out = {'load': await pg.evaluate("() => ({menu: !!document.querySelector('.lee-ctxmenu'), focus: document.activeElement?.id || document.activeElement?.tagName})")}
        await pg.evaluate("() => { leePane('right', true); leeRight('agent'); }")
        await pg.wait_for_selector('#agentmore', state='visible')
        SHOTS.mkdir(parents=True, exist_ok=True)
        out['buttons'] = await pg.evaluate("() => [...document.querySelectorAll('.lee-agent-head button')].filter(b => b.offsetParent).length")
        await pg.locator('.lee-agent-head').screenshot(path=str(SHOTS/'after-head.png'))
        await pg.locator('.lee-agent-composer').screenshot(path=str(SHOTS/'after-composer.png'))
        await pg.click('#agentmore'); await pg.wait_for_selector('.lee-ctxmenu')
        out['clicked'] = await pg.evaluate(STATE)
        out['rows'] = await pg.evaluate("() => ({checks: document.querySelectorAll('.lee-ctxmenu [role=menuitemcheckbox]').length, accept: document.querySelector('[data-action=agent_accept]').disabled, new: document.querySelector('[data-action=agent_new] kbd')?.textContent || ''})")
        await pg.keyboard.press('ArrowDown'); out['down1'] = (await pg.evaluate(STATE))['focus']
        await pg.keyboard.press('ArrowDown'); out['down2'] = (await pg.evaluate(STATE))['focus']
        await pg.keyboard.press('Escape'); out['escaped'] = await pg.evaluate(STATE)
        await pg.evaluate("() => leeAct('agent_menu')"); await pg.wait_for_selector('.lee-ctxmenu')
        out['keymap'] = await pg.evaluate(STATE)
        await pg.keyboard.press('Escape'); out['keymap_escaped'] = await pg.evaluate(STATE)
        await pg.evaluate("() => { lee.prefs = {agent: {}}; localStorage.clear(); }")
        await pg.click('#agentmore'); await pg.wait_for_selector('.lee-ctxmenu')
        await pg.screenshot(path=str(SHOTS/'after-menu-closed-toggle.png'))
        await pg.click('[data-action=agent_calm]')
        await pg.wait_for_function("() => document.querySelector('[data-action=agent_calm]').getAttribute('aria-checked') === 'true'")
        out['calm'] = await pg.evaluate(f"() => ({{...({STATE})(), on: agentCalm()}})")
        await pg.screenshot(path=str(SHOTS/'after-menu-open.png'))
        await pg.click('[data-action=agent_calm]')
        out['calm_off'] = await pg.evaluate("() => [document.querySelector('[data-action=agent_calm]').getAttribute('aria-checked'), agentCalm()]")
        await pg.keyboard.press('Escape')
        return out
    got = asyncio.run(_page(go))
    assert got['load'] == {'menu': False, 'focus': got['load']['focus']} and 'agentmore' not in got['load']['focus'], got['load']
    assert got['buttons'] == 5, got   # the Learn toggle sits before More
    assert (got['clicked']['role'], got['clicked']['inside'], got['clicked']['expanded']) == ('menu', True, 'true'), got['clicked']
    assert got['rows']['checks'] == 8 and got['rows']['accept'] is True and got['rows']['new'], got['rows']
    assert (got['down1'], got['down2']) == ('agent_new', 'agent_threads'), got
    assert (got['escaped']['open'], got['escaped']['focus'], got['escaped']['expanded']) == (False, 'agentmore', 'false'), got['escaped']
    assert got['keymap']['role'] == 'menu' and got['keymap']['inside'] is True, got['keymap']
    assert (got['keymap_escaped']['open'], got['keymap_escaped']['focus']) == (False, 'agentmore'), got['keymap_escaped']
    assert got['calm']['open'] and got['calm']['on'] and got['calm']['dotted'] and 'calm' in got['calm']['label'], got['calm']
    assert got['calm_off'] == ['false', False], got
