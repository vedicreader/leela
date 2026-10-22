"Switching and closing tabs while the language server is slow."

import pytest

pytestmark = pytest.mark.slow

import threading

pytest.importorskip('playwright.async_api')

from test_web_slow import _run   # noqa: E402

NAMES = ['a.py', 'b.py', 'c.py', 'd.py', 'e.py']

SWITCH = r"""async (i) => {
  const tabs = document.querySelectorAll('.lee-tab'), want = tabs[i].title, t0 = performance.now(), m = {};
  tabs[i].click();
  for (;;) {
    await new Promise(r => requestAnimationFrame(r));
    if (lee.path === want && document.querySelector('#editor .cm-content')) break;
    if (performance.now() - t0 > 8000) { m.timeout = true; break; }
  }
  await new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)));
  m.painted = performance.now() - t0;
  await new Promise(r => setTimeout(r, 700));
  const mine = window._reqs.filter(([u, t]) => t >= t0);
  m.lsp = mine.filter(([u]) => u.includes('/lsp/')).map(([u, t]) => t - t0);
  m.saveAll = mine.filter(([u]) => u.includes('/tabs/save-all')).length;
  m.urls = mine.map(([u]) => u.split('?')[0]);
  const sel = performance.getEntriesByType('resource').filter(e => e.name.includes('/tab/select') && e.startTime >= t0);
  m.stalled = sel.map(e => e.requestStart - e.startTime);
  return m;
}"""


def test_a_tab_switch_is_not_queued_behind_the_previous_tabs_language_server_calls(tmp_path, monkeypatch):
    """Each mount left a language-server and lint call held for seconds, six of them filled the browser's connections to the host, and the next `/tab/select` waited for one to free."""
    from leela.blocks.lsp.lsp import LspService
    for n in NAMES: (tmp_path/n).write_text(f'x = {n!r}\n')
    gate = threading.Event()
    def slow(self, *a, **k): gate.wait(10)
    def slow_diagnostics(self, *a, **k): gate.wait(10); return [], ''
    monkeypatch.setattr(LspService, 'request', slow)
    monkeypatch.setattr(LspService, 'diagnostics', slow_diagnostics)

    async def go(pg):
        await pg.evaluate("""() => {
          lee.editorPrefs.inlayHints = true; window._reqs = []; const f = window.fetch;
          window.fetch = (u, o) => { window._reqs.push([String(u), performance.now()]); return f(u, o); };
        }""")
        for n in NAMES:
            p = str(tmp_path/n)
            await pg.evaluate('p => leeOpenFile(p)', p)
            await pg.wait_for_function("p => lee.path === p && document.querySelector('#editor .cm-content')", arg=p)
            await pg.wait_for_timeout(700)
        out = [await pg.evaluate(SWITCH, i) for i in (0, 1, 2, 3, 0, 4)]
        gate.set()
        return out
    out = _run(go, roots=[tmp_path])
    for m in out:
        assert not m.get('timeout'), out
        assert m['painted'] < 300, f"a switch painted after {m['painted']:.0f}ms"
        assert all(s < 50 for s in m['stalled']), f"/tab/select waited {m['stalled']}ms for a connection"
        assert all(t >= m['painted'] for t in m['lsp']), f"a language-server call began before the paint: {m['lsp']} vs {m['painted']}"
        assert m['saveAll'] == 0, 'a clean switch still posted /tabs/save-all'
    for m in out[1:]:
        again = [u for u in m['urls'] if u in ('/workspace/info', '/cwd', '/git/info')]
        assert not again, f'a switch within one folder asked for the folder again: {again}'
