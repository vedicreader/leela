"The vendored browser bundles ship with a licence notice that matches the frontend lockfile."
import importlib.util, json, re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

def _tp():
    spec = importlib.util.spec_from_file_location('third_party', ROOT/'tools'/'third_party.py')
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m

def test_the_notice_lists_every_package_the_frontend_lock_installs():
    "No lockfile and no notice: the bundles could not be rebuilt to the same bytes, and their licences went unstated."
    tp = _tp()
    assert tp.LOCK.is_file() and tp.OUT.is_file()
    assert tp.check(), 'run tools/third_party.py'
    s = tp.OUT.read_text()
    assert all(w in s for w, *_ in tp.OTHERS), 'KaTeX, Font Awesome and rupaka are named too'

def test_the_vendored_htmx_is_the_locked_version():
    lock = json.loads((ROOT/'frontend'/'package-lock.json').read_text())['packages']['node_modules/htmx.org']['version']
    assert re.search(r'version:"([\d.]+)"', (ROOT/'leela'/'vendor'/'htmx.min.js').read_text())[1] == lock
