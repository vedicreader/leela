"""A `mod_maker` for `nbdev.export.nb_export` that writes a Rust crate with a PyO3 binding.

The notebook stays plain Rust that Leela's cargo runner can execute; the binding is generated here,
at export, from what the exported cells made public. `pub` is the export list, so unlike Python
there is no `__all__` to reconstruct.

What can and cannot cross into Python is decided by `parse`, which reads the code with `syn` rather
than with regular expressions, so an item that stays behind says why.
"""
from __future__ import annotations
import re
from pathlib import Path

from fastcore.nbio import langs

from .parse import rust_items

__all__ = ['CargoMaker', 'cargo_maker', 'Skipped', 'binding', 'CARGO_TOML', 'PYPROJECT',
           'GITIGNORE']

#: fastcore's map has no Rust, so `//| export` in a Rust notebook falls through to the `#` default
#: and is never seen as a directive. One entry upstream retires this line.
langs['rust'] = '//'

CARGO_TOML = '''[package]
name = "{crate}"
version = "{version}"
edition = "2021"

[lib]
name = "{crate}"
crate-type = ["cdylib", "rlib"]

[dependencies]
pyo3 = {{ version = "0.23", features = ["extension-module"] }}
{deps}'''

#: A crate built into a wheel has two build outputs a first-time reader has no reason to know
#: about. It ships with the ignore rules rather than waiting for someone to notice.
GITIGNORE = '''# Rust
/target/
**/*.rs.bk

# Wheels built from this crate
/dist/
*.so
*.pyd
'''

PYPROJECT = '''[build-system]
requires = ["maturin>=1.0,<2.0"]
build-backend = "maturin"

[project]
name = "{dist}"
dynamic = ["version"]
description = "{description}"
requires-python = ">=3.9"

[tool.maturin]
features = ["pyo3/extension-module"]
'''

#: How a Rust error becomes a Python exception. `Display` is all this needs, so it works for an
#: error type PyO3 has never heard of.
MAP_ERR = '.map_err(|e| pyo3::exceptions::PyValueError::new_err(e.to_string()))'

class Skipped:
    "One item that stayed in the crate, and the reason Python cannot see it."
    def __init__(self, what, name, why): self.what, self.name, self.why = what, name, why
    def __str__(self): return f'{self.what} `{self.name}` {self.why}'
    __repr__ = __str__

def _inner(t, wrap):
    return t[len(wrap)+1:-1] if t.startswith(f'{wrap}<') and t.endswith('>') else None

def _split_top(text):
    out, depth, cur = [], 0, ''
    for c in text:
        if c in '<([': depth += 1
        elif c in '>)]': depth -= 1
        if c == ',' and depth <= 0: out.append(cur.strip()); cur = ''
        else: cur += c
    if cur.strip(): out.append(cur.strip())
    return out

def _mentions(ty, names):
    "The exported types this type names, at any depth."
    return {n for n in names if re.search(rf'\b{re.escape(n)}\b', ty)}

def _spell(ty, names):
    "How the wrapper spells a type: an exported struct is its wrapper, everything else is itself."
    for n in names: ty = re.sub(rf'\b{re.escape(n)}\b', f'Py{n}', ty)
    return ty

