"""What the IDE page costs a browser: bytes, parse, layout, and one file-tree refresh.

Drives a real Chromium over a generated project, so the numbers are the ones a user pays.

    python tools/profile_web.py                 # everything
    python tools/profile_web.py --dirs 40       # a wider tree
"""
from __future__ import annotations
import argparse, asyncio, json, subprocess, sys, tempfile, threading, time
from fastcore.all import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

def make_project(dirs, per, dirty):
    "A generated checkout: `dirs` directories of `per` files, `dirty` of them uncommitted."
    root = Path(tempfile.mkdtemp())
    for d in range(dirs):
        p = root/f'pkg{d//10:02d}'/f'mod{d:03d}'
        p.mkdir(parents=True, exist_ok=True)
        for f in range(per): (p/f'file_{f:02d}.py').write_text(f'x = {f}\n' * 30)
    git = lambda *a: subprocess.run(['git', *a], cwd=str(root), capture_output=True, text=True)
    git('init', '-q'); git('config', 'user.email', 'a@b.c'); git('config', 'user.name', 'a')
    git('add', '-A'); git('commit', '-qm', 'init')
    for f in sorted(root.rglob('*.py'))[:dirty]: f.write_text('changed = 1\n')
    return root

def serve(root, port):
    "A workspace on `port`, with the kernels stubbed out."
    from tools.shots import fake_kernels
    from leela.app import ide_app
    from leela.workspace import Workspace
    import uvicorn
    fake_kernels()
    ws = Workspace(roots=[root], port=port + 1000, agent='off')
    srv = uvicorn.Server(uvicorn.Config(ide_app(ws), host='127.0.0.1', port=port, log_level='error'))
    threading.Thread(target=srv.run, daemon=True).start()
    import urllib.request
    for _ in range(600):
        try:
            urllib.request.urlopen(f'http://127.0.0.1:{port}/', timeout=1).read(); return ws
        except Exception: time.sleep(.05)
    raise SystemExit('the workspace never came up')

MEASURE = '''() => {
  const nav = performance.getEntriesByType('navigation')[0] || {};
  const res = performance.getEntriesByType('resource');
  const wire = res.reduce((n, r) => n + (r.encodedBodySize || 0), 0);
  const decoded = res.reduce((n, r) => n + (r.decodedBodySize || 0), 0);
  const big = res.filter(r => (r.decodedBodySize || 0) > 40000)
    .map(r => ({name: r.name.split('/').pop().split('?')[0],
                wire: r.encodedBodySize, raw: r.decodedBodySize, ms: Math.round(r.duration)}))
    .sort((a, b) => b.raw - a.raw);
  return {
    domContentLoaded: Math.round(nav.domContentLoadedEventEnd || 0),
    loadEvent: Math.round(nav.loadEventEnd || 0),
    wire, decoded, assets: big,
    nodes: document.getElementsByTagName('*').length,
    heapMB: +((performance.memory?.usedJSHeapSize || 0) / 1048576).toFixed(1),
  };
}'''

TREE = '''async (n) => {
  // Expand until `n` directories are open -- breadth first, because the roots are all
  // that exist before the first one is fetched.
  while (document.querySelectorAll('.lee-dir[open]').length < n) {
    const next = [...document.querySelectorAll('.lee-dir')].filter(d => !d.open);
    if (!next.length) break;
    for (const d of next.slice(0, n)) {
      await window.loadTreeDir(d);
      if (document.querySelectorAll('.lee-dir[open]').length >= n) break;
    }
  }
  const opened = document.querySelectorAll('.lee-dir[open]').length;
  window.__reqs = 0;
  const realFetch = window.fetch;
  window.fetch = (...a) => { window.__reqs++; return realFetch(...a); };
  const t0 = performance.now();
  await window.refreshFileTree(undefined, false);
  const refresh = performance.now() - t0;
  const refreshReqs = window.__reqs;
  window.fetch = realFetch;
  const info = await (await realFetch('/git/info')).json();
  const t1 = performance.now();
  window.paintGitTree(info);
  const paint = performance.now() - t1;
  const t2 = performance.now();
  for (let i = 0; i < 20; i++) window.moveTreeSelection?.(1);
  const nav = performance.now() - t2;
  return {opened, refreshReqs, changes: (info.changes || []).length,
          refreshMs: +refresh.toFixed(1), paintMs: +paint.toFixed(1),
          navMs: +nav.toFixed(1), nodes: document.getElementsByTagName('*').length,
          heapMB: +((performance.memory?.usedJSHeapSize || 0) / 1048576).toFixed(1)};
}'''

ARM = '''() => {
  const tree = document.querySelector('#filetree');
  tree.scrollTop = 90;
  const row = document.querySelector('.lee-file');
  window.__row = row;
  return {dirs: document.querySelectorAll('.lee-dir[open]').length,
          rows: document.querySelectorAll('.lee-node').length, scroll: tree.scrollTop};
}'''

READ = '''() => ({
  dirs: document.querySelectorAll('.lee-dir[open]').length,
  rows: document.querySelectorAll('.lee-node').length,
  scroll: document.querySelector('#filetree').scrollTop,
  kept: document.contains(window.__row),
})'''

def chrome_path():
    "The Chromium playwright will actually find, whichever build is installed beside it."
    from fastcore.all import first
    return str(first(Path('/opt/pw-browsers').glob('chromium-*/chrome-linux/chrome')) or '') or None

TREE_URLS = ('/tree?', '/files/panel', '/git/info')

