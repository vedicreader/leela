"""nbdev for the languages Leela now runs: a notebook exported into something shippable.

Rust goes to a cargo crate with a PyO3 binding and out as a wheel; JavaScript goes to an ESM
package and out as a CDN bundle. This covers `spikes/nbship`, which is not part of Leela's runtime.
It lives here rather than beside the spike so the export paths are checked on every run.

The generator's tests feed it the parser's output rather than running the parser, so they need no
toolchain. The parser has its own tests, and they are slow because it is a Rust program.
"""
import json, os as _os, shutil, subprocess, sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SPIKE = ROOT/'spikes'/'nbship'
sys.path.insert(0, str(ROOT/'spikes'))

from nbship import rust as R                                              # noqa: E402
from nbship.rust import CargoMaker, cargo_maker, binding, Skipped         # noqa: E402
from nbship.js import esm_maker, bundle, declarations, ToolMissing        # noqa: E402
from nbship.cli import export, _slug                                      # noqa: E402
from nbdev.export import nb_export                                        # noqa: E402
from fastcore.nbio import langs                                           # noqa: E402

NB = SPIKE/'nbs'/'geometry.ipynb'
JS_NB = SPIKE/'nbs'/'geometry-js.ipynb'

# building the parser's answers by hand, which is also what documents its shape ------------------

def fn(name, args=(), ret='()', doc='', recv=None, skip=None, **kw):
    return {'kind': 'fn', 'name': name, 'doc': doc, 'recv': recv, 'ret': ret, 'skip': skip,
            'is_async': False, 'args': [{'name': n, 'ty': t} for n, t in args], **kw}

def struct(name, fields=(), methods=(), statics=(), derives=('Debug', 'Clone'), doc='', skip=None):
    return {'kind': 'struct', 'name': name, 'doc': doc, 'derives': list(derives), 'skip': skip,
            'tuple': False, 'methods': list(methods), 'statics': list(statics),
            'fields': [{'name': n, 'ty': t, 'skip': None} for n, t in fields]}

def gen(items, crate='demo', monkeypatch=None):
    "Run the generator over one module's worth of parsed items."
    monkeypatch.setattr(R, 'rust_items', lambda src, exe=None: items)
    return binding({'geom': ''}, crate)

# what the generator writes ----------------------------------------------------------------------

def test_a_function_becomes_a_pyfunction_with_its_doc(monkeypatch):
    lib, left = gen([fn('dist2', [('x', 'i64'), ('y', 'i64')], 'i64', doc='Squared distance.')],
                    monkeypatch=monkeypatch)
    assert '/// Squared distance.' in lib, 'the Rust doc becomes the Python docstring'
    assert '#[pyfunction]' in lib
    assert 'fn dist2(x: i64, y: i64) -> i64 { geom::dist2(x, y) }' in lib
    assert 'm.add_function(wrap_pyfunction!(dist2, m)?)?;' in lib
    assert left == []

def test_a_result_becomes_a_python_exception(monkeypatch):
    "PyO3 only converts errors it knows. Mapping through `Display` works for any error type."
    lib, _ = gen([fn('parse', [('s', 'String')], 'Result<i64, ParseIntError>')],
                 monkeypatch=monkeypatch)
    assert 'fn parse(s: String) -> PyResult<i64>' in lib
    assert 'PyValueError::new_err(e.to_string())' in lib

def test_a_result_of_an_exported_type_is_wrapped_before_it_is_raised(monkeypatch):
    lib, _ = gen([struct('Point', [('x', 'i64')]),
                  fn('parse', [('s', 'String')], 'Result<Point, E>')], monkeypatch=monkeypatch)
    assert 'fn parse(s: String) -> PyResult<PyPoint>' in lib
    assert 'geom::parse(s).map(PyPoint).map_err(' in lib

def test_an_exported_type_crosses_in_both_directions(monkeypatch):
    lib, _ = gen([struct('Point', [('x', 'i64')]),
                  fn('mid', [('a', 'Point'), ('b', 'Point')], 'Point')], monkeypatch=monkeypatch)
    assert 'fn mid(a: PyPoint, b: PyPoint) -> PyPoint { PyPoint(geom::mid(a.0, b.0)) }' in lib

def test_an_exported_type_inside_a_container_is_refused_with_a_reason(monkeypatch):
    "Unpacking a `Vec<Point>` into a `Vec<PyPoint>` is a conversion this does not write yet."
    lib, left = gen([struct('Point', [('x', 'i64')]), fn('all', ret='Vec<Point>')],
                    monkeypatch=monkeypatch)
    assert 'fn all' not in lib
    assert len(left) == 1 and 'container' in left[0].why

