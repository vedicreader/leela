/* The browser vocabulary, as a module.

   `core.js` and `overlays.js` are classic scripts and they publish `window.leeKit`; this file is
   the import face of the same functions, so a module gets them by name rather than by reaching
   for a global. Both bundles run before any module does -- classic `defer` and `type=module`
   execute in document order -- so the object is complete by the time this evaluates.

   A second host supplies its own `window.leeKit` with these fifteen names and imports this file
   unchanged. */

const kit = globalThis.leeKit || {};

export const {$, $$, esc, api, post, status, renderMarkdown, flushMarkdown, compactPath,
              prefGet, prefSet, modal, inputDialog, textDialog, confirmDialog} = kit;
