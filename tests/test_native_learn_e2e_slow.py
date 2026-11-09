r"""Native Learn end to end: acceptance A1, A2, A4, A5 and A7 in a headless browser, on a scripted model that sends nothing off the machine.

A missing route or tool fails the test with its name. The contracts it is written against: `POST /agent/learn-mode {on}`, tab kind `learn_walk` hosting Abhyasa's real step page in `.abh`, `GET /learn/walk/{jid}`, `POST /learn/walk/{jid}/{i}/answer`.
"""
import asyncio, importlib.util, inspect, json, re
from pathlib import Path
import pytest

HERE = Path(__file__).resolve().parent
TOPIC = 'teach me fractions'
WALK = r'/w/([^/?#]+)/\d+(?:[?#].*)?$'

def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod

def test_the_launcher_parses_its_options_and_refuses_real_stores(tmp_path):
    tn = _load('try_native_learn', HERE.parent/'tools'/'try_native_learn.py')
    a = tn.parse([])
    assert a.port is None and a.copy_vault is None and a.state is None
    a = tn.parse(['--copy-vault', 'v.db', '--state', 'S', '--port', '5200'])
    assert (a.copy_vault, a.state, a.port) == ('v.db', 'S', 5200)
    assert tn.free_port() not in (None, 5001) and not tn.busy(tn.free_port())
    with pytest.raises(SystemExit): tn.pick_port(5001)
    assert tn.pick_port(None) != 5001 and tn.pick_port(5200) == 5200
    sl = _load('scripted_learn', HERE.parent/'tools'/'scripted_learn.py')
    assert 'fractions' in sl.reply('Plan a walk', 'plan').lower() and '"question"' in sl.reply('Write ONE question on x', 'tutor') and '"correct"' in sl.reply('Grade this', 'You grade one answer')
    real = tmp_path/'real'
    assert tn.refused([real/'a', tmp_path/'other'], [real]) == [str((real/'a').resolve())]
    iso = tn.load_isolate()
    assert tn.refused([Path.home()/'.config'/'leela'/'workspace.json'], iso.REAL_STORES)
    assert not tn.refused(iso.isolated_env(tmp_path).values(), iso.REAL_STORES)
    src, dest = tmp_path/'src.db', tmp_path/'iso'/'vault.db'
    src.write_bytes(b'vault')
    tn.copy_vault(src, dest)
    assert dest.read_bytes() == b'vault'
    with pytest.raises(SystemExit): tn.copy_vault(src, dest)

def _missing(status, what):
    if status in (404, 405): pytest.fail(f'{what} answered {status}')

def _find(o, key):
    "The first value stored under `key` anywhere in the JSON `o`."
    for v in (o.values() if isinstance(o, dict) else o if isinstance(o, list) else ()):
        if (r := _find(v, key)) is not None: return r
    return o.get(key) if isinstance(o, dict) else None

def _gauge(j):
    g = _find(j, 'gauge')
    return g if g is not None else _find(j, 'understanding')

async def _api(pg, method, url, body=None):
    return await pg.evaluate(r"""async ([m, u, b]) => {
      const r = await fetch(u, {method: m, headers: {'Content-Type': 'application/json', 'Accept': 'application/json'}, body: b === null ? undefined : JSON.stringify(b)});
      let j = null; try { j = await r.json(); } catch (e) {}
      return {status: r.status, json: j};
    }""", [method, url, body])

def _tool_names(tools): return [t[0] if isinstance(t, tuple) else getattr(t, '__name__', t) for t in tools]   # TOOLS holds (name, arguments) pairs

def _learn_tool(ws, name):
    "The scripted model's way to call the advertised create tool `name`: the topic goes in its first parameter."
    def find(_name):
        if (f := next((t for t in ws.ai.tools if getattr(t, '__name__', '') == name), None)) is None: return None
        first = next(iter(inspect.signature(f).parameters), None)
        return (lambda **kw: f(**{first: TOPIC})) if first else (lambda **kw: f())
    return find

