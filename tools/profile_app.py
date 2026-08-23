"""What the desktop app costs to start and to hold open.

Every measurement runs in a fresh subprocess, and is the best of a few runs: import cost is
order-dependent, RSS is cumulative, and a cold page cache makes the first run a lie.

    python tools/profile_app.py                # all three
    python tools/profile_app.py --imports      # what is on the startup path, and its cost
    python tools/profile_app.py --server       # a running workspace: startup and resident size
    python tools/profile_app.py --browser      # bytes and time per screencast frame
"""
from __future__ import annotations
import argparse, json, os, subprocess, sys, tempfile, textwrap
from fastcore.all import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable

# Heavy third-party roots worth naming. Leela's server has no use for any of them, so seeing one
# means a dependency dragged it in.
WATCH = ('pandas', 'IPython', 'numpy', 'matplotlib', 'torch', 'scipy')

PRELUDE = '''
import os, sys, time
sys.path.insert(0, {root!r})
os.environ['XDG_CONFIG_HOME'] = {cfg!r}
os.environ['LEELA_MEMORY_OFFLINE'] = '1'
os.environ['VISHALAKSHI_VAULT'] = {vault!r}

def rss():
    "Resident set size in MB. `/proc` where there is one, else the peak from getrusage."
    try:
        for line in open('/proc/self/status'):
            if line.startswith('VmRSS'): return int(line.split()[1]) // 1024
    except OSError: pass
    import resource
    n = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return n // (1024 if sys.platform != 'darwin' else 1024 * 1024)
'''

def run(body):
    "Run `body` in a fresh interpreter with the prelude, and parse the JSON line it prints."
    env = dict(os.environ, XDG_CONFIG_HOME=tempfile.mkdtemp())
    src = PRELUDE.format(root=str(ROOT), cfg=tempfile.mkdtemp(),
                         vault=tempfile.mkdtemp() + '/vault.db') + textwrap.dedent(body)
    out = subprocess.run([PY, '-c', src], capture_output=True, text=True, timeout=600, env=env)
    line = next((l for l in reversed(out.stdout.splitlines()) if l.startswith('{')), None)
    if line is None: raise SystemExit(f'measurement failed:\n{out.stdout[-2000:]}\n{out.stderr[-2000:]}')
    return json.loads(line)

def best(body, n=3, key='ms'):
    "The fastest of `n` runs. A cold import measures the page cache, not the code."
    return min([run(body) for _ in range(n)], key=lambda r: r.get(key, 0))

def table(rows, head):
    w = [max(len(str(r[i])) for r in [head, *rows]) for i in range(len(head))]
    line = lambda r: '  '.join(str(c).ljust(w[i]) if i == 0 else str(c).rjust(w[i]) for i, c in enumerate(r))
    print(line(head))
    print('  '.join('-' * n for n in w))
    for r in rows: print(line(r))

IMPORT = '''
import json
t = time.perf_counter()
import {mod}
ms = (time.perf_counter() - t) * 1000
heavy = sorted(m for m in {watch!r} if m in sys.modules)
print(json.dumps(dict(ms=round(ms), rss=rss(), mods=len(sys.modules), heavy=heavy)))
'''

MODULES = ('leela', 'leela.desktop', 'leela_app', 'fasthtml.common', 'dhrishti.core',
           'dhrishti.serving', 'leela.workspace', 'leela.blocks.runtime.kernels', 'leela.app')

def imports():
    "Every module on the path from `leela_app` to a served page, measured on its own."
    print('\n## import cost — a fresh interpreter per row\n')
    rows = []
    for mod in MODULES:
        try: r = best(IMPORT.format(mod=mod, watch=WATCH))
        except SystemExit: rows.append((mod, 'n/a', 'n/a', 'n/a', 'not installed')); continue
        rows.append((mod, f"{r['ms']}ms", f"{r['rss']}MB", r['mods'], ' '.join(r['heavy']) or '—'))
    table(rows, ('module', 'time', 'peak rss', 'modules', 'heavy deps pulled in'))

