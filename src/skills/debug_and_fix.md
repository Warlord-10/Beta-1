---
name: debug_and_fix
description: Reproduce a bug, find its root cause, fix it, and verify the fix holds.
---
## When to use
"It's broken", "this errors", "fix the bug", "why does X fail", a stack trace, or a
failing command/test. Any task where something should work and doesn't.

## Procedure
1. **Reproduce first.** Run the failing command/test with `agent_bash` and read the full
   stdout/stderr/exit code. A bug you cannot reproduce, you cannot confirm you fixed.
2. **Locate.** `search_content` for the error message and the relevant symbols. Read the
   failing code and its callers — don't patch the first line you land on.
3. **Root cause, not symptom.** Explain *why* it fails before editing. Grep every caller
   of the function you're about to change — fix it once where all paths route through,
   not per-caller.
4. **Fix minimally.** Smallest change that addresses the cause. No drive-by refactors.
5. **Verify.** Re-run the exact repro from step 1 and confirm it now passes. Run any
   nearby tests so the fix didn't break a sibling. Observe it working — don't assume.

## Rules
- If the root cause is unclear, add a temporary log/print to confirm the hypothesis
  before editing, then remove it.
- If you cannot reproduce or cannot fully fix it, say so plainly and report what you ruled out.

## Output
Root cause in one or two sentences, the change made (file + what), and the repro command
with its now-passing output.
