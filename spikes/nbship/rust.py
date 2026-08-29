"""A `mod_maker` for `nbdev.export.nb_export` that writes a Rust crate instead of a Python module.

The notebook stays plain Rust that Leela's cargo runner can execute, and the PyO3 binding is
generated here, at export, from what the exported cells made public. Rust's `pub` is the export
list, so unlike Python there is no `__all__` to reconstruct.
"""
from __future__ import annotations
import re
from pathlib import Path

from fastcore.nbio import langs

__all__ = ['CargoMaker', 'cargo_maker', 'pub_fns', 'pub_structs', 'Struct', 'CARGO_TOML',
           'PYPROJECT']

#: fastcore's map has no Rust, so `//| export` in a Rust notebook falls through to the `#` default
#: and is never seen as a directive. One entry upstream retires this line.
langs['rust'] = '//'

def _blocks(src, head):
    "Every `head ... { body }` in `src`, as `(match, body)`, with braces counted so nesting holds."
    out = []
    for m in re.finditer(head, src, re.M):
        i = src.find('{', m.end() - 1)
        if i < 0: continue
        depth, j = 0, i
        while j < len(src):
            if src[j] == '{': depth += 1
            elif src[j] == '}':
                depth -= 1
                if not depth: break
            j += 1
        out.append((m, src[i+1:j]))
    return out

def _args(text):
    "`a: T, b: U` as `[(a, T), ...]`, dropping any receiver."
    out = []
    for a in _split_top(text):
        if not a or a.lstrip().startswith(('&self', 'self', '&mut self', 'mut self')): continue
        if ':' in a: out.append(tuple(p.strip() for p in a.split(':', 1)))
    return out

def _split_top(text):
    "Split on commas that are not inside brackets, so `Vec<A, B>` stays one argument."
    out, depth, cur = [], 0, ''
    for c in text:
        if c in '<([': depth += 1
        elif c in '>)]': depth -= 1
        if c == ',' and depth <= 0:
            out.append(cur.strip()); cur = ''
        else: cur += c
    if cur.strip(): out.append(cur.strip())
    return out

#: A free `pub fn`. Simple signatures only: no generics, no lifetimes, no `where`.
PUB_FN = re.compile(r'^pub\s+fn\s+(\w+)\s*\(([^)]*)\)\s*(?:->\s*([^{]+?))?\s*\{', re.M)

def _ret(m, g): return (m.group(g) or '()').strip()

def pub_fns(src):
    "Every free public function, as `(name, [(arg, type)], return type)`. Methods are not free."
    out = []
    for m in PUB_FN.finditer(src):
        if re.search(r'\b(?:&mut\s+self|&self|self)\b', m.group(2)): continue
        out.append((m.group(1), _args(m.group(2)), _ret(m, 3)))
    return out

class Struct:
    "One exported `pub struct`: what it derives, its public fields, and its inherent methods."
    def __init__(self, name, derives, fields, methods, ctor=None):
        self.name, self.derives, self.fields, self.methods, self.ctor = (
            name, derives, fields, methods, ctor)
    @property
    def debug(self): return 'Debug' in self.derives
    @property
    def clone(self): return 'Clone' in self.derives or 'Copy' in self.derives

STRUCT = r'((?:^[ \t]*#\[[^\]]*\][ \t]*\n)*)^pub\s+struct\s+(\w+)\s*(?=\{)'
#: One `pub name: Type` out of a struct body, whether or not the body spans lines.
FIELD = re.compile(r'^\s*pub\s+(\w+)\s*:\s*(.+?)\s*$', re.S)
#: A method inside an `impl`, with its receiver kept so a `&mut self` stays mutable.
METHOD = re.compile(r'^\s*pub\s+fn\s+(\w+)\s*\(\s*(&mut self|&self)?\s*,?([^)]*)\)\s*(?:->\s*([^{]+?))?\s*\{', re.M)
ASSOC = re.compile(r'^\s*pub\s+fn\s+new\s*\(([^)]*)\)\s*->\s*Self\s*\{', re.M)

def pub_structs(src):
    "Every exported `pub struct`, with the methods its `impl` blocks give it."
    impls = {}
    for m, body in _blocks(src, r'^impl\s+(\w+)\s*(?=\{)'): impls.setdefault(m.group(1), []).append(body)
    out = []
    for m, body in _blocks(src, STRUCT):
        name = m.group(2)
        derives = re.findall(r'\w+', ''.join(re.findall(r'#\[derive\(([^)]*)\)\]', m.group(1))))
        fields = [(f.group(1), f.group(2).strip())
                  for part in _split_top(body) if (f := FIELD.match(part))]
        methods, ctor = [], None
        for imp in impls.get(name, []):
            if (c := ASSOC.search(imp)) is not None: ctor = _args(c.group(1))
            for f in METHOD.finditer(imp):
                if not f.group(2): continue              # associated, not a method
                methods.append((f.group(1), f.group(2), _args(f.group(3)), _ret(f, 4)))
        out.append(Struct(name, derives, fields, methods, ctor))
    return out

CARGO_TOML = '''[package]
name = "{crate}"
version = "{version}"
edition = "2021"

[lib]
name = "{crate}"
crate-type = ["cdylib", "rlib"]

[dependencies]
pyo3 = {{ version = "0.23", features = ["extension-module"] }}
'''

PYPROJECT = '''[build-system]
requires = ["maturin>=1.0,<2.0"]
build-backend = "maturin"

[project]
name = "{dist}"
dynamic = ["version"]
requires-python = ">=3.9"

[tool.maturin]
features = ["pyo3/extension-module"]
'''

