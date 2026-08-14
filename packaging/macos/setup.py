"""py2app definition for `dist/Leela.app`.

Run it through `setup_app.py`, which arranges the framework Python py2app needs; running
this file directly works too, and will simply fail later if the interpreter cannot supply
the stdlib extension modules as files.

The bundle contains Leela and its Python environment. It does *not* contain Chrome. The
inline browser and `--app` both drive the persistent CDP profile fossick already keeps in
`~/.cache/fastcdp`, so the copy of Chrome on the machine is the one that gets used, keeps
its logins, and gets updated by Google rather than by us.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from setuptools import setup

ROOT = Path(__file__).resolve().parents[2]
ASSETS = ROOT/'packaging'/'assets'
sys.path.insert(0, str(ROOT))

from leela import __version__  # noqa: E402


def tree(src, dest, skip=()):
    """Every file under `src` as py2app `(dest_dir, [files])` pairs, recursively.

    Recursively is the whole point of this helper existing. An earlier version listed
    `src.iterdir()`, which silently left `static/fonts/` out of the bundle -- the app ran, and
    rendered in whatever the system had instead.
    """
    out = []
    for d, dirs, files in os.walk(src):
        dirs[:] = [x for x in dirs if x not in skip and not x.startswith('__pycache__')]
        rel = Path(d).relative_to(src)
        keep = [str(Path(d)/f) for f in sorted(files) if not f.startswith('.')]
        if keep: out.append((str(Path(dest)/rel), keep))
    return out


# `static/js/` is the source `static/lee-ide.js` is built from, so shipping it would put the
# same ~570KB in the bundle twice -- the same exclusion the wheel makes.
DATA_FILES = (tree(ROOT/'leela'/'static', 'leela/static', skip={'js'}) +
              tree(ROOT/'leela'/'vendor', 'leela/vendor'))

# Packages py2app must copy whole. Anything reached only by `import` inside a function --
# which in Leela is most of the heavy machinery -- is invisible to the dependency scanner.
PACKAGES = [
    'leela', 'ramabana', 'dhrishti', 'fastcore', 'fasthtml', 'starlette', 'uvicorn',
    'httpx', 'httpcore', 'anyio', 'certifi', 'websockets',
    'fossick', 'fastcdp', 'scrapling', 'html2text', 'readability',
    'webview',                      # the shell itself
    'ipykernel', 'ipymini', 'jupyter_client', 'jupyter_core', 'zmq', 'traitlets',
    'koshas', 'litesearch', 'vishalakshi', 'exhash', 'mdhtml', 'numpy', 'yaml', 'packaging',
]

# Modules the scanner cannot see at all: entry points, lazily imported optionals, and the
# Cocoa half of pywebview, which is reached through `webview.platforms.<gui>`.
INCLUDES = [
    'leela.cli', 'leela.desktop', 'leela.app',
    'webview.platforms.cocoa',
    'objc', 'Foundation', 'AppKit', 'WebKit', 'Quartz',
]

# Build tooling and other platforms' backends. Excluding them is worth ~100MB and removes a
# class of import error where a frozen app finds half of a library it never wanted.
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
    # Without this the app is locked to the light appearance whatever the system is set to,
    # and Leela's dark themes render against a white window.
    'NSRequiresAquaSystemAppearance': False,
    'NSHumanReadableCopyright': 'Apache-2.0',
    # The window loads `http://127.0.0.1:<port>`, and App Transport Security blocks cleartext
    # HTTP by default -- including to loopback. This is the narrow exemption for exactly that,
    # rather than `NSAllowsArbitraryLoads`, which would also permit the open internet.
    'NSAppTransportSecurity': {'NSAllowsLocalNetworking': True},
}

OPTIONS = {
    'iconfile': str(ASSETS/'Leela.icns'),
    'packages': PACKAGES,
    'includes': INCLUDES,
    'excludes': EXCLUDES,
    'plist': PLIST,
    # Leela is opened from the Dock and from `open`, never with a shell's argv conventions;
    # argv emulation costs a visible Apple Event wait at launch and buys nothing.
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
