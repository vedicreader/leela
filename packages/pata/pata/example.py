"The worked document the tests and the prototypes read."

from __future__ import annotations
from importlib.resources import files

from .doc import Doc
from .layout import arrange

__all__ = ['procurement', 'PATH', 'VALUES']

PATH = 'procurement.canvas.md'

#: What a run of this document leaves in the namespace, for a prototype that has no kernel.
VALUES = {'c-share': '(0.341, 3.0)', 'c-backtest': '0.79',
          'c-cycle': 'region\nDACH     6.4\nIberia   5.9\nNordics  7.1\nUKI      6.0'}

def procurement(placed=True):
    "One goal worked end to end: framing, evidence, a baseline, a prototype, a decision."
    d = Doc.parse(files(__package__).joinpath(PATH).read_text(encoding='utf-8'), PATH)
    return arrange(d, values=VALUES) if placed else d
