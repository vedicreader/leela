"""Images are documents, not text: a viewer tab, served bytes, and figures that resolve.

Opened as text a PNG decodes to replacement characters, and saving that back would destroy the
file -- so the guarantee under test is that an image never reaches the editor at all.
"""

import sys

from fastcore.all import Path
from starlette.testclient import TestClient

from leela.app import ide_app
from leela.blocks.fs.app import SERVED_TYPES
from leela.workspace import IMAGE_EXTS, Tab, Workspace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT/'tools'))
import build_ide_js as builder  # noqa: E402

# A 1x1 PNG, so the bytes served are a real image rather than a file with the right name.
PNG = bytes.fromhex('89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4'
                    '890000000a49444154789c6300010000050001' '0d0a2db4' '0000000049454e44ae426082')


def test_every_image_tab_kind_can_actually_be_served():
    "A kind whose bytes `/file/raw` refuses is a tab that opens onto a broken image."
    assert IMAGE_EXTS <= set(SERVED_TYPES), sorted(IMAGE_EXTS - set(SERVED_TYPES))


def test_an_image_path_becomes_an_image_tab_not_a_text_one():
    for ext in sorted(IMAGE_EXTS):
        assert Tab(path=f'/tmp/a{ext}').kind == 'image', ext
        assert Tab(path=f'/tmp/a{ext.upper()}').kind == 'image', 'the extension is not case sensitive'
    assert Tab(path='/tmp/a.py').kind == 'text' and Tab(path='/tmp/a.pdf').kind == 'pdf'


def test_the_tab_payload_carries_no_bytes_and_the_raw_route_serves_them(tmp_path):
    "Base64ing a whole image into every tab switch is what the pdf kind already avoids."
    (tmp_path/'shot.png').write_bytes(PNG)
    ws = Workspace(roots=[tmp_path])
    with TestClient(ide_app(ws)) as c:
        ws.open(tmp_path/'shot.png')
        st = c.get('/tab/state').json()
        assert st['kind'] == 'image' and st['path'].endswith('shot.png')
        assert 'text' not in st and 'cells' not in st

        raw = c.get('/file/raw/shot.png', params={'path': str(tmp_path/'shot.png')})
        assert raw.status_code == 200 and raw.headers['content-type'] == 'image/png'
        assert raw.content == PNG


def test_an_image_tab_is_never_saved_over():
    "`saveTab` writes the editor's buffer; an image tab has none, so it must refuse before that."
    js = builder.OUT.read_text()
    assert "lee.kind === 'pdf' || lee.kind === 'image'" in js
    assert 'function mountImage' in js and "st.kind === 'image'" in js


def test_markdown_figures_are_resolved_against_the_document_not_the_page():
    js = builder.OUT.read_text()
    block = js[js.index('function resolveMarkdownImages'):js.index('function renderMarkdown')]
    assert "/^(https?:|data:|blob:|\\/file\\/raw)/" in block, 'an absolute or already-resolved src is left alone'
    assert "data-md-base" in js, 'the surfaces say which folder the document came from'
    assert "loading = 'lazy'" in block


def test_the_research_space_can_browse_the_vault():
    "The vault beside the web: what you already kept, in the column where sources go."
    js = builder.OUT.read_text()
    block = js[js.index('function researchWorkspace'):js.index('function webSearch')]
    assert 'data-mode="vault"' in block, 'the vault is a research mode'
    assert "elid=researchvault" in block, 'its fragment gets its own id, not the panel\'s'
    assert "activeMode === 'vault'" in block
    # An empty box is a real answer here: it puts the tree back.
    assert 'if (!query) return;' in block and block.index("activeMode === 'vault'") < block.index('if (!query) return;')


def test_opening_a_file_recovers_a_tab_bar_a_failed_swap_destroyed():
    """`#tabbar` is an htmx `outerHTML` target for tab select, vault open and every `htmxPost`.

    A response that is not a tab bar replaces the element with its text, and every later open
    then failed on the missing element rather than on the file -- which reads as a seized UI.
    """
    js = builder.OUT.read_text()
    block = js[js.index('async function leeOpenFile'):js.index('async function leeOpenFile') + 2200]
    assert "$('#header')?.insertBefore(fresh" in block, 'a destroyed tab bar is put back'
    # The refusal is a 200 carrying an error div, so the message is in the body.
    assert "doc.querySelector('.lee-err')?.textContent" in block, 'the server said why; show that'