def test_what_the_parser_refused_is_carried_through_verbatim(monkeypatch):
    lib, left = gen([fn('largest', ret='T', skip='takes a generic parameter `T`')],
                    monkeypatch=monkeypatch)
    assert 'largest' not in lib
    assert str(left[0]) == 'fn `largest` takes a generic parameter `T`'

def test_a_struct_becomes_a_class_the_module_never_learns_about(monkeypatch):
    """`#[pyclass]` has to sit on the struct definition, so rewriting the exported module to carry
    it would make that module need pyo3 -- and the notebook would stop running in Leela."""
    lib, _ = gen([struct('Point', [('x', 'i64'), ('y', 'i64')],
                         methods=[fn('dist2', ret='i64', recv='&self')],
                         statics=[fn('new', [('x', 'i64'), ('y', 'i64')], 'Self')])],
                 monkeypatch=monkeypatch)
    assert '#[pyclass(name = "Point")]' in lib
    assert '#[derive(Clone)]' in lib
    assert 'pub struct PyPoint(pub geom::Point);' in lib
    assert 'fn new(x: i64, y: i64) -> Self { Self(geom::Point::new(x, y)) }' in lib
    assert 'fn x(&self) -> i64 { self.0.x.clone() }' in lib
    assert 'fn dist2(&self) -> i64 { self.0.dist2() }' in lib
    assert 'fn __repr__' in lib
    assert 'm.add_class::<PyPoint>()?;' in lib

def test_a_struct_with_no_constructor_gets_one_from_its_fields(monkeypatch):
    lib, _ = gen([struct('P', [('x', 'i64')])], monkeypatch=monkeypatch)
    assert 'fn new(x: i64) -> Self { Self(geom::P { x }) }' in lib

def test_an_associated_function_becomes_a_staticmethod(monkeypatch):
    lib, _ = gen([struct('P', [('x', 'i64')], statics=[fn('origin', ret='Self')])],
                 monkeypatch=monkeypatch)
    assert '#[staticmethod]' in lib
    assert 'fn origin() -> Self { Self(geom::P::origin()) }' in lib

def test_a_mutating_method_keeps_its_receiver(monkeypatch):
    lib, _ = gen([struct('P', [('x', 'i64')],
                         methods=[fn('nudge', [('d', 'i64')], recv='&mut self')])],
                 monkeypatch=monkeypatch)
    assert 'fn nudge(&mut self, d: i64) { self.0.nudge(d) }' in lib

def test_repr_and_clone_appear_only_when_the_struct_derives_them(monkeypatch):
    lib, _ = gen([struct('P', [('x', 'i64')], derives=())], monkeypatch=monkeypatch)
    assert 'fn __repr__' not in lib and '#[derive(Clone)]' not in lib

def test_an_async_function_is_refused_rather_than_mis_generated(monkeypatch):
    lib, left = gen([{**fn('load', ret='String'), 'is_async': True}], monkeypatch=monkeypatch)
    assert 'fn load' not in lib and 'async' in left[0].why

def test_a_crate_with_no_python_binding_is_still_a_crate(tmp_path):
    dest, left = export(NB, out=tmp_path/'plain', crate='plain', pyo3=False)
    lib = (dest/'src'/'lib.rs').read_text()
    assert lib.strip().endswith('pub mod geom;')
    assert 'pyo3' not in lib and left == []

# the crate that comes out ------------------------------------------------------------------------

def test_the_exported_crate_has_the_shape_maturin_needs(tmp_path):
    dest, _ = export(NB, out=tmp_path/'demo', crate='demo_geom')
    assert sorted(p.relative_to(dest).as_posix() for p in dest.rglob('*') if p.is_file()) == [
        '.gitignore', 'Cargo.toml', 'pyproject.toml', 'src/geom.rs', 'src/lib.rs']
    cargo = (dest/'Cargo.toml').read_text()
    assert 'crate-type = ["cdylib", "rlib"]' in cargo and 'pyo3' in cargo
    proj = (dest/'pyproject.toml').read_text()
    assert 'build-backend = "maturin"' in proj
    ignore = (dest/'.gitignore').read_text()
    assert '/target/' in ignore and '/dist/' in ignore, 'the build outputs, named before they exist'
    # What `fastship.get_rs_config` refuses a project without.
    assert 'dynamic = ["version"]' in proj and '\nversion =' not in proj

