"Leela's part of kavacha's lock test and app build: the extras, the plist document types, and the checks of a built env. See docs/thin-app.md."
import json, os, sys, urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

def extra_reqs():
    "Each extra's requirements, as Leela's setup panel names them."
    sys.path.insert(0, str(ROOT))
    from leela.blocks.agent.models import TOOLS, runtime_requirements
    return {'mlx': runtime_requirements('mlx'), 'llama': runtime_requirements('llama'), 'langserver': list(TOOLS['langserver'][1])}

def plist():
    "The document types of the old app, from leela.workspace."
    import tempfile
    os.environ.setdefault('XDG_CONFIG_HOME', tempfile.mkdtemp())
    sys.path.insert(0, str(ROOT))
    from leela.workspace import doc_types, imported_types
    return dict(CFBundleDocumentTypes=doc_types(), UTImportedTypeDeclarations=imported_types())

EXTRA_CHECK = {'mlx': ['-c', 'import mlx_lm'], 'llama': ['-c', 'import llama_cpp'],
               'langserver': ['-c', 'import os, sys, sysconfig; sys.exit(0 if os.access(os.path.join(sysconfig.get_path("scripts"), "basedpyright-langserver"), os.X_OK) else 1)']}
def extra_check(x): return EXTRA_CHECK.get(x)

KERNEL = '''
import sys
from jupyter_client.manager import start_new_kernel
km, kc = start_new_kernel(kernel_name='python3')
try:
    mid, got = kc.execute('1+1'), None
    while got is None:
        m = kc.get_iopub_msg(timeout=60)
        if m['parent_header'].get('msg_id') == mid and m['msg_type'] == 'execute_result': got = m['content']['data']['text/plain']
    print(got)
finally: kc.stop_channels(); km.shutdown_kernel(now=True)
'''

PROJECT_CELL = """import json, os, sys, leela_lock_marker
print(json.dumps(dict(prefix=sys.prefix, uv=sorted(k for k in os.environ if k.startswith('UV_')), nousersite=os.environ.get('PYTHONNOUSERSITE'),
                      venv=os.environ.get('VIRTUAL_ENV'), path=os.environ.get('PATH', '').split(os.pathsep))))"""

AGENT_SHELL = '''
import json, subprocess, sys
from pathlib import Path
from leela.core import host
host.client.state.update(url='http://127.0.0.1:9', token='t')
from leela.blocks.agent.ai import WorkspaceHost
from types import SimpleNamespace
e = WorkspaceHost._env(SimpleNamespace(ws=None), Path(sys.argv[1]))
r = lambda c: subprocess.run(c, shell=True, cwd=sys.argv[1], env=e, capture_output=True, text=True)
ran = lambda n: (lambda p: f'usage: {n}' in (p.stdout + p.stderr).lower())(r(f'{n} --help'))   # kosha's --help exits 1
print(json.dumps(dict(ramabana=ran('ramabana'), kosha=ran('kosha'), python=r('command -v python').stdout.strip(),
                      at=r('command -v kosha').stdout.strip(), dir=str(host.tools_dir()), linked=sorted(p.name for p in host.tools_dir().iterdir()))))
'''

PNG = bytes.fromhex('89504e470d0a1a0a0000000d4948445200000001000000010802000000907753de0000000c4944415478da63f8ffff3f0005fe02fea7d6a4a10000000049454e44ae426082')

def sh(*a, **kw):
    from kavacha.lock import sh
    return sh(*a, **kw)

def prepare(s):
    "Leela reads no login shell in a test; the project .venv borrows ipykernel from the app env by a .pth, so it needs no network."
    s.server_extra = dict(LEELA_SHELL_ENV='0')

def prepare_steps(s):
    def project():
        d = s.tmp/'proj'; sh(s.py, '-m', 'venv', '--without-pip', d/'.venv')
        site = next((d/'.venv'/'lib').glob('python3*/site-packages'))
        (site/'leela_lock_marker.py').write_text('OK = 1\n')
        (site/'zz_app_env.pth').write_text(sh(s.py, '-I', '-c', 'import sysconfig; print(sysconfig.get_path("purelib"))') + '\n')
        cell = dict(cell_type='code', id='c0', metadata={}, execution_count=None, outputs=[], source=PROJECT_CELL)
        (d/'probe.ipynb').write_text(json.dumps(dict(cells=[cell], metadata={}, nbformat=4, nbformat_minor=5)))
    return s.step('project .venv', project)

def hold_open(s, base, port):
    "Each open window holds an endless /fs/events stream; the server must still stop in a few seconds."
    ports = {port, *(urllib.parse.urlsplit(r['url']).port for r in s.get(f'{base}/app/sites').get('sites', []))}
    return [(p, '/fs/events') for p in ports if p]

