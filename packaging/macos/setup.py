"py2app definition for `dist/Leela.app`. Run it through `setup_app.py`."
from __future__ import annotations
import sys
from fastcore.all import Path, first, globtastic, groupby
from setuptools import setup
from setuptools.dist import Distribution

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT/'packaging'/'assets'
sys.path.insert(0, str(ROOT))

from leela import __version__  # noqa: E402

def tree(src, dest, skip=()):
    "Every file under `src` as py2app `(dest_dir, [files])` pairs. Recursively: see `vendor/fonts/`."
    fs = globtastic(src, skip_folder_re=f'^({"|".join([*skip, "__pycache__"])})$', skip_file_re=r'^\.')
    dirs = groupby(fs, lambda f: str(Path(dest)/Path(f).parent.relative_to(src)))
    return sorted((d, sorted(v)) for d, v in dirs.items())

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
    'webview',                      # the shell itself
    'ipykernel', 'ipymini', 'jupyter_client', 'jupyter_core', 'zmq', 'traitlets',
    'kosha', 'litesearch', 'vishalakshi', 'exhash', 'mdhtml', 'yaml',
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

#: What `leela[local]` drags in, by module name. Measured on the bundle it used to be in: mlx 204MB,
#: cv2 125, transformers 99, scipy 97, spacy 24, llama_cpp 18, litert_lm and the mlx sidecars.
#: `tests/test_packaging.py` holds the two platform definitions to the same list.
HEAVY = ('mlx', 'mlx_lm', 'mlx_vlm', 'mlx_audio', 'litert_lm', 'llama_cpp', 'cv2', 'transformers',
         'scipy', 'spacy', 'torch', 'blis', 'thinc', 'srsly', 'llguidance')

#: Packages py2app cannot carry either way, put in place after it runs. `apsw` is one package whose
#: `__init__` is the extension module: the scanner flattens it to a lone `apsw.so` and loses
#: `apsw.ext`, which is how fastlite opens the vault, and naming it in `PACKAGES` instead only gets
#: `ImportError: No module named 'apsw'`, because the lookup wants an `__init__.py` to find.
GRAFTED = ('apsw',)
# Entry points, lazy optionals, and pywebview's Cocoa half, reached as `webview.platforms.<gui>`.
INCLUDES = [
    'leela.cli', 'leela.desktop', 'leela.app',
    'packaging.requirements',       # `leela.blocks.editor.app` imports it inside a function
    'webview.platforms.cocoa',
    'objc', 'Foundation', 'AppKit', 'WebKit', 'Quartz',
]

# Build tooling and other platforms' backends: ~100MB, and half a library a frozen app never wanted.
EXCLUDES = [
    'tkinter', 'test', 'setuptools', 'wheel', 'py2app', 'py2exe',
    'webview.platforms.gtk', 'webview.platforms.qt', 'webview.platforms.winforms',
    'gi', 'PyQt5', 'PyQt6', 'PySide2', 'PySide6', 'clr', 'matplotlib',
    # The on-device stack, which `leela[local]` installs beside the bundle instead. A lean build
    # has none of it to find; these keep a build made in a full development environment lean too,
    # which is the one a person is most likely to run by hand.
    *HEAVY,
]

#: Better opened somewhere else, whatever Leela can edit: a browser renders these and Leela would
#: only show their source. Everything else it knows a language for, it asks to own.
VIEW_ELSEWHERE = {'.svg', '.html', '.htm', '.pdf'}

def doc_types():
    "One document type per language Leela edits, taken from the map the file tree already uses."
    sys.path.insert(0, str(ROOT))
    from leela.blocks.fs.fs import LANGS
    exts = sorted({e.lstrip('.') for e, lang in LANGS.items() if lang and e not in VIEW_ELSEWHERE})
    return [
        # A folder stays `Alternate`: Finder is the right default for one, and this is what puts
        # "Open With" on it and makes a Dock drop mean something.
        {'CFBundleTypeName': 'Folder', 'CFBundleTypeRole': 'Viewer',
         'LSItemContentTypes': ['public.folder'], 'LSHandlerRank': 'Alternate'},
        {'CFBundleTypeName': 'Source file', 'CFBundleTypeRole': 'Editor',
         'CFBundleTypeExtensions': exts, 'LSHandlerRank': 'Owner'},
    ]

DOC_TYPES = doc_types()