def test_only_the_exported_cells_reach_the_crate(tmp_path):
    "The cell that printed while exploring is the point of a notebook, and must not be shipped."
    dest, _ = export(NB, out=tmp_path/'demo', crate='demo_geom')
    src = (dest/'src'/'geom.rs').read_text()
    assert 'pub fn dist2' in src and 'pub struct Point' in src
    assert 'println!' not in src, 'the exploration cell stayed in the notebook'
    assert '//| export' not in src, 'the directive is consumed, not copied'
    assert 'pyo3' not in src, 'the module the notebook runs stays free of pyo3'

def test_the_notebook_names_the_crate_when_nothing_else_does():
    "The crate takes the notebook's name; the module inside it takes `default_exp`."
    assert _slug('01_my-notebook.ipynb') == '01_my_notebook'

def test_a_second_notebook_joins_the_crate_rather_than_replacing_it(tmp_path):
    other = tmp_path/'extra.ipynb'
    nb = json.loads(NB.read_text())
    nb['cells'] = [{'cell_type': 'code', 'id': 'x0', 'metadata': {}, 'outputs': [],
                    'execution_count': None, 'source': '//| default_exp extra'},
                   {'cell_type': 'code', 'id': 'x1', 'metadata': {}, 'outputs': [],
                    'execution_count': None,
                    'source': '//| export\npub fn twice(n: i64) -> i64 { n * 2 }'}]
    other.write_text(json.dumps(nb))
    dest, _ = export([NB, other], out=tmp_path/'demo', crate='demo_geom')
    lib = (dest/'src'/'lib.rs').read_text()
    assert 'pub mod geom;' in lib and 'pub mod extra;' in lib
    assert 'wrap_pyfunction!(twice, m)' in lib and 'wrap_pyfunction!(dist2, m)' in lib

# what makes a Rust notebook exportable at all ----------------------------------------------------

def test_rust_gets_a_comment_character_so_its_directives_are_seen():
    "Without this, `//| export` falls through to fastcore's `#` default and nothing is exported."
    assert langs['rust'] == '//'

def test_javascript_needed_no_such_patch():
    assert langs['javascript'] == '//'

def test_the_notebooks_this_spike_exports_name_their_languages():
    assert json.loads(NB.read_text())['metadata']['kernelspec']['language'] == 'rust'
    assert json.loads(JS_NB.read_text())['metadata']['kernelspec']['language'] == 'javascript'

# JavaScript: an ESM package and a CDN bundle -----------------------------------------------------

def _export_js(tmp_path, pkg='demo-geom'):
    dest = tmp_path/pkg
    nb_export(str(JS_NB), lib_path=str(dest), mod_maker=esm_maker(pkg), solo_nb=True)
    return dest

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
    assert 'console.log' not in src and '//| export' not in src

def test_the_cdn_file_is_versioned_so_it_can_be_cached_forever(tmp_path, monkeypatch):
    "A CDN URL that is immutable needs the version in the name, not just in package.json."
    monkeypatch.setattr('nbship.js._run', lambda *a, **kw: None)
    monkeypatch.setattr('nbship.js._tool', lambda *a, **kw: 'deno')
    assert bundle(_export_js(tmp_path)).name == 'demo-geom-0.1.0.min.js'

def test_a_missing_bundler_is_named_rather_than_guessed_at(tmp_path, monkeypatch):
    monkeypatch.setattr(shutil, 'which', lambda name: None)
    with pytest.raises(ToolMissing) as e: bundle(_export_js(tmp_path))
    assert 'deno' in str(e.value)

# the parser, which is a Rust program -------------------------------------------------------------

HARD = '''
/// Squared distance.
pub fn dist2(x: i64, y: i64) -> i64 { x * x + y * y }
pub fn largest<T: PartialOrd>(v: Vec<T>) -> T { v.into_iter().next().unwrap() }
pub fn first(v: &Vec<String>) -> &String { &v[0] }
pub fn parse(s: String) -> Result<i64, std::num::ParseIntError> { s.parse() }
fn private_helper() -> i64 { 1 }

#[derive(Debug, Clone)]
pub struct Point { pub x: i64, pub y: i64, secret: i64 }

impl Point {
    pub fn new(x: i64, y: i64) -> Self { Self { x, y, secret: 0 } }
    pub fn dist2(&self) -> i64 { 0 }
    pub fn nudge(&mut self, d: i64) { self.x += d; }
    fn hidden(&self) -> i64 { 0 }
}

impl std::fmt::Display for Point {
    fn fmt(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result { write!(f, "p") }
}

pub struct Wrapper<T> { pub inner: T }
pub trait Shape { fn area(&self) -> f64; }
pub mod nested { pub fn deep() -> i64 { 7 } }
'''

