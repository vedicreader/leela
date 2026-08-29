"""nbdev for the languages Leela now runs: a notebook exported into something shippable.

Rust goes to a cargo crate with a PyO3 binding and out as a wheel; JavaScript goes to an ESM
package and out as a CDN bundle. This covers `spikes/nbship`, which is not part of Leela's
runtime. It lives here rather than beside the spike so the export paths are checked on every run;
only the builds ask for a toolchain.
"""
import json, os as _os, shutil, subprocess, sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SPIKE = ROOT/'spikes'/'nbship'
sys.path.insert(0, str(ROOT/'spikes'))

from nbship.rust import CargoMaker, cargo_maker, pub_fns, pub_structs     # noqa: E402
from nbship.js import esm_maker, bundle, declarations, ToolMissing        # noqa: E402
from nbdev.export import nb_export                                        # noqa: E402
from fastcore.nbio import langs                                           # noqa: E402

NB = SPIKE/'nbs'/'geometry.ipynb'
JS_NB = SPIKE/'nbs'/'geometry-js.ipynb'

def _export(tmp_path, crate='demo_geom', nb=None, pyo3=True):
    dest = tmp_path/crate
    nb_export(str(nb or NB), lib_path=str(dest), mod_maker=cargo_maker(crate, pyo3=pyo3),
              solo_nb=True)
    return dest

# what makes a Rust notebook exportable at all --------------------------------------------------

def test_rust_gets_a_comment_character_so_its_directives_are_seen():
    "Without this, `//| export` falls through to fastcore's `#` default and nothing is exported."
    assert langs['rust'] == '//'

def test_the_notebook_this_spike_exports_is_a_rust_notebook():
    meta = json.loads(NB.read_text())['metadata']
    assert meta['kernelspec']['language'] == 'rust', 'the language Leela now round-trips'

# reading the export list out of the language itself ---------------------------------------------

def test_public_functions_are_the_export_list():
    "Rust has a visibility keyword, so unlike Python there is no `__all__` to reconstruct."
    src = 'pub fn a(x: i64) -> i64 { x }\nfn b() {}\npub fn c(s: &str, n: u8) {}\n'
    assert pub_fns(src) == [('a', [('x', 'i64')], 'i64'), ('c', [('s', '&str'), ('n', 'u8')], '()')]

def test_a_method_is_not_a_free_function():
    assert pub_fns('impl P {\n    pub fn len(&self) -> i64 { 0 }\n}') == []

def test_a_doc_comment_does_not_hide_the_function_under_it():
    assert [n for n, _, _ in pub_fns('/// docs\npub fn f() {}')] == ['f']

# the crate that comes out ------------------------------------------------------------------------

def test_the_exported_crate_has_the_shape_maturin_needs(tmp_path):
    d = _export(tmp_path)
    assert sorted(p.relative_to(d).as_posix() for p in d.rglob('*') if p.is_file()) == [
        'Cargo.toml', 'pyproject.toml', 'src/geom.rs', 'src/lib.rs']
    cargo = (d/'Cargo.toml').read_text()
    assert 'crate-type = ["cdylib", "rlib"]' in cargo and 'pyo3' in cargo
    proj = (d/'pyproject.toml').read_text()
    assert 'build-backend = "maturin"' in proj
    # What `fastship.get_rs_config` refuses a project without.
    assert 'dynamic = ["version"]' in proj and '\nversion =' not in proj

def test_only_the_exported_cells_reach_the_crate(tmp_path):
    "The cell that printed while exploring is the point of a notebook, and must not be shipped."
    src = (_export(tmp_path)/'src'/'geom.rs').read_text()
    assert 'pub fn dist2' in src and 'pub fn gcd' in src
    assert 'println!' not in src, 'the exploration cell stayed in the notebook'
    assert '//| export' not in src, 'the directive is consumed, not copied'

def test_the_binding_is_generated_so_the_notebook_can_stay_plain_rust(tmp_path):
    """The cells carry no PyO3, so Leela's cargo runner can run them with no pyo3 dependency.
    Every `#[pyfunction]` here was written at export from a `pub fn` that was exported."""
    lib = (_export(tmp_path)/'src'/'lib.rs').read_text()
    assert 'pub mod geom;' in lib
    assert 'fn dist2(x: i64, y: i64) -> i64 { geom::dist2(x, y) }' in lib
    assert 'fn gcd(a: u64, b: u64) -> u64 { geom::gcd(a, b) }' in lib
    assert lib.count('#[pyfunction]') == 2
    assert 'wrap_pyfunction!(dist2, m)' in lib and 'wrap_pyfunction!(gcd, m)' in lib
    assert "fn demo_geom(m: &Bound<'_, PyModule>) -> PyResult<()>" in lib

