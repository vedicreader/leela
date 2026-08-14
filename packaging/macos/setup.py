"py2app definition for `dist/Leela.app`. Run it through `setup_app.py`."
from __future__ import annotations
import sys
from fastcore.all import Path, globtastic, groupby
from setuptools import setup

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT/'packaging'/'assets'
sys.path.insert(0, str(ROOT))

from leela import __version__  # noqa: E402

def tree(src, dest, skip=()):
    "Every file under `src` as py2app `(dest_dir, [files])` pairs. Recursively: see `vendor/fonts/`."
    fs = globtastic(src, skip_folder_re=f'^({"|".join([*skip, "__pycache__"])})$', skip_file_re=r'^\.')
    dirs = groupby(fs, lambda f: str(Path(dest)/Path(f).parent.relative_to(src)))
    return sorted((d, sorted(v)) for d, v in dirs.items())

# `static/js/` builds `static/lee-ide.js`; shipping both doubles ~570KB, as the wheel notes.
DATA_FILES = tree(ROOT/'leela'/'static', 'leela/static', skip={'js'}) + tree(ROOT/'leela'/'vendor', 'leela/vendor')

# Packages copied whole: anything imported inside a function -- most of Leela's heavy
# machinery -- is invisible to py2app's dependency scanner.
PACKAGES = [
    'leela', 'ramabana', 'dhrishti', 'fastcore', 'fasthtml', 'starlette', 'uvicorn',
    'httpx', 'httpcore', 'anyio', 'certifi', 'websockets',
    'fossick', 'fastcdp', 'scrapling', 'html2text', 'readability',
    'webview',                      # the shell itself
    'ipykernel', 'ipymini', 'jupyter_client', 'jupyter_core', 'zmq', 'traitlets',
    'koshas', 'litesearch', 'vishalakshi', 'exhash', 'mdhtml', 'numpy', 'yaml', 'packaging',
]

# Entry points, lazy optionals, and pywebview's Cocoa half, reached as `webview.platforms.<gui>`.
INCLUDES = [
    'leela.cli', 'leela.desktop', 'leela.app',
    'webview.platforms.cocoa',
    'objc', 'Foundation', 'AppKit', 'WebKit', 'Quartz',
]

# Build tooling and other platforms' backends: ~100MB, and half a library a frozen app never wanted.
EXCLUDES = [
    'tkinter', 'test', 'setuptools', 'pip', 'wheel', 'py2app', 'py2exe',
    'webview.platforms.gtk', 'webview.platforms.qt', 'webview.platforms.winforms',
    'gi', 'PyQt5', 'PyQt6', 'PySide2', 'PySide6', 'clr', 'matplotlib',
]

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
    # A folder is the document Leela opens: this is what puts "Open With → Leela" on one and
    # what makes a Dock drop mean something. `Alternate` keeps Finder the default handler.
    'CFBundleDocumentTypes': [{
        'CFBundleTypeName': 'Folder',
        'CFBundleTypeRole': 'Viewer',
        'LSItemContentTypes': ['public.folder'],
        'LSHandlerRank': 'Alternate',
    }],
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

if __name__ == '__main__':
    if not (ASSETS/'Leela.icns').is_file():
        raise SystemExit('missing packaging/assets/Leela.icns — run tools/build_icons.py first')
    setup(name='Leela', version=__version__, app=[str(ROOT/'leela_app.py')],
          data_files=DATA_FILES, options={'py2app': OPTIONS}, setup_requires=['py2app'])
