"""What a folder should not commit, and whether the repository already knows it.

Staging a folder is `git add`, which honours `.gitignore` -- so the whole problem is that a folder
you have just created does not have one yet. `target/`, `dist/`, `__pycache__` and `node_modules`
then go in with everything else, and a person meeting the language for the first time has no way to
know which of the files in front of them belong.

Git is asked rather than guessed at: `check-ignore` says whether a rule already covers a path, so a
repository whose ignores are already right is left alone.
"""
from __future__ import annotations
from fastcore.all import Path

__all__ = ['KINDS', 'kinds_in', 'missing_rules', 'prepare']

#: Per project kind: the files that say it is one, a path that must end up ignored, and the block
#: to write when it does not. `probe` is what `check-ignore` is asked about, so a `.gitignore`
#: written by hand in some other shape is still recognised as sufficient.
KINDS = {
    'rust': dict(
        markers=('Cargo.toml',), probes=('target/debug/build',),
        lines=('# Rust', '/target/', '**/*.rs.bk')),
    'maturin': dict(
        markers=('pyproject.toml', 'Cargo.toml'), probes=('dist/x.whl',),
        lines=('# Wheels built from this crate', '/dist/', '*.so', '*.pyd')),
    'python': dict(
        markers=('pyproject.toml', 'setup.py', 'setup.cfg'), probes=('__pycache__/x.pyc', '.venv/x'),
        lines=('# Python', '__pycache__/', '*.py[cod]', '.venv/', 'venv/', '/build/',
               '*.egg-info/', '.pytest_cache/', '.ipynb_checkpoints/')),
    'node': dict(
        markers=('package.json',), probes=('node_modules/x',),
        lines=('# Node', 'node_modules/', '*.tsbuildinfo')),
}

#: `maturin` needs every marker; the rest need any one. A `pyproject.toml` beside a `Cargo.toml` is
#: a Python package built from Rust, and its `dist/` holds wheels rather than an sdist.
_ALL_MARKERS = ('maturin',)

def kinds_in(folder):
    "Which kinds of project this folder is, by the files that declare one."
    folder = Path(folder)
    out = []
    for kind, spec in KINDS.items():
        hit = all if kind in _ALL_MARKERS else any
        if hit((folder/m).exists() for m in spec['markers']): out.append(kind)
    if 'maturin' in out and 'python' in out: out.remove('python')   # the same `dist/`, said twice
    return out

def _ignored(repo, path):
    "Whether git already ignores this path. Asking git is the only answer that is not a guess."
    try:
        rel = Path(path).resolve().relative_to(Path(repo.root).resolve())
    except ValueError: return False
    try: repo.run('check-ignore', '-q', '--no-index', str(rel))
    except Exception: return False
    return True

def missing_rules(repo, folder):
    "The `(kind, lines)` this folder needs and the repository does not already cover."
    folder = Path(folder)
    out = []
    for kind in kinds_in(folder):
        spec = KINDS[kind]
        if all(_ignored(repo, folder/p) for p in spec['probes']): continue
        out.append((kind, list(spec['lines'])))
    return out

def prepare(repo, folder, write=True):
    """Give `folder` the ignore rules its project kinds need, and say what was added.

    The rules go in the folder's own `.gitignore`, not the repository's. `/target/` at the root of
    a repository does not match `mycrate/target/`, so a crate in a subfolder written the other way
    would ignore nothing at all -- and a crate carrying its own ignores is what every crate does
    anyway, and survives being moved into another repository.

    Returns `{'kinds', 'added', 'path'}`. `added` is empty when the rules are already there, which
    is the common case on the second run and on a checkout someone else set up.
    """
    missing = missing_rules(repo, folder)
    wanted = [l for _, lines in missing for l in lines]
    target = Path(folder)/'.gitignore'
    added = list(wanted)
    if write and wanted:
        old = target.read_text(encoding='utf-8').splitlines() if target.exists() else []
        added = [l for l in wanted if l not in old]
        if added:
            head = old + ([''] if old and old[-1].strip() else [])
            target.write_text('\n'.join(head + added) + '\n', encoding='utf-8')
            from ramabana.git import _invalidate
            _invalidate(repo.root)
    return {'kinds': [k for k, _ in missing], 'added': added, 'path': str(target)}
