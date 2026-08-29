"""Read Rust with Rust. `rustparse/` is a small `syn` program; this builds it once and asks it.

Regular expressions cannot see a generic parameter, a lifetime, a `where` clause, a trait impl or
a nested module, so the binding generator used to emit Rust that did not compile and could not say
why. The parser answers with the real shape of the code, and with a reason for every item that
cannot cross into Python.
"""
from __future__ import annotations
import hashlib, json, shutil, subprocess
from pathlib import Path

from fastcore.xdg import xdg_data_home

__all__ = ['rust_items', 'parser_path', 'build_parser', 'RustSyntaxError', 'CargoMissing']

CRATE = Path(__file__).parent/'rustparse'

class RustSyntaxError(SyntaxError):
    "The exported cells are not parseable Rust. Carries the line the parser stopped on."

class CargoMissing(RuntimeError):
    "Raised instead of guessing when there is no toolchain to build the parser with."

def _digest():
    "A hash of the parser's own sources, so a change to them rebuilds it and nothing else does."
    h = hashlib.sha256()
    for p in sorted(CRATE.rglob('*')):
        if p.is_file() and p.suffix in ('.rs', '.toml'): h.update(p.read_bytes())
    return h.hexdigest()[:12]

def _cache(): return xdg_data_home()/'nbship'/'parser'/_digest()

def parser_path(build=True):
    "The parser binary, built on first use and cached until its sources change."
    exe = _cache()/'target'/'release'/'nbship-parse'
    if exe.exists(): return exe
    if not build: return None
    return build_parser()

def build_parser(quiet=True):
    """Build the parser into the cache. About twenty seconds, once.

    The package may be installed read-only, so the sources are copied out rather than built where
    they sit."""
    if not shutil.which('cargo'):
        raise CargoMissing('cargo is needed once, to build the Rust parser this exporter reads '
                           'your code with. Install Rust from https://rustup.rs')
    d = _cache()
    d.mkdir(parents=True, exist_ok=True)
    for p in ('Cargo.toml', 'src'):
        src, dst = CRATE/p, d/p
        if dst.exists(): shutil.rmtree(dst) if dst.is_dir() else dst.unlink()
        (shutil.copytree if src.is_dir() else shutil.copyfile)(src, dst)
    argv = ['cargo', 'build', '--release'] + (['--quiet'] if quiet else [])
    r = subprocess.run(argv, cwd=d, capture_output=True, text=True, timeout=900)
    if r.returncode: raise RuntimeError(f'could not build the Rust parser:\n{r.stderr[-2000:]}')
    return d/'target'/'release'/'nbship-parse'

def rust_items(src, exe=None):
    "Every public item in `src`, each with the reason it cannot be bound, or None."
    r = subprocess.run([str(exe or parser_path())], input=src, capture_output=True, text=True,
                       timeout=120)
    out = json.loads(r.stdout or '{}')
    if r.returncode == 2 or 'error' in out:
        raise RustSyntaxError(f"line {out.get('line', '?')}: {out.get('error', 'unparseable')}")
    if r.returncode: raise RuntimeError(f'the Rust parser failed:\n{r.stderr[-2000:]}')
    return out['items']
