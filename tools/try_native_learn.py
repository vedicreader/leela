r"""Serve Leela from this worktree on a free 127.0.0.1 port with every store isolated, for the owner's native Learn check.

Run: `uv run python tools/try_native_learn.py [--copy-vault PATH] [--state DIR] [--port N]`. It never calls the CLI, so no key is migrated out of the person's keychain. The vault is a new file under the state folder. With no model in the isolated config it installs the scripted model of `tools/scripted_learn.py`.
"""
import argparse, importlib.util, os, shutil, socket, sys, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
ABHYASA = ROOT.parent/'abhyasa-native-learn'
REFUSED_PORT = 5001

def parse(argv=None):
    "The launcher's options; nothing is started."
    p = argparse.ArgumentParser(prog='try_native_learn', description='Leela with native Learn on isolated state')
    p.add_argument('--copy-vault', default=None, help='a vault file to copy into the isolated folder; the original is only read')
    p.add_argument('--state', default=None, help='the isolated folder to use again (default: a new temporary one)')
    p.add_argument('--port', type=int, default=None, help='port on 127.0.0.1 (default: a free one)')
    p.add_argument('--abhyasa', default=str(ABHYASA), help='the Abhyasa worktree to import first')
    return p.parse_args(argv)

def refused(paths, real):
    "The `paths` that are, or sit under, one of the `real` stores."
    real = [Path(r).resolve() for r in real]
    return [str(p) for p in map(lambda x: Path(x).expanduser().resolve(), paths) if any(p.is_relative_to(r) for r in real)]

def load_isolate():
    spec = importlib.util.spec_from_file_location('leela_isolate', HERE/'isolate.py')
    iso = importlib.util.module_from_spec(spec); spec.loader.exec_module(iso)
    return iso

def stores(iso, state):
    "Every store variable and the two cache variables isolate() leaves alone, under `state`."
    extra = dict(HF_HOME=Path(state)/'cache'/'huggingface', LITESEARCH_CACHE=Path(state)/'cache'/'litesearch')
    os.environ.update({k: str(v) for k, v in extra.items()})
    return {**iso.isolated_env(state), **extra}

def copy_vault(src, dest):
    "Copy the vault file and any write-ahead siblings to `dest`; `src` is opened for reading only."
    src, dest = Path(src).expanduser().resolve(), Path(dest)
    if not src.is_file(): raise SystemExit(f'not a vault file: {src}')
    if dest.exists(): raise SystemExit(f'{dest} exists; not overwriting it')
    dest.parent.mkdir(parents=True, exist_ok=True)
    for sfx in ('', '-wal', '-shm'):
        if (s := Path(f'{src}{sfx}')).is_file(): shutil.copy2(s, f'{dest}{sfx}')

def busy(port):
    with socket.socket() as s: return s.connect_ex(('127.0.0.1', port)) == 0

def free_port():
    "A port on 127.0.0.1 that the OS hands out, never the one Leela's own server keeps."
    while True:
        with socket.socket() as s:
            s.bind(('127.0.0.1', 0))
            if s.getsockname()[1] != REFUSED_PORT: return s.getsockname()[1]

def pick_port(wanted):
    "`wanted`, or a free port; `SystemExit` for the refused port or one in use."
    if wanted is None: return free_port()
    if wanted == REFUSED_PORT or busy(wanted): raise SystemExit(f'port {wanted} is reserved or already in use')
    return wanted

def main(argv=None):
    a = parse(argv)
    abh = Path(a.abhyasa).resolve()
    if not abh.is_dir(): raise SystemExit(f'no Abhyasa worktree at {abh}')
    if (late := {'leela', 'abhyasa', 'ramabana', 'vishalakshi'} & set(sys.modules)): raise SystemExit(f'isolate before importing {sorted(late)}')
    sys.path[:0] = [str(ROOT), str(abh)]
    os.environ['PYTHONPATH'] = os.pathsep.join([str(ROOT), str(abh)] + [p for p in [os.environ.get('PYTHONPATH')] if p])
    iso = load_isolate()
    state = Path(a.state or tempfile.mkdtemp(prefix='leela-learn-')).resolve()
    if bad := refused([state], iso.REAL_STORES): raise SystemExit(f'the state folder is a real store: {bad}')
    state.mkdir(parents=True, exist_ok=True)
    iso.isolate(state)
    env = stores(iso, state)
    if bad := refused(env.values(), iso.REAL_STORES): raise SystemExit(f'refusing to start, these stores are real: {bad}')
    if a.copy_vault: copy_vault(a.copy_vault, env['VISHALAKSHI_VAULT'])
    port = pick_port(a.port)
    import abhyasa
    if not Path(abhyasa.__file__).resolve().is_relative_to(abh): raise SystemExit(f'abhyasa came from {abhyasa.__file__}, not {abh}')
    import leela
    if not Path(leela.__file__).resolve().is_relative_to(ROOT): raise SystemExit(f'leela came from {leela.__file__}, not {ROOT}')
    if refused([leela.leela_cfg], iso.REAL_STORES): raise SystemExit(f'leela_cfg is a real store: {leela.leela_cfg}')
    work = state/'work'; work.mkdir(exist_ok=True)
    import uvicorn
    from leela.app import ide_app
    from leela.workspace import Workspace
    ws = Workspace(roots=[work], agent='restricted', approvals='ask', transport='direct').at_exit()
    scripted = not ws.model
    if scripted:
        from tools.scripted_learn import install_scripted
        install_scripted(ws)
    ref = ws.vaults.active
    if refused([env['VISHALAKSHI_VAULT']], iso.REAL_STORES): raise SystemExit('the vault is a real store')
    print(f'url    http://127.0.0.1:{port}/\nstate  {state}\nvault  {ref.name}  {env["VISHALAKSHI_VAULT"]}', flush=True)
    if scripted: print('scripted model: answers are canned', flush=True)
    print(f'rerun  uv run python {Path(__file__).resolve()} --state {state}', flush=True)
    uvicorn.run(ide_app(ws), host='127.0.0.1', port=port, log_level='warning')

if __name__ == '__main__': main()
