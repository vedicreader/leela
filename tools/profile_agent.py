"""What one streaming agent turn costs the page it is painted into.

The agent pane repaints as the reply arrives, and every repaint used to rebuild the reply's code
blocks from scratch. This drives a scripted model through a real browser and counts the work:
editors constructed, renders asked for, and how long the main thread was blocked.

    python tools/profile_agent.py             # one turn, four code blocks
    python tools/profile_agent.py --blocks 8  # a longer reply
"""
from __future__ import annotations
import argparse, asyncio, subprocess, sys, tempfile, threading, time

from fastcore.all import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT/'tests'))
from tools.isolate import isolate; isolate()   # never the person's real stores

CODE = '''```python
def step_{n}(rows, keep={n}):
    "One pass over the frame, keeping the {n} widest columns."
    out = [r for r in rows if len(r) >= keep]
    return sorted(out, key=len, reverse=True)[:keep]
```'''

def reply(blocks):
    "A reply of the shape that hurts: prose, then a fenced block, over and over."
    parts = []
    for n in range(1, blocks + 1):
        parts.append(f'Step {n} narrows the frame before the join, so the shuffle stays small '
                     f'and the plan does not spill. Here is the pass it runs:')
        parts.append(CODE.format(n=n))
    return '\n\n'.join(parts)

def make_project():
    root = Path(tempfile.mkdtemp())
    (root/'pkg').mkdir()
    (root/'pkg'/'mod.py').write_text('x = 1\n' * 40)
    git = lambda *a: subprocess.run(['git', *a], cwd=str(root), stdin=subprocess.DEVNULL, capture_output=True, text=True)
    git('init', '-q'); git('config', 'user.email', 'a@b.c'); git('config', 'user.name', 'a')
    git('add', '-A'); git('commit', '-qm', 'init')
    return root

def serve(root, port, blocks, delay):
    "A workspace on `port` whose model is a script, so the turn is the same every run."
    import uvicorn

    from fakemodel import Step, install
    from tools.shots import fake_kernels

    from leela.app import ide_app
    from leela.workspace import Workspace
    fake_kernels()
    ws = Workspace(roots=[root], port=port + 1000, agent='off', approvals='auto')
    install(ws, [Step(text=reply(blocks))], token_delay=delay)
    srv = uvicorn.Server(uvicorn.Config(ide_app(ws), host='127.0.0.1', port=port, log_level='error'))
    threading.Thread(target=srv.run, daemon=True).start()
    import urllib.request
    for _ in range(600):
        try:
            urllib.request.urlopen(f'http://127.0.0.1:{port}/', timeout=1).read(); return ws
        except Exception: time.sleep(.05)
    raise SystemExit('the workspace never came up')

#: Counters the page keeps for us. `createEditor` is the bundle's own wrapper, not `LeeCM.create`:
#: esbuild exports its module namespace through getters with no setter, so patching `LeeCM` is a
#: silent no-op and every count comes back zero. `longtask` is every stretch the main thread could
#: not have answered a keystroke in.
ARM = '''() => {
  window.__editors = 0; window.__editorMs = 0;
  const real = window.createEditor;
  window.createEditor = (...a) => {
    const t = performance.now();
    try { return real(...a); } finally { window.__editors++; window.__editorMs += performance.now() - t; }
  };
  window.__carried = 0, window.__enhanceMs = 0, window.__enhanced = 0;
  const realEnhance = window.enhanceCodeBlocks;
  window.enhanceCodeBlocks = (el) => {
    // Surfaces this pass inherited from the last one: the work reuse is saving.
    window.__carried += (el._leeCodeSurfaces || new Map()).size;
    const t = performance.now();
    try { return realEnhance(el); } finally { window.__enhanced++; window.__enhanceMs += performance.now() - t; }
  };
  window.__long = [];
  try {
    new PerformanceObserver(list => { for (const e of list.getEntries()) window.__long.push(e.duration); })
      .observe({entryTypes: ['longtask']});
  } catch (_) {}
  // Scroll samples: a pane that is settled sits at the bottom, and one that is fighting itself
  // does not. `gap` is how far from the bottom the pane was when we looked.
  window.__gaps = [];
  const log = document.querySelector('#agentlog');
  window.__gapTimer = setInterval(() => {
    window.__gaps.push(Math.round(log.scrollHeight - log.scrollTop - log.clientHeight));
  }, 50);
  return true;
}'''

