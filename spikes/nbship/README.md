# nbship: a notebook in another language, exported into something shippable

Not part of Leela. This settles one question before a package gets designed around it: does the
nbdev path extend to the languages Leela now runs, all the way to a published artefact, using what
already exists? It does, for both.

    Rust notebook  ->  nb_export(mod_maker=CargoMaker)  ->  crate  ->  maturin  ->  wheel
    JS notebook    ->  nb_export(mod_maker=EsmMaker)    ->  package  ->  deno bundle  ->  CDN file

`tests/test_nbship.py` is the proof. Its slow tests build a real wheel and call into it, and fetch
a real bundle cross-origin into a real browser.

## What was already there

More than expected, and it is the reason this is two small modules rather than a project.

- **Cell collection is language-neutral.** `nbdev.export.ExportModuleProc` reads only
  `cell.directives_` and `cell_type`. Directive prefixes come from `_dir_pre(lang)`, which reads
  `langs[lang]` in `fastcore.nbio`, which reads `metadata.kernelspec.language` -- the metadata
  Leela now round-trips. JavaScript needed no change at all.
- **`nb_export` takes the maker as a parameter.** Everything Python-specific -- `make_all` over an
  AST, relative imports, `# %%` headers -- lives in `ModuleMaker`, and `mod_maker=` replaces it.
- **fastship ships Rust.** `ship-rs-init` accepted the generated crate unchanged and
  `ship-rs-build` produced a manylinux wheel. Its npm path is there for the JavaScript side too.
- **`deno bundle` is back.** Removed in Deno 2, reinstated in 2.4 on esbuild. Tree-shaking and
  minification for free.

## Why both makers are small

**Rust's `pub` and JavaScript's `export` are the export list.** nbdev reconstructs `__all__` with
an AST walk because Python has no visibility keyword; these two languages carry the information in
the source. Neither maker parses anything to decide what ships.

Rust needs one line that JavaScript does not: `langs['rust'] = '//'`, because fastcore's
comment-character map has no Rust and falls through to `#`, so `//| export` was never seen as a
directive. That belongs upstream in fastcore.

## The decision the Rust side makes concrete

The notebook stays plain Rust with no PyO3 in it, so Leela's cargo runner executes the cells at
the speed it would otherwise. The binding is generated at export.

For a free function that is a wrapper. For a struct it cannot be, because `#[pyclass]` has to sit
on the struct definition itself -- rewriting the exported module to carry it would make that
module need pyo3 to compile, and the notebook would stop running. So a struct gets a newtype:

    //| export
    #[derive(Debug, Clone)]
    pub struct Point { pub x: i64, pub y: i64 }

    //| export
    impl Point {
        pub fn new(x: i64, y: i64) -> Self { Self { x, y } }
        pub fn dist2(&self) -> i64 { dist2(self.x, self.y) }
        pub fn scaled(&self, k: i64) -> Self { Self::new(self.x * k, self.y * k) }
    }

becomes `src/geom.rs` verbatim, and this in `src/lib.rs`:

    #[pyclass(name = "Point")]
    #[derive(Clone)]
    pub struct PyPoint(pub geom::Point);

    #[pymethods]
    impl PyPoint {
        #[new]
        fn new(x: i64, y: i64) -> Self { Self(geom::Point::new(x, y)) }
        #[getter]
        fn x(&self) -> i64 { self.0.x.clone() }
        #[getter]
        fn y(&self) -> i64 { self.0.y.clone() }
        fn dist2(&self) -> i64 { self.0.dist2() }
        fn scaled(&self, k: i64) -> Self { Self(self.0.scaled(k)) }
        fn __repr__(&self) -> String { format!("{:?}", self.0) }
    }

`#[new]` prefers an inherent `new`, and falls back to a struct literal when every field is public.
`__repr__` and `#[derive(Clone)]` appear only when the struct derives `Debug` and `Clone`, because
generating them otherwise would be generating Rust that does not compile.

## The decision the JavaScript side makes concrete

Two artefacts, two tools, and the second is not the obvious one.

`deno bundle --platform=browser --minify` writes the CDN file, versioned in its name so it can be
served immutable. The demo package comes out at 283 bytes.

`deno bundle --declaration` is **not** how to get types. On a JavaScript entry it emits a
re-export carrying an absolute `file://` path, which is worse than shipping none. `tsc --allowJs
--declaration` reads the JSDoc the cells were written with and produces real ones:

    export function dist2(x: number, y: number): number;

## Run it

    python -m pytest tests/test_nbship.py            # both exports, no toolchain needed
    python -m pytest tests/test_nbship.py -m slow    # the wheel and the browser

By hand, against the notebooks in `nbs/`:

```python
from nbdev.export import nb_export
from nbship.rust import cargo_maker
from nbship.js import esm_maker, bundle, declarations

nb_export('nbs/geometry.ipynb', lib_path='demo_geom',
          mod_maker=cargo_maker('demo_geom'), solo_nb=True)
nb_export('nbs/geometry-js.ipynb', lib_path='demo-geom',
          mod_maker=esm_maker('demo-geom'), solo_nb=True)
bundle('demo-geom'); declarations('demo-geom')
```

then `cd demo_geom && ship-rs-init && ship-rs-build`.

## What this does not answer

- **Where it lives.** This belongs in its own package, not in Leela: CI has to run the export for
  a `cargo build`, and nothing about that should pull in FastHTML and uvicorn. `nb_export`'s
  `mod_maker` parameter is enough of an invitation that an nbdev pull request is worth asking
  about first.
- **Publishing.** `ship-rs-build` makes the wheel but nothing here uploads one, and the npm and
  CDN steps are `npm publish` and a copy to a bucket. fastship already has the npm release path.
- **Rust beyond simple signatures.** Generics, lifetimes, trait objects and enums export fine as
  Rust, but get no Python binding. Non-public fields get no getter. A method taking `self` by
  value is skipped. These are recognised and left alone rather than mis-generated, but they are
  not covered.
- **TypeScript.** It would give real types without the `tsc` pass and give the cells a type
  checker, and `deno` is already both its runner and its bundler. Leela's language registry lists
  it with no runner today.
