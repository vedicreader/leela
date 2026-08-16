# Vault

Leela stores research, pages, notes, feeds, API specifications, and clipped files in vishalakshi.

Tools > Vault opens one `vaultwb` editor tab.

| view | purpose |
|---|---|
| browse | shelves and documents |
| find | section search |
| add | pages, folders, and notes |
| news | feeds |
| specs | API specifications |
| topics | entity graph topics |

![Workbench](screenshots/vault-workbench.png)

Paste a URL, arXiv id, repository, YouTube URL, file path, or note. `detect` selects the reader. Folder imports show shelves, categories, and excluded generated paths before indexing.

![Add](screenshots/vault-add.png)

`@` completes vault documents. Document rows and search results attach sections to agent questions. Section attachments include only the selected text.

RSS and Atom items go to the `news` shelf. A source URL may resolve through its alternate-feed link. Item links prevent duplicate imports. Each item keeps the feed's own summary in `meta`, so the page prints a standfirst per story without reading the documents.

A source is read once on the way in; the cadence says when to read it again. Each source carries its own read button, and the front page narrows by source and by headline.

Feed items are on the `news` shelf and the memory tools read the main one, so the agent reaches them through `news_latest`, `news_story`, `news_feeds`, `news_refresh`, `news_follow`, and `news_unfollow`. The three that write go in front of the user.

API keys are entered on the specs view, one header per line, and kept where leela keeps its secrets. A key is sent only with calls to the specification it belongs to. `api_keys` reports which specifications are keyed and which header names they send, never the values, so an unauthenticated 401 is something the agent explains rather than retries.

Use notebooks and the live kernel for table analysis. PII reports appear on document rows and tidy candidates.
