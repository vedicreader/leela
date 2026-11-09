"The first-run page: three plain choices, the mode hint, and no old six-feature list."
import re
from starlette.testclient import TestClient
from tools.isolate import isolate
isolate()
from leela.app import ide_app
from leela.workspace import Workspace

def _page(ws): return TestClient(ide_app(ws)).get('/').text

def test_empty_workspace_offers_three_choices_and_the_switch_hint():
    h = _page(Workspace(roots=[]))
    assert h.count('lee-first-way') >= 3 and all(t in h for t in ('Open a folder', 'Learn something', 'Write or run code'))
    assert 'leeFirstLearn()' in h and 'leeAct(&quot;new_notebook&quot;)' in h or 'leeAct("new_notebook")' in h
    assert 'Switch between Code and Learn any time from the top bar.' in h and 'id="leerecent"' in h
    assert not any(w in h for w in ('Live variables', 'Git, release and deploy', 'Code, notebooks and research'))

def test_a_page_with_a_tab_open_does_not_show_the_choices(tmp_path):
    f = tmp_path/'a.py'; f.write_text('x = 1\n')
    ws = Workspace(roots=[tmp_path.resolve()]); ws.open(f)
    editor = re.search(r'<div[^>]*id="editor"[^>]*>(.*?)</div>', _page(ws), re.S)
    assert editor and not editor[1].strip()