READ = '''() => {
  clearInterval(window.__gapTimer);
  const long = window.__long || [], gaps = window.__gaps || [];
  const settled = gaps.filter(g => g > 60).length;
  return {
    editors: window.__editors, carried: window.__carried,
    editorMs: Math.round(window.__editorMs), enhanced: window.__enhanced,
    enhanceMs: Math.round(window.__enhanceMs),
    longTasks: long.length, longMs: Math.round(long.reduce((a, b) => a + b, 0)),
    worstMs: Math.round(Math.max(0, ...long)),
    gapSamples: gaps.length, gapsOffBottom: settled,
    worstGap: Math.max(0, ...gaps),
    codeBlocks: document.querySelectorAll('#agentlog pre > code').length,
    surfaces: document.querySelectorAll('#agentlog .lee-code-surface').length,
    cmInLog: document.querySelectorAll('#agentlog .cm-editor').length,
    prose: [...document.querySelectorAll('#agentlog .lee-timeline-prose')]
      .map(p => [p.querySelectorAll('.lee-code-surface').length,
                 p.querySelectorAll('pre > code').length,
                 (p._leeCodeSurfaces || new Map()).size,
                 (p.dataset.markdown || '').length]),
    nodes: document.getElementsByTagName('*').length,
    heapMB: +((performance.memory?.usedJSHeapSize || 0) / 1048576).toFixed(1),
  };
}'''

SEND = '''async (prompt) => {
  const box = document.querySelector('#agentprompt');
  box.value = prompt;
  window.sendAgent();
  const began = performance.now();
  while (performance.now() - began < 120000) {
    if (!window.lee.agentBusy && document.querySelector('.lee-agent-progress.complete')) break;
    await new Promise(r => setTimeout(r, 100));
  }
  return Math.round(performance.now() - began);
}'''

async def drive(url, prompt):
    from playwright.async_api import async_playwright
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(args=['--enable-precise-memory-info', '--no-sandbox'])
        page = await browser.new_page(viewport={'width': 1600, 'height': 1000})
        requests = []
        page.on('request', lambda r: requests.append(r.url))
        await page.goto(url, wait_until='networkidle')
        await page.wait_for_timeout(800)
        await page.evaluate(ARM)
        at = len(requests)
        secs = await page.evaluate(SEND, prompt)
        await page.wait_for_timeout(500)
        out = await page.evaluate(READ)
        urls = requests[at:]
        out['turnMs'] = secs
        out['renders'] = sum(1 for u in urls if '/markdown/render' in u)
        out['requests'] = len(urls)
        await browser.close()
        return out

def table(rows, head):
    w = [max(len(str(r[i])) for r in [head, *rows]) for i in range(len(head))]
    line = lambda r: '  '.join(str(c).ljust(w[i]) if not i else str(c).rjust(w[i]) for i, c in enumerate(r))
    print(line(head)); print('  '.join('-' * n for n in w))
    for r in rows: print(line(r))

def main(argv=None):
    p = argparse.ArgumentParser(prog='profile_agent', description=__doc__.splitlines()[0])
    p.add_argument('--blocks', type=int, default=4, help='fenced code blocks in the reply')
    p.add_argument('--delay', type=float, default=0.012, help='seconds between streamed words')
    p.add_argument('--port', type=int, default=5397)
    a = p.parse_args(argv)
    root = make_project()
    serve(root, a.port, a.blocks, a.delay)
    out = asyncio.run(drive(f'http://127.0.0.1:{a.port}/', 'explain the plan'))
    print(f'\n## one streamed turn — {a.blocks} code blocks\n')
    table([('turn, wall clock', f"{out['turnMs']}ms"),
           ('CodeMirror views built', out['editors']),
           ('CodeMirror views carried over', out['carried']),
           ('time building them', f"{out['editorMs']}ms"),
           ('enhanceCodeBlocks passes', out['enhanced']),
           ('time in enhanceCodeBlocks', f"{out['enhanceMs']}ms"),
           ('code surfaces left in the log', f"{out['surfaces']} ({out['cmInLog']} editors, "
                                             f"{out['codeBlocks']} bare)"),
           ('/markdown/render requests', out['renders']),
           ('HTTP requests, whole turn', out['requests']),
           ('long tasks (>50ms)', out['longTasks']),
           ('main thread blocked', f"{out['longMs']}ms"),
           ('worst single task', f"{out['worstMs']}ms"),
           ('scroll samples off the bottom', f"{out['gapsOffBottom']}/{out['gapSamples']}"),
           ('worst gap from the bottom', f"{out['worstGap']}px"),
           ('DOM nodes', f"{out['nodes']:,}"),
           ('JS heap', f"{out['heapMB']}MB")], ('measure', 'value'))
    print()

if __name__ == '__main__': main()
