# nbrust: a Rust notebook, exported to a crate, shipped as a wheel

Not part of Leela. This settles one question before a package gets designed around it: does the
chain from a Rust notebook to an installable Python wheel hold end to end, using what already
exists? It does. `tests/test_nbrust.py` is the proof, and the slow test in it builds a real wheel
and calls into it.

    Rust notebook  ->  nb_export(mod_maker=CargoMaker)  ->  crate  ->  ship-rs-build  ->  wheel

## What was already there

More than expected, and it is the reason this file is 108 lines rather than a project.

- **Cell collection is language-neutral.** `nbdev.export.ExportModuleProc` reads only
  `cell.directives_` and `cell_type`. Directive prefixes come from `_dir_pre(lang)`, which reads
  `langs[lang]` in `fastcore.nbio`, which reads `metadata.kernelspec.language` -- the metadata
  Leela now round-trips. JavaScript works untouched.
- **`nb_export` takes the maker as a parameter.** Everything Python-specific -- `make_all` over an
  AST, relative imports, `# %%` headers -- lives in `ModuleMaker`, and `mod_maker=` replaces it.
- **fastship ships Rust.** `ship-rs-init` accepted this generated crate unchanged, and
  `ship-rs-build` produced a manylinux wheel from it.

## What had to be written

One line and one class.

`langs['rust'] = '//'`, because fastcore's comment-character map has no Rust and falls through to
the `#` default, so `//| export` was never seen as a directive. That belongs upstream in fastcore.

`CargoMaker`, which is smaller than its Python counterpart rather than larger: **Rust's `pub` is
already the export list**, so there is no `__all__` to reconstruct and no parser to write.

## The design decision this makes concrete

The notebook stays plain Rust with no PyO3 in it, so Leela's cargo runner executes the cells with
no extra dependency. The binding is generated at export: every exported `pub fn` gets a
`#[pyfunction]` wrapper and a line in the `#[pymodule]`. Writing PyO3 attributes in the cells
would have been the other choice, and would have meant every notebook carrying a dependency it
only needs at ship time.

    //| export
    /// Squared distance from the origin.
    pub fn dist2(x: i64, y: i64) -> i64 { x * x + y * y }

becomes `src/geom.rs` verbatim, plus this in `src/lib.rs`:

    #[pyfunction]
    fn dist2(x: i64, y: i64) -> i64 { geom::dist2(x, y) }

## Run it

    python -m pytest tests/test_nbrust.py            # the export, no toolchain needed
    python -m pytest tests/test_nbrust.py -m slow    # the wheel, needs cargo and maturin

By hand, against the notebook here:

```python
from nbdev.export import nb_export
from nbrust import cargo_maker
nb_export('geometry.ipynb', lib_path='demo_geom', mod_maker=cargo_maker('demo_geom'), solo_nb=True)
```

then `cd demo_geom && ship-rs-init && ship-rs-build`.

## What this does not answer

- **JavaScript.** The same shape and cheaper, because the export half already works and needs no
  `langs` entry. An `EsmMaker` writes the module and `package.json`; `deno bundle` makes the CDN
  artifact and fastship's npm path publishes it. Not attempted here.
- **Where it lives.** This belongs in its own package, not in Leela: CI has to run the export for
  a `cargo build`, and nothing about that should pull in FastHTML and uvicorn. `nb_export`'s
  `mod_maker` parameter is enough of an invitation that an nbdev pull request is worth asking
  about first.
- **Anything beyond free functions.** Structs, traits, generics and lifetimes export fine as Rust,
  but only `pub fn` gets a Python binding. `pyo3::pyclass` for exported structs is the obvious
  next increment.
