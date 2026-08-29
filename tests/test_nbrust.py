"""The Rust half of nbdev: a notebook exported to a crate, and that crate built into a wheel.

This covers `spikes/nbrust`, which is not part of Leela's runtime. It is here rather than beside
the spike so the export path is checked on every run; only the build asks for a toolchain.
"""
import json, shutil, subprocess, sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SPIKE = ROOT/'spikes'/'nbrust'
sys.path.insert(0, str(SPIKE))

from nbrust import CargoMaker, cargo_maker, pub_fns                       # noqa: E402
from nbdev.export import nb_export                                        # noqa: E402
from fastcore.nbio import langs                                           # noqa: E402

NB = SPIKE/'geometry.ipynb'

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