def test_a_crate_that_is_not_for_python_carries_no_pyo3(tmp_path):
    lib = (_export(tmp_path, crate='plain', pyo3=False)/'src'/'lib.rs').read_text()
    assert 'pub mod geom;' in lib
    assert 'pyo3' not in lib and '#[pymodule]' not in lib

def test_a_second_notebook_joins_the_crate_rather_than_replacing_it(tmp_path):
    "`nb_export` makes one maker per module, so `lib.rs` has to be rebuilt from what is on disk."
    other = tmp_path/'extra.ipynb'
    nb = json.loads(NB.read_text())
    nb['cells'] = [{'cell_type': 'code', 'id': 'x0', 'metadata': {}, 'outputs': [],
                    'execution_count': None, 'source': '//| default_exp extra'},
                   {'cell_type': 'code', 'id': 'x1', 'metadata': {}, 'outputs': [],
                    'execution_count': None, 'source': '//| export\npub fn twice(n: i64) -> i64 { n * 2 }'}]
    other.write_text(json.dumps(nb))
    d = _export(tmp_path)
    nb_export(str(other), lib_path=str(d), mod_maker=cargo_maker('demo_geom'), solo_nb=True)
    lib = (d/'src'/'lib.rs').read_text()
    assert 'pub mod geom;' in lib and 'pub mod extra;' in lib
    assert 'wrap_pyfunction!(twice, m)' in lib and 'wrap_pyfunction!(dist2, m)' in lib

# a struct becomes a class ------------------------------------------------------------------------

def test_a_struct_is_read_with_its_derives_fields_and_methods():
    src = ("""#[derive(Debug, Clone)]
pub struct P { pub x: i64, pub y: i64 }

impl P {
    pub fn new(x: i64, y: i64) -> Self { Self { x, y } }
    pub fn norm(&self) -> i64 { self.x }
    pub fn bump(&mut self) {}
    pub fn hidden() -> i64 { 1 }
}""")
    st = pub_structs(src)[0]
    assert (st.name, st.debug, st.clone) == ('P', True, True)
    assert st.fields == [('x', 'i64'), ('y', 'i64')]
    assert st.ctor == [('x', 'i64'), ('y', 'i64')]
    assert [(n, r, a, t) for n, r, a, t in st.methods] == [
        ('norm', '&self', [], 'i64'), ('bump', '&mut self', [], '()')]

def test_an_impl_block_in_another_cell_still_belongs_to_its_struct(tmp_path):
    "Cells are concatenated into one module, so the struct and its impl need not be one cell."
    lib = (_export(tmp_path)/'src'/'lib.rs').read_text()
    assert 'fn dist2(&self) -> i64 { self.0.dist2() }' in lib

def test_the_wrapper_keeps_the_module_it_wraps_free_of_pyo3(tmp_path):
    """`#[pyclass]` has to sit on the struct definition, so rewriting `geom.rs` to carry it would
    make that module need pyo3 to compile -- and the notebook would stop running in Leela."""
    d = _export(tmp_path)
    assert 'pyo3' not in (d/'src'/'geom.rs').read_text()
    assert 'pyclass' not in (d/'src'/'geom.rs').read_text()
    lib = (d/'src'/'lib.rs').read_text()
    assert '#[pyclass(name = "Point")]' in lib
    assert 'pub struct PyPoint(pub geom::Point);' in lib
    assert 'm.add_class::<PyPoint>()?;' in lib

def test_the_generated_class_carries_the_constructor_getters_and_methods(tmp_path):
    lib = (_export(tmp_path)/'src'/'lib.rs').read_text()
    assert 'fn new(x: i64, y: i64) -> Self { Self(geom::Point::new(x, y)) }' in lib
    assert lib.count('#[getter]') == 2
    assert 'fn x(&self) -> i64 { self.0.x.clone() }' in lib
    assert 'fn dist2(&self) -> i64 { self.0.dist2() }' in lib

