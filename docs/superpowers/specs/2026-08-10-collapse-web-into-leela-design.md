# Web consolidation design

Status: historical design record.

Move web features into Leela blocks. Keep browser transport in fossick. Keep markdown rendering in mdhtml.

Target blocks: browser, research, memory, agent, and vault.

Constraints:

- loopback-only browser access
- CDP owns browser automation
- Leela owns workspace state and UI
- external packages retain domain logic
- tests cover routes, browser lifecycle, and extraction

Implementation landed through the block extraction and browser integration work.