SERVER = '''
import json, threading, urllib.request
t0 = time.perf_counter()
from tools.shots import fake_kernels
from leela.app import ide_app
from leela.workspace import Workspace
t_import = time.perf_counter()
fake_kernels()
ws = Workspace(roots=[{proj!r}], port=8000)
app = ide_app(ws)
t_build = time.perf_counter()
import uvicorn
srv = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port={port}, log_level='error'))
threading.Thread(target=srv.run, daemon=True).start()
url = 'http://127.0.0.1:{port}/'
while True:
    try:
        urllib.request.urlopen(url, timeout=1).read(); break
    except Exception: time.sleep(0.01)
t_first = time.perf_counter()
idle = rss()
for _ in range(10): urllib.request.urlopen(url, timeout=10).read()
print(json.dumps(dict(ms=round((t_first - t0) * 1000),
                      imp=round((t_import - t0) * 1000),
                      build=round((t_build - t_import) * 1000),
                      serve=round((t_first - t_build) * 1000),
                      rss=idle, after=rss(),
                      heavy=sorted(m for m in {watch!r} if m in sys.modules))))
'''

def server():
    "Process start to a page served, and what the process weighs once it is."
    proj = Path(tempfile.mkdtemp())
    (proj/'hello.py').write_text('x = 1\n')
    r = best(SERVER.format(proj=str(proj), port=5321, watch=WATCH), n=3)
    print('\n## a running workspace\n')
    table([('import leela.app + workspace', f"{r['imp']}ms"),
           ('build Workspace + ide_app', f"{r['build']}ms"),
           ('bind and serve the first page', f"{r['serve']}ms"),
           ('total, process start to page', f"{r['ms']}ms"),
           ('resident, idle', f"{r['rss']}MB"),
           ('resident, after 10 renders', f"{r['after']}MB"),
           ('heavy deps resident', ' '.join(r['heavy']) or '—')],
          ('measure', 'value'))