PLIST = {
    'CFBundleName': 'Leela',
    'CFBundleDisplayName': 'Leela',
    'CFBundleIdentifier': 'org.vedicreader.leela',
    'CFBundleVersion': __version__,
    'CFBundleShortVersionString': __version__,
    'CFBundleGetInfoString': 'leela — creative workspace that starts with coding',
    'LSApplicationCategoryType': 'public.app-category.developer-tools',
    'LSMinimumSystemVersion': '11.0',
    'NSHighResolutionCapable': True,
    # Without this the app is locked to the light appearance, and Leela's dark themes render
    # against a white window.
    'NSRequiresAquaSystemAppearance': False,
    'NSHumanReadableCopyright': 'Apache-2.0',
    # App Transport Security blocks cleartext HTTP, loopback included, so WKWebView refuses
    # `http://127.0.0.1:<port>`. The narrow exemption, not `NSAllowsArbitraryLoads`.
    'NSAppTransportSecurity': {'NSAllowsLocalNetworking': True},
    'CFBundleDocumentTypes': DOC_TYPES,
    # Set before the interpreter starts, which `leela.use_utf8` cannot be. Both are wanted.
    'LSEnvironment': {'LANG': 'en_US.UTF-8', 'PYTHONUTF8': '1'},
}

OPTIONS = {
    'iconfile': str(ASSETS/'Leela.icns'),
    'packages': PACKAGES,
    'includes': INCLUDES,
    'excludes': EXCLUDES,
    'plist': PLIST,
    # Leela is opened from the Dock and from `open`, never with a shell's argv conventions;
    # argv emulation costs a visible Apple Event wait at launch.
    'argv_emulation': False,
    'semi_standalone': False,
    'site_packages': True,
    'strip': True,
}

def graft(app, name):
    "Put the real `name` package into a built bundle, over whatever the freezer left of it."
    import importlib.util, shutil
    spec = importlib.util.find_spec(name)
    src = Path(first(spec.submodule_search_locations))
    lib = first(sorted((app/'Contents'/'Resources'/'lib').glob('python3.*')))
    # The package carries compiled modules built for the interpreter running this, so a bundle on
    # another version would take a wrong-ABI `.so` and fail at import with nothing to point at it.
    want = 'python%d.%d' % sys.version_info[:2]
    if lib.name != want: raise SystemExit(f'cannot graft {name}: bundle is {lib.name}, this is {want}')
    dest = Path(lib)/name
    for stray in lib.glob(f'{name}.*'): stray.unlink()     # the flattened extension module
    shutil.rmtree(dest, ignore_errors=True)
    shutil.copytree(src, dest, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    return dest.relative_to(app)

class Frozen(Distribution):
    """A distribution with no `install_requires`, which py2app 0.28.10 and up refuse outright.

    The build runs from the repository root, so setuptools reads `pyproject.toml` and fills the
    field in from `[project] dependencies`. Nothing here wants it: `PACKAGES` and `INCLUDES` say
    what the bundle carries, because the scanner cannot see an import made inside a function.
    """
    def parse_config_files(self, *args, **kwargs):
        super().parse_config_files(*args, **kwargs)
        self.install_requires = []

def install_modern_icon(app, identity=None):
    """Compile `Leela.icon` into a built bundle, after py2app and before anything signs it.

    `iconfile` above is the ICNS fallback, all py2app installs and all macOS before 26 reads. The
    Icon Composer document is what 26 draws, and its plist entries must reach `Info.plist` before
    a signature covers them. None when the document or the tooling is absent: a machine without
    Xcode 26 still builds a working app, with the older icon.
    """
    icon = ASSETS/'Leela.icon'
    if not icon.is_dir(): return None
    try: from iconmage import install_icon
    except ImportError:
        print('  iconmage not installed; keeping the ICNS icon alone '
              '(uv tool install git+https://github.com/AnswerDotAI/iconmage.git)')
        return None
    try: return install_icon(icon, app, deployment_target='14.0', identity=identity)
    except Exception as e:
        print(f'  Icon Composer icon not installed ({type(e).__name__}: {e}); keeping the ICNS one')
        return None

if __name__ == '__main__':
    if not (ASSETS/'Leela.icns').is_file():
        raise SystemExit('missing packaging/assets/Leela.icns — run tools/build_icons.py first')
    setup(name='Leela', version=__version__, app=[str(ROOT/'leela_app.py')],
          data_files=DATA_FILES, options={'py2app': OPTIONS}, setup_requires=['py2app'],
          distclass=Frozen)
    # `ROOT/dist`, because py2app writes it relative to the working directory and `setup_app.py`
    # builds from the root. Taken from this file's own folder it named a path nothing writes, so
    # the icon step never ran and a stale bundle sat there instead.
    if (built := ROOT/'dist'/'Leela.app').is_dir():
        for name in GRAFTED: print(f'  grafted {name} -> {graft(built, name)}')
        if install_modern_icon(built): print(f'  Icon Composer icon installed in {built}')
