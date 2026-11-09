# Add a surface: append `(r'^/path-regex', dict(css=['x.css'], js=['x.js'], rerun=['x.js']))` to `SURFACES`. The tab loads each file once per page load.
# A name with a prefix `abhyasa:` is looked up in Abhyasa's folders only, for a file whose name Leela's `learn/` folder also has.
# Files are found by name in Abhyasa's `core/`, `core/vendor/`, `blocks/*/` or Leela's `learn/` folder. `rerun` scripts start themselves, so the tab runs them at every visit.
import hashlib, re
from importlib.resources import files
from pathlib import Path

ALWAYS = dict(css=[], js=['voice.js'], rerun=[], files=['vad.js'])   # no Abhyasa Keys panel: Leela's own keys help lists the Learn keys
SURFACES = [
    (r'^/[wc]/', dict(css=[], js=['detour.js'], rerun=[])),
    (r'^/dictate$', dict(js=['dictate.js'])),
    (r'^/(?:[wc]|t)/', dict(css=[], js=['learn-demo.js'], rerun=[])),
    (r'^/(?:$|c/|course/|w/|walks)', dict(css=['home.css'], js=['home.js'], rerun=['home.js'])),
    (r'^/[wc]/', dict(css=['learn-cell.css'], js=['learn-cell.js'], rerun=['learn-cell.js'])),
    (r'^/(?:w/|walks)', dict(css=[], js=['edit.js', 'abhyasa:walk.js', 'walkpage.js'])),
    (r'^/t/[^/]+/present', dict(css=['stage.css'], js=['stage.js'])),
    (r'^/(?:t/|talks)', dict(css=['learn-talk.css'], js=['edit.js', 'abhyasa:talk.js', 'learn-talk.js'])),
    (r'^/(?:library/)?graph(?:/|$)', dict(css=['learn-graph.css'], js=['d3.min.js', 'graph.js'], rerun=['graph.js'])),
]


def _dirs():
    root = files('abhyasa')
    return [Path(__file__).parent, Path(str(root/'core')), Path(str(root/'core'/'vendor')), *sorted(p for p in Path(str(root/'blocks')).glob('*') if p.is_dir())]


def _names(e): return [n for k in ('css', 'js', 'rerun', 'files') for n in e.get(k, [])]


def known(): return {n for e in (ALWAYS, *(e for _, e in SURFACES)) for n in _names(e)}


def asset(name):
    "The file the manifest names `name`, or None; never a path built from a request."
    if name not in known() or '/' in name: return None
    own, _, n = name.rpartition(':')
    return next((p for d in (_dirs()[1:] if own else _dirs()) if (p := d/n).is_file()), None)


def asset_url(name):
    "The `/learn/abh-asset/` URL of `name`, with a content hash so a changed file loads again."
    p = asset(name)
    return f'/learn/abh-asset/{name}?v={hashlib.sha1(p.read_bytes()).hexdigest()[:10]}' if p else None


def surface(path):
    "The css, js, rerun and files URLs (files are known, not loaded) the Abhyasa page at `path` needs, `ALWAYS` first, without duplicates, and every name the manifest knows."
    path = re.split(r'[?#]', path or '/')[0] or '/'
    es = [ALWAYS, *(e for rx, e in SURFACES if re.search(rx, path))]
    out = {}
    for k in ('css', 'js', 'rerun', 'files'):
        names = list(dict.fromkeys(n for e in es for n in e.get(k, [])))
        out[k] = [u for n in names if (u := asset_url(n))]
    return {**out, 'known': sorted(known())}