async def watch_probe(page, root, seen):
    "One change from outside, and one the client made itself, with the tree armed either way."
    out = {}
    mark = lambda: len([u for u in seen if any(x in u for x in TREE_URLS)])
    opened = await page.evaluate("() => [...document.querySelectorAll('.lee-dir[open]')].map(d => d.dataset.path)")
    home = Path(opened[-1]) if opened else Path(root)
    before, at = await page.evaluate(ARM), mark()
    (home/'from_elsewhere.py').write_text('brand = "new"\n')
    await page.wait_for_timeout(1400)
    out['theirs'] = {**await page.evaluate(READ), 'was': before, 'reqs': mark() - at}
    before, at = await page.evaluate(ARM), mark()
    mine = home/'mine.py'
    await page.evaluate("p => window.noteSelfWrite(p)", str(mine))
    mine.write_text('saved = "by me"\n')
    await page.wait_for_timeout(1400)
    out['mine'] = {**await page.evaluate(READ), 'was': before, 'reqs': mark() - at}
    return out

async def idle_traffic(page, seen, secs=12):
    "What the page asks for when nobody is doing anything. A desktop app pays this all day."
    at = len(seen)
    await page.wait_for_timeout(secs * 1000)
    urls = seen[at:]
    by = {}
    for u in urls: by[u.split('?')[0].rsplit('/', 1)[-1] or '/'] = by.get(u.split('?')[0].rsplit('/', 1)[-1] or '/', 0) + 1
    return {'total': len(urls), 'per_min': round(len(urls) * 60 / secs),
            'top': sorted(by.items(), key=lambda kv: -kv[1])[:6]}

async def drive(url, dirs, root):
    from playwright.async_api import async_playwright
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(executable_path=chrome_path(),
            args=['--enable-precise-memory-info', '--no-sandbox'])
        page = await browser.new_page(viewport={'width': 1600, 'height': 1000})
        requests = []
        page.on('request', lambda r: requests.append(r.url))
        await page.goto(url, wait_until='networkidle')
        await page.wait_for_timeout(800)
        load = await page.evaluate(MEASURE)
        before = len(requests)
        tree = await page.evaluate(TREE, dirs)
        tree['requests'] = len(requests) - before
        watch = await watch_probe(page, root, requests)
        idle = await idle_traffic(page, requests)
        await browser.close()
        return load, tree, watch, idle

def table(rows, head):
    w = [max(len(str(r[i])) for r in [head, *rows]) for i in range(len(head))]
    line = lambda r: '  '.join(str(c).ljust(w[i]) if not i else str(c).rjust(w[i]) for i, c in enumerate(r))
    print(line(head)); print('  '.join('-' * n for n in w))
    for r in rows: print(line(r))

def main(argv=None):
    p = argparse.ArgumentParser(prog='profile_web', description=__doc__.splitlines()[0])
    p.add_argument('--dirs', type=int, default=60)
    p.add_argument('--per', type=int, default=12)
    p.add_argument('--dirty', type=int, default=40)
    p.add_argument('--open', type=int, default=25, help='directories to expand before refreshing')
    p.add_argument('--port', type=int, default=5399)
    a = p.parse_args(argv)
    root = make_project(a.dirs, a.per, a.dirty)
    serve(root, a.port)
    load, tree, watch, idle = asyncio.run(drive(f'http://127.0.0.1:{a.port}/', a.open, root))
    print(f'\n## one cold page load — {a.dirs * a.per} files, {a.dirty} uncommitted\n')
    table([('bytes on the wire', f"{load['wire']:,}"),
           ('bytes after decoding', f"{load['decoded']:,}"),
           ('DOMContentLoaded', f"{load['domContentLoaded']}ms"),
           ('load', f"{load['loadEvent']}ms"),
           ('DOM nodes', f"{load['nodes']:,}"),
           ('JS heap', f"{load['heapMB']}MB")], ('measure', 'value'))
    print('\n### assets over 40KB\n')
    table([(x['name'], f"{x['wire']:,}", f"{x['raw']:,}", f"{x['ms']}ms") for x in load['assets']],
          ('asset', 'wire', 'raw', 'time'))
    print(f"\n## one file-tree refresh, {tree['opened']} directories open\n")
    table([('HTTP requests, one refresh', tree['refreshReqs']),
           ('HTTP requests, expand + refresh', tree['requests']),
           ('refreshFileTree', f"{tree['refreshMs']}ms"),
           (f"paintGitTree, {tree['changes']} changes", f"{tree['paintMs']}ms"),
           ('20 arrow-key moves', f"{tree['navMs']}ms"),
           ('DOM nodes after', f"{tree['nodes']:,}"),
           ('JS heap after', f"{tree['heapMB']}MB")], ('measure', 'value'))
    print('\n## one change from outside, and one the client made itself\n')
    table([(name, r['reqs'], f"{r['was']['rows']} → {r['rows']}", f"{r['was']['dirs']} → {r['dirs']}",
            f"{r['was']['scroll']} → {r['scroll']}", 'yes' if r['kept'] else 'NO')
           for name, r in (('a file appears from elsewhere', watch['theirs']),
                           ('the client saves its own', watch['mine']))],
          ('change', 'requests', 'rows', 'folders open', 'scroll', 'rows kept'))
    print(f"\n## what the page asks for while nobody touches it\n")
    table([('requests per minute, idle', idle['per_min'])] +
          [(f'  {name}', n) for name, n in idle['top']], ('measure', 'value'))
    print('\n  A push reconciles only the folder that changed, so expansion, scroll and every\n'
          '  untouched row survive it -- and a write the client made itself is not news.')

if __name__ == '__main__': main()
