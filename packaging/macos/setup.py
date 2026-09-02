"py2app definition for `dist/Leela.app`. Run it through `setup_app.py`."
from __future__ import annotations
import sys
from fastcore.all import Path
from setuptools import setup

from kavacha import App, doc_types, finish, frozen_distribution, mypyc_modules, tree

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT/'packaging'/'assets'
sys.path.insert(0, str(ROOT))

from leela import __version__  # noqa: E402

# The modules under `blocks/*/*.js` and `static/js/` build the `static/lee-*.js` bundles;
# shipping both doubles ~680KB, as the wheel notes.
DATA_FILES = tree(ROOT/'leela'/'static', 'leela/static', skip={'js'}) + tree(ROOT/'leela'/'vendor', 'leela/vendor')

# Packages copied whole. py2app's scanner cannot see an import made inside a function, which is
# most of Leela's heavy machinery. Never name one a directory in the repository root also spells:
# py2app tries a bare name as a path first. `INCLUDES` takes those.
PACKAGES = [
    'leela', 'ramabana', 'dhrishti', 'fastcore', 'fasthtml', 'starlette', 'uvicorn',
    'httpx', 'httpcore', 'anyio', 'certifi', 'websockets',
    'fossick', 'fastcdp', 'scrapling', 'html2text', 'readability',
    'kavacha', 'kunda', 'pullup',   # the casing, the kernels and the release half
    'webview',                      # the shell itself
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
    # `blocks/fs/watch.py` imports it inside the watch thread, so the scanner never sees it, and
    # the thread answers a failed import by returning: the file tree simply stopped following the
    # disk in every packaged build, with nothing said.
    'watchfiles',
    # `ramabana.cli` is imported inside a function, so the scanner follows it to none of these.
    'rich', 'pyghostty', 'teleprint',
    # Copied whole because pygments finds a style or a lexer by importing its name: 49 and 263 of
    # them that no scanner sees. Without them `import IPython` dies inside the kernel process, the
    # gateway waits for a kernel that is already gone, and every cell fails on a read timeout.
    'pygments',
    # Shipped so the app can install `leela[local]` into `leela.extras_site()`. Nothing imports it,
    # so the scanner would never find it, and without it the on-demand backends cannot be fetched
    # at all: a signed bundle has no other way to add a package. ~16MB against the ~400MB it saves.
    'pip',
]

INCLUDES = [
    'leela.cli', 'leela.desktop', 'leela.app',
    'packaging.requirements',       # `leela.blocks.editor.app` imports it inside a function
    'webview.platforms.cocoa',
    'objc', 'Foundation', 'AppKit', 'WebKit', 'Quartz',
    # Reached from inside a Cython module, so the scanner cannot see them, and `pandas` is copied
    # whole rather than scanned. Without `cmath` the variables panel is dead in the shipped app and
    # nowhere else: a build machine has a system Python to fall back on and a user does not.
    'cmath', 'readline', 'syslog',
    # Named as a string in the kernel's argv, so nothing follows it. A project with no environment of
    # its own runs on the bundle's interpreter, which then has no kernel to launch.
    'ipykernel_launcher',
    *mypyc_modules(),
]

#: What `leela[local]` drags in, by module name. Measured on the bundle it used to be in: mlx 204MB,
#: cv2 125, transformers 99, scipy 97, spacy 24, llama_cpp 18, and the mlx sidecars.
#: `litert_lm` is not among them any more: `vishalakshi` imports `rishi.litert` to read one model id,
#: so leaving it out took the vault, and with it memory, out of the packaged app entirely.
#: `tests/test_packaging.py` holds the two platform definitions to the same list.
HEAVY = ('mlx', 'mlx_lm', 'mlx_vlm', 'mlx_audio', 'llama_cpp', 'cv2', 'transformers',
         'scipy', 'spacy', 'torch', 'blis', 'thinc', 'srsly', 'llguidance')

#: Packages the freezer's zip cannot hold. `apsw` has the extension module for its own `__init__`,
#: and a flattened copy loses `apsw.ext` and with it the vault. `playwright` and `patchright` each
#: carry a Node binary they have to *execute*, and a file inside an archive cannot be executed, so
#: browser fetching failed in the packaged app and nowhere else.
GRAFTED = ('apsw', 'playwright', 'patchright')

#: Entries that can never be reached from inside `python313.zip`. `claude_agent_sdk` looks for its
#: bundled CLI with `Path(__file__).parent.parent.parent/'_bundled'/name` and `.exists()`, which is
#: always false for a path inside an archive. Leela reaches the real `claude` on PATH, which
#: `use_login_path` repairs at startup, so the copy is 93MB of a 205MB zip that nothing can open.
UNREACHABLE = ('claude_agent_sdk/_bundled/',)

#: Better opened somewhere else, whatever Leela can edit: a browser renders these and Leela would
#: only show their source. Everything else it knows a language for, it asks to own.
VIEW_ELSEWHERE = {'.svg', '.html', '.htm', '.pdf'}

def _doc_types():
    "One document type per language Leela edits, taken from the map the file tree already uses."
    from leela.blocks.fs.fs import LANGS
    return doc_types([e for e, lang in LANGS.items() if lang], VIEW_ELSEWHERE)

APP = App(
    name       = 'Leela',
    entry      = str(ROOT/'leela_app.py'),
    version    = __version__,
    icon       = str(ASSETS/'Leela.icns'),
    modern_icon= str(ASSETS/'Leela.icon'),
    identifier = 'org.vedicreader.leela',
    summary    = 'leela — creative workspace that starts with coding',
    packages   = PACKAGES,
    includes   = INCLUDES,
    # `webview.platforms.qt` is not one of kavacha's three backends, and the on-device stack is
    # what `leela[local]` installs beside the bundle instead. A lean build has none of it to find;
    # these keep a build made in a full development environment lean too, which is the one a
    # person is most likely to run by hand.
    excludes   = ['webview.platforms.qt', *HEAVY],
    grafted    = GRAFTED,
    unreachable= UNREACHABLE,
    data       = DATA_FILES,
    plist      = {'NSHumanReadableCopyright': 'Apache-2.0'},
    doc_types  = _doc_types(),
    extras     = ['gateway', 'macapp'],
)

OPTIONS = APP.py2app_options()
PLIST, EXCLUDES = OPTIONS['plist'], OPTIONS['excludes']
Frozen = frozen_distribution()

if __name__ == '__main__':
    if not (ASSETS/'Leela.icns').is_file():
        raise SystemExit('missing packaging/assets/Leela.icns — run tools/build_icons.py first')
    setup(name=APP.name, version=APP.version, app=[APP.entry], data_files=DATA_FILES,
          options={'py2app': OPTIONS}, setup_requires=['py2app'], distclass=Frozen)
    # `ROOT/dist`, because py2app writes it relative to the working directory and `setup_app.py`
    # builds from the root. Taken from this file's own folder it named a path nothing writes, so
    # the icon step never ran and a stale bundle sat there instead.
    if (built := APP.out(ROOT)).is_dir():
        got = finish(built, APP)
        for name in GRAFTED: print(f'  grafted {name} -> {got[name]}')
        if got['stripped_mb']: print(f"  dropped {got['stripped_mb']}MB of unreachable archive entries")
        if got['linked_mb']: print(f"  linked {got['linked_mb']}MB of duplicate grafted files")
        if got['modern_icon']: print(f'  Icon Composer icon installed in {built}')
