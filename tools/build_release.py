"""Build the distributable: a signed-local macOS app + DMG, or a zipped Windows folder."""
from __future__ import annotations
import os, re, shutil, subprocess, sys
from fastcore.all import Path

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ('Leela-macOS.dmg', 'Leela-Windows.zip')


def run(*args, **kw): return subprocess.run([str(x) for x in args], check=True, **kw)


def build_app(*extra):
    "The platform bundle itself, unless a caller already has one it wants to package."
    if os.environ.get('LEELA_SKIP_APP_BUILD') == '1': return
    run(sys.executable, ROOT/'setup_app.py', *extra)


def mac_release():
    run(sys.executable, ROOT/'tools'/'build_icons.py')
    build_app()
    app, out = ROOT/'dist'/'Leela.app', ROOT/'dist'/'Leela-macOS.dmg'
    if not app.is_dir(): raise SystemExit(f'{app} was not built')
    # A local py2app build is linker-signed and launchable as-is; distribution signing is
    # opt-in because it needs the developer's identity and notarization credentials.
    if (identity := os.environ.get('LEELA_CODESIGN_IDENTITY', '').strip()):
        run('codesign', '--force', '--deep', '--options', 'runtime', '--sign', identity, app)
        run('codesign', '--verify', '--deep', '--strict', app)
    stage = ROOT/'build'/'dmg'
    shutil.rmtree(stage, ignore_errors=True); stage.mkdir(parents=True)
    shutil.copytree(app, stage/'Leela.app', symlinks=True)
    (stage/'Applications').symlink_to('/Applications')
    shutil.copy2(ROOT/'packaging'/'assets'/'Leela.icns', stage/'.VolumeIcon.icns')
    try: run('SetFile', '-a', 'C', stage)
    except Exception: pass
    out.unlink(missing_ok=True)
    run('hdiutil', 'create', '-volname', 'Leela', '-srcfolder', stage,
        '-ov', '-format', 'UDZO', '-imagekey', 'zlib-level=9', out)
    print(f'Created {app}')
    print(f'Created {out}')


def windows_release():
    "py2exe produces a folder; the artefact is that folder zipped, which is what a user gets."
    run(sys.executable, ROOT/'tools'/'build_icons.py')
    build_app()
    app = ROOT/'dist'/'Leela'
    if not app.is_dir(): raise SystemExit(f'{app} was not built')
    out = ROOT/'dist'/'Leela-Windows'
    shutil.make_archive(str(out), 'zip', root_dir=app.parent, base_dir=app.name)
    print(f'Created {app}')
    print(f'Created {out}.zip')


def version():
    "The version the release step just tagged, read the way hatchling reads it."
    text = (ROOT/'leela'/'__init__.py').read_text(encoding='utf-8')
    m = re.search(r"""__version__\s*=\s*['"]([^'"]+)""", text)
    if not m: raise SystemExit('no __version__ in leela/__init__.py')
    return m.group(1)


def upload(tag=''):
    "Attach what this platform built to a release. Defaults to the tag for the current version."
    built = [p for name in ARTIFACTS if (p := ROOT/'dist'/name).exists()]
    if not built: raise SystemExit(f'nothing to upload: build one of {", ".join(ARTIFACTS)} first')
    run('gh', 'release', 'upload', tag or f'v{version()}', *built, '--clobber')
    for p in built: print(f'Uploaded {p}')


def main():
    if sys.argv[1:2] == ['upload']: return upload(*sys.argv[2:3])
    if sys.argv[1:]: raise SystemExit(f'usage: {Path(sys.argv[0]).name} [upload [tag]]')
    if sys.platform == 'darwin': mac_release()
    elif sys.platform == 'win32': windows_release()
    else: raise SystemExit('release artifacts build on their target OS')


if __name__ == '__main__': main()
