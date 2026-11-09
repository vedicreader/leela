r"""Serve Leela from this worktree on a free 127.0.0.1 port with every store isolated, for the owner's native Learn check.

Run: `python tools/try_native_learn.py [--copy-vault PATH] [--no-seed] [--web] [--model NAME] [--state DIR] [--port N]`; see `docs/try-native-learn.md`. It never calls the CLI, so no key is migrated out of the person's keychain. Every store is a new file under the state folder. With no `--model` it installs the scripted model of `tools/scripted_learn.py`. With no `--copy-vault` the new Learn vault gets the demo data of `tools/seed_learn_demo.py`; with it, the copy is the standalone vault and the first Learn open shows the import offer.
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
    p.add_argument('--copy-vault', default=None, help='a vault file to copy into the isolated folder as the standalone vault, so Learn offers to import it; the original is only read')
    p.add_argument('--no-seed', action='store_true', help='leave the new Learn vault empty')
    p.add_argument('--web', action='store_true', help="let the agent search the web (topic words go to the web search through Leela's privacy guard)")
    p.add_argument('--model', default=None, help='name of an already configured model to use instead of the scripted one')
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

TRY = """what to try
 1  Learn: Home in the command palette; the Today page opens in a tab
 2  Open the paper walk "Attention Is All You Need"; read the quote and open its source link
 3  Answer a check on a step; the feedback and the understanding strip change
 4  Option+W on a step for a hint
 5  Agent pane: switch Learn on, then type "teach me fractions"; watch the job card
 6  Open the graph from the palette; change the theme and see it restyle
 7  Open the talk and press Present; Esc leaves, End opens the after-talk page
 8  Dictate an answer with the microphone action
 9  Press "I don't get this" on a step, or ask it in the agent pane
10  Settings > Learn: change a row and see it saved
11  Course page: the demo course "Diffusion for comics" with its stage
12  With --copy-vault: open Learn and see the import offer (Attach, Back up and copy, Skip)"""

WEB_OFF = 'web research: off (add --web to let the agent search the web)'
WEB_ON = "web research: ON: topic words are sent to the web search through Leela's privacy guard"

def banner(url, state, ref, scripted, seeded, copied, web=False):
    "The text the owner reads first."
    model = 'scripted model: canned replies, nothing leaves this machine' if scripted else 'configured model (see Settings > Models); it may leave this machine'
    data = 'a copy of your vault is the standalone vault; Learn offers to import it on first open' if copied else ('demo data (not yours)' if seeded else 'empty')
    return f'pid    {os.getpid()}\nurl    {url}\nstate  {state}\nvault  {ref[0]}  {ref[1]}\nmodel  {model}\nweb    {WEB_ON if web else WEB_OFF}\ndata   {data}\n{TRY}'

def check(a):
    "The refusals that come before anything starts: the Abhyasa worktree, the state folder, the port. Returns `(abh, iso, state, port)`."
    abh = Path(a.abhyasa).resolve()
    if not abh.is_dir(): raise SystemExit(f'no Abhyasa worktree at {abh}')
    iso = load_isolate()
    state = Path(a.state or tempfile.mkdtemp(prefix='leela-learn-')).resolve()
    if bad := refused([state], iso.REAL_STORES): raise SystemExit(f'the state folder is a real store: {bad}')
    return abh, iso, state, pick_port(a.port)

def standalone(state, copy):
    "Point ABHYASA_VAULT at the copy of `copy` under `state`, or at the isolated workspace vault; never at an inherited path. Returns the path."
    dest = Path(state)/'standalone'/'vault.db' if copy else Path(os.environ['VISHALAKSHI_VAULT'])
    if copy: copy_vault(copy, dest)
    os.environ['ABHYASA_VAULT'] = str(dest)
    return dest

def main(argv=None):
    a = parse(argv)
    abh, iso, state, port = check(a)
    if (late := {'leela', 'abhyasa', 'ramabana', 'vishalakshi'} & set(sys.modules)): raise SystemExit(f'isolate before importing {sorted(late)}')
    sys.path[:0] = [str(ROOT), str(abh)]
    os.environ['PYTHONPATH'] = os.pathsep.join([str(ROOT), str(abh)] + [p for p in [os.environ.get('PYTHONPATH')] if p])
    state.mkdir(parents=True, exist_ok=True)
    iso.isolate(state)
    env = stores(iso, state)
    if bad := refused(env.values(), iso.REAL_STORES): raise SystemExit(f'refusing to start, these stores are real: {bad}')
    standalone(state, a.copy_vault)
    import abhyasa
    if not Path(abhyasa.__file__).resolve().is_relative_to(abh): raise SystemExit(f'abhyasa came from {abhyasa.__file__}, not {abh}')
    import leela
    if not Path(leela.__file__).resolve().is_relative_to(ROOT): raise SystemExit(f'leela came from {leela.__file__}, not {ROOT}')
    if refused([leela.leela_cfg], iso.REAL_STORES): raise SystemExit(f'leela_cfg is a real store: {leela.leela_cfg}')
    work = state/'work'; work.mkdir(exist_ok=True)
    import uvicorn
    from leela.app import ide_app
    from leela.workspace import Workspace
    from leela.blocks.memory.vaults import LEARN, learn_path
    ws = Workspace(roots=[work], agent='restricted', approvals='ask', transport='direct', model=a.model).at_exit()
    ws.learn_research = bool(a.web)
    scripted = not ws.model
    if scripted:
        from tools.scripted_learn import install_scripted
        install_scripted(ws)
    seeded = False
    if not a.copy_vault and not a.no_seed:
        from leela.blocks.learn.tools import learn_store
        from tools.seed_learn_demo import seed
        seeded = bool(seed(learn_store(ws)[1], abh))
    ref = ws.vaults.get(LEARN)
    ref = (ref.name, ref.path) if ref else (LEARN, f'{learn_path()}  (made when you choose Attach, Back up and copy, or Skip)')
    if refused([ref[1].split('  ')[0]], iso.REAL_STORES): raise SystemExit('the Learn vault is a real store')
    print(banner(f'http://127.0.0.1:{port}/', state, ref, scripted, seeded, bool(a.copy_vault), bool(a.web)), flush=True)
    print(f'rerun  python {Path(__file__).resolve()} --state {state}', flush=True)
    try: uvicorn.run(ide_app(ws), host='127.0.0.1', port=port, log_level='warning')
    except KeyboardInterrupt: pass
    finally: ws.shutdown_now(); print('stopped: Abhyasa pools, kernels and jobs are closed', flush=True)

if __name__ == '__main__': main()
