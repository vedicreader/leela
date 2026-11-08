"`make ship` (tools/release.sh) stops at once when gh is not usable, before any slow or outward step."
import os, subprocess
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT/'tools'/'release.sh'

def _run(tmp_path, gh):
    "The script with a stand-in `gh` first on PATH; /usr/bin and /bin only give it grep, dirname and the like."
    (bin := tmp_path/'bin').mkdir()
    (g := bin/'gh').write_text(gh); g.chmod(0o755)
    env = {'PATH': f'{bin}:/usr/bin:/bin', 'V': '1.0.1', 'HOME': str(tmp_path)}
    return subprocess.run(['/bin/sh', str(SCRIPT)], cwd=ROOT, env=env, text=True, capture_output=True, timeout=60)

def test_a_gh_with_no_login_stops_the_release_before_step_1(tmp_path):
    "In the 1.0.1 release gh had no login at the upload, and the script found out only after notarizing."
    r = _run(tmp_path, '#!/bin/sh\necho "To get started with GitHub CLI, please run:  gh auth login" >&2\nexit 4\n')
    assert r.returncode == 1 and 'gh cannot reach vedicreader/leela' in r.stderr and 'gh auth login' in r.stderr, (r.stdout, r.stderr)
    assert '== 1.' not in r.stdout, 'nothing ran, so nothing was fetched, built or published'

def test_gh_is_checked_before_step_1_and_again_before_the_app(tmp_path):
    "Signing and notarizing take minutes, and the keychain can lock in that time."
    s = SCRIPT.read_text()
    calls = [i for i in range(len(s)) if s.startswith('\nneed_gh ', i)]
    assert len(calls) == 2, 'two calls: the definition is need_gh() with no space'
    assert calls[0] < s.index('say "1.') and calls[1] > s.index('say "8.') and calls[1] < s.index('sh tools/ship_app.sh')
    assert s.index('say "5.') < calls[1], 'the second look comes after the signing steps'