@pytest.fixture(scope='module')
def parsed():
    from nbship.parse import rust_items, parser_path
    if not shutil.which('cargo') and not parser_path(build=False):
        pytest.skip('cargo is needed once, to build the Rust parser')
    return {i['name']: i for i in rust_items(HARD)}

@pytest.mark.slow
def test_the_parser_sees_what_a_regex_cannot(parsed):
    "Every one of these was either invisible to the old regexes or silently mis-generated."
    assert parsed['dist2']['skip'] is None
    assert 'generic parameter' in parsed['largest']['skip']
    assert 'borrow' in parsed['first']['skip']
    assert parsed['parse']['skip'] is None, 'a Result is bindable; the error becomes an exception'
    assert 'generic' in parsed['Wrapper']['skip']
    assert 'no Python equivalent' in parsed['Shape']['skip']
    assert 'private_helper' not in parsed, 'private items are not public API'
    assert parsed['deep']['skip'] is None, 'an item inside a `mod` is still exported code'

@pytest.mark.slow
def test_the_parser_reads_a_struct_the_way_rustc_does(parsed):
    p = parsed['Point']
    assert p['derives'] == ['Debug', 'Clone']
    assert [f['name'] for f in p['fields']] == ['x', 'y'], 'a private field is not a getter'
    assert [m['name'] for m in p['methods']] == ['dist2', 'nudge'], 'and `hidden` is private'
    assert [s['name'] for s in p['statics']] == ['new']
    assert parsed['Point']['methods'][1]['recv'] == '&mut self'
    assert not any(m['name'] == 'fmt' for m in p['methods']), 'a trait impl is not the type API'

@pytest.mark.slow
def test_unparseable_rust_is_reported_with_a_line_rather_than_mis_read():
    from nbship.parse import rust_items, RustSyntaxError, parser_path
    if not shutil.which('cargo') and not parser_path(build=False): pytest.skip('no cargo')
    with pytest.raises(RustSyntaxError) as e: rust_items('pub fn broken( {')
    assert 'line' in str(e.value)

# the whole chain, against the real toolchains ----------------------------------------------------

@pytest.mark.slow
def test_a_notebook_becomes_a_wheel_whose_bindings_all_work(tmp_path):
    "The claim the whole spike exists to settle, settled the only way it can be."
    for tool in ('cargo', 'maturin'):
        if not shutil.which(tool): pytest.skip(f'{tool} is not installed')
    dest, skipped = export(NB, out=tmp_path/'geometry', crate='geometry')
    assert [s.name for s in skipped] == ['largest'], 'the generic one, and only that one'

    from nbship.cli import build
    wheel = build(dest)
    venv = tmp_path/'venv'
    subprocess.run(['uv', 'venv', '-q', str(venv)], check=True, timeout=300)
    py = venv/'bin'/'python'
    subprocess.run(['uv', 'pip', 'install', '-q', '--python', str(py), str(wheel)],
                   check=True, timeout=900)
    script = '''
import geometry as g, json
p = g.Point(3, 4)
q = g.Point(1, 1); q.nudge(2, 3)
out = {'fn': g.dist2(3, 4), 'doc': g.dist2.__doc__,
       'repr': repr(p), 'getter': p.x, 'method': p.dist2(), 'self': repr(p.scaled(2)),
       'static': repr(g.Point.origin()), 'mut': repr(q),
       'ok': repr(g.parse_point("7, 8")), 'generic': hasattr(g, 'largest')}
try: g.parse_point("nope")
except ValueError as e: out['err'] = str(e)
print(json.dumps(out))
'''
    r = subprocess.run([str(py), '-c', script], capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    out = json.loads(r.stdout)
    assert out['fn'] == 25
    assert out['doc'] == 'Squared distance from the origin.'
    assert out['repr'] == 'Point { x: 3, y: 4 }' and out['getter'] == 3 and out['method'] == 25
    assert out['self'] == 'Point { x: 6, y: 8 }'
    assert out['static'] == 'Point { x: 0, y: 0 }'
    assert out['mut'] == 'Point { x: 3, y: 4 }', '`&mut self` mutated the wrapped value'
    assert out['ok'] == 'Point { x: 7, y: 8 }'
    assert 'invalid digit' in out['err'], 'the Rust error arrived as a Python ValueError'
    assert out['generic'] is False, 'and the one that could not cross is simply absent'

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
            exe = _os.environ.get('LEELA_CHROMIUM', '/opt/pw-browsers/chromium')
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
