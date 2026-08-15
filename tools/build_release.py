"""Build the distributable: a signed-local macOS app + DMG, or a zipped Windows folder."""
from __future__ import annotations
import os, shutil, subprocess, sys
from fastcore.all import Path

ROOT = Path(__file__).resolve().parents[1]


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


def main():
    if sys.platform == 'darwin': mac_release()
    elif sys.platform == 'win32': windows_release()
    else: raise SystemExit('release artifacts build on their target OS')


if __name__ == '__main__': main()