def project_cell(s, base, uv=('UV_INDEX_URL',)):
    "Through the server's routes, a notebook cell in the project runs on the project's .venv, and no app build setting reaches it."
    proj = s.tmp/'proj'
    d = s.get(f'{base}/hub/open?path={urllib.parse.quote(str(proj))}', data=b'', timeout=120)
    if not d.get('ok'): raise RuntimeError(d)
    site, h, nb = d['url'].rstrip('/'), {'Content-Type': 'application/json'}, str(proj/'probe.ipynb')
    s.get(f'{site}/tab/open?path={urllib.parse.quote(nb)}', headers=h, timeout=60, raw=True)
    r = s.get(f'{site}/nb/run', data=json.dumps(dict(path=nb, i=0, id='c0')).encode(), headers=h, timeout=180)
    outs = r.get('cell', {}).get('outputs', [])
    text = ''.join(o.get('text', '') for o in outs if o.get('output_type') == 'stream')
    if not r.get('ok') or not text.strip(): raise RuntimeError(f'the cell failed: {json.dumps(outs)[-800:]}')
    got, app = json.loads(text.strip().splitlines()[-1]), os.path.realpath(s.env_dir)
    bad = [f'sys.prefix is {got["prefix"]}'] if os.path.realpath(got['prefix']) != os.path.realpath(proj/'.venv') else []
    bad += [f'UV keys {got["uv"]}, not {list(uv)}'] if got['uv'] != list(uv) else []
    bad += ['PYTHONNOUSERSITE is set'] if got['nousersite'] else []
    bad += ['VIRTUAL_ENV is the app env'] if got['venv'] and os.path.realpath(got['venv']) == app else []
    bad += ['the app env bin is on PATH'] if any(p and os.path.realpath(p) == os.path.join(app, 'bin') for p in got['path']) else []
    if bad: raise RuntimeError('; '.join(bad))

def windows_by_port(s, base, port):
    "A folder window and a dropped image's loose window, each on a loopback port of its own."
    (d := s.tmp/'drop').mkdir(exist_ok=True); (png := d/'shot.png').write_bytes(PNG)
    (f := s.tmp/'folder').mkdir(exist_ok=True); (f/'a.py').write_text('x = 1\n')
    for q, want in ((dict(path=str(f)), None), (dict(path=str(d), file=str(png)), 'image')):
        r = s.get(f'{base}/hub/open?{urllib.parse.urlencode(q)}', data=b'', timeout=120)
        u = urllib.parse.urlsplit(r.get('url', ''))
        if not r.get('ok') or u.hostname != '127.0.0.1' or u.port in (None, port): raise RuntimeError(f'not a port of its own: {r}')
        if b'<html' not in s.get(r['url'], raw=True, timeout=60).lower(): raise RuntimeError(f'no page at {r["url"]}')
        if want and (t := s.get(r['url'] + 'tab/state', timeout=30)).get('kind') != want: raise RuntimeError(f'the loose window shows {t}')

def venv_and_quicklook(s, base):
    "A Python project with no venv: the notice, a run that asks and makes nothing, then Set up .venv; and Quick Look's slides."
    d = s.tmp/'novenv'; d.mkdir(exist_ok=True)
    (d/'pyproject.toml').write_text('[project]\nname = "p"\nversion = "0"\n')
    cell = dict(cell_type='code', id='c0', metadata={}, execution_count=None, outputs=[], source='1+1')
    (d/'nb.ipynb').write_text(json.dumps(dict(cells=[cell], metadata={}, nbformat=4, nbformat_minor=5)))
    sh(s.py, '-I', '-c', 'import sys; from pptx import Presentation; p = Presentation(); p.slides.add_slide(p.slide_layouts[0]).shapes.title.text = "Probe slide"; p.save(sys.argv[1])', d/'deck.pptx')
    site = s.get(f'{base}/hub/open?path={urllib.parse.quote(str(d))}', data=b'', timeout=120)['url'].rstrip('/')
    info = s.get(f'{site}/runtime/info', timeout=60)
    if not info.get('needs_create') or info.get('python'): raise RuntimeError(f'no venv notice: {info}')
    s.get(f'{site}/tab/open?path={urllib.parse.quote(str(d/"nb.ipynb"))}', timeout=60, raw=True)
    code, body = s.post(f'{site}/nb/run', dict(path=str(d/'nb.ipynb'), i=0, id='c0'))
    if 'venv' not in body.lower(): raise RuntimeError(f'the run did not ask about a venv: {code} {body[-300:]}')
    if (d/'.venv').exists(): raise RuntimeError('a run made a .venv nobody asked for')
    q = s.get(f'{site}/office/quicklook?path={urllib.parse.quote(str(d/"deck.pptx"))}', timeout=120)
    if not q.get('ok') or not q.get('pages'): raise RuntimeError(f'Quick Look gave {q}')
    if b'<' not in s.get(f"{site}/office/ql/{q['token']}/{q['pages'][0]['src']}", timeout=60, raw=True)[:200]: raise RuntimeError('Quick Look gave no page')
    code, body = s.post(f'{site}/runtime/create', {}, timeout=600)
    if code != 200 or not (d/'.venv'/'bin'/'python').exists(): raise RuntimeError(f'Set up .venv: {code} {body[-300:]}')

