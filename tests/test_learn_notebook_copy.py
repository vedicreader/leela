"A walk that abhyasa made from one of the learner's notebooks: Open as a lesson opens the learning copy that abhyasa wrote, as it is."
import json
from leela.blocks.nb.nb import Notebook
from learn_data import JID, rig  # noqa: F401

def copy_walk(lr, j, tmp_path):
    "Walk `j` as a notebook walk, with its learning copy in `<assets>/walks/<walk id>/`."
    d = tmp_path/'assets'/'walks'/JID; d.mkdir(parents=True)
    c = d/'15_DDPM.ipynb'
    c.write_text(json.dumps(dict(cells=[dict(cell_type='markdown', metadata={}, source='# DDPM\n\n```rupaka\n{}\n```')], metadata={}, nbformat=4, nbformat_minor=5)))
    lr.put_journey({**j, 'notebook': dict(path=str(tmp_path/'nbs'/'15_DDPM.ipynb'), copy=str(c))})
    return c

def test_open_opens_the_learning_copy_and_writes_nothing(rig, tmp_path_factory):
    c, ws, lr, j, root = rig
    copy = copy_walk(lr, j, tmp_path_factory.mktemp('vault'))
    was = copy.read_bytes()
    r = c.post('/learn/open', data=dict(walk=JID, step='0'), follow_redirects=False)
    assert r.status_code == 303 and ws.tab.path == str(copy) and copy.read_bytes() == was
    assert not (root/'lessons').exists()   # no lesson of its own
    assert Notebook.load(copy)[0].source.startswith('# DDPM')

def test_a_copy_outside_the_folder_of_the_walk_is_not_opened(rig, tmp_path_factory):
    "A copy that is not in `walks/<walk id>/` is not the learning copy: Leela makes its own lesson, as for any walk."
    c, ws, lr, j, root = rig
    t = tmp_path_factory.mktemp('vault')
    bad = t/'15_DDPM.ipynb'; bad.write_text('{}')
    lr.put_journey({**j, 'notebook': dict(path=str(bad), copy=str(bad))})
    assert c.post('/learn/open', data=dict(walk=JID, step='0'), follow_redirects=False).status_code == 303
    assert ws.tab.path == str(root/'lessons'/f'{JID}-0.ipynb')