def test_a_method_returning_self_is_rewrapped(tmp_path):
    "Otherwise it would return the inner Rust type, which Python has never heard of."
    lib = (_export(tmp_path)/'src'/'lib.rs').read_text()
    assert 'fn scaled(&self, k: i64) -> Self { Self(self.0.scaled(k)) }' in lib

def test_repr_is_only_written_when_the_struct_can_be_debugged(tmp_path):
    lib = (_export(tmp_path)/'src'/'lib.rs').read_text()
    assert 'fn __repr__' in lib, 'the demo struct derives Debug'
    nb = tmp_path/'plain.ipynb'
    d = json.loads(NB.read_text())
    d['cells'] = [{'cell_type': 'code', 'id': 'p0', 'metadata': {}, 'outputs': [],
                   'execution_count': None, 'source': '//| default_exp bare'},
                  {'cell_type': 'code', 'id': 'p1', 'metadata': {}, 'outputs': [],
                   'execution_count': None, 'source': '//| export\npub struct Bare { pub n: i64 }'}]
    nb.write_text(json.dumps(d))
    lib2 = (_export(tmp_path/'other', nb=nb, crate='bare')/'src'/'lib.rs').read_text()
    assert '#[pyclass(name = "Bare")]' in lib2
    assert 'fn __repr__' not in lib2 and '#[derive(Clone)]' not in lib2

# JavaScript: an ESM package and a CDN bundle -----------------------------------------------------

def _export_js(tmp_path, pkg='demo-geom'):
    dest = tmp_path/pkg
    nb_export(str(JS_NB), lib_path=str(dest), mod_maker=esm_maker(pkg), solo_nb=True)
    return dest

def test_javascript_needs_no_patch_to_be_exportable():
    "Unlike Rust, `javascript` is already in fastcore's comment-character map."
    assert langs['javascript'] == '//'

def test_the_exported_package_is_a_publishable_esm_package(tmp_path):
    d = _export_js(tmp_path)
    pkg = json.loads((d/'package.json').read_text())
    assert pkg['type'] == 'module' and pkg['sideEffects'] is False
    assert pkg['exports']['.']['default'] == './mod.js'
    assert pkg['exports']['./geom'] == './src/geom.js'
    assert (d/'mod.js').read_text().strip().endswith("export * from './src/geom.js';")

def test_only_exported_javascript_cells_reach_the_package(tmp_path):
    src = (_export_js(tmp_path)/'src'/'geom.js').read_text()
    assert 'export function dist2' in src and 'export class Point' in src
    assert 'console.log' not in src, 'the exploration cell stayed in the notebook'
    assert '//| export' not in src

def test_the_cdn_file_is_versioned_so_it_can_be_cached_forever(tmp_path, monkeypatch):
    "A CDN URL that is immutable needs the version in the name, not just in package.json."
    monkeypatch.setattr('nbship.js._run', lambda *a, **kw: None)
    monkeypatch.setattr('nbship.js._tool', lambda *a, **kw: 'deno')
    assert bundle(_export_js(tmp_path)).name == 'demo-geom-0.1.0.min.js'

def test_a_missing_bundler_is_named_rather_than_guessed_at(tmp_path, monkeypatch):
    monkeypatch.setattr(shutil, 'which', lambda name: None)
    with pytest.raises(ToolMissing) as e: bundle(_export_js(tmp_path))
    assert 'deno' in str(e.value)

# the whole chain, against the real toolchains ----------------------------------------------------

