"""One command from a notebook to an installable wheel.

    nbship-rs geometry.ipynb

Everything else has a default: the crate is named after the notebook, the version starts at 0.1.0,
the wheel lands in `dist/`. What could not cross into Python is printed rather than hidden, because
that list is how you learn where PyO3's edge is.
"""
from __future__ import annotations
import shutil, subprocess, sys
from pathlib import Path

from fastcore.script import call_parse

from .parse import CargoMissing, RustSyntaxError
from .rust import cargo_maker

__all__ = ['ship_rs', 'export', 'build']

def _slug(name): return ''.join(c if c.isalnum() else '_' for c in Path(name).stem).strip('_')

def export(nbs, out=None, crate=None, version='0.1.0', description='', pyo3=True, deps=''):
    "Write the crate for `nbs`, and return `(crate directory, what stayed behind)`."
    from nbdev.export import nb_export
    nbs = [Path(n) for n in ([nbs] if isinstance(nbs, (str, Path)) else nbs)]
    crate = crate or _slug(nbs[0].name)
    dest = Path(out or crate)
    mk = cargo_maker(crate, version=version, description=description, pyo3=pyo3, deps=deps)
    maker = None
    for nb in nbs:
        # Each notebook writes its module and rebuilds `lib.rs`, so the last one holds the report.
        class Recording(mk):
            def make(self, cells, all_cells=None, lib_path=None):
                super().make(cells, all_cells, lib_path)
                nonlocal maker
                maker = self
        nb_export(str(nb), lib_path=str(dest), mod_maker=Recording, solo_nb=True)
    return dest, (maker.skipped if maker else [])

def build(dest, release=True, outdir='dist'):
    "Build the wheel with maturin, and return the path to it."
    if not shutil.which('maturin'):
        raise RuntimeError('maturin is not installed. `pip install maturin`, or `uv tool install maturin`')
    argv = ['maturin', 'build', '--out', outdir] + (['--release'] if release else [])
    r = subprocess.run(argv, cwd=dest, capture_output=True, text=True, timeout=1800)
    if r.returncode: raise RuntimeError(f'maturin failed:\n{(r.stderr or r.stdout)[-4000:]}')
    wheels = sorted((Path(dest)/outdir).glob('*.whl'), key=lambda p: p.stat().st_mtime)
    if not wheels: raise RuntimeError('maturin reported success but wrote no wheel')
    return wheels[-1]

def _report(skipped, quiet=False):
    if quiet or not skipped: return
    print(f'\n{len(skipped)} item(s) stayed in the crate, with no Python binding:', file=sys.stderr)
    for s in skipped: print(f'  - {s}', file=sys.stderr)
    print('  These are still Rust you can call from Rust. Widen a signature to bring one across.',
          file=sys.stderr)

@call_parse
def ship_rs(
    nb: str,                  # A Rust notebook, or a folder of them
    out: str = None,          # Where to write the crate; defaults to the crate name
    crate: str = None,        # Crate name; defaults to the notebook's
    version: str = '0.1.0',   # Crate version
    description: str = '',    # One line for the package metadata
    deps: str = '',           # Extra [dependencies] lines, eg 'rand = "0.8"'
    no_pyo3: bool = False,    # Write a plain Rust crate with no Python binding
    no_build: bool = False,   # Write the crate and stop
    install: bool = False,    # Install the wheel into this interpreter
    quiet: bool = False,      # Do not list what stayed behind
):
    "A Rust notebook, exported to a crate and built into an installable wheel."
    p = Path(nb)
    nbs = sorted(p.glob('*.ipynb')) if p.is_dir() else [p]
    if not nbs: raise SystemExit(f'no notebooks in {p}')
    try: dest, skipped = export(nbs, out, crate, version, description, not no_pyo3, deps)
    except RustSyntaxError as e: raise SystemExit(f'the exported cells are not valid Rust: {e}')
    except CargoMissing as e: raise SystemExit(str(e))
    print(f'crate  {dest}')
    _report(skipped, quiet)
    if no_build: return
    try: wheel = build(dest)
    except RuntimeError as e: raise SystemExit(str(e))
    print(f'wheel  {wheel}')
    if install:
        pip = [sys.executable, '-m', 'pip', 'install', '--force-reinstall', '-q', str(wheel)]
        if shutil.which('uv'): pip = ['uv', 'pip', 'install', '-q', '--python', sys.executable,
                                      '--reinstall', str(wheel)]
        subprocess.run(pip, check=True, timeout=900)
        print(f'installed into {sys.executable}')
