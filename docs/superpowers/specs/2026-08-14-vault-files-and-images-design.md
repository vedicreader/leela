# Vault files and images design

Status: historical design record.

Vault attachments support files, folders, selections, document references, images, and audio.

Requirements:

- bounded attachment content
- workspace path validation
- source metadata
- image and audio model parts
- document-section references
- folder manifests instead of bulk source injection

`Workspace._attachment_context` assembles grounded context for agent turns.