@pytest.mark.slow
def test_the_exported_crate_builds_into_a_wheel_that_python_can_call(tmp_path):
    "The claim this spike exists to settle: a Rust notebook reaches PyPI as a wheel that works."
    for tool in ('cargo', 'maturin'):
        if not shutil.which(tool): pytest.skip(f'{tool} is not installed')
    d = _export(tmp_path)
    r = subprocess.run(['maturin', 'build', '--release', '--out', 'dist'], cwd=d,
                       capture_output=True, text=True, timeout=900)
    assert r.returncode == 0, r.stderr[-3000:]
    wheels = list((d/'dist').glob('*.whl'))
    assert len(wheels) == 1, wheels
    venv = tmp_path/'venv'
    subprocess.run(['uv', 'venv', '-q', str(venv)], check=True, timeout=300)
    py = venv/'bin'/'python'
    subprocess.run(['uv', 'pip', 'install', '-q', '--python', str(py), str(wheels[0])],
                   check=True, timeout=600)
    out = subprocess.run([str(py), '-c', 'import demo_geom as g; print(g.dist2(3,4), g.gcd(48,18))'],
                         capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    assert out.stdout.split() == ['25', '6']

@pytest.mark.slow
def test_the_class_the_wrapper_generated_behaves_like_a_python_class(tmp_path):
    "The pyclass claim, settled the only way it can be: build it and use it."
    for tool in ('cargo', 'maturin'):
        if not shutil.which(tool): pytest.skip(f'{tool} is not installed')
    d = _export(tmp_path)
    r = subprocess.run(['maturin', 'build', '--release', '--out', 'dist'], cwd=d,
                       capture_output=True, text=True, timeout=900)
    assert r.returncode == 0, r.stderr[-3000:]
    venv = tmp_path/'venv'
    subprocess.run(['uv', 'venv', '-q', str(venv)], check=True, timeout=300)
    py = venv/'bin'/'python'
    subprocess.run(['uv', 'pip', 'install', '-q', '--python', str(py),
                    str(next((d/'dist').glob('*.whl')))], check=True, timeout=600)
    script = ('import demo_geom as g\n'
              'p = g.Point(3, 4)\n'
              'print(repr(p), p.x, p.y, p.dist2(), p.scaled(2).dist2())\n')
    out = subprocess.run([str(py), '-c', script], capture_output=True, text=True, timeout=120)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == 'Point { x: 3, y: 4 } 3 4 25 100'

@pytest.mark.slow
def test_the_javascript_package_bundles_and_runs_in_a_browser(tmp_path):
    "The CDN claim: one minified file, fetched cross-origin by a real browser, that works."
    if not shutil.which('deno'): pytest.skip('deno is not installed')
    pytest.importorskip('playwright.sync_api')
    import functools, http.server, socket, threading
    from playwright.sync_api import sync_playwright

    d = _export_js(tmp_path)
    out = bundle(d)
    assert out.exists() and out.stat().st_size < 4000, 'tree-shaken and minified'

    class CORS(http.server.SimpleHTTPRequestHandler):
        def end_headers(self):
            self.send_header('Access-Control-Allow-Origin', '*')
            super().end_headers()
        def log_message(self, *a): pass
    def serve(root):
        with socket.socket() as s:
            s.bind(('127.0.0.1', 0)); port = s.getsockname()[1]
        srv = http.server.ThreadingHTTPServer(
            ('127.0.0.1', port), functools.partial(CORS, directory=str(root)))
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        return srv, port

    cdn, cdn_port = serve(out.parent)
    site = tmp_path/'site'; site.mkdir()
    web, site_port = serve(site)
    url = f'http://127.0.0.1:{cdn_port}/{out.name}'
    (site/'index.html').write_text(
        '<!doctype html><meta charset=utf-8><script type="module">'
        f'const m = await import("{url}");'
        'const p = new m.Point(3, 4);'
        'window.r = [m.dist2(3,4), m.gcd(48,18), String(p.scaled(2)), Object.keys(m).sort()];'
        '</script>', encoding='utf-8')
    try:
        with sync_playwright() as pw:
            kw = {'args': ['--no-sandbox']}
            if (exe := _os.environ.get('LEELA_CHROMIUM', '/opt/pw-browsers/chromium')):
                if Path(exe).exists(): kw['executable_path'] = exe
            try: b = pw.chromium.launch(**kw)
            except Exception as e: pytest.skip(f'no chromium: {e}')
            pg = b.new_page()
            pg.goto(f'http://127.0.0.1:{site_port}/index.html')
            pg.wait_for_function('window.r', timeout=20000)
            r = pg.evaluate('window.r')
            b.close()
    finally:
        cdn.shutdown(); web.shutdown()
    assert r == [25, 6, 'Point(6, 8)', ['Point', 'dist2', 'gcd']]

@pytest.mark.slow
def test_the_declarations_come_from_the_jsdoc_the_cells_carried(tmp_path):
    "Hand-written JavaScript gets no types unless something reads the JSDoc. `tsc` does."
    d = _export_js(tmp_path)
    if not (shutil.which('tsc') or (d/'node_modules'/'.bin'/'tsc').exists()):
        pytest.skip('typescript is not installed')
    types = (declarations(d).parent/'src'/'geom.d.ts').read_text()
    assert 'export function dist2(x: number, y: number): number;' in types
    assert 'export class Point' in types