def _learn_names(ws, names): return [n for n in _tool_names(ws.ai.tools) if n in names]

def _result(res, ERRORS):
    "The engine result of a response; an `error` status fails with whether its code is a known one."
    j = res['json']
    if j.get('status') == 'error':
        err = j.get('error'); code = err.get('code') if isinstance(err, dict) else err
        pytest.fail(f'engine error {err!r} {j.get("data")}, in ERRORS: {code in ERRORS}')
    return j

@pytest.mark.slow
def test_ask_for_a_module_in_the_pane_opens_a_native_walk_and_a_check_moves_the_gauge(tmp_path, monkeypatch):
    pytest.importorskip('playwright.async_api')
    from playwright.async_api import async_playwright
    from ramabana.core import ModelSpec
    from leela.workspace import Workspace
    from test_web_slow import fake_kernels, _free_port, _serve, _started, _launch
    from tests.fakemodel import install, Step
    from tools.scripted_learn import reply
    try: from abhyasa.agent_tools import ERRORS, TOOLS
    except ImportError as e: pytest.fail(f'abhyasa.agent_tools does not import: {e}')
    names = _tool_names(TOOLS)
    create = next((n for n in names if 'create' in n), None)
    assert create, f'abhyasa.agent_tools.TOOLS has no create tool: {names}'
    try: import psutil
    except ImportError: psutil = None
    monkeypatch.setenv('VISHALAKSHI_VAULT', str(tmp_path/'vault.db'))
    monkeypatch.setenv('LEELA_MEMORY_OFFLINE', '1')
    listening = lambda: {c.laddr.port for c in psutil.Process().net_connections(kind='tcp') if c.status == psutil.CONN_LISTEN}
    before_ports = listening() if psutil else set()
    async def go():
        restore = fake_kernels()
        ws = Workspace(roots=[tmp_path.resolve()], approvals='auto')
        be = install(ws, [Step(text='Making your module.', tool=(create, {}))], token_delay=0,
                     spec=ModelSpec('hosted-scripted', 'remote', 'scripted/model', ctx=8000))
        be.supports_deadline = True
        be._oneshot, be._tool = reply, _learn_tool(ws, create)
        port = _free_port(); srv = _serve(ws, port); await _started(srv)
        jids, out = [], {}
        def note(r):
            if (m := re.search(WALK, r.url)): jids.append(m[1])
        try:
            async with async_playwright() as pw:
                b = await _launch(pw)
                try:
                    pg = await b.new_page(); pg.on('request', note)
                    await pg.goto(f'http://127.0.0.1:{port}/', wait_until='networkidle')
                    await pg.wait_for_function('window.lee && lee.keys.length')
                    on = await _api(pg, 'POST', '/agent/learn-mode', {'on': True})
                    _missing(on['status'], 'POST /agent/learn-mode')
                    assert on['status'] == 200, on
                    out['tools_on'] = _learn_names(ws, names)
                    await pg.evaluate("() => leeRight('agent')")
                    await pg.fill('#agentprompt', TOPIC)
                    await pg.evaluate('() => sendAgent()')
                    await pg.wait_for_selector('#agentlog .lee-agent-turn')
                    try:
                        await pg.wait_for_function("""() => lee.kind === 'learn_walk' || document.querySelector('.lee-tab[data-kind="learn_walk"]')""", timeout=30000)
                    except Exception as e:
                        jobs = [(j.status, j.error, j.result) for j in ws.jobs.all(kind='learn_walk')]
                        pytest.fail(f'no learn_walk tab opened after the turn: {e}\njobs: {jobs}\ntabs: {[(t.kind, t.ref) for t in ws.tabs]}\nagent log: {await pg.inner_text("#agentlog")}')
                    assert await pg.locator('.lee-tab[data-kind="learn_walk"]').count() == 1, 'the walk tab is in the tab strip, with no reload'
                    assert await pg.evaluate('() => document.activeElement && document.activeElement.id') == 'agentprompt', 'the new tab leaves focus in the agent prompt'
                    await pg.wait_for_selector('.abh #check .check', timeout=30000)
                    assert jids, 'the walk tab never asked GET /w/{jid}/{i}'
                    jid = jids[-1]
                    assert not await pg.evaluate("() => !!document.activeElement?.closest('.abh')"), 'the walk page took focus'
                    out['job'] = next((j for j in ws.jobs.all(kind='learn_walk') if (j.result or {}).get('walk') == jid), None)
                    vq = '?vault=' + json.loads(next(t for t in ws.tabs if t.kind == 'learn_walk').ref)[0]
                    first = await _api(pg, 'GET', f'/learn/walk/{jid}{vq}')
                    _missing(first['status'], 'GET /learn/walk/{jid}')
                    out['first'] = first
                    await pg.locator('.abh #ans').fill('add the numerators')
                    await pg.locator('.abh #send').click()
                    await pg.locator('.abh #check .tag, .abh #check .msg').first.wait_for(timeout=30000)
                    out['ui_answered'] = await pg.locator('.abh #check').inner_text()
                    out['ui_after'] = await _api(pg, 'GET', f'/learn/walk/{jid}{vq}')
                    out['quoted'] = await pg.locator('.abh blockquote a[href]').count()
                    out['ungrounded'] = bool(re.search(r"tutor.s words|find a source|ungrounded", await pg.inner_text('.abh'), re.I))
                    now = _find(out['ui_after']['json'], 'current') or 0
                    body = {'answer': 'add the numerators', 'attempt_id': 'e2e-attempt-1'}
                    ans = await _api(pg, 'POST', f'/learn/walk/{jid}/{now}/answer{vq}', body)
                    _missing(ans['status'], 'POST /learn/walk/{jid}/{i}/answer')
                    out['answer'] = ans
                    out['retry'] = await _api(pg, 'POST', f'/learn/walk/{jid}/{now}/answer{vq}', body)
                    out['after'] = await _api(pg, 'GET', f'/learn/walk/{jid}{vq}')
                    cards, hist = await pg.locator('#agentlog .lee-agent-turn').count(), len(be.hist_)
                    off = await _api(pg, 'POST', '/agent/learn-mode', {'on': False})
                    out['off'] = off
                    out['tools_off'] = _learn_names(ws, names)
                    out['kept'] = (await pg.locator('#agentlog .lee-agent-turn').count() >= cards, len(be.hist_) >= hist, ws.ai._be() is be)
                    out['frames'] = await pg.evaluate("() => document.querySelectorAll('iframe, frame, embed, object').length")
                    out['new_ports'] = (listening() - before_ports) if psutil else {port}
                finally: await b.close()
        finally:
            srv.should_exit = True
            ws.shutdown_now()
            restore()
        return out, port
    out, port = asyncio.run(asyncio.wait_for(go(), 150))
    assert out['tools_on'], 'A5: Learn mode on advertises the learn tools'
    assert out['job'] and out['job'].status == 'complete', 'A1: the create_walk job completes'
    assert out['quoted'] or out['ungrounded'], 'A2: a linked quote, or a tutor-words label'
    ans, retry = _result(out['answer'], ERRORS), _result(out['retry'], ERRORS)
    assert ans['status'] == 'ok' and retry == ans, 'A4: a retry returns the stored result'
    g0, g1 = _gauge(out['first']['json']), _gauge(out['after']['json'])
    assert g0 is not None and g1 != g0, f'A4: the gauge moved from {g0!r} to {g1!r}'
    assert out['ui_answered'].strip() and _gauge(out['ui_after']['json']) != g0, 'A4: answering in the tab moves the gauge'
    assert out['off']['status'] == 200 and not out['tools_off'], 'A5: Learn mode off removes the learn tools'
    assert all(out['kept']), 'A5: history and the backend remain'
    assert out['frames'] == 0, 'A7: no iframe'
    assert out['new_ports'] == {port}, 'A7: the app port is the only new listener'
