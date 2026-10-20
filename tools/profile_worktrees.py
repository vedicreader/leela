"""What N agent threads on N git worktrees would cost.

Measures making the worktrees, running git in all of them at once, and holding a Workspace open
per thread.

    python tools/profile_worktrees.py            # all three
    python tools/profile_worktrees.py -n 8       # eight threads
"""
from __future__ import annotations
import argparse, os, shutil, subprocess, sys, tempfile, threading, time
from concurrent.futures import ThreadPoolExecutor
from fastcore.all import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

def rss():
    try:
        for line in open('/proc/self/status'):
            if line.startswith('VmRSS'): return int(line.split()[1]) // 1024
    except OSError: pass
    import resource
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024

def du(p):
    return sum(f.stat().st_size for f in Path(p).rglob('*') if f.is_file()) // 1024

def make_repo(dirs, per):
    root = Path(tempfile.mkdtemp())/'main'
    root.mkdir(parents=True)
    for d in range(dirs):
        q = root/f'pkg{d//10:02d}'/f'mod{d:03d}'
        q.mkdir(parents=True, exist_ok=True)
        for f in range(per): (q/f'file_{f:02d}.py').write_text(f'x = {f}\n' * 30)
    g = lambda *a: subprocess.run(['git', *a], cwd=str(root), stdin=subprocess.DEVNULL, capture_output=True, text=True)
    g('init', '-q', '-b', 'main'); g('config', 'user.email', 'a@b.c'); g('config', 'user.name', 'a')
    g('add', '-A'); g('commit', '-qm', 'init')
    return root

def table(rows, head):
    w = [max(len(str(r[i])) for r in [head, *rows]) for i in range(len(head))]
    line = lambda r: '  '.join(str(c).ljust(w[i]) if not i else str(c).rjust(w[i]) for i, c in enumerate(r))
    print(line(head)); print('  '.join('-' * n for n in w))
    for r in rows: print(line(r))

def worktrees(root, n):
    "Add `n` worktrees, each on its own branch, and time every one."
    from leela.blocks.git.git import GitRepo
    r, times, paths = GitRepo.at(root), [], []
    for i in range(n):
        p = root.parent/f'thread-{i}'
        t = time.perf_counter()
        r.add_worktree(str(p), f'agent/thread-{i}', create=True)
        times.append((time.perf_counter() - t) * 1000)
        paths.append(p)
    return times, paths

def best(f, rounds=3):
    out = []
    for _ in range(rounds):
        t = time.perf_counter(); f(); out.append((time.perf_counter() - t) * 1000)
    return min(out)

def concurrency(paths):
    "Reads across worktrees, and whether a write held in one blocks reads in the others."
    from leela.blocks.git.git import GitRepo
    from gheasy.repo import gateway
    repos = [GitRepo.at(p) for p in paths]
    read = lambda r: r._changes_uncached()
    def spread(rs):
        with ThreadPoolExecutor(max_workers=len(rs)) as ex: list(ex.map(read, rs))
    solo, together = best(lambda: read(repos[0])), best(lambda: spread(repos))
    held = threading.Event()
    def hold():
        with gateway()._lock(repos[0].root).write(): held.wait(5)
    t = threading.Thread(target=hold, daemon=True); t.start(); time.sleep(.05)
    try: blocked = best(lambda: spread(repos[1:]))
    finally: held.set(); t.join()
    free = best(lambda: spread(repos[1:]))
    locks = {id(gateway()._lock(r.root)) for r in repos}
    return solo, together, free, blocked, len(locks)

def workspaces(paths):
    "What each extra open Workspace adds to the process."
    from tools.shots import fake_kernels
    from leela.workspace import Workspace
    fake_kernels()
    base, rows, held = rss(), [], []
    for i, p in enumerate(paths, 1):
        t = time.perf_counter()
        held.append(Workspace(roots=[p], port=8000 + i, agent='off'))
        rows.append((i, round((time.perf_counter() - t) * 1000), rss() - base))
    return base, rows

def main(argv=None):
    ap = argparse.ArgumentParser(prog='profile_worktrees', description=__doc__.splitlines()[0])
    ap.add_argument('-n', '--threads', type=int, default=6)
    ap.add_argument('--dirs', type=int, default=60)
    ap.add_argument('--per', type=int, default=12)
    a = ap.parse_args(argv)
    os.environ.setdefault('LEELA_MEMORY_OFFLINE', '1')
    root = make_repo(a.dirs, a.per)
    print(f'\n## {a.threads} worktrees of a {a.dirs * a.per}-file repository\n')
    times, paths = worktrees(root, a.threads)
    checkout = du(root) - du(root/'.git')
    table([('first worktree', f'{times[0]:.0f}ms'),
           ('median worktree', f'{sorted(times)[len(times) // 2]:.0f}ms'),
           ('all of them', f'{sum(times):.0f}ms'),
           ('working tree on disk, each', f'{du(paths[0]):,}KB'),
           ('the repository they share', f'{du(root/".git"):,}KB'),
           ('checkout, for comparison', f'{checkout:,}KB')], ('measure', 'value'))
    solo, together, free, blocked, locks = concurrency(paths)
    print('\n### git status across worktrees\n')
    table([('one worktree, alone', f'{solo:.0f}ms'),
           (f'all {len(paths)} at once', f'{together:.0f}ms'),
           (f'{len(paths) - 1} of them, freely', f'{free:.0f}ms'),
           (f'the same {len(paths) - 1}, while one is held under a write', f'{blocked:.0f}ms'),
           ('distinct gateway locks', f'{locks} of {len(paths)}')], ('measure', 'value'))
    print(f'\n  A worktree is its own root, so GitGateway gives each one its own lock. A write held\n'
          f'  in one costs the others {blocked / free:.1f}x -- they are not serialised behind it, which is the\n'
          f'  point for parallel threads and the risk for the ref store they all share.\n')
    base, rows = workspaces(paths)
    print(f'### a Workspace per thread — process was {base}MB before the first\n')
    table([(f'{n} open', f'{ms}ms', f'+{mb}MB') for n, ms, mb in rows],
          ('workspaces', 'build', 'resident added'))
    print('\n  Kernels are stubbed and the index, vault and browser are built on first use, so this\n'
          '  is the floor, not the cost of a thread that is actually working.')
    shutil.rmtree(root.parent, ignore_errors=True)

if __name__ == '__main__': main()
