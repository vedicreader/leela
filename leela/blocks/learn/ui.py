from fasthtml.common import Blockquote, Body, Button, Form, H1, Head, Hidden, Html, Link, Main, Meta, P, Strong, Title
from ...core.web import asset

__all__ = ['StepPage']

def StepPage(v, q):
    "The page for the `find_step` result `v` of a step or a topic, with the button that opens it as a lesson."
    if v.kind == 'step':
        r = v.step.get('read') or {}
        title, step = v.j.title, str(v.i)
        body = [P(r['section'], cls='lee-learn-section') if r.get('section') else None,
                Blockquote(r['text']) if r.get('text') else None,
                P(v.step['note'], cls='lee-learn-note') if v.step.get('note') else None,
                P('Idea: ', Strong(v.name))]
    else:
        title, step = v.name, ''
        body = [P(v.concept.get('statement') or '') if v.concept else P('This idea is not in your learning store.', cls='lee-learn-line')]
    return Html(Head(Meta(charset='utf-8'), Title(title), Link(rel='stylesheet', href=asset('lee-ide.css'))),
                Body(Main(H1(title), *body,
                          Form(Hidden(name='walk', value=q.walk), Hidden(name='step', value=step), Hidden(name='topic', value=q.topic),
                               Button('Open as a lesson', type='submit'), method='post', action='/learn/open'), cls='lee-learn')))
