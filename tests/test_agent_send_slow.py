"A sent prompt shows in the agent pane before the server accepts the turn, and a refused one goes back in the box."
import asyncio, json
import pytest

pytestmark = pytest.mark.slow

CARD = """q => [...document.querySelectorAll('#agentlog .lee-agent-turn')].filter(c => c.querySelector('.lee-user-message-body')?.textContent === q)
  .map(c => ({sending: c.classList.contains('sending')}))"""

async def _send(pg, q, presses=1):
    await pg.fill('#agentprompt', q)
    await pg.focus('#agentprompt')
    for _ in range(presses): await pg.keyboard.press('ControlOrMeta+Enter')

async def _go(pg):
    await pg.evaluate("() => { leePane('right', true); leeRight('agent'); }")
    await pg.wait_for_selector('#agentprompt')
    posts, out = [], {}
    async def slow(route):
        posts.append(json.loads(route.request.post_data or '{}'))
        await asyncio.sleep(1.5); await route.continue_()
    await pg.route('**/agent/turn', slow)
    await _send(pg, 'first question', presses=2)
    await pg.wait_for_timeout(300)
    out['early'] = dict(cards=await pg.evaluate(CARD, 'first question'), box=await pg.input_value('#agentprompt'), posts=len(posts))
    await pg.wait_for_function("() => !lee.agentSending && !lee.agentBusy", timeout=20000)
    out['accepted'] = dict(cards=await pg.evaluate(CARD, 'first question'), posts=len(posts))
    await pg.unroute('**/agent/turn')
    async def refuse(route):
        await asyncio.sleep(.8)
        await route.fulfill(status=409, content_type='application/json',
            body=json.dumps({'ok': False, 'code': 'thread_busy', 'message': 'the assistant is already working', 'thread': ''}))
    await pg.route('**/agent/turn', refuse)
    await _send(pg, 'second question')
    await pg.wait_for_timeout(300)
    out['pending'] = await pg.evaluate(CARD, 'second question')
    await pg.wait_for_function("() => !lee.agentSending", timeout=10000)
    out['refused'] = dict(cards=await pg.evaluate(CARD, 'second question'), box=await pg.input_value('#agentprompt'),
                          status=await pg.evaluate("() => document.querySelector('#status')?.textContent || ''"))
    return out

def test_a_sent_prompt_shows_at_once_and_a_refused_one_comes_back(tmp_path):
    "The pane awaited POST /agent/turn before it drew anything, and the reply waited on a model probe and the system prompt."
    pytest.importorskip('playwright.async_api')
    from test_completion_caret_slow import _real_page
    out = asyncio.run(_real_page(_go, tmp_path))
    assert out['early'] == dict(cards=[{'sending': True}], box='', posts=1), out   # drawn before the reply; a second press sent nothing
    assert out['accepted'] == dict(cards=[{'sending': False}], posts=1), out
    assert out['pending'] == [{'sending': True}], out
    assert out['refused']['cards'] == [] and out['refused']['box'] == 'second question', out
    assert 'already working' in out['refused']['status'], out