class _Fn:
    """One function or method, and how to call the real one from the wrapper.

    A `Result` becomes a `PyResult` and its error becomes a `ValueError`; an exported struct that
    comes back is put into its wrapper; a nested one is refused, because unpacking a `Vec<Point>`
    into a `Vec<PyPoint>` is a conversion this does not write yet.
    """
    def __init__(self, row, path, names, receiver=None):
        self.row, self.path, self.names, self.recv = row, path, names, receiver
        self.name, self.doc = row['name'], row.get('doc') or ''
        self.args = [(a['name'], a['ty']) for a in row['args']]
        self.skip = row.get('skip')
        if not self.skip and row.get('is_async'): self.skip = 'is async, which PyO3 cannot bind here'
        if not self.skip: self.skip = self._nested()
    def _nested(self):
        for _, t in self.args:
            if _mentions(t, self.names) and t not in self.names:
                return f'takes `{t}`, and an exported type inside a container is not bound yet'
        r = self.ret
        if _mentions(r, self.names) and r not in self.names:
            return f'returns `{r}`, and an exported type inside a container is not bound yet'
        return None
    @property
    def ret(self):
        r = self.row['ret']
        return (_split_top(inner)[0] if (inner := _inner(r, 'Result')) else r)
    @property
    def fallible(self): return _inner(self.row['ret'], 'Result') is not None
    def sig(self):
        "The wrapper's argument list, with the receiver first when there is one."
        a = ', '.join(f'{n}: {_spell(t, self.names)}' for n, t in self.args)
        return f'{self.recv}{", " if a else ""}{a}' if self.recv else a
    def rust_ret(self):
        r = 'Self' if self.ret == 'Self' else _spell(self.ret, self.names)
        if self.fallible: return f' -> PyResult<{r}>'
        return '' if r == '()' else f' -> {r}'
    def body(self):
        call = ', '.join(f'{n}.0' if t in self.names else n for n, t in self.args)
        expr = f'self.0.{self.name}({call})' if self.recv else f'{self.path}::{self.name}({call})'
        wrap = 'Self' if self.ret == 'Self' else (f'Py{self.ret}' if self.ret in self.names else '')
        if self.fallible:
            if wrap: expr += f'.map({wrap})'
            return expr + MAP_ERR
        return f'{wrap}({expr})' if wrap else expr
    def render(self, attrs=()):
        out = [f'/// {l}' for l in self.doc.splitlines() if l]
        out += [f'#[{a}]' for a in attrs]
        out.append(f'fn {self.name}({self.sig()}){self.rust_ret()} {{ {self.body()} }}')
        return out

def binding(mods, crate):
    """The `lib.rs` for a crate, and the list of what stayed behind.

    `mods` is `{module name: source}`. Every module is parsed before any is rendered, so a function
    in one can take a struct from another.
    """
    parsed = {m: rust_items(src) for m, src in mods.items()}
    names = [i['name'] for rows in parsed.values() for i in rows
             if i['kind'] == 'struct' and not i.get('skip')]
    lines = ['// AUTOGENERATED! DO NOT EDIT! Written by nbship.', '']
    lines += [f'pub mod {m};' for m in sorted(mods)]
    lines += ['', 'use pyo3::prelude::*;', '']
    fns, classes, left = [], [], []
    for mod in sorted(parsed):
        for it in parsed[mod]:
            kind, name = it['kind'], it['name']
            if it.get('skip'):
                left.append(Skipped(kind, name, it['skip']))
                continue
            if kind == 'fn':
                f = _Fn(it, mod, names)
                if f.skip: left.append(Skipped('fn', name, f.skip)); continue
                fns.append(name)
                lines += f.render(attrs=('pyfunction',)) + ['']
            elif kind == 'struct':
                if it.get('tuple'):
                    left.append(Skipped('struct', name, 'is a tuple struct, which is not bound yet'))
                    continue
                classes.append(name)
                lines += _pyclass(mod, it, names, left)
            elif kind == 'enum':
                left.append(Skipped('enum', name, 'enums are not bound yet'))
    lines += ['#[pymodule]', f"fn {crate}(m: &Bound<'_, PyModule>) -> PyResult<()> {{"]
    lines += [f'    m.add_function(wrap_pyfunction!({n}, m)?)?;' for n in fns]
    lines += [f'    m.add_class::<Py{n}>()?;' for n in classes]
    lines += ['    Ok(())', '}', '']
    return '\n'.join(lines), left

