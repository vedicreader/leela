"The runs menu: a run whose command has finished but whose process is still up can be stopped."
import json, shutil, subprocess
from pathlib import Path
import pytest

LOGS = Path(__file__).parents[1]/'leela'/'blocks'/'runs'/'logs.js'

# logs.js in Node with the browser globals it touches stubbed: `api` answers /dev/list from `servers`
# and records every call, `openChromeMenu` records the rows the menu would show.
HARNESS = r'''
const vm = require('vm'), fs = require('fs');
const [src, servers] = [fs.readFileSync(process.argv[1], 'utf8'), JSON.parse(process.argv[2])];
const calls = [], menus = [];
const el = new Proxy(function () {}, {get: (t, k) => k === Symbol.toPrimitive ? () => '' : el, apply: () => el, set: () => true});
const ctx = {
  console, setTimeout, clearTimeout, setInterval: () => 0, clearInterval() {}, Map, Set, JSON, Promise, encodeURIComponent,
  lee: {terms: new Map()}, $: () => null, document: el, status() {}, openExternal() {}, runApp() {},
  leeRunTerm: async () => {}, openChromeMenu: (a, rows) => menus.push(rows),
  api: async u => { calls.push(u); return u.startsWith('/dev/list') ? {servers} : {}; },
  post: async u => { calls.push('POST ' + u); return {}; },
};
ctx.window = ctx; ctx.globalThis = ctx;
vm.createContext(ctx); vm.runInContext(src, ctx);
(async () => {
  await ctx.leeRunsMenu(null);
  const stop = (menus[0] || []).find(r => (r.label || '').startsWith('stop '));
  if (stop) await stop.run();
  console.log(JSON.stringify({rows: (menus[0] || []).map(r => r.label || ''), calls}));
})().catch(e => { console.error(e && e.stack || e); process.exit(1); });
'''

def menu(servers):
    node = shutil.which('node')
    if not node: pytest.skip('node is not installed')
    r = subprocess.run([node, '-e', HARNESS, str(LOGS), json.dumps(servers)], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])

def test_a_finished_command_whose_process_is_up_can_be_stopped():
    "The child keeps the inspector up after the command returns, and the server keeps its port: stop must be offered."
    out = menu([dict(label='vedicreader', path='main.py', script='main.py', alive=True, running=False, code=0, pid=26535)])
    assert 'stop vedicreader' in out['rows'], out
    assert 'POST /dev/stop?path=main.py' in out['calls'], out

def test_a_run_whose_process_is_gone_offers_no_stop():
    out = menu([dict(label='vedicreader', path='main.py', script='main.py', alive=False, running=False, code=0, pid=None)])
    assert not [r for r in out['rows'] if r.startswith('stop ')], out