class CargoMaker:
    """Write one exported notebook into `src/<name>.rs`, and keep `lib.rs` naming every module.

    `nb_export` builds one of these per module and calls `make`, so the crate is assembled across
    however many notebooks the project has: each writes its own file and adds its own `pub mod`.
    """
    crate = 'nbcrate'
    version = '0.1.0'
    pyo3 = True
    def __init__(self, dest, name, nb_path, is_new=True, parse=True, solo_nb=False):
        self.dest, self.name, self.nb_path = Path(dest), name, Path(nb_path)
        self.fname = self.dest/'src'/f"{name.replace('.', '_')}.rs"
    def make(self, cells, all_cells=None, lib_path=None):
        "Write this notebook's module, then rebuild the crate around whatever modules now exist."
        self.fname.parent.mkdir(parents=True, exist_ok=True)
        src = '\n\n'.join(c.source.strip() for c in cells
                          if c.cell_type == 'code' and c.source.strip())
        self.fname.write_text(
            f'// AUTOGENERATED! DO NOT EDIT! File to edit: {self.nb_path.name}.\n\n{src}\n',
            encoding='utf-8')
        self._crate()
    def _mods(self):
        return sorted(p.stem for p in (self.dest/'src').glob('*.rs') if p.stem != 'lib')
    def _crate(self):
        (self.dest/'Cargo.toml').write_text(
            CARGO_TOML.format(crate=self.crate, version=self.version), encoding='utf-8')
        (self.dest/'pyproject.toml').write_text(
            PYPROJECT.format(dist=self.crate.replace('_', '-')), encoding='utf-8')
        (self.dest/'src'/'lib.rs').write_text(self._lib_rs(), encoding='utf-8')
    def _lib_rs(self):
        mods = self._mods()
        lines = [f'// AUTOGENERATED! DO NOT EDIT! Written by {type(self).__name__}.', '']
        lines += [f'pub mod {m};' for m in mods]
        if not self.pyo3: return '\n'.join(lines) + '\n'
        srcs = {m: (self.dest/'src'/f'{m}.rs').read_text() for m in mods}
        fns = [(m, f) for m in mods for f in pub_fns(srcs[m])]
        classes = [(m, s) for m in mods for s in pub_structs(srcs[m])]
        lines += ['', 'use pyo3::prelude::*;', '']
        for mod, (name, args, ret) in fns:
            sig = ', '.join(f'{a}: {t}' for a, t in args)
            arrow = '' if ret == '()' else f' -> {ret}'
            lines += ['#[pyfunction]',
                      f'fn {name}({sig}){arrow} {{ {mod}::{name}({", ".join(a for a, _ in args)}) }}', '']
        for mod, st in classes: lines += self._pyclass(mod, st)
        lines += ['#[pymodule]', f"fn {self.crate}(m: &Bound<'_, PyModule>) -> PyResult<()> {{"]
        lines += [f'    m.add_function(wrap_pyfunction!({n}, m)?)?;' for _, (n, _, _) in fns]
        lines += [f'    m.add_class::<Py{s.name}>()?;' for _, s in classes]
        lines += ['    Ok(())', '}', '']
        return '\n'.join(lines)
    def _pyclass(self, mod, st):
        """A newtype around the exported struct, so the module it came from stays plain Rust.

        `#[pyclass]` has to sit on the struct definition itself, and rewriting the exported source
        to carry it would make that module need pyo3 to compile at all. Wrapping costs a field of
        indirection and keeps the notebook runnable with no pyo3 anywhere.
        """
        w, path = f'Py{st.name}', f'{mod}::{st.name}'
        out = [f'#[pyclass(name = "{st.name}")]']
        if st.clone: out.append('#[derive(Clone)]')
        out += [f'pub struct {w}(pub {path});', '', '#[pymethods]', f'impl {w} {{']
        if (ctor := st.ctor) is not None:
            sig = ', '.join(f'{a}: {t}' for a, t in ctor)
            out += ['    #[new]',
                    f'    fn new({sig}) -> Self {{ Self({path}::new({", ".join(a for a, _ in ctor)})) }}']
        elif st.fields:
            sig = ', '.join(f'{a}: {t}' for a, t in st.fields)
            lit = ', '.join(a for a, _ in st.fields)
            out += ['    #[new]', f'    fn new({sig}) -> Self {{ Self({path} {{ {lit} }}) }}']
        for f, t in st.fields:
            out += ['    #[getter]', f'    fn {f}(&self) -> {t} {{ self.0.{f}.clone() }}']
        for name, recv, args, ret in st.methods:
            sig = ''.join(f', {a}: {t}' for a, t in args)
            call = ', '.join(a for a, _ in args)
            if ret == 'Self':
                out.append(f'    fn {name}({recv}{sig}) -> Self {{ Self(self.0.{name}({call})) }}')
            else:
                arrow = '' if ret == '()' else f' -> {ret}'
                out.append(f'    fn {name}({recv}{sig}){arrow} {{ self.0.{name}({call}) }}')
        if st.debug: out.append('    fn __repr__(&self) -> String { format!("{:?}", self.0) }')
        out += ['}', '']
        return out

def cargo_maker(crate, version='0.1.0', pyo3=True):
    "A `CargoMaker` bound to one crate name, ready to hand to `nb_export(mod_maker=...)`."
    return type('BoundCargoMaker', (CargoMaker,), {'crate': crate, 'version': version, 'pyo3': pyo3})
