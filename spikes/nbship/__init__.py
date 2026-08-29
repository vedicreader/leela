"""Notebooks in other languages, exported into something shippable.

`rust` writes a cargo crate with a PyO3 binding; `js` writes an ESM package with a CDN bundle.
Both are `mod_maker=` arguments to `nbdev.export.nb_export`, whose cell collection is already
language-neutral: it reads directives and cell types, and takes the comment character from the
notebook's own kernelspec.
"""
__all__ = ['rust', 'js']
