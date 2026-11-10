# vendored from the abhyasa repo, tests/walk_data.py
import json, os, re, time
from pathlib import Path

PAGES = [(0, '1 Introduction\n\nRecurrent models compute along the positions of the input. '
             'This inherently sequential nature precludes parallelization within training examples.'),
         (3, '3.2.1 Scaled Dot-Product Attention\n\nWe compute the dot products of the query with all keys, divide each by √dk, '
             'and apply a softmax function to obtain the weights on the values.\n\n![Figure 2](images/fig2.png)'),
         (4, 'We suspect that for large values of dk, the dot products grow large in magnitude, pushing the softmax '
             'function into regions where it has extremely small gradients.')]

def add_paper(lr):
    "File the paper on the main shelf with its figure file; return the doc id."
    d = lr.vault.add(PAGES, 'Attention Is All You Need', source='/tmp/attention.pdf', kind='pdf')
    img = lr.vault.assets('attention')/'images'/'fig2.png'
    img.parent.mkdir(parents=True, exist_ok=True); img.write_bytes(b'\x89PNG\r\n\x1a\n')
    return d['doc_id']

EXTRACT_REPLY = dict(concepts=[
    dict(name='Sequential computation', statement='A recurrent model computes one position after another, so it cannot run the positions of one example in parallel.',
         aliases=[], prereqs=[], section='1 Introduction', quote='This inherently sequential nature precludes parallelization within training examples.',
         figure='', ways=['words', 'analogy'], moves=[], when=None, who=[]),
    dict(name='Softmax', statement='Softmax turns a list of scores into weights that are above 0 and add to 1.', aliases=['softmax function'], prereqs=[],
         section='3.2.1 Scaled Dot-Product Attention', quote='apply a softmax function to obtain the weights on the values',
         figure='images/fig2.png', ways=['code', 'maths'], moves=['weights'], when=None, who=[]),
    dict(name='Scaling by the root of dk', statement='Attention divides the dot products by √dk, so large vectors do not push softmax into regions with very small gradients.',
         aliases=[], prereqs=['Softmax'], section='3.2.1 Scaled Dot-Product Attention', quote='the dot products grow large in magnitude',
         figure='', ways=['demo', 'maths'], moves=['dot products', 'weights'], when=None, who=['Vaswani'])])

def wait_for(f, secs=5.):
    "The first value of `f()` that is not None, asked every 0.1 s for `secs`; None at the end."
    end = time.monotonic() + secs
    while time.monotonic() < end:
        if (v := f()) is not None: return v
        time.sleep(.1)

def walk(cl, lr):
    "File the paper, make a walk from it through the app, and return the journey id."
    return cl.post('/walk/new', data=dict(ref=add_paper(lr))).headers['hx-redirect'].split('/')[-1]

def leela_file(root, port=5011, pid=None, url=None):
    "Write the address file that a running Leela writes, under `root`; the pid of this test makes it look alive."
    f = Path(root)/'leela'/'serving.json'; f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(dict(host='127.0.0.1', port=port, pid=pid or os.getpid(), url=url or f'http://127.0.0.1:{port}/')))
    return f
