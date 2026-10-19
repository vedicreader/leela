"""Build the distributable: a signed-local macOS app + DMG, or a zipped Windows folder."""
from __future__ import annotations
import os, re, shutil, subprocess, sys, tempfile
import kavacha
from fastcore.all import Path, first

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
    # Distribution signing is opt-in: it needs the developer's identity and notarization
    # credentials, and a local py2app build is already linker-signed and launchable.
    if (identity := os.environ.get('LEELA_CODESIGN_IDENTITY', '').strip()): sign(app, identity)
    # Staged outside the repository, and gone when the image is written. The drag-to-install
    # shortcut a DMG wants is a symlink to `/Applications`, and one of those left behind under
    # `build/` is a path from this checkout into the real folder: a tool resolving `leela` by name
    # from the wrong directory walks straight down it. It belongs to the image, not to the tree.
    with tempfile.TemporaryDirectory(prefix='leela-dmg-') as tmp:
        stage = Path(tmp)/'Leela'
        stage.mkdir(parents=True)
        shutil.copytree(app, stage/'Leela.app', symlinks=True)
        (stage/'Applications').symlink_to('/Applications')
        shutil.copy2(ROOT/'packaging'/'assets'/'Leela.icns', stage/'.VolumeIcon.icns')
        try: run('SetFile', '-a', 'C', stage)
        except Exception: pass
        out.unlink(missing_ok=True)
        run('hdiutil', 'create', '-volname', 'Leela', '-srcfolder', stage,
            '-ov', '-format', 'UDZO', '-imagekey', 'zlib-level=9', out)
    if notary_args(): notarize(out)
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


ENTITLEMENTS = ROOT/'packaging'/'macos'/'entitlements.plist'

def sign(app, identity):
    "Every Mach-O file once per inode, deepest first, then frameworks, then the bundle; never `--deep`."
    kavacha.sign(app, identity, ENTITLEMENTS, run=run)


def notary_args():
    "How to reach the notary service, or `[]`. A keychain profile first: one secret, not three."
    env = os.environ.get
    if (profile := (env('LEELA_NOTARY_PROFILE') or '').strip()):
        return ['--keychain-profile', profile]
    key, kid, issuer = (env('LEELA_ASC_KEY') or '').strip(), (env('LEELA_ASC_KEY_ID') or '').strip(), (env('LEELA_ASC_ISSUER') or '').strip()
    if key and kid and issuer:
        return ['--key', key, '--key-id', kid, '--issuer', issuer]
    apple, password, team = ((env('LEELA_APPLE_ID') or '').strip(), (env('LEELA_APPLE_PASSWORD') or '').strip(),
                            (env('LEELA_TEAM_ID') or '').strip())
    if apple and password and team:
        return ['--apple-id', apple, '--password', password, '--team-id', team]
    return []


def notarize(dmg):
    "Submit the DMG, wait for the verdict, and staple it so Gatekeeper needs no network."
    args = notary_args()
    if not args: raise SystemExit('nothing to notarize with; see notary_args')
    run('xcrun', 'notarytool', 'submit', dmg, *args, '--wait')
    run('xcrun', 'stapler', 'staple', dmg)
    run('xcrun', 'stapler', 'validate', dmg)
    print(f'Notarized {dmg}')

def version():
    "The version the release step just tagged, read the way hatchling reads it."
    text = (ROOT/'leela'/'__init__.py').read_text(encoding='utf-8')
    m = re.search(r"""__version__\s*=\s*['"]([^'"]+)""", text)
    if not m: raise SystemExit('no __version__ in leela/__init__.py')
    return m.group(1)


def has_release(tag):
    "Whether a GitHub release exists for `tag`."
    return subprocess.run(['gh', 'release', 'view', str(tag)],
                          capture_output=True, text=True).returncode == 0


def release_tag(tag=''):
    """The release to attach to: `tag` where given, else whichever spelling of this version exists.

    fastship tags a Python project with the bare version and its other flows with a `v` prefix, so
    which one the release carries is not knowable from here. `gh release upload` on the wrong one
    fails with `release not found` and names no alternative.
    """
    if tag: return tag
    v = version()
    if (found := first(t for t in (f'v{v}', v) if has_release(t))): return found
    raise SystemExit(f'no release for {v}: run `ship-gh` first, or pass the tag to upload')


def upload(tag=''):
    "Attach what this platform built to a release. Defaults to the release for the current version."
    built = [p for name in ARTIFACTS if (p := ROOT/'dist'/name).exists()]
    if not built: raise SystemExit(f'nothing to upload: build one of {", ".join(ARTIFACTS)} first')
    run('gh', 'release', 'upload', release_tag(tag), *built, '--clobber')
    for p in built: print(f'Uploaded {p}')


def main():
    if sys.argv[1:2] == ['upload']: return upload(*sys.argv[2:3])
    if sys.argv[1:]: raise SystemExit(f'usage: {Path(sys.argv[0]).name} [upload [tag]]')
    if sys.platform == 'darwin': mac_release()
    elif sys.platform == 'win32': windows_release()
    else: raise SystemExit('release artifacts build on their target OS')


if __name__ == '__main__': main()
