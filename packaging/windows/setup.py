"""py2exe definition for `dist/Leela/Leela.exe`.

Run it through `setup_app.py`. py2exe produces a folder, not a single file: `Leela.exe` beside
its Python runtime and a `leela/` asset tree, which is where `leela.core.web.asset_dir` looks
when `sys.frozen` is set. The window is the Edge WebView2 runtime, reached through pythonnet;
as on macOS, Chrome is the machine's own rather than bundled.
"""
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
    'koshas', 'litesearch', 'vishalakshi', 'exhash', 'mdhtml', 'numpy', 'yaml', 'packaging',
]

INCLUDES = ['leela.cli', 'leela.desktop', 'leela.app',
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