def checks(s, base, port):
    "The first server: a folder opens, a project cell, a window per port, the venv notice and Quick Look."
    def hub_open():
        d = s.get(f'{base}/hub/open?path={urllib.parse.quote(str(s.tmp/"work"))}', data=b'', timeout=120)
        if not d.get('ok'): raise RuntimeError(d)
    return (s.step('/hub/open', hub_open) & s.step('project kernel cell', lambda: project_cell(s, base, uv=[]))
            & s.step('windows by port', lambda: windows_by_port(s, base, port)) & s.step('venv notice, Quick Look', lambda: venv_and_quicklook(s, base)))

def kernel_env(s, jd='jd'): return s.server_env(JUPYTER_DATA_DIR=str(s.tmp/jd))

def agent_shell(s):
    "The server's links: an agent's shell in the project runs ramabana and kosha from the app's env, and its python is the project's."
    proj = s.tmp/'proj'
    got = json.loads(sh(s.py, '-I', '-c', AGENT_SHELL, proj, env=s.server_env(), timeout=120).splitlines()[-1])
    bad = [f'{n} --help printed no usage' for n in ('ramabana', 'kosha') if not got[n]]
    bad += [f'kosha is {got["at"]}, not the linked one'] if os.path.dirname(got['at']) != got['dir'] else []
    bad += [f'python is {got["python"]}'] if os.path.realpath(os.path.dirname(got['python'])) != os.path.realpath(proj/'.venv'/'bin') else []
    bad += [f'{n} is linked' for n in got['linked'] if n.startswith(('python', 'pip', 'uv'))]
    if bad: raise RuntimeError('; '.join(bad))

def smoke(s):
    "After the first server: the agent's shell, a server under app 1.0.0's environment, a kernel cell, the file walk."
    ok = s.step('agent shell tools', lambda: agent_shell(s))
    # the person's own uv setting, stored in Leela, for the next server only: its index is not real, and Set up .venv above installs from the real one
    (s.tmp/'cfg'/'leela').mkdir(parents=True, exist_ok=True); (s.tmp/'cfg'/'leela'/'env.json').write_text(json.dumps({'UV_INDEX_URL': 'https://example.invalid/simple'}))
    old = s.lk.server_env_old(s.env_dir, cache='', python='', python_version=s.t.python) | dict(XDG_CONFIG_HOME=str(s.tmp/'cfg'), XDG_DATA_HOME=str(s.tmp/'data')) | s.server_extra
    ok &= s.serve(' (app 1.0.0 env)', old, lambda base, port: s.step('project kernel cell (app 1.0.0 env)', lambda: project_cell(s, base)))
    def cell():
        if (got := sh(s.py, '-I', '-c', KERNEL, env=kernel_env(s), cwd=s.tmp, timeout=180).splitlines()[-1:]) != ['2']: raise RuntimeError(f'the cell gave {got}')
    ok &= s.step('kernel cell 1+1', cell)
    def find():   # rgapi 0.2.3 swapped fd's first two arguments, and an empty file list looked like a pass
        work = s.tmp/'work'; (work/'probe.py').write_text('x = 1\n')
        got = sh(s.py, '-I', '-c', f'from pathlib import Path; from leela.blocks.fs.fs import _walked; print(len(_walked([Path({str(work)!r})], False, 100, None)))', env=kernel_env(s), cwd=s.tmp, timeout=120)
        if got.splitlines()[-1:] != ['1']: raise RuntimeError(f'the file walk found {got.strip()[-200:]!r} files, not 1')
    return ok & s.step('file walk', find)

def copy_checks(s, env):
    "A kernel cell on the env copied from the one in use."
    return [] if sh(Path(env)/'bin'/'python', '-I', '-c', KERNEL, env=kernel_env(s, 'jd-b'), cwd=s.tmp, timeout=180).splitlines()[-1:] == ['2'] else ['the kernel cell failed on the copy']
