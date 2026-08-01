"""The browser frontend: a FastHTML app over the same workspace the TUI drives."""

from .app import ide_app, serve_ide

__all__ = ['ide_app', 'serve_ide']
