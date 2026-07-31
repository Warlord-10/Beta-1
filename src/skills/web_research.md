---
name: web_research
description: Research a topic across multiple web sources and synthesize a cited, balanced answer.
---
## When to use
The task needs current or outside-the-repo information: "find out", "research",
"compare X vs Y", "what's the latest on", "is it true that". Skip for anything
answerable from files already on disk.

## Procedure
1. Break the question into 2–4 concrete sub-questions. Note what a good answer must cover.
2. For each sub-question, run `regular_search` (broad) then `advanced_search` for the
   promising angles. Prefer primary/official sources over blog aggregations.
3. Open the strongest 3–6 results with `extract_text`. Read them — don't answer from snippets.
4. Cross-check: when two sources disagree, say so and note which is more authoritative
   and more recent. A single source is a lead, not a fact.
5. Synthesize a direct answer first, then the supporting detail. Cite each claim with
   the source URL. Flag anything you could not confirm.

## Output
- One-paragraph direct answer up top.
- Bullet points of key findings, each with a source URL.
- A short "confidence / gaps" note: what's solid, what's uncertain, what to verify next.
