from fasthtml.common import Button, Div, P, Span

__all__ = ['CreatePage']

KEYS = 'A and D move the time bar. Q and E jump between the marks. W plays and pauses. On a handle, A D W S move it.'

def CreatePage(slug, title):
    "The body of the Create tab: a bar with the scene name and its buttons, a line for notes, and the place the scene is drawn into."
    return Div(Div(Span(title, cls='lee-create-title'), Span(slug, cls='lee-dim lee-create-slug'), Span(cls='lee-spacer'),
                   Button('New scene', type='button', cls='lee-btn', data_create='new', title='Make a new scene from the dawn-to-dusk template'),
                   Button('Export page', type='button', cls='lee-btn', data_create='export', title='Save the scene as one web page that opens from a file'),
                   cls='lee-create-bar'),
               P(KEYS, cls='lee-dim lee-create-keys'), P('', cls='lee-create-say', role='status', aria_live='polite'),
               Div(cls='lee-create-stage', data_slug=slug), cls='lee-create', data_slug=slug)
