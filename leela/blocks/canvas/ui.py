"The canvas page: one document, one margin, three overlays."

from pathlib import Path
from fasthtml.common import *

__all__ = ['page', 'bundle', 'FILES']

HERE = Path(__file__).parent
FILES = ('md.js', 'menu.js', 'canvas.js', 'gutter.js', 'format.js', 'wire.js', 'helper.js')

def bundle():
    "This block's client, in the order it must execute: vocabulary, document, wiring, helper."
    return '\n'.join((HERE/f).read_text() for f in FILES)

def page(path, files, host):
    head = Head(Meta(charset='utf-8'), Meta(name='viewport', content='width=device-width,initial-scale=1'),
                Title('canvas'), Link(rel='stylesheet', href='/canvas/css'))
    bar = Header(cls='cv-bar')(
        Div(cls='cv-doctitle')(Select(id='cv-file')),
        Span('make', id='cv-mode', cls='cv-pill'),
        Span(cls='cv-keys')(NotStr('<kbd>/</kbd> blocks &nbsp;<kbd>⌘K</kbd> ask')),
        Div(cls='cv-tools')(
            Span(id='cv-status', cls='cv-status'),
            Button('▶ run all', id='cv-runall', cls='cv-tbtn', title='mod+shift+enter'),
            Button('save', id='cv-save', cls='cv-tbtn', title='mod+s'),
            Button('◐', id='cv-theme', cls='cv-tbtn', title='light or dark'),
            Button('✦ helper', id='cv-toggle', cls='cv-tbtn', title='mod+j')))
    margin = Aside(cls='cv-margin')(
        H4('helper'), Div(id='cv-thread'),
        Div(id='cv-steer', hidden=True)(Span('steer this turn'), Input(placeholder='…and use the local prices')),
        Form(id='cv-askform')(Input(placeholder='ask the document…')),
        Div(id='cv-trail'))
    body = Body(data_host=host, data_theme='light')(
        bar, Main(cls='cv-wrap margin-open')(Article(id='cv-doc', cls='cv-doc'), margin),
        Div(id='cv-inline', hidden=True)(Input(), Div(cls='cv-isel')),
        Div(id='cv-wire', hidden=True), Script(src='/canvas/js'))
    return HTMLResponse('<!doctype html>' + to_xml(Html(head, body)))
