import pytest

from tools.isolate import isolate

isolate()
pytestmark = pytest.mark.slow

MIC = """(mode) => {
  window.__posts = [];
  const f = window.fetch; window.fetch = (u, o) => { if (String(u).includes('/speech/')) window.__posts.push(String(u).replace(/\\?.*/, '')); return f(u, o); };
  navigator.mediaDevices.getUserMedia = async () => {
    if (mode === 'denied') throw new DOMException('Permission denied', 'NotAllowedError');
    const ac = new AudioContext(), dest = ac.createMediaStreamDestination(), osc = ac.createOscillator();
    osc.frequency.value = 220; osc.connect(dest); osc.start(); return dest.stream;
  };
}"""


@pytest.fixture
def engine(monkeypatch):
    import abhyasa.models as m
    from leela.blocks.learn import speech
    monkeypatch.setattr(m, 'cached', lambda model: True)
    monkeypatch.setattr(m, 'transcribe', lambda audio, engine=None, hint='', model=None: 'spoken words')
    monkeypatch.setattr(speech, 'TOLD', set())


def run(go):
    from tests.test_web_slow import _run
    return _run(go)


def test_permission_denied_says_so_and_leaves_no_button(engine):
    async def go(pg):
        await pg.evaluate("leeRight('agent')")
        await pg.locator('#agentprompt').click()
        await pg.evaluate(MIC, 'denied')
        await pg.evaluate("leeAct('dictate')")
        await pg.wait_for_function("document.querySelector('#status')?.textContent.includes('microphone did not start')")
        await pg.wait_for_function("!document.querySelector('#mic-dictate')")
        return await pg.evaluate("window.__posts")
    posts = run(go)
    assert '/speech/ready' in posts and '/speech/start' not in posts


def test_dictate_listens_into_the_agent_prompt_and_stops_on_the_second_run(engine):
    async def go(pg):
        await pg.evaluate("leeRight('agent')")
        await pg.locator('#agentprompt').click()
        await pg.evaluate(MIC, 'ok')
        await pg.evaluate("leeAct('dictate')")
        await pg.wait_for_selector('#mic-dictate.on', state='attached')
        await pg.wait_for_timeout(1500)
        await pg.evaluate("leeAct('dictate')")
        await pg.wait_for_function("!document.querySelector('#mic-dictate')", timeout=15000)
        return await pg.evaluate("[window.__posts, document.querySelector('#agentprompt').value, document.querySelector('#status')?.textContent]")
    posts, text, said = run(go)
    assert all(any(p.startswith(u) for p in posts) for u in ('/speech/ready', '/speech/start', '/speech/seg/', '/speech/stop/'))
    assert 'microphone did not start' not in (said or '') and 'failed' not in (said or '')
    assert 'spoken words' in text