BROWSER = '''
import base64, json, statistics, threading, urllib.parse, urllib.request
import http.server, functools, tempfile
from pathlib import Path
os.environ['FOSSICK_ALLOW_PRIVATE'] = '1'

site = Path(tempfile.mkdtemp())
(site/'index.html').write_text(
    "<!doctype html><meta charset=utf-8><title>frames</title>"
    "<style>body{{margin:0;font:16px sans-serif}}#b{{width:100vw;height:100vh;"
    "background:linear-gradient(90deg,#fff,#456)}}</style><div id=b></div>"
    "<script>let n=0;setInterval(()=>{{n=(n+7)%100;"
    "document.getElementById('b').style.filter='hue-rotate('+n*3+'deg)'}},40)</script>")
h = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(site))
sv = http.server.ThreadingHTTPServer(('127.0.0.1', 0), h)
sv.RequestHandlerClass.log_message = lambda *a, **k: None
threading.Thread(target=sv.serve_forever, daemon=True).start()
url = f'http://127.0.0.1:{{sv.server_address[1]}}/index.html'

from starlette.testclient import TestClient
from tools.shots import fake_kernels
from leela.app import ide_app
from leela.workspace import Workspace
from leela.blocks.browser.browser import Browser
from leela.desktop import start_cdp
import subprocess

def chrome_rss(port):
    "RSS and process count for the Chrome on `port`, children included."
    try:
        root = int(subprocess.run(['pgrep', '-f', f'remote-debugging-port={{port}}'],
                                  capture_output=True, text=True).stdout.split()[0])
    except (IndexError, ValueError, OSError): return 0, 0
    rows = [l.split() for l in subprocess.run(['ps', '-eo', 'pid,ppid,rss'],
            capture_output=True, text=True).stdout.splitlines()[1:]]
    kids, rss = {{}}, {{}}
    for r in rows:
        if len(r) != 3: continue
        kids.setdefault(int(r[1]), []).append(int(r[0])); rss[int(r[0])] = int(r[2])
    seen, stack, total = set(), [root], 0
    while stack:
        p = stack.pop()
        if p in seen: continue
        seen.add(p); total += rss.get(p, 0); stack += kids.get(p, [])
    return total // 1024, len(seen)

fake_kernels()
proj = Path(tempfile.mkdtemp()); (proj/'a.py').write_text('x=1\\n')
ws = Workspace(roots=[proj], port=8000)
profile = Path(tempfile.mkdtemp())/'chrome'
start_cdp({cdp}, headless=True, wait=True, timeout=120, profile=str(profile))
time.sleep(2)
chrome_idle, procs_idle = chrome_rss({cdp})
ws.browser = Browser(port={cdp}, headless=True, profile=profile)

with TestClient(ide_app(ws)) as c:
    before = rss()
    c.get('/browser/open?url=' + urllib.parse.quote(url, safe=''))
    tid = ws.tabs[ws.active].ref
    sizes, kinds = [], []
    t0 = time.perf_counter()
    with c.websocket_connect('/browser/ws') as sock:
        sock.send_text(json.dumps(dict(id=tid, w=1200, h=800)))
        while len(sizes) < {frames}:
            m = sock.receive()
            if 'bytes' in m and m['bytes'] is not None:
                sizes.append(len(m['bytes'])); kinds.append('binary')
                continue
            d = json.loads(m['text'])
            if d['t'] == 'frame':
                sizes.append(len(d.get('data') or '')); kinds.append('base64')
            elif d['t'] == 'error': raise SystemExit(d['error'])
    secs = time.perf_counter() - t0
    chrome, procs = chrome_rss({cdp})
    print(json.dumps(dict(ms=round(secs * 1000), frames=len(sizes),
                          wire=round(statistics.mean(sizes)) if sizes else 0,
                          kind=kinds[0] if kinds else '-',
                          fps=round(len(sizes) / secs, 1) if secs else 0,
                          rss_before=before, rss=rss(),
                          chrome_idle=chrome_idle, chrome_procs_idle=procs_idle,
                          chrome=chrome, chrome_procs=procs, heavy=[])))
'''

def browser(frames=40):
    "What one streaming tab adds: bytes on the wire per frame, and megabytes held."
    sys.path.insert(0, str(ROOT))
    from leela.blocks.browser.browser import Browser
    if not Browser().available():
        print('\n## one inline browser tab, streaming\n\nskipped: no Chrome on this machine to '
              'render into. Install one, or set $FASTCDP_CHROME.')
        return
    r = run(BROWSER.format(cdp=9430, frames=frames))
    print('\n## one inline browser tab, streaming\n')
    table([('frames sampled', r['frames']),
           ('transport', r['kind']),
           ('mean bytes per frame, on the wire', f"{r['wire']:,}"),
           ('frames per second', r['fps']),
           ('workspace rss before the tab', f"{r['rss_before']}MB"),
           ('workspace rss while streaming', f"{r['rss']}MB"),
           ('chrome, idle', f"{r['chrome_idle']}MB in {r['chrome_procs_idle']} processes"),
           ('chrome, holding the page', f"{r['chrome']}MB in {r['chrome_procs']} processes")],
          ('measure', 'value'))
    print('\nChrome is the larger half of the application by far, which is why it is started\n'
          'by the first page that needs one rather than at launch. `ps` counts shared pages\n'
          'once per process, so the totals overstate what is actually held.')

def main(argv=None):
    p = argparse.ArgumentParser(prog='profile_app', description=__doc__.splitlines()[0])
    p.add_argument('--imports', action='store_true')
    p.add_argument('--server', action='store_true')
    p.add_argument('--browser', action='store_true')
    a = p.parse_args(argv)
    todo = a.imports or a.server or a.browser
    if a.imports or not todo: imports()
    if a.server or not todo: server()
    if a.browser or not todo: browser()

if __name__ == '__main__': main()