def _pyclass(mod, it, names, left):
    """A newtype around the exported struct, so the module it came from stays plain Rust.

    `#[pyclass]` has to sit on the struct definition itself, and rewriting the exported source to
    carry it would make that module need pyo3 to compile at all -- and the notebook would stop
    running. Wrapping costs one field of indirection and keeps the cells executable.
    """
    name, path = it['name'], f"{mod}::{it['name']}"
    # An associated function is reached through the type, a free one through the module.
    w, derives = f'Py{name}', it.get('derives') or []
    clone = 'Clone' in derives or 'Copy' in derives
    out = [f'/// {l}' for l in (it.get('doc') or '').splitlines() if l]
    out.append(f'#[pyclass(name = "{name}")]')
    if clone: out.append('#[derive(Clone)]')
    out += [f'pub struct {w}(pub {path});', '', '#[pymethods]', f'impl {w} {{']
    def add(lines): out.extend('    ' + l for l in lines)

    ctor = next((s for s in it.get('statics', []) if s['name'] == 'new'), None)
    if ctor is not None and not ctor.get('skip'):
        add(_Fn(ctor, path, names).render(attrs=('new',)))
    elif ctor is None and it['fields'] and not any(f.get('skip') for f in it['fields']):
        # Every field is public and bindable, so the struct literal is a usable constructor.
        sig = ', '.join(f"{f['name']}: {_spell(f['ty'], names)}" for f in it['fields'])
        lit = ', '.join(f['name'] for f in it['fields'])
        add(['#[new]', f'fn new({sig}) -> Self {{ Self({path} {{ {lit} }}) }}'])

    for f in it['fields']:
        if f.get('skip'):
            left.append(Skipped('field', f"{name}.{f['name']}", f['skip']))
            continue
        if f['ty'] in names:
            left.append(Skipped('field', f"{name}.{f['name']}",
                                'is an exported type, and a getter for one is not written yet'))
            continue
        add(['#[getter]', f"fn {f['name']}(&self) -> {f['ty']} {{ self.0.{f['name']}.clone() }}"])

    for s in it.get('statics', []):
        if s['name'] == 'new' and ctor is not None: continue
        fn = _Fn(s, path, names)
        if fn.skip: left.append(Skipped('static', f"{name}::{s['name']}", fn.skip)); continue
        add(fn.render(attrs=('staticmethod',)))
    for m in it.get('methods', []):
        fn = _Fn(m, mod, names, receiver=m['recv'])
        if fn.skip: left.append(Skipped('method', f"{name}.{m['name']}", fn.skip)); continue
        add(fn.render())
    if 'Debug' in derives:
        add(['fn __repr__(&self) -> String { format!("{:?}", self.0) }'])
    out += ['}', '']
    return out

class CargoMaker:
    """Write one exported notebook into `src/<name>.rs`, and rebuild the crate around it.

    `nb_export` builds one of these per module and calls `make`, so a crate is assembled across
    however many notebooks it has: each writes its own file and rejoins `lib.rs`.
    """
    crate = 'nbcrate'
    version = '0.1.0'
    description = ''
    pyo3 = True
    deps = ''
    def __init__(self, dest, name, nb_path, is_new=True, parse=True, solo_nb=False):
        self.dest, self.name, self.nb_path = Path(dest), name, Path(nb_path)
        self.fname = self.dest/'src'/f"{name.replace('.', '_')}.rs"
        self.skipped = []
    def make(self, cells, all_cells=None, lib_path=None):
        self.fname.parent.mkdir(parents=True, exist_ok=True)
        src = '\n\n'.join(c.source.strip() for c in cells
                          if c.cell_type == 'code' and c.source.strip())
        self.fname.write_text(
            f'// AUTOGENERATED! DO NOT EDIT! File to edit: {self.nb_path.name}.\n\n{src}\n',
            encoding='utf-8')
        self._crate()
    def _mods(self):
        return {p.stem: p.read_text(encoding='utf-8')
                for p in sorted((self.dest/'src').glob('*.rs')) if p.stem != 'lib'}
    def _crate(self):
        (self.dest/'Cargo.toml').write_text(
            CARGO_TOML.format(crate=self.crate, version=self.version, deps=self.deps),
            encoding='utf-8')
        (self.dest/'pyproject.toml').write_text(
            PYPROJECT.format(dist=self.crate.replace('_', '-'), description=self.description),
            encoding='utf-8')
        (self.dest/'.gitignore').write_text(GITIGNORE, encoding='utf-8')
        mods = self._mods()
        if not self.pyo3:
            text = ('// AUTOGENERATED! DO NOT EDIT! Written by nbship.\n\n'
                    + ''.join(f'pub mod {m};\n' for m in sorted(mods)))
            self.skipped = []
        else: text, self.skipped = binding(mods, self.crate)
        (self.dest/'src'/'lib.rs').write_text(text, encoding='utf-8')

def cargo_maker(crate, version='0.1.0', description='', pyo3=True, deps=''):
    "A `CargoMaker` bound to one crate, ready to hand to `nb_export(mod_maker=...)`."
    return type('BoundCargoMaker', (CargoMaker,),
                {'crate': crate, 'version': version, 'description': description,
                 'pyo3': pyo3, 'deps': deps})
