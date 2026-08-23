"py2exe definition for `dist/Leela/Leela.exe`, a folder not a file. Run it through `setup_app.py`."
from __future__ import annotations
import sys
from fastcore.all import Path, globtastic, groupby

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT/'packaging'/'assets'
sys.path.insert(0, str(ROOT))

from leela import __version__  # noqa: E402

def tree(src, dest, skip=()):
    "Every file under `src` as `(dest_dir, [files])` pairs, recursively. See the macOS note."
    fs = globtastic(src, skip_folder_re=f'^({"|".join([*skip, "__pycache__"])})$', skip_file_re=r'^\.')
    dirs = groupby(fs, lambda f: str(Path(dest)/Path(f).parent.relative_to(src)))
    return sorted((d, sorted(v)) for d, v in dirs.items())

DATA_FILES = (tree(ROOT/'leela'/'static', 'leela/static', skip={'js'}) +
              tree(ROOT/'leela'/'vendor', 'leela/vendor') + [('.', [str(ASSETS/'Leela.png')])])

PACKAGES = [
    'leela', 'ramabana', 'dhrishti', 'fastcore', 'fasthtml', 'starlette', 'uvicorn',
    'httpx', 'httpcore', 'anyio', 'certifi', 'websockets',
    'fossick', 'fastcdp', 'scrapling', 'html2text', 'readability',
    'webview', 'clr_loader', 'pythonnet',
    'ipykernel', 'ipymini', 'jupyter_client', 'jupyter_core', 'zmq', 'traitlets',
    'kosha', 'litesearch', 'vishalakshi', 'exhash', 'mdhtml', 'numpy', 'yaml',
]

#: See the macOS definition: `apsw` has the extension module for its `__init__`, and a freezer that
#: flattens it loses `apsw.ext` and with it the vault. py2exe is not py2app and this build has not
#: been run against one, so the name is recorded here and the CI job on a tag is what proves it.
GRAFTED = ('apsw',)

# `packaging` is included and not copied whole: the repository root holds a directory of that name,
# and a bare name is a path to py2app before it is a module. See the macOS definition.
INCLUDES = ['leela.cli', 'leela.desktop', 'leela.app', 'packaging.requirements',
            'webview.platforms.winforms', 'webview.platforms.edgechromium']

EXCLUDES = ['tkinter', 'test', 'py2app', 'webview.platforms.cocoa', 'webview.platforms.gtk',
            'webview.platforms.qt', 'gi', 'objc', 'PyQt5', 'PyQt6', 'matplotlib']

VERSION_INFO = {
    'version': __version__,
    'description': 'leela — creative workspace that starts with coding',
    'company_name': 'vedicreader',
    'copyright': 'Apache-2.0',
    'product_name': 'Leela',
}

if __name__ == '__main__':
    from py2exe import freeze
    icon = ASSETS/'Leela.ico'
    if not icon.is_file(): raise SystemExit('missing packaging/assets/Leela.ico — run tools/build_icons.py first')
    freeze(
        # `windows=`, not `console=`: a double-clicked app must not open a console behind its window.
        windows=[{'script': str(ROOT/'leela_app.py'), 'dest_base': 'Leela',
                  'icon_resources': [(1, str(icon))]}],
        data_files=DATA_FILES,
        version_info=VERSION_INFO,
        options={'packages': PACKAGES, 'includes': INCLUDES, 'excludes': EXCLUDES,
                 'dist_dir': str(ROOT/'dist'/'Leela'), 'bundle_files': 3, 'compressed': 1,
                 'optimize': 1},
        # Modules stay as files: ipykernel is launched as a *subprocess* of this interpreter,
        # and a child cannot import out of the parent's library.zip.
        zipfile=None,
    )
