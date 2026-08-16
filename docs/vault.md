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

RSS and Atom items go to the `news` shelf. A source URL may resolve through its alternate-feed link. Item links prevent duplicate imports. Each item keeps the feed's own summary in `meta`. The page prints that standfirst per story and reads no documents to do it.

Following a source reads it once. The cadence governs later reads. Each source carries its own read button. The front page narrows by source and by headline.

The memory tools read the main shelf. Feed items sit on `news`. The agent gets its own: `news_latest`, `news_story`, `news_feeds`, `news_refresh`, `news_follow`, `news_unfollow`. The three that write go in front of the user.

The specs view takes API keys, one header per line, and keeps them where leela keeps its secrets. Each key travels only with calls to the spec it belongs to. `api_keys` names the keyed specs and their header names. It never hands the model a value. An unauthenticated 401 becomes something the agent explains rather than retries.

Use notebooks and the live kernel for table analysis. PII reports appear on document rows and tidy candidates.
