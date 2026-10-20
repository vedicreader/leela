"py2exe definition for `dist/Leela/Leela.exe`, a folder not a file. Run it through `setup_app.py`."
from __future__ import annotations
import sys
from fastcore.all import Path

from kavacha import App, mypyc_modules, tree

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT/'packaging'/'assets'
sys.path.insert(0, str(ROOT))

from leela import __version__  # noqa: E402

DATA_FILES = (tree(ROOT/'leela'/'static', 'leela/static', skip={'js'}) +
              tree(ROOT/'leela'/'vendor', 'leela/vendor') + [('.', [str(ASSETS/'Leela.png')])])

PACKAGES = [
    # `blocks/fs/watch.py` imports it inside the watch thread, so the scanner never sees it, and
    # the thread answers a failed import by returning: the file tree simply stopped following the
    # disk in every packaged build, with nothing said.
    'watchfiles',
    'leela', 'ramabana', 'dhrishti', 'fastcore', 'fasthtml', 'starlette', 'uvicorn',
    'httpx', 'httpcore', 'anyio', 'certifi', 'websockets',
    'fossick', 'fastcdp', 'scrapling', 'html2text', 'readability',
    'kavacha', 'kunda', 'pullup',   # see the macOS definition
    # Copied whole for their source, not only their bytecode. `fastcore.funccall` schemas every
    # tool with `docments`, which calls `inspect.getsource` on the function: a package reached from
    # the zip has `.pyc` and no `.py`, so the model resolved to
    # `OSError: could not get source code` and the app fell back off every model it was asked for.
    # This worked while the toolset lived in `ramabana`, which is copied whole; it is `shalya` now.
    'shalya', 'fastspec', 'urai',
    'fastclaude',                   # see the macOS definition
    'webview', 'clr_loader', 'pythonnet',
    'ipykernel', 'ipymini', 'jupyter_client', 'jupyter_core', 'zmq', 'traitlets',
    'kosha', 'litesearch', 'vishalakshi', 'exhash', 'mdhtml', 'yaml',
    # `readability` falls back to `chardet`, whose accelerator is a top-level extension the
    # scanner never sees, and whose models are data files a zip import cannot read. Without it
    # the agent's web tool, research and `to_md` all die in the bundle and nowhere else.
    'chardet', 'nbformat', 'uvloop',
    # Named, not left to the scanner. Leela's server imports neither, and deliberately: the
    # comment at `blocks/runtime/kernels.py` says so. They are here for the kernel, which
    # imports dhrishti, which imports both at module level. Without them the variables panel
    # is dead in every kernel that cannot find its own copy.
    'numpy', 'pandas',
    # `ramabana.cli` is imported inside a function, so the scanner follows it to none of these.
    'rich', 'pyghostty', 'teleprint',
    'pygments',  # see the macOS definition: styles and lexers are imported by name, so none are found
    'fastaudit', 'safepyrun',   # see the macOS definition
    'pip',       # see the macOS definition: the on-demand backends have no other way in
]

#: See the macOS definition: `apsw` has the extension module for its `__init__`, and a freezer that
#: flattens it loses `apsw.ext` and with it the vault. py2exe is not py2app and this build has not
#: been run against one, so the name is recorded here and the CI job on a tag is what proves it.
GRAFTED = ('apsw',)

# `packaging` is included and not copied whole: the repository root holds a directory of that name,
# and a bare name is a path to py2app before it is a module. See the macOS definition.
INCLUDES = ['leela.cli', 'leela.desktop', 'leela.app', 'packaging.requirements',
            'webview.platforms.winforms', 'webview.platforms.edgechromium',
            # Reached from inside a Cython module, so the scanner never sees them, and `pandas` is
            # copied whole rather than scanned. Without `cmath` the variables panel is dead in the
            # shipped app and nowhere else. `ipykernel_launcher` is named as a string in the kernel's
            # argv, so nothing follows it.
            'cmath', 'ipykernel_launcher',
            *mypyc_modules()]

#: See the macOS definition. Kept identical there and here, which `test_packaging.py` asserts.
HEAVY = ('mlx', 'mlx_lm', 'mlx_vlm', 'mlx_audio', 'llama_cpp', 'cv2', 'transformers',
         'scipy', 'spacy', 'torch', 'blis', 'thinc', 'srsly', 'llguidance')

APP = App(
    name     = 'Leela',
    entry    = str(ROOT/'leela_app.py'),
    version  = __version__,
    icon     = str(ASSETS/'Leela.ico'),
    summary  = 'leela — creative workspace that starts with coding',
    packages = PACKAGES,
    includes = INCLUDES,
    excludes = ['webview.platforms.qt', *HEAVY],   # see the macOS definition
    grafted  = GRAFTED,
    data     = DATA_FILES,
    extras   = ['gateway', 'windows'],
)

OPTIONS = APP.py2exe_options() | {'dist_dir': str(ROOT/'dist'/'Leela'), 'optimize': 1}
EXCLUDES = OPTIONS['excludes']

VERSION_INFO = {
    'version': __version__,
    'description': APP.summary,
    'company_name': 'vedicreader',
    'copyright': 'Apache-2.0',
    'product_name': APP.name,
}

if __name__ == '__main__':
    from py2exe import freeze
    icon = ASSETS/'Leela.ico'
    if not icon.is_file(): raise SystemExit('missing packaging/assets/Leela.ico — run tools/build_icons.py first')
    freeze(
        # `windows=`, not `console=`: a double-clicked app must not open a console behind its window.
        windows=[{'script': APP.entry, 'dest_base': APP.name,
                  'icon_resources': [(1, str(icon))]}],
        data_files=DATA_FILES,
        version_info=VERSION_INFO,
        options=OPTIONS,
        # Modules stay as files: ipykernel is launched as a *subprocess* of this interpreter,
        # and a child cannot import out of the parent's library.zip.
        zipfile=None,
    )
