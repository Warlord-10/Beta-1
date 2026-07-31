---
name: summarize_document
description: Read a file or set of files and produce a faithful, structured summary.
---
## When to use
"Summarize", "TL;DR", "what does this file/doc say", "give me the gist of". Works
on code, markdown, logs, transcripts, config — anything readable on disk.

## Procedure
1. Locate the target. If a path was given, `get_file_info` to check size and existence.
   If only a description was given, `search_files` / `search_content` to find it first.
2. Read it. For a large file, read in sections rather than guessing from the first page —
   the important part is often not at the top (logs, appendices, conclusions).
3. Identify: the document's purpose, its main points, any decisions/action items, and
   anything surprising or contradictory.
4. Summarize at the length the task asked for (default: ~150 words + bullets). Preserve
   concrete specifics — names, numbers, dates, file paths — do not blur them into vagueness.
5. Never invent content to fill gaps. If a section is unclear, say so.

## Output
- 1–2 sentence overview of what the document is.
- Key points as bullets, in the document's own order.
- "Action items / decisions" section if any exist.
