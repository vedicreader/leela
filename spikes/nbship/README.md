# nbship: a notebook in another language, exported into something shippable

Not part of Leela. This settles one question before a package gets designed around it: does the
nbdev path extend to the languages Leela now runs, all the way to a published artefact, using what
already exists? It does, for both.

    nbship-rs geometry.ipynb --install

    Rust notebook  ->  syn  ->  crate + PyO3 binding  ->  maturin  ->  wheel  ->  installed
    JS notebook    ->  ESM package  ->  deno bundle  ->  one file a CDN can serve

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
the source. Neither maker decides what ships -- the language already did.

Rust needs one line that JavaScript does not: `langs['rust'] = '//'`, because fastcore's
comment-character map has no Rust and falls through to `#`, so `//| export` was never seen as a
directive. That belongs upstream in fastcore.

## Reading Rust with Rust

`rustparse/` is a small `syn` program: Rust source on stdin, JSON on stdout. `syn` is the parser
the whole Rust macro ecosystem is built on, so what comes back is the real shape of the code.

This replaced a pile of regular expressions, and the reason is not tidiness. A regex cannot see a
generic parameter, a lifetime, a `where` clause, a trait impl or a nested module, so the generator
used to emit Rust that did not compile and could not say why. Now every item that stays behind
carries its reason, and `nbship-rs` prints them:

    1 item(s) stayed in the crate, with no Python binding:
      - fn `largest` takes a generic parameter `T : PartialOrd`, which PyO3 cannot bind
      These are still Rust you can call from Rust. Widen a signature to bring one across.

That list is the point as much as the wheel is. It is where PyO3's edge actually is, written out
against your own code.

The parser is built once into `$XDG_DATA_HOME/nbship/parser/<hash>` and reused until its own
sources change. About twenty seconds, and only ever again if this crate changes.

## The decision the Rust side makes concrete

The notebook stays plain Rust with no PyO3 in it, so Leela's cargo runner executes the cells at
full speed. The binding is generated at export.

For a free function that is a wrapper. For a struct it cannot be, because `#[pyclass]` has to sit
on the struct definition itself -- rewriting the exported module to carry it would make that
module need pyo3 to compile, and the notebook would stop running. So a struct gets a newtype in
`lib.rs`, and the module it came from never learns pyo3 exists.

What crosses over:

| in the notebook | in Python |
|---|---|
| `pub fn f(..) -> T` | a module-level function |
| `/// doc comment` | `__doc__` |
| `pub struct S` | a class, named `S` |
| `pub fn new(..) -> Self` | `__init__` |
| a `pub` field | a property |
| `pub fn m(&self)` | a method |
| `pub fn m(&mut self)` | a method that mutates |
| `pub fn m(..) -> Self` | a method returning a new instance |
| `pub fn f()` with no receiver | a `@staticmethod` |
| `#[derive(Debug)]` | `__repr__` |
| `Result<T, E>` | `T`, or a `ValueError` carrying the error |
| an exported struct in a signature | that class, in and out |

What does not, each reported by name: generics, lifetimes, `where` clauses, borrows in a
signature, `impl Trait`, `async`, traits, enums, tuple structs, private fields and methods, an
exported type nested inside a container.

`Result` is worth a note. PyO3 converts only the error types it knows about, so the wrapper maps
through `Display` instead, which works for an error type PyO3 has never heard of and for one you
wrote yourself.

## The decision the JavaScript side makes concrete

Two artefacts, two tools, and the second is not the obvious one.

`deno bundle --platform=browser --minify` writes the CDN file, versioned in its name so it can be
served immutable. The demo package comes out at 283 bytes.

`deno bundle --declaration` is **not** how to get types. On a JavaScript entry it emits a
re-export carrying an absolute `file://` path, which is worse than shipping none. `tsc --allowJs
--declaration` reads the JSDoc the cells were written with and produces real ones:

    export function dist2(x: number, y: number): number;

## Run it

One command, notebook to installed wheel:

    python -m nbship geometry.ipynb --install

`--no-build` stops at the crate, `--no-pyo3` writes a plain Rust crate with no binding, `--deps
'rand = "0.8"'` adds a dependency, `--crate`, `--version` and `--description` name the package. A
folder instead of a notebook exports every notebook in it into one crate.

The tests:

    python -m pytest tests/test_nbship.py            # no toolchain needed
    python -m pytest tests/test_nbship.py -m slow    # the parser, the wheel and the browser

## What this does not answer

- **Where it lives.** This belongs in its own package, not in Leela: CI has to run the export for
  a `cargo build`, and nothing about that should pull in FastHTML and uvicorn. `nb_export`'s
  `mod_maker` parameter is enough of an invitation that an nbdev pull request is worth asking
  about first.
- **Enums, tuple structs, and containers of exported types.** Recognised and reported, not bound.
  Each is a next increment rather than a hard problem: an enum of unit variants maps to a
  `#[pyclass]` enum, and a `Vec<Point>` needs one `map` in the wrapper.
- **Publishing.** `nbship-rs` makes the wheel; nothing here uploads one. `ship-gh` and `ship-pypi`
  from fastship do that, and `ship-rs-init` accepts the generated crate unchanged.
- **TypeScript.** It would give real types without the `tsc` pass and give the cells a type
  checker, and `deno` is already both its runner and its bundler. Leela's language registry lists
  it with no runner today.
